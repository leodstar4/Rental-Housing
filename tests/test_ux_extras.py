"""/explain and /timeline (api/explain.py, api/timeline.py). Offline; needs out/ like test_api."""

from __future__ import annotations

from pathlib import Path

import pytest

OUT = Path(__file__).resolve().parent.parent / "out"
pytestmark = pytest.mark.skipif(not all((OUT / f).exists() for f in ("rules_normalized.json", "rules_attested.json",
                                                                      "changes.json")),
                                reason="run `python -m extractor.cli reproduce` and `python -m resolver.cli changes` first")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        yield c


def _lookup_entries(client, aid, **params):
    lk = client.get(f"/lookup/{aid}", params=params).json()
    return {x["team_rule_id"]: x for g in lk["results"].values() for x in g}


# --------------------------------------------------------------------------- #
# /explain
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("aid,as_of", [("A0016", None), ("A0001", None), ("A0489", "2027-07-02"), ("A0006", None),
                                       ("A0005", "2025-01-01"), ("A0009", None)])
def test_explain_coherent_with_lookup(client, aid, as_of):
    """Same result, status, confidence, conflict flag and superseding rule as /lookup on the same date."""
    params = {"as_of": as_of} if as_of else {}
    entries = _lookup_entries(client, aid, **params)
    assert entries
    for rid, x in entries.items():
        e = client.get(f"/explain/{aid}/{rid}", params=params).json()
        assert (e["result"], e["status"], e["effective_date"], e["confidence"], e["conflict_flag"], e["superseded_by"]) \
            == (x["result"], x["status"], x["effective_date"], x["confidence"], x["conflict_flag"], x["superseded_by"]), rid
        assert e["confidence_breakdown"]["combined"] == x["confidence"]
        assert e["status_line"] == x["plain_language"]["status_line"] if x["plain_language"] else True


def test_explain_ca_rent_01_sf(client):
    en = client.get("/explain/A0016/CA-RENT-01").json()
    assert en["result"] == "superseded" and en["precedence"]["governed_by"] == "SF-RENT-01"
    assert en["precedence"]["basis"] in ("other_law", "overrides")
    assert en["coverage_steps"][0]["outcome"] == "yes" and "building age" in en["coverage_steps"][0]["condition"]
    classes = {s["class"] for s in en["exemption_steps"]}
    assert {"special_status", "other_law", "unit_or_tenancy"} <= classes
    presumed = next(s for s in en["exemption_steps"] if s["class"] == "special_status")
    assert presumed["outcome"] == "no" and "Presumed" in presumed["note"]
    eff = next(s for s in en["status_steps"] if s["step"] == "effective_date")
    assert eff["origin"] == "literal" and eff["quote"]
    cb = en["confidence_breakdown"]
    assert round(cb["rule"]["value"] * cb["coverage"]["value"] * cb["geocoding"]["value"], 3) == cb["combined"]
    assert en["provenance"]["doc_id"] and en["provenance"]["snapshot"] == "a-0.4.0"
    assert en["disclaimer"].startswith("Not legal advice")
    es = client.get("/explain/A0016/CA-RENT-01", params={"lang": "es"}).json()
    assert es["result"] == en["result"] and es["summary"].startswith("CA-RENT-01 cubre este edificio")
    assert "rige SF-RENT-01" in es["summary"] and es["disclaimer"].startswith("No es asesoría legal")
    assert " a el " not in str(es) and " tú " not in str(es)
    # each other_law exemption is resolved against its own law (the LA RSO does not reach San Francisco)
    other = {s["source_text"]: s for s in en["exemption_steps"] if s["class"] == "other_law"}
    rso = next(s for t, s in other.items() if "RSO" in t or "Rent Stabilization" in t)
    assert rso["outcome"] == "no" and "SF-RENT-01" not in rso["note"]
    local = next(s for t, s in other.items() if "local rent" in t)
    assert local["outcome"] == "yes" and "SF-RENT-01" in local["note"]


def test_explain_calendar_default_and_review(client):
    e = client.get("/explain/A0016/CA-ALG-01").json()
    eff = next(s for s in e["status_steps"] if s["step"] == "effective_date")
    assert eff["origin"] == "calendar_default" and "Cal. Const. art. IV" in eff["calendar_source"]
    es = client.get("/explain/A0016/CA-ALG-01", params={"lang": "es"}).json()
    assert "regla de calendario" in next(s for s in es["status_steps"] if s["step"] == "effective_date")["note"]
    hr = client.get("/explain/A0016/CA-JUST-02").json()["provenance"]["human_review"]
    assert any(r["id"] == "HR-003" for r in hr)


def test_explain_same_law_and_out_of_stack(client):
    e = client.get("/explain/A0016/CA-JUST-02").json()
    if e["result"] == "superseded" and e["precedence"]["basis"] == "same_law":
        assert e["precedence"]["same_law_as"]
    out = client.get("/explain/A0016/LA-RENT-01").json()
    assert out["result"] == "not_in_stack" and out["jurisdiction"]["in_stack"] is False
    assert client.get("/explain/A0016/XX-NOPE-01").status_code == 404
    assert client.get("/explain/A9999/CA-RENT-01").status_code == 404


# --------------------------------------------------------------------------- #
# /timeline
# --------------------------------------------------------------------------- #


def test_timeline_hoboken_nj_alg(client):
    t = client.get("/timeline/A0489").json()
    assert t["from"] == "2024-10-01" and t["to"] == "2028-12-31"
    ev = next(e for e in t["events"] if e["team_rule_id"] == "NJ-ALG-01" and e["after"] == "applies")
    assert ev["date"] == "2027-07-01" and ev["before"] == "not_yet_effective" and ev["conflict_flag"] is True
    assert ev["past"] is False and t["next_change"]["date"] == "2027-07-01"
    assert [e["date"] for e in t["events"]] == sorted(e["date"] for e in t["events"])
    assert sum(len(v) for v in t["by_year"].values()) == t["count"] == len(t["events"])
    es = client.get("/timeline/A0489", params={"lang": "es"}).json()
    ev_es = next(e for e in es["events"] if e["team_rule_id"] == "NJ-ALG-01" and e["after"] == "applies")
    assert ev_es["status_line"] == "Vigente desde el 2027-07-01" and ev_es["after_label"] == "aplica"


def test_timeline_sf_ca_alg_past(client):
    t = client.get("/timeline/A0016").json()
    ev = next(e for e in t["events"] if e["team_rule_id"] == "CA-ALG-01" and e["after"] == "applies")
    assert ev["date"] == "2026-01-01" and ev["past"] is True and ev["date_origin"] == "calendar_default"


def test_timeline_matches_lookup_on_both_sides(client):
    """Each event's before/after equal /lookup at d-1 and d (no duplicated logic)."""
    from datetime import date, timedelta

    t = client.get("/timeline/A0489").json()
    for e in t["events"]:
        d = date.fromisoformat(e["date"])
        for when, key in ((d - timedelta(days=1), "before"), (d, "after")):
            x = _lookup_entries(client, "A0489", as_of=when.isoformat()).get(e["team_rule_id"])
            assert (x["result"] if x else "omitted") == e[key], (e, when)


def test_timeline_boston_pending(client):
    t = client.get("/timeline/A0006", params={"lang": "es"}).json()
    ids = {p["team_rule_id"] for p in t["pending"]}
    assert {"MA-ALG-P1", "MA-ALG-P2"} <= ids
    assert all(p["note"] == "sin fecha: proyecto de ley, no es ley" for p in t["pending"])


def test_timeline_newark_no_local_events(client):
    for aid in ("A0003", "A0011", "A0013"):
        t = client.get(f"/timeline/{aid}").json()
        assert not [e for e in t["events"] if e["level"] == "city"], aid


def test_timeline_range_and_errors(client):
    t = client.get("/timeline/A0016", params={"from": "2026-01-01", "to": "2026-01-01"}).json()
    assert {e["date"] for e in t["events"]} <= {"2026-01-01"}
    assert client.get("/timeline/A0016", params={"from": "2027-01-01", "to": "2026-01-01"}).status_code == 422
    assert client.get("/timeline/A0016", params={"from": "2026-13-01"}).status_code == 422
    assert client.get("/timeline/A9999").status_code == 404
