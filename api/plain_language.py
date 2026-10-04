"""Plain-language summaries per rule for tenants, in English and Spanish
(``data/plain_language.json``, reproducible without an API key).

Each summary has ``what_it_means`` (1-2 simple sentences), ``who_it_covers`` (1 sentence) and
``what_you_can_do`` (1 practical sentence, no legal advice). The model (``PLAIN_MODEL``, default
claude-haiku-4-5, tool use) sees ONLY the rule's requirement, key_value, coverage_text,
exemptions and effective_date. A validator checks that every number, amount, percentage,
month and date in the summary appears in those fields and that nothing suggests avoiding or
getting around the rule; a rejected answer is regenerated once with the reason, then a
deterministic template is used. Manifest-attested rules (no rule text) always use the template.

``python -m api.plain_language`` (re)builds the file; entries whose input is unchanged are reused.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
import yaml

from extractor import config, llm

PLAIN_MODEL = os.getenv("PLAIN_MODEL", "claude-haiku-4-5")
PROMPT_VERSION = "pl-0.2.0"  # pl-0.2.0: Spanish glossary + "usted"
ES_VERSION = "es-0.2.0"      # Spanish-only revision of summaries that fail the glossary / usted checks
KEY_VERSION = "pl-0.1.0"     # salt of the input hash: changes only when the INPUT definition changes
PLAIN_PATH: Path = config.DATA_DIR / "plain_language.json"
GLOSSARY_PATH: Path = config.DATA_DIR / "glossary_es.yaml"
FIELDS = ("requirement", "key_value", "coverage_text", "exemptions", "effective_date")
PARTS = ("what_it_means", "who_it_covers", "what_you_can_do")
WORKERS = 4
TOOL = "record_summary"

@functools.lru_cache(maxsize=1)
def glossary() -> list[dict]:
    return yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))["terms"]


def glossary_text() -> str:
    return "\n".join(f"- {t['en']} -> {' / '.join(t['es'])}" for t in glossary())


SPANISH_RULES = """Spanish: neutral Latin American Spanish, always formal "usted" (never "tú": no "tu", "puedes",
"pregúntale"; write "su", "puede", "pregúntele"). Translate these legal terms exactly as given:
{glossary}"""

SYSTEM = f"""You write plain-language summaries of U.S. rental-housing rules for TENANTS, in English and in
Spanish (same content). Use short, simple sentences (about grade 6).
{SPANISH_RULES}

Use ONLY the fields you are given (requirement, key_value, coverage_text, exemptions, effective_date).
Never add a number, amount, percentage, month or date that is not written in those fields; copy
figures exactly. Do not invent rights, deadlines, agencies or phone numbers.

- what_it_means: 1-2 sentences on what the rule requires or forbids.
- who_it_covers: 1 sentence on who or what is covered (say if the text does not describe it).
- what_you_can_do: 1 practical sentence a tenant can act on, e.g. "Ask your landlord for ... in
  writing", "Keep a copy of ...", "Contact your local rent board or housing department". It is NOT
  legal advice and must never suggest how to avoid, get around or evade the rule.
If the rule is a pending bill, say it is a proposal and not law.
Answer with one {TOOL} call. ({PROMPT_VERSION})"""


def system_prompt() -> str:
    return SYSTEM.replace("{glossary}", glossary_text())


def tool() -> dict:
    part = {"type": "object", "additionalProperties": False, "required": list(PARTS),
            "properties": {p: {"type": "string"} for p in PARTS}}
    return {"name": TOOL, "description": "Record the tenant summary in English and Spanish.",
            "input_schema": {"type": "object", "additionalProperties": False, "required": ["en", "es"],
                             "properties": {"en": part, "es": part}}}


def rule_fields(rule: dict) -> dict:
    cov = rule.get("coverage_conditions")
    text = cov.get("text") if isinstance(cov, dict) else cov
    return {"requirement": rule.get("requirement"), "key_value": rule.get("key_value"),
            "coverage_text": text, "exemptions": rule.get("exemptions"), "effective_date": rule.get("effective_date")}


# --------------------------------------------------------------------------- #
# Validator
# --------------------------------------------------------------------------- #

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
          "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "thirty": "30", "sixty": "60",
          "ninety": "90", "half": "0.5"}
_MONTHS = {**{m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"], 1)},
           **{m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                          "septiembre", "octubre", "noviembre", "diciembre"], 1)}}
_FORBIDDEN = re.compile(r"\b(avoid|get around|work around|loophole|evade|circumvent|bypass|sidestep|"
                        r"evitar|eludir|rodear|esquivar|burlar|sortear|evadir)\b", re.I)


def _numbers(text: str) -> set[str]:
    out = set()
    for n in _NUM.findall(text):
        n = n.replace(",", "").rstrip(".")
        out.add(n.lstrip("0") or "0")
        if "." in n:
            out.add(n.rstrip("0").rstrip("."))
    return out


def _source_numbers(fields: dict) -> tuple[set[str], set[int]]:
    src = " ".join(str(v) for v in fields.values() if v)
    nums = _numbers(src)
    nums |= {d for w, d in _WORDS.items() if re.search(rf"\b{w}\b", src, re.I)}
    months = {i for m, i in _MONTHS.items() if re.search(rf"\b{m}\b", src, re.I)}
    months |= {int(m) for m in re.findall(r"\b\d{4}-(\d{2})(?:-\d{2})?\b", src)}
    for iso in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", src):  # 2027-07-01 -> 7, 1
        nums |= {str(int(x)) for x in iso.split("-")}
    return nums, months


def problems(summary: dict, fields: dict) -> list[str]:
    nums, months = _source_numbers(fields)
    bad = []
    for lang in ("en", "es"):
        for p in PARTS:
            text = (summary.get(lang) or {}).get(p) or ""
            if not text.strip():
                bad.append(f"{lang}.{p} is empty")
                continue
            extra = sorted(n for n in _numbers(text) if n not in nums)
            if extra:
                bad.append(f"{lang}.{p} has figures not in the rule fields: {extra}")
            mon = sorted({m for m, i in _MONTHS.items() if re.search(rf"\b{m}\b", text, re.I) and i not in months})
            if mon:
                bad.append(f"{lang}.{p} names months not in the rule fields: {mon}")
            if _FORBIDDEN.search(text):
                bad.append(f"{lang}.{p} suggests avoiding the rule ({_FORBIDDEN.search(text).group(0)!r})")
    return bad + spanish_problems(summary)


#: tú forms (the Spanish summaries use "usted")
_TUTEO = re.compile(r"\b(tu|tus|tú|te|ti|contigo|puedes|tienes|debes|quieres|sabes|crees|vives|recibes|"
                    r"pregúntale|pídele|comunícate|contacta|llama|pide|guarda|revisa|habla|busca|consulta tu)\b", re.I)


def spanish_problems(summary: dict) -> list[str]:
    """Glossary terms used exactly (when the English summary uses the English term) and "usted"."""
    en = " ".join((summary.get("en") or {}).get(p) or "" for p in PARTS)
    es = " ".join((summary.get("es") or {}).get(p) or "" for p in PARTS)
    bad = []
    for t in glossary():
        if re.search(rf"\b{re.escape(t['en'])}s?\b", en, re.I) and not any(
                re.search(rf"(?<!\w){re.escape(s)}(?!\w)", es, re.I) for s in t["es"]):
            bad.append(f"es must translate '{t['en']}' as {' / '.join(repr(s) for s in t['es'])}")
        for a in t.get("avoid", []):
            if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", es, re.I):
                bad.append(f"es uses '{a}'; the glossary term is {t['es'][0]!r}")
    tu = sorted({m.group(0).lower() for m in _TUTEO.finditer(es)})
    if tu:
        bad.append(f"es uses tú forms {tu}; use usted")
    return bad


# --------------------------------------------------------------------------- #
# Template (deterministic fallback)
# --------------------------------------------------------------------------- #

CATEGORY = {
    "rent_increase_limits": ("rent increases", "aumentos de renta",
                             "Ask your landlord for any rent increase notice in writing and keep a copy.",
                             "Pida por escrito cualquier aviso de aumento de renta y guarde una copia."),
    "just_cause_eviction": ("evictions", "desalojos",
                            "If you get a notice to leave, ask for the reason in writing and contact your local "
                            "housing department or a tenant organization.",
                            "Si recibe un aviso para desalojar, pida la razón por escrito y comuníquese con la oficina "
                            "de vivienda local o una organización de inquilinos."),
    "security_deposits": ("security deposits", "depósitos de garantía",
                          "Ask for a written receipt for your deposit and keep it.",
                          "Pida un recibo por escrito de su depósito y guárdelo."),
    "application_screening_fees": ("application and screening fees", "cuotas de solicitud y evaluación",
                                   "Ask for a written list of the fees and receipts before you pay.",
                                   "Pida por escrito la lista de cuotas y los recibos antes de pagar."),
    "screening_restrictions": ("tenant screening", "evaluación de inquilinos",
                               "Ask the landlord in writing what criteria they use to review applications.",
                               "Pregunte por escrito al propietario qué criterios usa para revisar solicitudes."),
    "algorithmic_rent_setting": ("algorithmic rent setting", "fijación de renta con algoritmos",
                                 "If you think rent was set with pricing software, contact your local housing "
                                 "department or the state attorney general's office.",
                                 "Si cree que la renta se fijó con software de precios, comuníquese con la oficina de "
                                 "vivienda local o la fiscalía general del estado."),
}


def template(rule: dict) -> dict:
    from resolver.results import _first_sentence

    en_cat, es_cat, en_do, es_do = CATEGORY[rule["category"]]
    jur = rule["jurisdiction"]
    req = _first_sentence(rule.get("requirement"))
    if not req:  # manifest-attested: no rule text in the corpus
        en_means = f"A {jur} law on {en_cat} that the challenge materials name; its text is not in our sources."
        es_means = f"Una ley de {jur} sobre {es_cat} mencionada en los materiales del reto; su texto no está en nuestras fuentes."
    else:
        en_means = req
        es_means = f"Regla de {jur} sobre {es_cat}. Texto oficial (en inglés): {req}"
    pending = rule.get("status") == "pending"
    return {"en": {"what_it_means": en_means + (" This is a proposal, not law." if pending else ""),
                   "who_it_covers": f"Rentals covered by this rule in {jur}.", "what_you_can_do": en_do},
            "es": {"what_it_means": es_means + (" Es una propuesta, no una ley." if pending else ""),
                   "who_it_covers": f"Viviendas de alquiler cubiertas por esta regla en {jur}.", "what_you_can_do": es_do}}


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def generate(rule: dict, *, use_cache: bool = True) -> dict:
    """{method: llm|template, en, es, problems?}"""
    fields = rule_fields(rule)
    if rule.get("evidence_type") == "manifest_only" or not fields["requirement"]:
        return {"method": "template", **template(rule)}
    user = json.dumps({"rule_id": rule["team_rule_id"], "jurisdiction": rule["jurisdiction"],
                       "status": rule.get("status"), **fields}, ensure_ascii=False, indent=1)
    key = _sha([system_prompt(), PLAIN_MODEL, user])
    path = config.CACHE_DIR / "plain" / f"{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if config.OFFLINE:
        return {"method": "template", **template(rule), "problems": ["offline"]}
    last = []
    for attempt in range(2):  # first answer + one regeneration
        content = user if not last else f"{user}\n\nYour previous answer was rejected: {'; '.join(last)}. Fix it."
        try:
            msg = llm.get_client().messages.create(
                model=PLAIN_MODEL, max_tokens=4000, system=system_prompt(), tools=[tool()],
                tool_choice={"type": "tool", "name": TOOL}, messages=[{"role": "user", "content": content}])
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            return {"method": "template", **template(rule), "problems": [f"API error: {e}"]}
        calls = [b for b in msg.content if b.type == "tool_use"]
        summary = calls[0].input if calls else {}
        last = problems(summary, fields)
        if not last:
            out = {"method": "llm", "attempts": attempt + 1, "en": summary["en"], "es": summary["es"]}
            break
    else:
        out = {"method": "template", **template(rule), "problems": last}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return out


ES_SYSTEM = """You fix the SPANISH version of a plain-language tenant summary of a U.S. rental-housing rule.
Rewrite what_it_means, who_it_covers and what_you_can_do in Spanish with the same content as the English
version, using ONLY figures, amounts, months and dates that appear in the rule fields; never suggest how
to avoid or get around the rule. """ + SPANISH_RULES + "\nAnswer with one record_spanish call."


def spanish_tool() -> dict:
    part = {"type": "object", "additionalProperties": False, "required": list(PARTS),
            "properties": {p: {"type": "string"} for p in PARTS}}
    return {"name": "record_spanish", "description": "Record the corrected Spanish summary.",
            "input_schema": {"type": "object", "additionalProperties": False, "required": ["es"],
                             "properties": {"es": part}}}


def fix_spanish(rule: dict, entry: dict) -> dict:
    """Regenerate only ``es`` of an LLM summary that fails the current Spanish checks (one retry with the
    reason; then the Spanish template). English stays as reviewed."""
    fields = rule_fields(rule)
    system = ES_SYSTEM.replace("{glossary}", glossary_text())
    base = json.dumps({"rule_id": rule["team_rule_id"], **fields, "english_summary": entry["en"],
                       "current_spanish": entry["es"]}, ensure_ascii=False, indent=1)
    issues = problems({"en": entry["en"], "es": entry["es"]}, fields)
    key = _sha([system, PLAIN_MODEL, base])
    path = config.CACHE_DIR / "plain" / f"es-{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    out = None
    for attempt in range(2):
        msg = llm.get_client().messages.create(
            model=PLAIN_MODEL, max_tokens=3000, system=system, tools=[spanish_tool()],
            tool_choice={"type": "tool", "name": "record_spanish"},
            messages=[{"role": "user", "content": f"{base}\n\nProblems to fix: {'; '.join(issues)}"}])
        calls = [b for b in msg.content if b.type == "tool_use"]
        es = (calls[0].input if calls else {}).get("es") or {}
        issues = problems({"en": entry["en"], "es": es}, fields)
        if not issues:
            out = {**entry, "es": es, "es_version": ES_VERSION, "es_attempts": attempt + 1}
            break
    if out is None:
        out = {**entry, "es": template(rule)["es"], "es_version": ES_VERSION, "es_method": "template",
               "es_problems": issues}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return out


def build(*, refresh: bool = False, only: list[str] | None = None, log=print) -> dict:
    """``only``: regenerate just these rule ids (ignoring snapshot and cache for them)."""
    from resolver.compile_exemptions import load_rules

    snap = (json.loads(PLAIN_PATH.read_text(encoding="utf-8"))
            if PLAIN_PATH.exists() and not refresh else {"rules": {}})
    rules = load_rules()

    def entry(r: dict) -> dict:
        sha = _sha([KEY_VERSION, PLAIN_MODEL, r["jurisdiction"], r.get("status"), rule_fields(r),
                    r.get("evidence_type")])
        old = snap["rules"].get(r["team_rule_id"])
        forced = bool(only) and r["team_rule_id"] in only
        if old and old.get("input_sha256") == sha and not forced:
            e = old
        else:
            e = {"input_sha256": sha, "prompt_version": PROMPT_VERSION, **generate(r, use_cache=not (refresh or forced))}
        # Spanish revision: summaries written before the glossary / usted rules are fixed in Spanish only
        if e["method"] == "llm" and spanish_problems(e) and not config.OFFLINE:
            e = fix_spanish(r, e)
        return e

    with ThreadPoolExecutor(WORKERS) as ex:
        entries = dict(zip([r["team_rule_id"] for r in rules], ex.map(entry, rules)))
    data = {"model": PLAIN_MODEL, "prompt_version": PROMPT_VERSION, "es_version": ES_VERSION,
            "fields_used": list(FIELDS), "glossary": "data/glossary_es.yaml", "rules": entries}
    PLAIN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    methods = {}
    for e in entries.values():
        methods[e["method"]] = methods.get(e["method"], 0) + 1
    log(f"{len(entries)} rules -> {PLAIN_PATH} {methods}")
    return data


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    build(refresh="--refresh" in sys.argv, only=only)
