"""Human review register (data/human_review.yaml) and the hour-16 flow without it (offline)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from extractor import config, llm
from resolver.compile_exemptions import apply_reviews, review_register

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "a-0.4.0"
FIXTURES = ROOT / "tests" / "fixtures"


def test_register_entries_are_complete_and_quoted():
    reg = review_register()
    assert [r["id"] for r in reg] == sorted({r["id"] for r in reg})  # unique, ordered
    for r in reg:
        assert {"id", "rule_id", "action", "kind", "quoted_span", "reason", "reviewer", "date"} <= set(r)
        date.fromisoformat(r["date"])


def test_register_refuses_unquoted_or_incomplete_entries():
    rule = {"team_rule_id": "X-1", "coverage_conditions": {"notes": "Applies only to buildings of 3 units."}}
    compiled = {"X-1": {"conditions": [], "exemptions": []}}
    entry = {"id": "HR-T", "rule_id": "X-1", "action": "add_item", "kind": "condition", "reviewer": "t",
             "date": "2026-10-03", "reason": "r", "predicate": {"fact": "units", "op": "==", "value": 3}}
    with pytest.raises(ValueError, match="not found verbatim"):
        apply_reviews(compiled, {"X-1": rule}, [{**entry, "quoted_span": "buildings of three units"}])
    with pytest.raises(ValueError, match="missing"):
        apply_reviews(compiled, {"X-1": rule}, [{k: v for k, v in entry.items() if k != "reviewer"}])
    assert apply_reviews(compiled, {"X-1": rule}, [{**entry, "quoted_span": "buildings of 3 units"}]) == ["HR-T"]
    assert compiled["X-1"]["conditions"][0]["origin"] == "human_review"


@pytest.mark.skipif(not SNAPSHOT.exists() or not (ROOT / "out" / "rules_attested.json").exists(),
                    reason="needs snapshot a-0.4.0 and out/rules_attested.json")
def test_extract_doc_flow_needs_no_human_review_entry(tmp_path, monkeypatch):
    """Hour 16: a new document goes extract-doc -> compile -> coverage with an EMPTY register,
    and the real register adds nothing for the new rule."""
    from extractor import incremental
    from resolver.compile_exemptions import compile_all, load_rules
    from resolver.coverage import evaluate, load_inputs

    monkeypatch.setattr(config, "NEW_DOCS_DIR", tmp_path / "corpus_new")
    for name, path in (("NORMALIZED_PATH", "rules_normalized.json"), ("CONFLICTS_PATH", "conflicts.json"),
                       ("RULES_PATH", "rules.json")):
        monkeypatch.setattr(config, name, tmp_path / "out" / path)
    (tmp_path / "out").mkdir(parents=True)
    frozen = json.loads((FIXTURES / "fake_cambridge_llm_result.json").read_text(encoding="utf-8"))
    frozen.pop("created_at", None)
    frozen["usage"] = llm.LLMUsage(**frozen["usage"])
    monkeypatch.setattr(llm, "extract_structured", lambda *a, **k: llm.LLMResult(**frozen))
    incremental.run_increment(FIXTURES / "fake_cambridge_ordinance.txt", jurisdiction="Cambridge, MA",
                              snapshot_dir=SNAPSHOT, as_of=date(2026, 10, 1))
    llm._snapshot_index.cache_clear()
    monkeypatch.setattr(config, "SNAPSHOT_DIR", None)
    monkeypatch.setattr(config, "OFFLINE", True)  # free text of the new rule stays uncompiled, no API

    rules = load_rules()
    assert "CAM-ALG-01" in {r["team_rule_id"] for r in rules}
    empty = compile_all(write=False, register=[], rules=rules, log=lambda *a: None)
    real = compile_all(write=False, rules=rules, log=lambda *a: None)
    assert empty["human_review_applied"] == [] and real["rules"]["CAM-ALG-01"] == empty["rules"]["CAM-ALG-01"]

    _, _, facts, stacks = load_inputs()
    new = next(r for r in rules if r["team_rule_id"] == "CAM-ALG-01")
    seen = {}
    for aid, f in facts.items():
        r = evaluate(new, empty["rules"]["CAM-ALG-01"], f, stacks[aid], date(2027, 3, 14))
        if r:
            seen[aid] = (f["units"]["range"][0], r["coverage"])
    assert seen and all(facts[a]["dataset_city"] == "Cambridge, MA" for a in seen)
    # units_min 6; the Cambridge Housing Authority exemption is a special status presumed absent
    assert all(cov == ("not_covered" if units < 6 else "covered") for units, cov in seen.values())
