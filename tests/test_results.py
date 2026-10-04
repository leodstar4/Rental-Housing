"""resolver/results.py end to end on the real outputs (offline).

Needs the Module A outputs in out/ (`python -m extractor.cli reproduce`); skipped otherwise.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
pytestmark = pytest.mark.skipif(not (OUT / "rules_normalized.json").exists() or not (OUT / "rules_attested.json").exists(),
                                reason="run `python -m extractor.cli reproduce` first")


@pytest.fixture(scope="module")
def engines():
    from resolver.results import Engine

    return {d: Engine(date.fromisoformat(d)) for d in ("2025-12-31", "2026-01-02", "2026-10-01", "2027-07-02")}


def res(engines, as_of, aid):
    return {r["team_rule_id"]: r for r in engines[as_of].lookup(aid)["results"]}


def ids_in(engines, city):
    e = engines["2026-10-01"]
    return [a for a, f in e.facts.items() if f["dataset_city"] == city]


def test_sf_brief_example(engines):
    """Brief p.3: SF building before 1979, 15-30 units (A0016: 1926, 21 units)."""
    r = res(engines, "2026-10-01", "A0016")
    assert r["SF-RENT-01"]["result"] == "applies"
    assert (r["CA-RENT-01"]["result"], r["CA-RENT-01"]["superseded_by"]) == ("superseded", "SF-RENT-01")
    assert r["SF-JUST-01"]["result"] == "applies"
    assert (r["CA-JUST-02"]["result"], r["CA-JUST-02"]["superseded_by"]) == ("superseded", "SF-JUST-01")
    # HR-003: CA-JUST-01 folded into CA-JUST-02; HR-004: demolition condition stated, rule still applies
    assert "CA-JUST-01" not in r
    assert r["CA-JUST-03"]["result"] == "applies"
    assert "Applies only if the unit is demolished for new housing development." in r["CA-JUST-03"]["explanation"]
    assert not r["SF-RENT-01"]["conflict_flag"] and r["CA-FEE-01"]["conflict_flag"]  # legal conflicts only
    assert r["CA-DEP-03"]["result"] == "applies" and "CA-DEP-06" not in r  # small-landlord rule does not cover 21 units
    assert r["CA-FEE-01"]["result"] == "applies"
    assert r["SF-ALG-01"]["result"] == r["CA-ALG-01"]["result"] == "applies"


def test_t1_ab325_as_of(engines):
    for aid in ids_in(engines, "San Diego, CA")[:5]:
        assert res(engines, "2025-12-31", aid)["CA-ALG-01"]["result"] == "not_yet_effective"
        assert res(engines, "2026-01-02", aid)["CA-ALG-01"]["result"] == "applies"


def test_t2_t3_local_bans_and_fair_act(engines):
    for city, own, other in (("Hoboken, NJ", "HOB-ALG-A1", "JC-ALG-A1"), ("Jersey City, NJ", "JC-ALG-A1", "HOB-ALG-A1"),
                             ("Newark, NJ", None, None)):
        for aid in ids_in(engines, city):
            r = res(engines, "2026-10-01", aid)
            assert r["NJ-ALG-01"]["result"] == "not_yet_effective"
            assert r["NJ-ALG-01"]["conflict_flag"] == (own is not None)
            assert ("HOB-ALG-A1" in r, "JC-ALG-A1" in r) == (own == "HOB-ALG-A1", own == "JC-ALG-A1")
            if own:
                assert r[own]["attested"] and r[own]["conflict_flag"] and other not in r
    aid = ids_in(engines, "Newark, NJ")[0]
    assert res(engines, "2027-07-02", aid)["NJ-ALG-01"]["result"] == "applies"


def test_t4_t5_massachusetts(engines):
    for aid in ids_in(engines, "Boston, MA") + ids_in(engines, "Cambridge, MA"):
        r = res(engines, "2026-10-01", aid)
        assert r["MA-ALG-P1"]["result"] == r["MA-ALG-P2"]["result"] == "pending"
        assert "MA-RENT-A1" not in r and "MA-RENT-F1" not in r  # failed: omitted
        caps = [x for x in r.values() if x["category"] == "rent_increase_limits" and x["result"] == "applies"]
        assert [x["team_rule_id"] for x in caps] == ["MA-RENT-01"]  # the ban on local rent control, not a cap


def test_la_rso_cutoff_and_precedence(engines):
    e = engines["2026-10-01"]
    old = next(a for a, f in e.facts.items() if f["dataset_city"] == "Los Angeles, CA" and (f["year_built"]["value"] or 9999) < 1970)
    new = next(a for a, f in e.facts.items() if f["dataset_city"] == "Los Angeles, CA" and (f["year_built"]["value"] or 0) > 1990)
    r_old, r_new = res(engines, "2026-10-01", old), res(engines, "2026-10-01", new)
    assert r_old["LA-RENT-02"]["result"] == "applies" and r_old["CA-RENT-01"]["result"] == "superseded"
    assert "LA-RENT-02" not in r_new and "LA-RENT-05" not in r_new  # RSO-only rule follows the RSO cutoff
    assert r_new["LA-JUST-01"]["result"] == "applies"  # JCO covers the non-RSO building


def test_lookups_file_format():
    from resolver.results import run

    out = run(date(2026, 10, 1), write=False)["lookups"]
    assert set(out) == {"as_of", "lookups"} and len(out["lookups"]) == 500
    rules = {r["team_rule_id"] for r in json.loads((OUT / "rules.json").read_text(encoding="utf-8"))["rules"]}
    for rs in out["lookups"].values():
        for r in rs:
            assert set(r) == {"team_rule_id", "result", "explanation", "conflict_flag"} and r["team_rule_id"] in rules
            assert r["result"] in {"applies", "unknown", "superseded", "not_yet_effective", "pending"}
            assert r["explanation"].endswith("Not legal advice.") and "As of 2026-10-01." in r["explanation"]
