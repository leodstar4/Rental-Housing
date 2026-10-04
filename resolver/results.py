"""Address lookups at a query date: status (Module A) + coverage (B2) + precedence -> results.

Per (address, rule of its jurisdiction stack):

1. **Base result.** status ``failed`` -> omitted; coverage ``not_covered`` / ``exempt`` ->
   omitted (reason kept in lookups_full); ``pending`` -> pending; ``not_yet_effective`` ->
   not_yet_effective; ``in_force`` -> applies (covered) or unknown.
2. **other_law exemptions** (B2 scope ``other_law``, e.g. CA-RENT-01 "housing subject to stricter
   local rent control", LA-JUST-01 "units regulated by the RSO"): the law named
   (``data/other_law_map.yaml``) is looked up among the address's rules. A covered, in-force
   target -> ``superseded`` naming it; an unknown target -> a "may yield to" note.
3. **Dependent rules**: a rule whose only coverage is "applies to units covered by <law>"
   (LA-RENT-05, LA-JUST-02/04/05) applies only where that law applies: a target that applies
   keeps it, an unknown one makes it unknown, none drops it.
4. **Precedence** (Module A ``overrides``/``interaction``: "[Yields to: ...]" / "[Takes
   precedence over ...]"): same test as 2 against the local rule the state rule yields to.
5. **Preemption** in the other direction (a state law that displaces local law: "[Preempts:
   ...]", a state interaction that prohibits local ordinances, the attested rules' notes): never
   superseded; both rules get ``conflict_flag`` and a note for human review.
6. ``conflict_flag`` = a legal conflict only: the rule's Module A conflict_flag OR a preemption
   conflict at the address. ``needs_review`` (lookups_full only) = combined confidence < 0.5,
   where combined = rule confidence x coverage confidence x geocoding certainty (fallback x0.85).
7. When a rule prevails over R, it also prevails over the other in-force rules with R's base
   citation (same law and section) and category.

Manifest-attested rules (``out/rules_attested.json``) are evaluated the same way but written only
to ``out/lookups_full.json`` (no literal quote, so never to ``lookups.json``).
"""

from __future__ import annotations

import functools
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from extractor import config
from extractor.export import load_internal
from extractor.normalize import base_citation, preempts
from extractor.status import compute_status, effective_date_for

from .coverage import evaluate, load_inputs

LOOKUPS_PATH: Path = config.OUT_DIR / "lookups.json"
FULL_PATH: Path = config.OUT_DIR / "lookups_full.json"
OTHER_LAW_PATH: Path = config.DATA_DIR / "other_law_map.yaml"
GEOCODE_FALLBACK = 0.85
REVIEW_BELOW = 0.5  # combined confidence below this -> needs_review (not a conflict)
_INCLUSION = re.compile(r"\b(are|is) (also )?covered\b|\beven if\b", re.I)
_RULE_ID = re.compile(r"\b[A-Z]{2,3}-[A-Z]{3,4}-[A-Z]?\d{1,2}\b")
CATEGORY_LABEL = {"rent_increase_limits": "RENT", "just_cause_eviction": "JUST CAUSE",
                  "security_deposits": "DEPOSIT", "application_screening_fees": "SCREENING FEE",
                  "screening_restrictions": "SCREENING", "algorithmic_rent_setting": "ALGORITHMIC"}


@functools.lru_cache(maxsize=1)
def other_laws() -> list[dict]:
    laws = yaml.safe_load(OTHER_LAW_PATH.read_text(encoding="utf-8"))["laws"]
    return [{**l, "_rx": re.compile(l["pattern"], re.I)} for l in laws]


def law_named(text: str | None, rule: dict) -> list[dict]:
    """Laws ``text`` refers to. A city's law can only be meant by that city's rules or by its
    state's rules ("the Rent Ordinance" in an SF rule is not Berkeley's)."""
    if not text or _INCLUSION.search(text):
        return []
    state = rule["jurisdiction"][-2:]
    return [l for l in other_laws() if l["_rx"].search(text)
            and (not l.get("jurisdiction") or rule["jurisdiction"] in (l["jurisdiction"], state)
                 and l["jurisdiction"].endswith(state))]


def is_law(rule: dict, law: dict, category: str | None) -> bool:
    return ((not law.get("jurisdiction") or rule["jurisdiction"] == law["jurisdiction"])
            and (not law.get("level") or rule["level"] == law["level"])
            and (not law.get("citation") or re.search(law["citation"], rule.get("citation") or ""))
            and (category is None or rule["category"] == category))


def own_coverage(compiled: dict) -> bool:
    return any(c["scope"] == "building" and c["predicate"] != {"const": True} for c in compiled["conditions"])


def dependencies(rule: dict, compiled: dict) -> list[dict]:
    """Laws a rule's coverage is defined by, when it has no coverage condition of its own."""
    if own_coverage(compiled):
        return []
    out = []
    for c in compiled["conditions"]:
        if c["scope"] in ("other_law", "review"):
            out += [l for l in law_named(c["text"], rule) if l not in out]
    return out


# --------------------------------------------------------------------------- #
# Precedence data
# --------------------------------------------------------------------------- #


def precedence(rules: list[dict]) -> tuple[dict[str, set[str]], set[frozenset]]:
    """(yields: R -> rules R yields to, preemption pairs)."""
    yields: dict[str, set[str]] = defaultdict(set)
    pairs: set[frozenset] = set()
    ids = {r["team_rule_id"] for r in rules}
    for r in rules:
        rid, inter = r["team_rule_id"], r.get("interaction") or ""
        for m in re.finditer(r"\[Yields to: ([^\]]+)\]", inter):
            yields[rid] |= {x.strip() for x in m.group(1).split(",")}
        for m in re.finditer(r"\[Takes precedence over ([A-Z0-9-]+)", inter):
            yields[m.group(1)].add(rid)
        for m in re.finditer(r"\[Preempts: ([^\]]+)\]", inter):
            pairs |= {frozenset((rid, x.strip())) for x in m.group(1).split(",")}
        for m in re.finditer(r"\[Subject to preemption by ([A-Z0-9-]+)\]", inter):
            pairs.add(frozenset((rid, m.group(1))))
        if r.get("evidence_type") == "manifest_only" and r.get("conflict_note"):
            pairs |= {frozenset((rid, x)) for x in _RULE_ID.findall(r["conflict_note"]) if x in ids and x != rid}
    for s in rules:  # state interaction that prohibits / preempts local ordinances of its category
        if s["level"] == "state" and preempts(s.get("interaction")):
            for l in rules:
                if l["level"] == "city" and l["jurisdiction"].endswith(f", {s['jurisdiction']}") \
                        and l["category"] == s["category"]:
                    pairs.add(frozenset((s["team_rule_id"], l["team_rule_id"])))
    return yields, pairs


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


def rule_status(rule: dict, internal: dict, as_of: date) -> tuple[str, date | None]:
    if rule.get("evidence_type") == "manifest_only":
        eff = None
        if rule.get("effective_date"):
            parts = [int(x) for x in rule["effective_date"].split("-")] + [1, 1]
            eff = date(parts[0], parts[1], parts[2])
        if rule["status"] == "in_force" and eff and as_of < eff:
            return "not_yet_effective", eff
        return rule["status"], eff
    r = internal[rule["team_rule_id"]]
    return compute_status(r, as_of), effective_date_for(r, as_of)


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #


_ABBREV = re.compile(r"\b(Gov|Civ|Code|Stat|Stats|Bus|Prof|Mun|Admin|Cal|Sec|No|St|Ave|U\.S|e\.g|i\.e|etc|vs|Inc|Co)\.$")


def _first_sentence(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    s, start = text.strip(), 0
    for m in re.finditer(r"(?<=[.;])\s+(?=[A-Z(])", s):
        if not _ABBREV.search(s[start:m.start()]):
            s = s[: m.start()]
            break
    s = s.rstrip(";")
    s = s if s.endswith(".") else s + "."
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def facts_phrase(e: dict, facts: dict) -> str:
    used = {f for rs in e["coverage"]["reasons"] for f in rs["value_used"]}
    parts = []
    y = facts["year_built"]["value"]
    if y and used & {"year_built", "co_date", "building_age"}:
        parts.append(f"built {y}")
    u = facts["units"]
    if "units" in used and u["range"]:
        lo, hi = u["range"]
        parts.append({"exact": f"{lo} units", "parsed": f"{lo} units (assessor description)"}.get(
            u["certainty"], f"{lo}+ units (use code)" if hi is None else f"{lo}–{hi} units (use code)"))
    return "; ".join(parts)


def missing_phrase(m: str, facts: dict) -> str:
    y = facts["year_built"]["value"]
    return {"year_built": "the construction year", "units": "the number of units",
            "owner_type": "the owner's legal type", "owner_occupied": "whether an owner lives on the property",
            "certificate of occupancy date (built in cutoff year)":
                f"the certificate-of-occupancy date (built {y}, the cutoff year)",
            "certificate of occupancy date (rolling cutoff in building year)":
                f"the certificate-of-occupancy date (built {y}, at the rolling cutoff)"}.get(m, m)


def explanation(e: dict, facts: dict, as_of: date, titles: dict[str, str]) -> str:
    rule, res = e["rule"], e["result"]
    req = _first_sentence(rule.get("requirement")) or f"{rule['title']} (text not in the corpus)."
    fp = facts_phrase(e, facts)
    where = f" ({fp})" if fp else f" (all covered rentals in {rule['jurisdiction']})"
    if res == "applies" and e.get("dependency_via"):
        label, via = e["dependency_via"]
        why = f"Applies here because {label} covers this building ({via}{'; ' + fp if fp else ''})."
    elif res == "applies":
        why = f"Applies here{where}."
    elif res == "superseded":
        r2 = e["superseded_by"]
        why = f"Covered here{where}, but {r2} ({titles.get(r2, r2)[:70]}) governs instead."
    elif res == "not_yet_effective":
        why = (f"Enacted but not yet in force: takes effect {e['effective_date']}." if e.get("effective_date")
               else "Enacted but not yet in force.")
    elif res == "pending":
        why = "Pending bill, not law."
    else:
        miss = ", ".join(missing_phrase(m, facts) for m in e["missing_facts"]) or "facts not in the data"
        why = f"Depends on {miss}, which is not in the assessor data."
    if res in ("applies", "unknown") and e.get("explain"):
        why = f"{why} {' '.join(e['explain'])}"  # reviewed unit-level conditions (human review register)
    notes = [p.replace("presumed: ", "Presumed ") for p in e["presumptions"]]
    notes += [f"may yield to {x} if it applies" for x in e["may_yield_to"]]
    notes += e["conflict_notes"]
    sentences = [req, why] + (["Notes: " + "; ".join(notes) + "."] if notes else [])
    if rule.get("evidence_type") == "manifest_only":
        src = (f"Source: {rule.get('citation') or rule['title']}; text not in the corpus (manifest-attested: "
               f"{', '.join(s['url'] for s in rule['sources'])}).")
    else:
        src = f"Source: {rule['citation']} ({rule['source_url']}, retrieved {e['retrieved']})."
    return " ".join(sentences + [src, f"As of {as_of.isoformat()}.", "Not legal advice."])


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #


class Engine:
    def __init__(self, as_of: date, *, rules: list[dict] | None = None, compiled: dict | None = None):
        self.as_of = as_of
        self.rules, self.compiled, self.facts, self.stacks = load_inputs()
        if rules is not None:
            self.rules = rules
        if compiled is not None:
            self.compiled = compiled
        self.internal = {r.team_rule_id: r for r in load_internal() if r.disposition == "accepted"}
        self.yields, self.pairs = precedence(self.rules)
        self.deps = {r["team_rule_id"]: dependencies(r, self.compiled[r["team_rule_id"]]) for r in self.rules}
        self.own = {rid: own_coverage(c) for rid, c in self.compiled.items()}
        # derivative: no coverage of its own and its coverage text refers to another law ("RSO rental
        # units; JCO rental units") -> never evidence that that law covers an address
        self.derivative = {r["team_rule_id"] for r in self.rules if not self.own[r["team_rule_id"]] and any(
            law_named(c["text"], r) for c in self.compiled[r["team_rule_id"]]["conditions"])}
        self.titles = {r["team_rule_id"]: r["title"] for r in self.rules}

    def lookup(self, aid: str) -> dict:
        facts, stack, as_of = self.facts[aid], self.stacks[aid], self.as_of
        entries: dict[str, dict] = {}
        for rule in self.rules:
            rid = rule["team_rule_id"]
            cov = evaluate(rule, self.compiled[rid], facts, stack, as_of)
            if cov is None:
                continue
            status, eff = rule_status(rule, self.internal, as_of)
            e = {"rule": rule, "rule_id": rid, "status": status, "effective_date": eff.isoformat() if eff else None,
                 "coverage": cov, "missing_facts": list(cov["missing_facts"]), "presumptions": list(cov["presumptions"]),
                 "superseded_by": None, "may_yield_to": [], "conflict_notes": [], "omitted": None, "notes": [],
                 "attested": rule.get("evidence_type") == "manifest_only",
                 "explain": [x["explanation"] for x in self.compiled[rid]["conditions"] + self.compiled[rid]["exemptions"]
                             if x.get("explanation")],
                 "retrieved": (self.internal[rid].retrieved_at[:10] if rid in self.internal else None)}
            if status == "failed":
                e["omitted"] = "status failed"
            elif cov["coverage"] in ("not_covered", "exempt"):
                e["omitted"] = f"coverage {cov['coverage']}"
            e["result"] = None if e["omitted"] else {"pending": "pending", "not_yet_effective": "not_yet_effective"}.get(
                status, "applies" if cov["coverage"] == "covered" else "unknown")
            entries[rid] = e

        def targets(law: dict, category: str | None, exclude: str) -> list[dict]:
            return [t for t in entries.values() if t["rule_id"] != exclude and not self.deps[t["rule_id"]]
                    and t["rule_id"] not in self.derivative and is_law(t["rule"], law, category)]

        def best(cands: list[dict]) -> list[dict]:
            """Covered in-force candidates, best first: one that applies (not itself superseded)
            and defines its own coverage (e.g. RSO just cause over a rule merely 'for RSO units')."""
            live = [t for t in cands if t["status"] == "in_force" and t["result"] is not None]
            return sorted((t for t in live if t["coverage"]["coverage"] == "covered"),
                          key=lambda t: (t["result"] != "applies", not self.own[t["rule_id"]], t["rule_id"]))

        def supersede(e: dict, cands: list[dict]) -> None:
            e.setdefault("_cands", []).extend(cands)
            covered = best(cands)
            if covered:
                e["result"], e["superseded_by"] = "superseded", covered[0]["rule_id"]
            else:
                e["may_yield_to"] += [t["rule_id"] for t in cands if t["status"] == "in_force" and t["result"]
                                      and t["coverage"]["coverage"] == "unknown" and t["rule_id"] not in e["may_yield_to"]]

        # 2. other_law exemptions (decided on the base results, so the order of rules does not matter)
        plan = []
        for e in entries.values():
            unresolved, ts = [], []
            for x in self.compiled[e["rule_id"]]["exemptions"]:
                if x["scope"] != "other_law":
                    continue
                laws = law_named(x["text"], e["rule"])
                if not laws:
                    unresolved.append(x["text"])
                for law in laws:
                    ts += [t for t in targets(law, law.get("category") or e["rule"]["category"], e["rule_id"])
                           if t not in ts]
            e["unresolved_other_law"] = unresolved
            if ts and e["result"] in ("applies", "unknown"):
                plan.append((e, ts))
        for e, ts in plan:
            supersede(e, ts)
        # 3. rules defined by another law's coverage
        for e in entries.values():
            deps = self.deps[e["rule_id"]]
            if not deps or e["result"] is None:
                continue
            ts = [t for law in deps for t in targets(law, law.get("category"), e["rule_id"])]
            labels = " or ".join(l["label"] for l in deps)
            via = next((t["rule_id"] for t in sorted(ts, key=lambda t: (not self.own[t["rule_id"]], t["rule_id"]))
                        if t["result"] == "applies"), None)
            if via:
                e["dependency_via"] = (labels, via)
                continue
            if any(t["result"] == "unknown" or (t["result"] and t["coverage"]["coverage"] == "unknown") for t in ts):
                if e["result"] == "applies":
                    e["result"] = "unknown"
                e["missing_facts"].append(f"whether {labels} covers this building")
            else:
                e["result"], e["omitted"] = None, f"applies only to units covered by {labels}, which does not apply here"
        # 4. Module A precedence (state rule yields to the local rule)
        for e in entries.values():
            if e["result"] in ("applies", "unknown") and self.yields.get(e["rule_id"]):
                supersede(e, [entries[x] for x in self.yields[e["rule_id"]] if x in entries])
        # name a superseding rule that itself applies (follow to the best candidate)
        for e in entries.values():
            t = entries.get(e["superseded_by"] or "")
            if t and t["result"] != "applies":
                b = best(e.get("_cands", []))
                if b and b[0]["result"] == "applies":
                    e["superseded_by"] = b[0]["rule_id"]
        # when R2 prevails over R, it prevails over every other in-force rule of the same law and
        # section (base citation) and category (e.g. all Civ. Code § 1946.2 rules)
        for e in [x for x in entries.values() if x["result"] == "superseded"]:
            key = (base_citation(e["rule"].get("citation")), e["rule"]["category"])
            for s in entries.values():
                if (s is not e and s["result"] in ("applies", "unknown") and s["status"] == "in_force"
                        and key[0] and (base_citation(s["rule"].get("citation")), s["rule"]["category"]) == key):
                    s["result"], s["superseded_by"] = "superseded", e["superseded_by"]
                    s["notes"].append(f"same law and section as {e['rule_id']}")
        # 5. preemption the other way: flag both, never supersede
        for pair in self.pairs:
            a, b = sorted(pair)
            if a in entries and b in entries and entries[a]["result"] and entries[b]["result"]:
                for x, y in ((a, b), (b, a)):
                    ry = entries[y]["rule"]
                    name = (f"the {ry['jurisdiction']} local ordinance ({ry.get('citation') or 'text not in corpus'})"
                            if ry.get("evidence_type") == "manifest_only" and not entries[x]["attested"] else y)
                    entries[x]["conflict_notes"].append(f"possible preemption conflict with {name}, flagged for human review")
                    entries[x]["preemption"] = True
        # 6. confidence and conflict flag; explanation
        geo = GEOCODE_FALLBACK if stack.get("source") == "dataset_fallback" else 1.0
        results, omitted = [], []
        for e in entries.values():
            if e["result"] is None:
                omitted.append({"team_rule_id": e["rule_id"], "reason": e["omitted"], "attested": e["attested"]})
                continue
            conf = round((e["rule"].get("confidence") or 1.0) * e["coverage"]["confidence_coverage"] * geo, 3)
            # conflict_flag = a LEGAL conflict only; low confidence is needs_review (lookups_full / UI)
            flag = bool(e["rule"].get("conflict_flag") or e.get("preemption"))
            results.append({
                "team_rule_id": e["rule_id"], "result": e["result"],
                "explanation": explanation(e, facts, as_of, self.titles), "conflict_flag": flag,
                "needs_review": conf < REVIEW_BELOW,
                "attested": e["attested"], "category": e["rule"]["category"], "level": e["rule"]["level"],
                "status": e["status"], "effective_date": e["effective_date"], "coverage": e["coverage"]["coverage"],
                "confidence": conf, "superseded_by": e["superseded_by"], "may_yield_to": e["may_yield_to"],
                "conflict_notes": e["conflict_notes"], "missing_facts": e["missing_facts"],
                "presumptions": e["presumptions"], "reasons": e["coverage"]["reasons"],
                "caveats": e["coverage"]["caveats"], "unresolved_other_law": e["unresolved_other_law"],
                "rule_conflict_flag": bool(e["rule"].get("conflict_flag")),
            })
        results.sort(key=lambda r: (list(CATEGORY_LABEL).index(r["category"]), r["level"] != "city", r["team_rule_id"]))
        return {"address_id": aid, "jurisdiction": {k: stack.get(k) for k in
                                                    ("state", "city", "county", "match_quality", "source", "certainty")},
                "results": results, "omitted": omitted}


def run(as_of: date, *, write: bool = True) -> dict:
    eng = Engine(as_of)
    full = {aid: eng.lookup(aid) for aid in sorted(eng.facts)}
    exported = {r["team_rule_id"] for r in json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]}
    lookups = {aid: [{k: r[k] for k in ("team_rule_id", "result", "explanation", "conflict_flag")}
                     for r in d["results"] if not r["attested"]] for aid, d in full.items()}
    bad = sorted({r["team_rule_id"] for rs in lookups.values() for r in rs} - exported)
    if bad:
        raise ValueError(f"lookups reference ids not in rules.json: {bad}")
    if len(lookups) != 500:
        raise ValueError(f"expected 500 addresses, got {len(lookups)}")
    data = {"as_of": as_of.isoformat(), "lookups": lookups}
    if write:
        config.OUT_DIR.mkdir(parents=True, exist_ok=True)
        LOOKUPS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        FULL_PATH.write_text(json.dumps({"as_of": as_of.isoformat(), "lookups": full}, ensure_ascii=False, indent=1),
                             encoding="utf-8", newline="\n")
    return {"lookups": data, "full": full, "engine": eng}
