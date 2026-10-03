"""Snapshot reproduction, incremental mode and stage merge (offline)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import make_doc, make_rule

from extractor import config, llm
from extractor.models import LegalStage
from extractor.normalize import normalize_rules

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "a-0.4.0"
FIXTURES = ROOT / "tests" / "fixtures"
needs_snapshot = pytest.mark.skipif(not SNAPSHOT.exists(), reason="snapshot a-0.4.0 not present")


@pytest.fixture
def snapshot_mode(monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOT_DIR", None)
    monkeypatch.setattr(config, "OFFLINE", False)
    yield
    llm._snapshot_index.cache_clear()


@needs_snapshot
def test_reproduce_from_snapshot_is_identical(tmp_path, snapshot_mode):
    from extractor.conflicts import detect_conflicts
    from extractor.corpus import load_documents
    from extractor.export import export_rules
    from extractor.extract import extract_all
    from extractor.snapshot import activate

    activate(SNAPSHOT, offline=True)
    results = extract_all(load_documents())
    assert not [r.doc_id for r in results if r.error]
    existing = json.loads((SNAPSHOT / "ids.json").read_text(encoding="utf-8"))
    rules, _ = normalize_rules([x for r in results for x in r.rules], {d.doc_id: d for d in load_documents()}, existing)
    detect_conflicts(rules)
    out = export_rules(rules, date(2026, 10, 1), tmp_path / "rules.json")
    assert out.read_bytes() == (SNAPSHOT / "rules.json").read_bytes()


@needs_snapshot
def test_offline_mode_never_calls_api(snapshot_mode):
    from extractor.snapshot import activate

    activate(SNAPSHOT, offline=True)
    with pytest.raises(llm.ExtractionLLMError, match="offline"):
        llm.extract_structured("sys", "user", text_sha256="0" * 64)


@needs_snapshot
def test_incremental_fake_cambridge(tmp_path, monkeypatch, snapshot_mode):
    from extractor import incremental

    monkeypatch.setattr(config, "NEW_DOCS_DIR", tmp_path / "corpus_new")
    monkeypatch.setattr(config, "NORMALIZED_PATH", tmp_path / "out" / "rules_normalized.json")
    monkeypatch.setattr(config, "CONFLICTS_PATH", tmp_path / "out" / "conflicts.json")
    monkeypatch.setattr(config, "RULES_PATH", tmp_path / "out" / "rules.json")
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    frozen = json.loads((FIXTURES / "fake_cambridge_llm_result.json").read_text(encoding="utf-8"))
    frozen.pop("created_at", None)
    frozen["usage"] = llm.LLMUsage(**frozen["usage"])
    monkeypatch.setattr(llm, "extract_structured", lambda *a, **k: llm.LLMResult(**frozen))

    s = incremental.run_increment(FIXTURES / "fake_cambridge_ordinance.txt", jurisdiction="Cambridge, MA",
                                  snapshot_dir=SNAPSHOT, as_of=date(2026, 10, 1))
    [r] = s["rules"]
    assert (r["change"], r["team_rule_id"], r["jurisdiction"], r["level"], r["category"]) == (
        "new", "CAM-ALGO-01", "Cambridge, MA", "city", "algorithmic_rent_setting")
    assert r["status"] == "not_yet_effective"
    assert r["effective_date"] == "2027-03-13" and r["effective_date_derived"]
    assert any(e["field"] == "units" and e["op"] == "<" and e["value"] == 6
               for e in r["coverage_conditions"]["exemption_conditions"])
    snap = {x["team_rule_id"]: x for x in json.loads((SNAPSHOT / "rules.json").read_text(encoding="utf-8"))["rules"]}
    now = {x["team_rule_id"]: x for x in json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]}
    assert set(now) - set(snap) == {"CAM-ALGO-01"}
    assert all(now[k] == v for k, v in snap.items())  # existing ids and records untouched
    assert "incremental" in incremental.render(s).lower()


def test_ingest_html_and_txt(tmp_path, monkeypatch):
    from extractor import incremental

    monkeypatch.setattr(config, "NEW_DOCS_DIR", tmp_path / "new")
    page = tmp_path / "page.html"
    page.write_text("<html><script>x()</script><body><h1>Ord. 9</h1><p>No landlord shall use it.</p></body></html>",
                    encoding="utf-8")
    doc_id, text_path, meta = incremental.ingest(page, "Cambridge, MA")
    body = text_path.read_text(encoding="utf-8")
    assert doc_id == "NEW-page" and body.startswith("SOURCE: file://corpus/new/page.html\nRETRIEVED: ")
    assert "No landlord shall use it." in body and "x()" not in body
    assert len(meta["original_sha256"]) == 64 and meta["jurisdiction_hint"] == "Cambridge, MA"


DOCS = {d: make_doc("Approved October 6, 2025.", doc_id=d) for d in ("D1", "D2")}
Q = "It shall be unlawful for a landlord to use an algorithmic device to set rents."


def test_stage_merge_most_advanced_wins_and_history_kept():
    bill = make_rule(Q, uid="D1#0", source_doc_id="D1", jurisdiction="Berkeley, CA", level="city",
                     citation="Berkeley Mun. Code § 13.63.030", stage="bill_pending")
    law = make_rule(Q, uid="D2#0", source_doc_id="D2", jurisdiction="Berkeley, CA", level="city",
                    citation="Berkeley Mun. Code § 13.63.030", stage="enacted")
    out, _ = normalize_rules([bill, law], DOCS)
    [acc] = [r for r in out if r.disposition == "accepted"]
    assert acc.stage == LegalStage.ENACTED and acc.team_rule_id == "BRK-ALGO-01"
    assert sorted((c.stage, c.source_doc_id) for c in acc.stage_history) == [("bill_pending", "D1"), ("enacted", "D2")]


def test_stable_ids_with_existing_map():
    a = make_rule(Q, uid="D1#0", source_doc_id="D1", citation="Cal. Civ. Code § 1950.6",
                  category="application_screening_fees", title="Zeta rule")
    b = make_rule(Q, uid="D2#0", source_doc_id="D2", citation="Cal. Civ. Code § 1940", title="Alpha rule",
                  category="application_screening_fees")
    out, _ = normalize_rules([a, b], DOCS, existing_ids={"D1#0": "CA-FEE-01"})
    ids = {r.uid: r.team_rule_id for r in out}
    assert ids == {"D1#0": "CA-FEE-01", "D2#0": "CA-FEE-02"}  # new rule appended, old id kept
