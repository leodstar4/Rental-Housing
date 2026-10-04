"""Manifest-attested rules (extractor/attested.py) and the change-test id map."""

from __future__ import annotations

import json

import yaml

from extractor import config
from extractor.attested import build_attested


def test_attested_rules_have_no_text_and_low_confidence():
    rules = {r["team_rule_id"]: r for r in build_attested()}
    assert set(rules) == {"HOB-ALG-A1", "JC-ALG-A1", "MA-RENT-A1"}
    for r in rules.values():
        assert r["evidence_type"] == "manifest_only" and r["confidence"] == 0.3
        assert r["quoted_span"] is None and r["requirement"] is None and r["sources"]
    assert (rules["JC-ALG-A1"]["effective_date"], rules["HOB-ALG-A1"]["effective_date"]) == ("2025-06", "2025-07")
    assert rules["JC-ALG-A1"]["status_basis"] == "Challenge brief p.3 (organizer-provided); text not in corpus"
    assert rules["MA-RENT-A1"]["citation"] is None and rules["MA-RENT-A1"]["effective_date"] is None
    assert (rules["HOB-ALG-A1"]["jurisdiction"], rules["HOB-ALG-A1"]["category"]) == (
        "Hoboken, NJ", "algorithmic_rent_setting")
    assert rules["HOB-ALG-A1"]["source_doc_ids"] == ["D032", "D033", "D034"]  # no topical URL: all listed
    assert rules["JC-ALG-A1"]["source_doc_ids"] == ["D035", "D037"]
    assert rules["JC-ALG-A1"]["conflict_flag"] and "NJ-ALG-01" in rules["JC-ALG-A1"]["conflict_note"]
    assert rules["MA-RENT-A1"]["status"] == "failed" and not rules["MA-RENT-A1"]["conflict_flag"]


def test_every_change_test_rule_id_is_mapped():
    spec = yaml.safe_load(config.TEST_RULE_MAP_PATH.read_text(encoding="utf-8"))["map"]
    tests = json.loads(config.CHANGE_TESTS_PATH.read_text(encoding="utf-8"))
    ids = {x for t in tests for x in [*t["rule_ids"], *t.get("conflict_with", [])]}
    assert ids == set(spec)
    assert all(bool(e.get("ours")) != bool(e.get("attested")) for e in spec.values())
