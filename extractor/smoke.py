"""smoke-check: offline dashboard over the current outputs (out/rules_normalized.json,
out/rules.json). No API calls.

* Pipeline invariants: corpus loads, cleaning keeps raw lines verbatim, rules.json is
  schema-valid, every exported rule has a citation and a verified quote.
* Expected citations (tests/expected_citations.yaml, measurement only): found / found as
  held / absent because the source is link-only / absent without explanation.
* Behaviour checks: T1, T3 (dates), T4 (S.2983 and H.5222 pending), T5 (no MA, Boston or
  Cambridge rent_increase_limits rule in force).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

from . import config
from .corpus import load_documents, load_manifest
from .models import RuleInternal
from .normalize import preempts
from .status import compute_status
from .validate import load_schema, validate_schema

EXPECTED_PATH = config.ROOT / "tests" / "expected_citations.yaml"
OK, FAIL, WARN = "PASS", "FAIL", "WARN"


def _rule_cites(r: RuleInternal) -> list[str]:
    return [c for c in [r.citation, *r.citation_aliases, *(e.citation for e in r.evidence),
                        *(d.citation for d in r.key_value_details)] if c]


def _final(r: RuleInternal, by_uid: dict[str, RuleInternal]) -> RuleInternal:
    while r.disposition == "merged" and r.merged_into in by_uid:
        r = by_uid[r.merged_into]
    return r


def expected_citations(rules: list[RuleInternal], docs, manifest_rows) -> list[dict]:
    spec = yaml.safe_load(EXPECTED_PATH.read_text(encoding="utf-8"))["citations"]
    by_uid = {r.uid: r for r in rules}
    out = []
    for e in spec:
        pats = [re.compile(p, re.I) for p in e["patterns"]]
        hits = []
        for r in rules:
            if r.disposition == "rejected":
                continue
            f = _final(r, by_uid)
            if f.jurisdiction != e["jurisdiction"] or (e["category"] and f.category != e["category"]):
                continue
            if any(p.search(c) for c in _rule_cites(r) for p in pats):
                hits.append(f)
        accepted = sorted({h.team_rule_id for h in hits if h.disposition == "accepted"})
        held = sorted({h.team_rule_id for h in hits if h.disposition == "held"})
        if accepted:
            status, detail = "found", ", ".join(accepted)
        elif held:
            status, detail = "found as held", ", ".join(held)
        else:
            in_text = sorted(d.doc_id for d in docs if any(p.search(d.raw_text) for p in pats))
            link_only = sorted(r.doc_id for r in manifest_rows if r.status != "ok"
                               and e["jurisdiction"] in r.jurisdictions.split(";"))
            if in_text:
                status, detail = "absent (no explanation)", f"text present in {', '.join(in_text)} but not extracted"
            elif link_only:
                status, detail = "absent: source link-only", f"no corpus text; link-only/check-terms: {', '.join(link_only)}"
            else:
                status, detail = "absent (no explanation)", "not in corpus text and no link-only source"
        out.append({"id": e["id"], "label": e["label"], "status": status, "detail": detail, "note": e.get("note")})
    return out


_BARS = re.compile(r"\b(prohibit\w*|bars?|barred|forbid\w*|preempt\w*)\b[^.]{0,60}\brent control\b|"
                   r"\bno (local )?rent control\b", re.I)


def _bars_local_control(r: RuleInternal) -> bool:
    """Rule prohibits / preempts local rent control rather than setting a cap."""
    return preempts(r.interaction) or any(_BARS.search(t or "") for t in (r.title, r.requirement, r.key_value))


def behaviour_checks(rules: list[RuleInternal]) -> list[dict]:
    acc = [r for r in rules if r.disposition == "accepted"]
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "result": OK if ok else FAIL, "detail": detail})

    def find(pred):
        return [r for r in acc if pred(r)]

    ab325 = find(lambda r: r.jurisdiction == "CA" and "16729" in (r.citation or ""))
    for as_of, exp in (("2025-12-31", "not_yet_effective"), ("2026-01-02", "in_force")):
        got = [compute_status(r, date.fromisoformat(as_of)) for r in ab325]
        add(f"T1 AB 325 @ {as_of} = {exp}", bool(got) and all(g == exp for g in got),
            f"{[r.team_rule_id for r in ab325]} -> {got}")
    fair = find(lambda r: r.jurisdiction == "NJ" and r.category == "algorithmic_rent_setting"
                and re.search(r"2026, ?c\. ?43", r.citation or ""))
    for as_of, exp in (("2026-10-01", "not_yet_effective"), ("2027-07-02", "in_force")):
        got = [compute_status(r, date.fromisoformat(as_of)) for r in fair]
        add(f"T3 FAIR Act @ {as_of} = {exp}", bool(got) and all(g == exp for g in got),
            f"{[r.team_rule_id for r in fair]} -> {got}")
    for bill in ("S.2983", "H.5222"):
        rs = find(lambda r, b=bill: b in (r.citation or ""))
        got = [compute_status(r, config.DEFAULT_AS_OF) for r in rs]
        add(f"T4 MA {bill} = pending", bool(got) and all(g == "pending" for g in got),
            f"{[r.team_rule_id for r in rs]} -> {got}")
    # T5: a rule fails only if it is an in-force CAP: it has a key_value and is not a
    # prohibition/preemption of local rent control (M.G.L. c. 40P is reported, not a cap).
    ma = find(lambda r: r.jurisdiction in ("MA", "Boston, MA", "Cambridge, MA")
              and r.category == "rent_increase_limits" and compute_status(r, config.DEFAULT_AS_OF) == "in_force")
    bars = [r for r in ma if _bars_local_control(r)]
    bad = [r for r in ma if r.key_value and r not in bars]
    notes = ["c. 40P bars local rent control → no local cap" if re.search(r"40P", r.citation or "")
             else f"{r.team_rule_id} bars local rent control → no local cap" for r in bars]
    add("T5 no rent cap in force in MA/Boston/Cambridge", not bad,
        "; ".join(f"{r.team_rule_id} {r.citation}: {r.key_value}" for r in bad) if bad
        else "; ".join(notes) or "none")
    return checks


def invariants(rules: list[RuleInternal], docs) -> list[dict]:
    out = []
    bad_clean = [d.doc_id for d in docs if d.clean_result and not all(
        d.raw_text[s.raw_start:s.raw_start + s.length] == d.clean_text[s.clean_start:s.clean_start + s.length]
        for s in d.clean_result.segments)]
    out.append({"check": f"corpus loads ({len(docs)} docs), clean lines verbatim", "result": OK if not bad_clean else FAIL,
                "detail": "ok" if not bad_clean else str(bad_clean)})
    exported = json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]
    schema = load_schema()
    errs = sum(len(validate_schema(r, schema)) for r in exported)
    out.append({"check": f"rules.json schema-valid ({len(exported)} rules)", "result": OK if not errs else FAIL,
                "detail": f"{errs} errors"})
    acc = [r for r in rules if r.disposition == "accepted"]
    noq = [r.team_rule_id for r in acc if not r.citation or not r.quote_location]
    out.append({"check": "every exported rule has citation + verified quote", "result": OK if not noq else FAIL,
                "detail": "ok" if not noq else str(noq)})
    return out


def test_rule_map() -> list[dict]:
    """Every dev/change_tests.json rule_id is mapped, to an exported or a manifest-attested id."""
    spec = yaml.safe_load(config.TEST_RULE_MAP_PATH.read_text(encoding="utf-8"))["map"]
    tests = json.loads(config.CHANGE_TESTS_PATH.read_text(encoding="utf-8"))
    exported = {r["team_rule_id"] for r in json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]}
    attested = ({r["team_rule_id"] for r in json.loads(config.ATTESTED_PATH.read_text(encoding="utf-8"))["rules"]}
                if config.ATTESTED_PATH.exists() else set())
    out = []
    for tid in sorted({x for t in tests for x in [*t["rule_ids"], *t.get("conflict_with", [])]}):
        e = spec.get(tid) or {}
        if e.get("ours"):
            ok, detail = e["ours"] in exported, f"-> {e['ours']} (rules.json)"
        elif e.get("attested"):
            ok, detail = e["attested"] in attested, f"-> {e['attested']} (attested, no text)"
        else:
            ok, detail = False, "not in data/test_rule_map.yaml"
        out.append({"check": f"test rule {tid}", "result": OK if ok else FAIL, "detail": detail})
    return out


def run() -> dict:
    rules = [RuleInternal.model_validate(r)
             for r in json.loads(config.NORMALIZED_PATH.read_text(encoding="utf-8"))["rules"]]
    docs = load_documents()
    rows = load_manifest()
    return {"invariants": invariants(rules, docs), "citations": expected_citations(rules, docs, rows),
            "behaviour": behaviour_checks(rules), "test_rule_map": test_rule_map()}


def render(res: dict) -> str:
    w = 92
    sym = {"found": "[OK]  ", "found as held": "[HELD]", "absent: source link-only": "[LINK]",
           "absent (no explanation)": "[MISS]"}
    lines = ["=" * w, " MODULE A · SMOKE CHECK".ljust(w), "=" * w, "", " PIPELINE"]
    for c in res["invariants"]:
        lines.append(f"   [{c['result']}] {c['check']:<58} {c['detail'][:28]}")
    lines += ["", " EXPECTED CITATIONS (measurement only)"]
    for c in res["citations"]:
        lines.append(f"   {sym[c['status']]} {c['label']:<46} {c['detail'][:38]}")
    counts = {}
    for c in res["citations"]:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    lines.append("   " + " · ".join(f"{k}: {v}" for k, v in counts.items()))
    lines += ["", " BEHAVIOUR"]
    for c in res["behaviour"]:
        lines.append(f"   [{c['result']}] {c['check']:<48} {c['detail'][:52]}")
    lines += ["", " TEST RULE MAP (data/test_rule_map.yaml)"]
    for c in res["test_rule_map"]:
        lines.append(f"   [{c['result']}] {c['check']:<48} {c['detail'][:52]}")
    n_fail = sum(c["result"] == FAIL for c in res["invariants"] + res["behaviour"] + res["test_rule_map"])
    lines += ["", f" RESULT: {'ALL CHECKS PASS' if not n_fail else f'{n_fail} CHECK(S) FAILED'}", "=" * w]
    return "\n".join(lines)
