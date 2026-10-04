"""Module C: change tests T1-T5 on the real outputs (offline). Needs out/ from `reproduce`."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

OUT = Path(__file__).resolve().parent.parent / "out"
pytestmark = pytest.mark.skipif(not (OUT / "rules_normalized.json").exists() or not (OUT / "rules_attested.json").exists(),
                                reason="run `python -m extractor.cli reproduce` first")


@pytest.fixture(scope="module")
def run():
    from resolver.changes import run_all_tests

    return run_all_tests()


def test_every_test_has_the_three_keys(run):
    changes, _, _ = run
    assert list(changes) == ["T1", "T2", "T3", "T4", "T5"]
    for e in changes.values():
        assert set(e) == {"affected_address_ids", "conflict_flag_address_ids", "notes"}
        assert set(e["conflict_flag_address_ids"]) <= set(e["affected_address_ids"]) and e["notes"]


def test_dashboard_matches_change_tests(run):
    from resolver.changes import verify

    changes, _, tl = run
    failed = [c for c in verify(changes, tl) if c["result"] != "PASS"]
    assert not failed, failed


def test_diff_reports_omitted_and_not_in_stack(run):
    from resolver.changes import diff

    _, _, tl = run
    sf = next(a for a, f in tl.engine(date(2026, 10, 1)).facts.items() if f["dataset_city"] == "San Francisco, CA")
    d = diff(tl, sf, ["CA-ALG-01", "MA-RENT-A1", "NJ-ALG-01"], date(2025, 12, 31), date(2026, 1, 2))
    assert d["CA-ALG-01"] == {"before": "not_yet_effective", "after": "applies"}
    assert d["NJ-ALG-01"] == {"before": "not_in_stack", "after": "not_in_stack"}
