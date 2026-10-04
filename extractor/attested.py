"""Manifest-attested rules: laws the starter pack says exist but whose text is not in the corpus.

Built from ``data/test_rule_map.yaml`` (entries with an ``attested`` id), ``dev/change_tests.json``
and the manifest's link-only / check-terms rows. Written to ``out/rules_attested.json`` and
NEVER to ``rules.json``: they have no quoted span, no citation and no coverage conditions, so
Module B/C use them only for affected-address sets and conflict flags (README, "Responsible
design").

Jurisdiction and category come from the id codes (``HOB`` -> "Hoboken, NJ", ``ALG`` ->
``algorithmic_rent_setting``). Sources are the jurisdiction's link-only rows whose URL names the
topic; when no URL does (Hoboken's ecode360 pages), every link-only row of the jurisdiction is
listed with ``match: jurisdiction_only``.
"""

from __future__ import annotations

import json
import re

import yaml

from . import config
from .corpus import load_manifest
from .normalize import CAT_CODES, JUR_CODES

EVIDENCE_TYPE = "manifest_only"
CONFIDENCE = 0.3
USE = "affected address sets and conflict flags only (never exported to rules.json)"

#: URL words that show a link-only source is about the rule's category.
TOPIC_URL = {
    "algorithmic_rent_setting": re.compile(r"algorithm|realpage|rent-pricing|rent-setting|price-fix", re.I),
    "rent_increase_limits": re.compile(r"rent-control|rent-stabili|ballot", re.I),
}


def _decode(test_rule_id: str) -> tuple[str, str]:
    """``HOB-ALG-01`` -> ("Hoboken, NJ", "algorithmic_rent_setting")."""
    jur_code, cat_code = test_rule_id.split("-")[:2]
    jur = {v: k for k, v in JUR_CODES.items()}[jur_code]
    cat = {v: k for k, v in CAT_CODES.items()}[cat_code]
    return jur, cat


def build_attested() -> list[dict]:
    spec = yaml.safe_load(config.TEST_RULE_MAP_PATH.read_text(encoding="utf-8"))["map"]
    tests = json.loads(config.CHANGE_TESTS_PATH.read_text(encoding="utf-8"))
    link_rows = [r for r in load_manifest() if r.status != "ok"]
    ours = {tid: e.get("ours") or e.get("attested") for tid, e in spec.items()}
    out = []
    for tid, e in spec.items():
        if not e.get("attested"):
            continue
        jur, cat = _decode(tid)
        rows = [r for r in link_rows if jur in [j.strip() for j in r.jurisdictions.split(";")]]
        topical = [r for r in rows if TOPIC_URL.get(cat) and TOPIC_URL[cat].search(r.url)]
        sources = [{"doc_id": r.doc_id, "url": r.url, "source_type": r.source_type, "capture": r.capture,
                    "match": "topical_url" if topical else "jurisdiction_only"} for r in (topical or rows)]
        by_tests = [t for t in tests if tid in t["rule_ids"]]
        conflicts = sorted({ours.get(x) or x for t in tests if tid in t.get("conflict_with", [])
                            for x in t["rule_ids"]})
        out.append({
            "team_rule_id": e["attested"],
            "test_rule_id": tid,
            "jurisdiction": jur,
            "level": "city" if ", " in jur else "state",
            "category": cat,
            "status": e["attested_status"],
            "status_basis": " ".join(e["status_basis"].split()),
            "title": f"{jur}: {cat.replace('_', ' ')} law named by the starter pack (text not in corpus)",
            "requirement": None,
            "key_value": None,
            "coverage_conditions": None,
            "effective_date": e.get("attested_effective_date"),
            "citation": e.get("attested_citation"),
            "quoted_span": None,
            "source_doc_ids": [s["doc_id"] for s in sources],
            "sources": sources,
            "attested_by": [{"source": "dev/change_tests.json", "test_id": t["test_id"], "title": t["title"],
                             "expected_behavior": t["expected_behavior"]} for t in by_tests],
            "evidence_type": EVIDENCE_TYPE,
            "confidence": CONFIDENCE,
            "use": USE,
            "conflict_flag": bool(conflicts),
            "conflict_note": (f"Possible preemption by {', '.join(conflicts)} once effective "
                              "(change_tests conflict_with; participant guide §9)") if conflicts else None,
            "note": " ".join(e.get("note", "").split()) or None,
        })
    return out


def write_attested() -> list[dict]:
    rules = build_attested()
    config.ATTESTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.ATTESTED_PATH.write_text(json.dumps({"evidence_type": EVIDENCE_TYPE, "use": USE, "rules": rules},
                                               ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return rules
