"""Hour 16 pieces (offline): byte-identical ingest, .docx, a kept increment replayed into T6."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from extractor import config, llm

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "a-0.4.0"
FIXTURES = ROOT / "tests" / "fixtures"


def test_ingest_keeps_the_original_bytes(tmp_path, monkeypatch):
    from extractor.incremental import ingest

    monkeypatch.setattr(config, "NEW_DOCS_DIR", tmp_path / "new")
    src = FIXTURES / "fake_cambridge_ordinance.pdf"
    doc_id, text_path, meta = ingest(src, "Cambridge, MA")
    copy = tmp_path / "new" / f"{doc_id}.source.pdf"
    assert copy.read_bytes() == src.read_bytes()
    assert meta["original_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert "ORDINANCE NO. 2026-17" in text_path.read_text(encoding="utf-8")


def test_docx_text(tmp_path):
    from extractor.incremental import read_text

    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body><w:p><w:r><w:t>ORDINANCE NO. 7</w:t></w:r></w:p><w:p><w:r><w:t>No landlord shall </w:t></w:r>"
           "<w:r><w:t>use it.</w:t></w:r></w:p></w:body></w:document>")
    p = tmp_path / "o.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    assert read_text(p) == "ORDINANCE NO. 7\nNo landlord shall use it.\n"


@pytest.mark.skipif(not SNAPSHOT.exists() or not (ROOT / "out" / "rules_attested.json").exists(),
                    reason="needs snapshot a-0.4.0 and out/rules_attested.json")
def test_kept_increment_is_replayed_and_reported(tmp_path, monkeypatch):
    from extractor import incremental
    from resolver.changes import Timeline, doc_test
    from resolver.compile_exemptions import compile_all, load_rules

    monkeypatch.setattr(config, "NEW_DOCS_DIR", tmp_path / "corpus_new")
    for name, path in (("NORMALIZED_PATH", "rules_normalized.json"), ("CONFLICTS_PATH", "conflicts.json"),
                       ("RULES_PATH", "rules.json")):
        monkeypatch.setattr(config, name, tmp_path / "out" / path)
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    (tmp_path / "out").mkdir(parents=True)
    frozen = json.loads((FIXTURES / "fake_cambridge_llm_result.json").read_text(encoding="utf-8"))
    frozen.pop("created_at", None)
    frozen["usage"] = llm.LLMUsage(**frozen["usage"])
    monkeypatch.setattr(llm, "extract_structured", lambda *a, **k: llm.LLMResult(**frozen))
    summary = incremental.run_increment(FIXTURES / "fake_cambridge_ordinance.txt", jurisdiction="Cambridge, MA",
                                        snapshot_dir=SNAPSHOT, as_of=date(2026, 10, 1))
    meta = incremental.persist_increment(summary)
    assert meta["new_rule_ids"] == ["CAM-ALG-01"]

    # replay: the kept increment comes back with its validated rules, no extraction
    monkeypatch.setattr(llm, "extract_structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("API")))
    [inc] = incremental.increments()
    assert inc["doc"].doc_id == meta["doc_id"] and inc["rules"]

    llm._snapshot_index.cache_clear()
    monkeypatch.setattr(config, "SNAPSHOT_DIR", None)
    monkeypatch.setattr(config, "OFFLINE", True)
    rules = load_rules()
    compiled = compile_all(write=False, rules=rules, log=lambda *a: None)["rules"]
    tl = Timeline(rules=rules, compiled=compiled)
    entry, full = doc_test("T6", meta, tl)
    facts = tl.engine(date(2026, 10, 1)).facts
    assert entry["affected_address_ids"] and all(facts[a]["dataset_city"] == "Cambridge, MA"
                                                 for a in entry["affected_address_ids"])
    assert full["test"]["type"] == "new_document" and full["test"]["as_of_after"] == "2027-03-14"
    assert all(d["CAM-ALG-01"] == {"before": "not_yet_effective", "after": "applies"}
               for a, d in full["addresses"].items() if a in entry["affected_address_ids"])

    from api.i18n import change_notes_es, change_title

    rule = next(r for r in rules if r["team_rule_id"] == "CAM-ALG-01")
    es = change_notes_es(full["test"], entry, [rule], full["addresses"],
                         {a: f["dataset_city"] for a, f in facts.items()})
    assert "13 de marzo de 2027" in es and "14 de marzo de 2027" in es and str(len(entry["affected_address_ids"])) in es
    assert change_title(full["test"], [rule], "es").startswith("Documento nuevo")
