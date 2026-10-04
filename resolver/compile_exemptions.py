"""Compile each rule's coverage conditions and exemptions ONCE into predicates over building
facts (``resolver/predicates.py``) -> ``data/compiled_exemptions.json``.

* **Code** translates the structured parts: coverage scalars (``units_min``, ``year_built_max``,
  ``certificate_of_occupancy_on_or_before``, ``building_age_min_years``...) and exemption
  conditions with ``field != other`` (units / year_built / co_date / owner_occupied /
  owner_type / use_type; use types through ``USE_TYPE_TERMS``).
* **A small LLM** (``COMPILE_MODEL``, default claude-haiku-4-5, tool use) translates the free
  text: ``field == other`` exemptions, the ``exemptions`` text, coverage ``notes`` and
  ``property_types_covered``; and gives the building conditions hidden in the text of
  owner_occupied / owner_type exemptions ("owner-occupied two- or three-family dwellings"), which
  the code ANDs with the owner test. Each result has a ``scope``: building (evaluated),
  unit_or_tenancy (caveat), other_law (deferred to precedence) or review (a coverage condition
  read from free text: shown for human review, not evaluated — such conditions proved
  unreliable; coverage restrictions come from the structured fields and property types).

Cache: ``.cache/compile/<sha256>.json`` keyed by the rule's compile input + prompt + model; the
versioned snapshot ``data/compiled_exemptions.json`` is reused whenever a rule's input hash is
unchanged, so reproducing makes no API call.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
import yaml
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from extractor import config, llm

from .predicates import FACTS, PREDICATE_SCHEMA_DEFS, PredicateError, render, validate

COMPILE_MODEL = os.getenv("COMPILE_MODEL", "claude-haiku-4-5")
PROMPT_PATH = config.PROMPTS_DIR / "compile_exemptions.md"
COMPILED_PATH: Path = config.DATA_DIR / "compiled_exemptions.json"
REVIEW_PATH: Path = config.DATA_DIR / "human_review.yaml"
CACHE_SUBDIR = "compile"
TOOL = "record_items"
WORKERS = 4
ATTEMPTS = 3
DUP_SIMILARITY = 90  # rapidfuzz token_set_ratio: free-text exemption restating a structured one

# --------------------------------------------------------------------------- #
# Code translation (structured parts)
# --------------------------------------------------------------------------- #


def cmp(fact: str, op: str, value) -> dict:
    return {"fact": fact, "op": op, "value": value}


def _flag(name: str) -> dict:
    return cmp(f"use.{name}", "==", True)


def _cls(name: str) -> dict:
    return cmp("use_class", "==", name)


#: use_type value -> terms (ALL matching patterns are ANDed for one value; values are ORed).
USE_TYPE_TERMS: list[tuple[re.Pattern, dict]] = [(re.compile(p, re.I), t) for p, t in [
    (r"hotel|motel|transient|tourist|guest house|short-term|vacation|seasonal|recreational", _cls("hotel_transient")),
    (r"dormitor|fraternity|sorority|shared living", _cls("dormitory")),
    (r"hospital|inpatient|medical", _cls("hospital")),
    (r"care facilit|long-term care|extended care|residential care|adult residential|substance abuse|treatment",
     _cls("care_facility")),
    (r"religious facility", _cls("religious_facility")),
    (r"detention|correctional", _cls("detention")),
    (r"homeless|transitional", _cls("shelter_transitional")),
    (r"mobile ?home", _cls("mobilehome")),
    (r"universit|college|higher education", cmp("owner_type", "==", "university")),
    (r"section 8", _flag("section8")),
    (r"public housing|HACLA|government", cmp("owner_type", "==", "government")),
    (r"affordab|deed-restrict|income-restrict", _flag("affordable")),
    (r"condominium|\bcondo|townhome", _flag("condo")),
    (r"cooperative|co-op", _flag("coop")),
    (r"single[- ]family|single home|one-family", _flag("single_family")),
    (r"owner-occupied|owner's|roommate", cmp("owner_occupied", "==", True)),
]]


#: A units threshold on the OWNER's holdings, not on the building.
PORTFOLIO = re.compile(r"\bown(s|ing|ed)?\b[^.]{0,40}\b(less|fewer|more|no more|not more) than\b|"
                       r"\bowned by a person or entity owning\b", re.I)

#: use_type values that concern one unit / tenancy, not the building (caveats, not evaluated).
UNIT_USE_TYPES = re.compile(r"roommate", re.I)


def use_type_predicate(values: list[str]) -> tuple[dict | None, list[str], list[str]]:
    """OR over values -> (predicate or None, unmapped values, unit-level values). A value no
    pattern recognizes becomes a ``missing`` leaf; unit-level values are left out."""
    alts, unmapped, unit = [], [], []
    for v in values:
        if UNIT_USE_TYPES.search(v):
            unit.append(v)
            continue
        terms = [t for rx, t in USE_TYPE_TERMS if rx.search(v)]
        if not terms:
            unmapped.append(v)
            alts.append({"missing": f"use type: {v}"})
        else:
            alts.append(terms[0] if len(terms) == 1 else {"and": terms})
    pred = None if not alts else alts[0] if len(alts) == 1 else {"or": alts}
    return pred, unmapped, unit


def scalar_conditions(cov: dict) -> list[dict]:
    m = [("units_min", "units", ">="), ("units_max", "units", "<="), ("year_built_min", "year_built", ">="),
         ("year_built_max", "year_built", "<="), ("certificate_of_occupancy_on_or_before", "co_date", "<="),
         ("building_age_min_years", "building_age", ">=")]
    return [{"source": k, "kind": "condition", "scope": "building", "origin": "code", "text": f"{k} = {cov[k]}",
             "predicate": cmp(f, op, cov[k])} for k, f, op in m if cov.get(k) is not None]


def structured_exemption(e: dict) -> tuple[dict | None, bool, list[str]]:
    """(predicate, needs_llm_qualifier, unit-level use types). ``None`` predicate with no
    unit-level values = free text (field other)."""
    f, op, v = e["field"], e["op"], e["value"]
    if f == "other":
        return None, False, []
    if f == "units" and PORTFOLIO.search(e["condition"]) and op in ("<", "<="):
        # "owned by a person owning less than ten rental units": the building's units are only a
        # lower bound of the owner's portfolio, so a large building refutes it, a small one cannot
        return {"and": [cmp(f, op, v), {"missing": "owner's total rental units (portfolio)"}]}, False, []
    if f in ("units", "year_built", "co_date"):
        return cmp(f, op, v), False, []
    if f == "owner_occupied":
        return cmp("owner_occupied", "==", bool(v)), True, []
    if f == "owner_type":
        vals = v if isinstance(v, list) else [v]
        return cmp("owner_type", "in", [str(x) for x in vals]), True, []
    if f == "use_type":
        vals = v if isinstance(v, list) else [v]
        pred, _, unit = use_type_predicate([str(x) for x in vals])
        return pred, False, unit
    raise ValueError(f"unknown exemption field {f!r}")


# --------------------------------------------------------------------------- #
# LLM (free text)
# --------------------------------------------------------------------------- #


def prompt() -> tuple[str, str]:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    version = re.search(r"PROMPT_VERSION:\s*([\w.\-]+)", first).group(1)
    facts = "\n".join(f"- `{k}` ({t}): {d}" for k, (t, d) in FACTS.items())
    return version, rest.replace("{FACTS}", facts).strip() + "\n"


def tool() -> dict:
    return {
        "name": TOOL,
        "description": "Record the predicate for every item of the rule.",
        "input_schema": {
            "type": "object", "additionalProperties": False, "required": ["results"],
            "$defs": PREDICATE_SCHEMA_DEFS,
            "properties": {"results": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["ref", "kind", "scope", "text", "predicate", "irreducible", "missing_fact"],
                "properties": {
                    "ref": {"type": "string", "description": "the item's ref (EXEMPTIONS_TEXT / NOTES for free text)"},
                    "kind": {"type": "string", "enum": ["exemption", "condition", "qualifier", "property_types"]},
                    "scope": {"type": "string", "enum": ["building", "unit_or_tenancy", "other_law"]},
                    "text": {"type": "string", "description": "the exemption/condition, quoted or closely paraphrased"},
                    "predicate": {"anyOf": [{"$ref": "#/$defs/predicate"}, {"type": "null"}]},
                    "irreducible": {"type": "boolean"},
                    "missing_fact": {"type": ["string", "null"]},
                }}}},
        },
    }


def llm_items(rule: dict) -> list[dict]:
    """The rule's parts that need the LLM (empty list = none)."""
    cov = rule.get("coverage_conditions") or {}
    cov = cov if isinstance(cov, dict) else {"notes": cov}
    items = []
    for i, e in enumerate(cov.get("exemption_conditions") or []):
        if e["field"] == "other":
            items.append({"ref": f"E{i}", "kind": "exemption", "text": e["condition"], "value": e["value"]})
        elif e["field"] in ("owner_occupied", "owner_type"):
            items.append({"ref": f"E{i}", "kind": "qualifier", "text": e["condition"],
                          "structured": f"{e['field']} {e['op']} {json.dumps(e['value'])}"})
    pt = cov.get("property_types_covered")
    if pt:
        items.append({"ref": "PT", "kind": "property_types", "text": "; ".join(pt)})
    if rule.get("exemptions"):
        items.append({"ref": "EXEMPTIONS_TEXT", "kind": "free_text", "text": rule["exemptions"]})
    if cov.get("notes"):
        items.append({"ref": "NOTES", "kind": "free_text", "text": cov["notes"]})
    return items


def compile_input(rule: dict) -> dict:
    """Everything the compilation depends on (its hash keys cache and snapshot)."""
    cov = rule.get("coverage_conditions") or {}
    cov = cov if isinstance(cov, dict) else {"notes": cov}
    return {"rule_id": rule["team_rule_id"], "jurisdiction": rule["jurisdiction"], "category": rule["category"],
            "title": rule["title"], "requirement": rule.get("requirement"),
            "coverage": {k: v for k, v in cov.items() if k != "text"}, "exemptions": rule.get("exemptions"),
            "coverage_text": cov.get("text")}


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _user_message(rule: dict, items: list[dict]) -> str:
    cov = compile_input(rule)["coverage"]
    handled = [render(c["predicate"]) for c in scalar_conditions(cov)]
    handled += [f"{e['field']} {e['op']} {json.dumps(e['value'])}: {e['condition']}"
                for e in cov.get("exemption_conditions") or [] if e["field"] not in ("other",)]
    return json.dumps({
        "rule": {k: rule.get(k) for k in ("team_rule_id", "jurisdiction", "category", "title", "requirement")},
        "coverage_text": (rule.get("coverage_conditions") or {}).get("text")
        if isinstance(rule.get("coverage_conditions"), dict) else None,
        "already_structured (do not repeat)": handled,
        "items": items,
    }, ensure_ascii=False, indent=1)


def check_results(items: list[dict], results: list[dict]) -> list[str]:
    """Problems in an LLM answer (empty = acceptable)."""
    bad = []
    refs = [r.get("ref") for r in results]
    for it in items:
        if it["kind"] != "free_text" and refs.count(it["ref"]) != 1:
            bad.append(f"item {it['ref']} needs exactly one result (got {refs.count(it['ref'])})")
    kinds = {it["ref"]: it["kind"] for it in items}
    for r in results:
        p, ref = r.get("predicate"), r.get("ref")
        if ref not in kinds:
            bad.append(f"unknown ref {ref!r}")
            continue
        if kinds[ref] == "free_text" and r.get("kind") not in ("exemption", "condition"):
            bad.append(f"{ref}: free-text results must be kind exemption or condition, not {r.get('kind')!r}")
        if p is None:
            continue
        try:
            validate(p)
        except PredicateError as e:
            bad.append(f"{ref}: {e}")
            continue
        if r.get("kind") == "exemption" and (p == {"const": True} or "not" in p):
            bad.append(f"{ref}: an exemption predicate must be TRUE when the exemption applies "
                       f"(got {render(p)}); do not negate it and do not return TRUE")
    return bad


def call_llm(rule: dict, items: list[dict], *, use_cache: bool = True) -> dict:
    version, system = prompt()
    user = _user_message(rule, items)
    key = _sha([version, system, COMPILE_MODEL, user])
    path = config.CACHE_DIR / CACHE_SUBDIR / f"{key}.json"
    if use_cache and path.exists():
        return {**json.loads(path.read_text(encoding="utf-8")), "cached": True}
    if config.OFFLINE:
        raise llm.ExtractionLLMError("offline: compiled exemptions not in the snapshot or cache")
    problem = ""
    usage = llm.LLMUsage()
    for _ in range(ATTEMPTS):
        content = user if not problem else (
            f"{user}\n\nYour previous answer was rejected: {problem}\nAnswer again with one {TOOL} call.")
        try:
            msg = llm.get_client().messages.create(
                model=COMPILE_MODEL, max_tokens=8000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[tool()], tool_choice={"type": "tool", "name": TOOL},
                messages=[{"role": "user", "content": content}])
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            raise llm.ExtractionLLMError(f"API error: {e}") from e
        usage = usage + llm._usage_of(msg)
        calls = [b for b in msg.content if b.type == "tool_use" and b.name == TOOL]
        if len(calls) != 1:
            problem = f"{len(calls)} tool calls (stop_reason={msg.stop_reason})"
            continue
        results = calls[0].input.get("results", [])
        bad = check_results(items, results)
        if bad:
            problem = "; ".join(bad)
            continue
        out = {"model": COMPILE_MODEL, "served_model": msg.model, "prompt_version": version, "results": results,
               "usage": {k: v for k, v in vars(usage).items() if k != "cached"}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        return out
    raise llm.ExtractionLLMError(f"no valid {TOOL} call after {ATTEMPTS} attempts: {problem}")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


#: Deterministic scope corrections for LLM items marked "building" (the small model is not
#: consistent on these): (pattern on the item text, scope, note).
SCOPE_HINTS: list[tuple[re.Pattern, str, str]] = [(re.compile(p, re.I), s, n) for p, s, n in [
    (r"\bsubject to (a |an |the )?(qualifying )?(local|city'?s?|RSO|JCO|rent (stabilization|control)|just cause)"
     r"|\bcovered by (the )?(RSO|JCO|Rent Ordinance|Just Cause)|Costa-Hawkins|same exempt categories",
     "other_law", "depends on another law's coverage"),
    (r"\b(convict\w*|sex offender|service member|applicant|prospective tenant|methamphetamine|tenant'?s? income)\b"
     r"|\bshares? (a )?(bath\w*|kitchen)|\broommate", "unit_or_tenancy", "depends on the tenant, applicant or unit"),
    (r"\b(coordinator|coordinating function|end consumer|licensee|software|product|algorithmic device|"
     r"preference)\b", "unit_or_tenancy", "defines an actor, product or transaction, not the building"),
    (r"\b(are|is) (also )?covered\b|\bare included\b|\bnow (fully or partially )?covered\b",
     "review", "describes what IS covered (an inclusion, not an exemption)"),
]]


def scope_hint(text: str | None) -> tuple[str, str] | None:
    return next(((s, n) for rx, s, n in SCOPE_HINTS if text and rx.search(text)), None)


#: Exemptions / conditions that need a recorded or documented special status (deed or regulatory
#: affordability restriction, HUD subsidy contract, nonprofit cooperative, single-sex designation,
#: fee-simple / condo / co-op conversion, institutional or care use, government or university
#: ownership). coverage.py presumes them absent unless a use flag shows them
#: (PRESUME_SPECIAL_STATUS). Generic owner type and owner occupancy are NOT special status.
SPECIAL_STATUS = re.compile(
    r"deed|regulatory (agreement|restrict)|affordab|income[- ]restrict|\bHUD\b|Section (8|202|811)|subsid|"
    r"Shelter Plus|VASH|LIHTC|cooperative|co-?op\b|single[- ]sex|one sex|fee simple|convert\w* to condo|"
    r"institution|hospital|care facilit|long-term care|extended care|residential care|religious facilit|"
    r"dormitor|fraternity|sorority|homeless|transitional|treatment cent|detention|correctional|"
    r"government|public housing|housing authority|HACLA|universit|elderly|age-restricted", re.I)


def special_by_code(entry: dict) -> bool:
    return bool(SPECIAL_STATUS.search(" ".join(filter(None, [entry.get("text"), entry.get("structured")]))))


def presumable(p: dict) -> bool:
    """The predicate has leaves a special-status presumption could decide."""
    if "and" in p or "or" in p:
        return any(presumable(a) for a in p.get("and", p.get("or")))
    if "not" in p:
        return presumable(p["not"])
    return "missing" in p or p.get("fact", "").startswith("use.") or p.get("fact") == "owner_type"


SPECIAL_SYSTEM = """You classify exemptions and coverage conditions of U.S. rental-housing rules.
For each item say whether it applies only to a property with a SPECIAL STATUS that must be recorded
or documented somewhere (a deed or regulatory affordability restriction, a government subsidy contract
such as HUD Section 8/202/811, a nonprofit or cooperative ownership form, a government or university
owner, an institutional, hospital, care or dormitory use, a single-sex designation, a condominium,
cooperative or fee-simple conversion, an age restriction). Ordinary facts are NOT special status:
whether an owner is a natural person or a company, whether the owner lives on the property, the
number of units, the construction year, the tenant or the lease. Answer with one record_special call."""

SPECIAL_TOOL = {
    "name": "record_special",
    "description": "Record the classification of every item.",
    "input_schema": {"type": "object", "additionalProperties": False, "required": ["results"], "properties": {
        "results": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                "required": ["i", "special_status", "status"], "properties": {
                                                    "i": {"type": "integer"}, "special_status": {"type": "boolean"},
                                                    "status": {"type": ["string", "null"],
                                                               "description": "the status, in a few words"}}}}}},
}


def classify_special(texts: list[str], *, use_cache: bool = True) -> dict[str, dict]:
    """One LLM call -> {text: {"special_status": bool, "status": str}} (cached by content)."""
    if not texts:
        return {}
    user = json.dumps([{"i": i, "text": t} for i, t in enumerate(texts)], ensure_ascii=False, indent=1)
    key = _sha([SPECIAL_SYSTEM, COMPILE_MODEL, user])
    path = config.CACHE_DIR / CACHE_SUBDIR / f"special-{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["by_text"]
    if config.OFFLINE:
        raise llm.ExtractionLLMError("offline: special-status classification not cached")
    for _ in range(ATTEMPTS):
        msg = llm.get_client().messages.create(
            model=COMPILE_MODEL, max_tokens=8000, system=SPECIAL_SYSTEM, tools=[SPECIAL_TOOL],
            tool_choice={"type": "tool", "name": "record_special"}, messages=[{"role": "user", "content": user}])
        calls = [b for b in msg.content if b.type == "tool_use"]
        res = calls[0].input.get("results", []) if calls else []
        if sorted(r["i"] for r in res) == list(range(len(texts))):
            by_text = {texts[r["i"]]: {"special_status": r["special_status"], "status": r["status"]} for r in res}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": COMPILE_MODEL, "served_model": msg.model, "by_text": by_text},
                                       ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
            return by_text
    raise llm.ExtractionLLMError("no valid record_special call")


REVIEW_FIELDS = {"id", "rule_id", "action", "quoted_span", "reason", "reviewer", "date"}
ACTION_FIELDS = {"set_scope": {"kind", "scope"}, "add_item": {"kind", "predicate"}, "merge_rule": {"into"}}


@functools.lru_cache(maxsize=1)
def review_register() -> list[dict]:
    return yaml.safe_load(REVIEW_PATH.read_text(encoding="utf-8"))["reviews"]


def rule_texts(rule: dict) -> list[str]:
    cov = rule.get("coverage_conditions") or {}
    cov = cov if isinstance(cov, dict) else {"notes": cov}
    return [t for t in (cov.get("notes"), cov.get("text"), rule.get("exemptions"),
                        *(e.get("condition") for e in cov.get("exemption_conditions") or []),
                        *(cov.get("property_types_covered") or [])) if t]


def apply_reviews(compiled: dict, rules: dict[str, dict], register: list[dict] | None = None) -> list[str]:
    """Apply data/human_review.yaml; returns the ids applied. Entries for rules not present are
    skipped (e.g. a new document only adds rules, it never needs an entry)."""
    applied = []
    for o in review_register() if register is None else register:
        missing = REVIEW_FIELDS - set(o)
        if o.get("action") not in ACTION_FIELDS:
            raise ValueError(f"human review {o.get('id')}: unknown action {o.get('action')!r}")
        missing |= ACTION_FIELDS[o["action"]] - set(o)
        if missing:
            raise ValueError(f"human review {o.get('id')}: missing {sorted(missing)}")
        if o["action"] == "merge_rule":  # applied in Module A (extractor/normalize.py)
            continue
        c, rule = compiled.get(o["rule_id"]), rules.get(o["rule_id"])
        if c is None or rule is None:
            continue
        if not any(o["quoted_span"] in t for t in rule_texts(rule)):
            raise ValueError(f"human review {o['id']}: quoted_span not found verbatim in {o['rule_id']}")
        note = f"human review {o['id']} ({o['reviewer']}, {o['date']}): {' '.join(o['reason'].split())}"
        if o["action"] == "add_item":
            validate(o["predicate"])
            c[o["kind"] + "s"].append({"source": f"human_review:{o['id']}", "kind": o["kind"], "origin": "human_review",
                                       "scope": o.get("scope", "building"), "text": o["quoted_span"],
                                       "predicate": o["predicate"], "irreducible": False, "note": note,
                                       **({"explanation": o["explanation"]} if o.get("explanation") else {})})
        else:  # set_scope
            for e in c.get(o["kind"] + "s", []):
                if e["scope"] != o["scope"]:
                    e.update(scope=o["scope"], note=note)
        applied.append(o["id"])
    return applied


def mark_special(compiled: dict, llm_labels: dict[str, dict]) -> None:
    """``special_status`` (+ basis) on every building-scope item a presumption could decide."""
    for c in compiled.values():
        for e in c["conditions"] + c["exemptions"]:
            if e["scope"] != "building" or not presumable(e["predicate"]):
                continue
            code, lab = special_by_code(e), llm_labels.get(e["text"] or "", {})
            if code or lab.get("special_status"):
                e["special_status"] = True
                e["special_basis"] = "+".join(b for b, on in (("code", code), ("llm", lab.get("special_status"))) if on)
                e["special_label"] = lab.get("status") or None


def special_candidates(compiled: dict) -> list[str]:
    return sorted({e["text"] for c in compiled.values() for e in c["conditions"] + c["exemptions"]
                   if e["scope"] == "building" and e["text"] and presumable(e["predicate"])})


_OPPOSITE = {"<=": {">"}, "<": {">="}, ">=": {"<"}, ">": {"<="}, "==": {"!="}, "!=": {"=="}}


def contradicts(p: dict, code_conditions: list[dict]) -> bool:
    """A free-text condition that is the exact negation of a code condition (``co_date > D`` vs
    ``co_date <= D``) would make the rule never apply: it restates the exempt side."""
    if "fact" not in p:
        return False
    return any(c["predicate"].get("fact") == p["fact"] and c["predicate"].get("value") == p["value"]
               and p["op"] in _OPPOSITE.get(c["predicate"].get("op"), set()) for c in code_conditions)


def _irreducible(r: dict) -> dict:
    if r.get("irreducible") or r.get("predicate") is None:
        return {"missing": r.get("missing_fact") or r.get("text") or "not expressible"}
    return r["predicate"]


def _llm_entry(source: str, kind: str, r: dict, text: str | None) -> dict:
    entry = {"source": source, "kind": kind, "origin": "llm", "scope": r.get("scope", "building"), "text": text,
             "predicate": _irreducible(r), "irreducible": bool(r.get("irreducible"))}
    hint = scope_hint(text) if entry["scope"] == "building" else None
    if hint:
        entry.update(scope=hint[0], note=f"scope hint: {hint[1]} (LLM said building)")
    return entry


def assemble(rule: dict, llm_out: dict | None) -> dict:
    """Compiled rule: conditions (ANDed) and exemptions (ORed), each with origin and scope."""
    cov = compile_input(rule)["coverage"]
    results = {}
    for r in (llm_out or {}).get("results", []):
        results.setdefault(r["ref"], []).append(r)
    conditions = scalar_conditions(cov)
    exemptions = []
    structured_texts = [e["condition"] for e in cov.get("exemption_conditions") or []]
    for i, e in enumerate(cov.get("exemption_conditions") or []):
        ref = f"E{i}"
        base, qualify, unit = structured_exemption(e)
        got = results.get(ref, [])
        for v in unit:  # unit-level use types: caveat only
            exemptions.append({"source": f"exemption_conditions[{i}]", "kind": "exemption", "origin": "code",
                               "scope": "unit_or_tenancy", "text": f"{e['condition']} [{v}]",
                               "predicate": {"missing": v}, "irreducible": True})
        if base is None and unit:
            continue
        if base is None:  # field other -> LLM
            for r in got or [{"irreducible": True, "missing_fact": e["condition"], "scope": "building"}]:
                exemptions.append(_llm_entry(f"exemption_conditions[{i}]", "exemption", r, e["condition"]))
            continue
        pred, origin, scope = base, "code", "building"
        if qualify and got:
            q = got[0]
            scope = q.get("scope", "building")
            if q.get("predicate") and q["predicate"] != {"const": True}:
                pred, origin = {"and": [base, q["predicate"]]}, "code+llm"
        entry = {"source": f"exemption_conditions[{i}]", "kind": "exemption", "origin": origin,
                 "scope": scope, "text": e["condition"], "predicate": pred,
                 "structured": f"{e['field']} {e['op']} {json.dumps(e['value'])}", "irreducible": False}
        hint = scope_hint(e["condition"]) if qualify and scope == "building" else None
        if hint and hint[0] != "review":
            entry.update(scope=hint[0], note=f"scope hint: {hint[1]}")
        exemptions.append(entry)
    for r in results.get("PT", []):
        conditions.append({"source": "property_types_covered", "kind": "condition", "origin": "llm",
                           "scope": r.get("scope", "building"), "text": "; ".join(cov.get("property_types_covered") or []),
                           "predicate": _irreducible(r), "irreducible": bool(r.get("irreducible"))})
    for ref in ("EXEMPTIONS_TEXT", "NOTES"):
        for r in results.get(ref, []):
            kind = "exemption" if r["kind"] == "exemption" else "condition"
            entry = _llm_entry(ref.lower(), kind, r, r.get("text"))
            dup = next((t for t in structured_texts if fuzz.token_set_ratio(entry["text"] or "", t,
                                                                           processor=default_process) >= DUP_SIMILARITY), None)
            if kind == "exemption" and dup and entry["scope"] in ("building", "unit_or_tenancy"):
                # restates a structured exemption already compiled (by code): evaluating the free-text
                # copy too would only add a weaker, often irreducible, duplicate
                entry.update(scope="duplicate", note=f"restates structured exemption: {dup[:80]!r}")
            if kind == "condition":
                # Free-text conditions narrow coverage and proved unreliable (inclusive examples and
                # exemption qualifiers read as restrictions): kept for human review, not evaluated.
                entry.update(scope="review", note="free-text condition: not evaluated until reviewed")
                if contradicts(entry["predicate"], scalar_conditions(cov)):
                    entry["note"] = "negates a structured coverage condition (restates the exempt side)"
            (conditions if kind == "condition" else exemptions).append(entry)
    # An LLM exemption equal to a coverage condition (or one of its conjuncts) restates the rule's
    # own scope ("the exemption lasts 30 years" in a rule covering buildings <= 30 years old):
    # evaluated, it would make the rule never apply where it is covered.
    conjuncts = [c["predicate"] for c in conditions if c["scope"] == "building"]
    conjuncts += [a for c in conditions if c["scope"] == "building" for a in c["predicate"].get("and", [])]
    for e in exemptions:
        if e["origin"] == "llm" and e["scope"] == "building" and e["predicate"] in conjuncts:
            e.update(scope="review", note="equals a coverage condition of the rule (restates its scope)")
    return {"rule_id": rule["team_rule_id"], "input_sha256": _sha(compile_input(rule)),
            "conditions": conditions, "exemptions": exemptions,
            # raw answer kept so assembly changes never need a new API call
            "llm": {k: llm_out.get(k) for k in ("model", "served_model", "prompt_version", "results", "free_text_sha",
                                                  "partial_reuse") if k in llm_out}
            if llm_out else None}


def free_text_sha(rule: dict) -> str:
    return _sha([it["text"] for it in llm_items(rule) if it["ref"] in ("PT", "EXEMPTIONS_TEXT", "NOTES")])


def partial_reuse(rule: dict, snap_entry: dict | None) -> tuple[list[dict], list[dict]] | None:
    """When a rule changed but kept items already compiled (e.g. a human-review merge appended an
    exemption), reuse the reviewed answers for unchanged items and return only the new items for
    the LLM. None = nothing reusable."""
    old = (snap_entry or {}).get("llm")
    if not old:
        return None
    old_ref_by_text = {}
    for e in snap_entry["exemptions"] + snap_entry["conditions"]:
        m = re.fullmatch(r"exemption_conditions\[(\d+)\]", e.get("source", ""))
        if m:
            old_ref_by_text.setdefault(e["text"], f"E{m.group(1)}")
    free_ok = old.get("free_text_sha") in (None, free_text_sha(rule))  # None: legacy entry, text unchanged
    reused, new = [], []
    for it in llm_items(rule):
        is_e = bool(re.fullmatch(r"E\d+", it["ref"]))
        if is_e and it["text"] in old_ref_by_text:
            reused += [{**r, "ref": it["ref"]} for r in old["results"] if r["ref"] == old_ref_by_text[it["text"]]]
        elif not is_e and free_ok:
            reused += [r for r in old["results"] if r["ref"] == it["ref"]]
        else:
            new.append(it)
    return reused, new


REVIEW_TABLE_PATH: Path = config.DATA_DIR / "compiled_exemptions_review.md"


def write_review_table(data: dict) -> dict:
    """data/compiled_exemptions_review.md: every compiled item (text, predicate, scope) for review;
    returns counts per (kind, scope, irreducible)."""
    from collections import Counter

    lines = ["# Compiled coverage conditions and exemptions (review)", "",
             f"Model `{data['model']}`, prompt `{data['prompt_version']}`. Conditions are ANDed (rule covers the "
             "building), exemptions ORed (rule does not apply). Scope `building` is evaluated; "
             "`unit_or_tenancy` is a caveat; `other_law` is deferred to precedence (B3).", "",
             "| rule | kind | scope | origin | original text | predicate | irreducible |", "|---|---|---|---|---|---|---|"]
    counts: Counter = Counter()
    for rid, c in data["rules"].items():
        for e in c["conditions"] + c["exemptions"]:
            counts[(e["kind"], e["scope"], e.get("irreducible", False))] += 1
            txt = (e["text"] or "").replace("|", "/").replace("\n", " ")
            lines.append(f"| {rid} | {e['kind']} | {e['scope']} | {e['origin']} | {txt} | "
                         f"`{render(e['predicate']).replace('|', '/')}` | {'**yes**' if e.get('irreducible') else ''} |")
    REVIEW_TABLE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return counts


def load_rules() -> list[dict]:
    rules = json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]
    if config.ATTESTED_PATH.exists():
        rules += json.loads(config.ATTESTED_PATH.read_text(encoding="utf-8"))["rules"]
    return rules


def compile_all(*, refresh: bool = False, log=print, write: bool = True, register: list[dict] | None = None,
                rules: list[dict] | None = None) -> dict:
    """Compile every rule. A rule whose input and prompt are unchanged reuses the raw LLM answer
    stored in data/compiled_exemptions.json (no API call); assembly always re-runs. ``write=False``
    returns the result without touching the snapshot (incremental runs); ``register`` replaces the
    human-review register (tests)."""
    snap = json.loads(COMPILED_PATH.read_text(encoding="utf-8"))["rules"] if COMPILED_PATH.exists() and not refresh else {}
    rules = load_rules() if rules is None else rules
    version, _ = prompt()

    def reusable(r: dict) -> bool:
        s = snap.get(r["team_rule_id"])
        return bool(s and s["input_sha256"] == _sha(compile_input(r)) and s.get("llm")
                    and (s["llm"]["prompt_version"], s["llm"]["model"]) == (version, COMPILE_MODEL))

    todo = [r for r in rules if llm_items(r) and not reusable(r)]
    if todo:
        log(f"compiling {len(todo)} rule(s) not in the snapshot with {COMPILE_MODEL}...")
    def one(r: dict) -> dict:
        try:
            part = None if refresh else partial_reuse(r, snap.get(r["team_rule_id"]))
            if part is None:
                out = call_llm(r, llm_items(r), use_cache=not refresh)
            else:
                reused, new = part
                out = call_llm(r, new, use_cache=True) if new else {
                    "model": COMPILE_MODEL, "served_model": None, "prompt_version": version, "results": [],
                    "usage": {}, "cached": True}
                out = {**out, "results": reused + out["results"], "partial_reuse": len(reused)}
            return {**out, "free_text_sha": free_text_sha(r)}
        except llm.ExtractionLLMError as e:
            return {"error": str(e)}

    with ThreadPoolExecutor(WORKERS) as ex:
        outs = dict(zip([r["team_rule_id"] for r in todo], ex.map(one, todo)))
    compiled, usage = {}, llm.LLMUsage()
    for r in rules:
        rid = r["team_rule_id"]
        if rid in outs and "error" in outs[rid]:
            # Free text stays uncompiled: every field-other exemption becomes irreducible (unknown).
            compiled[rid] = {**assemble(r, None), "llm_error": outs[rid]["error"]}
            log(f"  {rid}: LLM failed ({outs[rid]['error'][:160]}); free text left uncompiled")
        elif rid in outs:
            compiled[rid] = assemble(r, outs[rid])
            if not outs[rid].get("cached"):
                usage = usage + llm.LLMUsage(**outs[rid]["usage"])
        elif llm_items(r) and reusable(r):
            compiled[rid] = assemble(r, snap[rid]["llm"])
        else:
            compiled[rid] = assemble(r, None)
    reviews = apply_reviews(compiled, {r["team_rule_id"]: r for r in rules}, register)
    # special-status labels from the LLM: reuse the snapshot's when it has every candidate text
    stored = (json.loads(COMPILED_PATH.read_text(encoding="utf-8")).get("special_status_llm", {})
              if COMPILED_PATH.exists() and not refresh else {})
    cands = special_candidates(compiled)
    labels = {t: stored[t] for t in cands if t in stored}  # reviewed labels are kept
    new_texts = [t for t in cands if t not in stored]
    if new_texts:
        log(f"classifying {len(new_texts)} new item(s) for special status with {COMPILE_MODEL}...")
        try:
            labels.update(classify_special(new_texts, use_cache=not refresh))
        except llm.ExtractionLLMError as e:  # offline: code regex only for the new texts
            log(f"  special-status classification unavailable ({e}); regex only for new items")
    mark_special(compiled, labels)
    data = {"model": COMPILE_MODEL, "prompt_version": version, "rules": compiled, "special_status_llm": labels,
            "human_review_applied": reviews}
    if write:
        COMPILED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    if todo:
        calls = sum(1 for o in outs.values() if "error" not in o and not o.get("cached"))
        log(f"  {calls} API call(s), {len(todo) - calls} from .cache/compile; tokens in={usage.input_tokens} "
            f"out={usage.output_tokens} USD≈{llm.estimate_cost(usage, COMPILE_MODEL) or 0:.4f}")
    return data
