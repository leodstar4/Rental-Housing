"""api/main.py routes (FastAPI TestClient, offline). Needs out/ from `reproduce` + `resolver.cli changes`."""

from __future__ import annotations

import json
from datetime import date
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


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["addresses"] == 500 and r["disclaimer"].startswith("Not legal advice")
    assert client.get("/health?lang=es").json()["disclaimer"].startswith("No es asesoría legal")


def test_addresses_search(client):
    r = client.get("/addresses", params={"city": "Hoboken"}).json()
    assert r["count"] == 40 and all(a["dataset_city"] == "Hoboken, NJ" for a in r["addresses"])
    assert client.get("/addresses", params={"q": "A0016"}).json()["addresses"][0]["address_id"] == "A0016"


def test_lookup_matches_lookups_json(client):
    from resolver.results import run

    expected = {r["team_rule_id"]: r for r in run(date(2026, 10, 1), write=False)["lookups"]["lookups"]["A0016"]}
    body = client.get("/lookup/A0016", params={"as_of": "2026-10-01"}).json()
    got = {x["team_rule_id"]: x for g in body["results"].values() for x in g if not x["attested"]}
    assert set(got) == set(expected)
    for rid, e in expected.items():
        assert (got[rid]["result"], got[rid]["explanation"], got[rid]["conflict_flag"]) == (
            e["result"], e["explanation"], e["conflict_flag"])
    x = got["SF-RENT-01"]
    assert x["citation"] and x["source_url"] and x["retrieved_at"] == "2026-10-01" and x["quoted_span"]
    assert x["plain_language"]["what_it_means"] and body["building_facts"]["units"]["certainty"] == "exact"
    assert body["jurisdiction_stack"]["city"] == "San Francisco, CA" and body["disclaimer"].startswith("Not legal")


def test_lookup_spanish(client):
    body = client.get("/lookup/A0016", params={"lang": "es"}).json()
    assert "RENTA" in body["results"] and body["disclaimer"].startswith("No es asesoría legal")
    x = body["results"]["RENTA"][0]
    assert x["explanation"].endswith("No es asesoría legal.") and x["plain_language"]["what_it_means"]


def test_plain_language_status_line(client):
    en = {x["team_rule_id"]: x for g in client.get("/lookup/A0489").json()["results"].values() for x in g}
    assert en["NJ-ALG-01"]["plain_language"]["status_line"] == "Not in force yet — takes effect 2027-07-01"
    later = {x["team_rule_id"]: x for g in client.get("/lookup/A0489", params={"as_of": "2027-07-02", "lang": "es"})
             .json()["results"].values() for x in g}
    assert later["NJ-ALG-01"]["plain_language"]["status_line"] == "Vigente desde el 2027-07-01"
    sf = {x["team_rule_id"]: x for g in client.get("/lookup/A0016").json()["results"].values() for x in g}
    assert sf["CA-RENT-01"]["plain_language"]["status_line"] == "Covered, but SF-RENT-01 governs instead"
    ma = {x["team_rule_id"]: x for g in client.get("/lookup/A0048").json()["results"].values() for x in g}
    assert ma["MA-ALG-P1"]["plain_language"]["status_line"] == "Pending bill — not law"


def test_spanish_summaries_follow_glossary_and_usted():
    from api.plain_language import PLAIN_PATH, spanish_problems

    data = json.loads(PLAIN_PATH.read_text(encoding="utf-8"))["rules"]
    bad = {k: spanish_problems(v) for k, v in data.items() if v["method"] == "llm" and v.get("es_method") != "template"}
    assert not {k: v for k, v in bad.items() if v}
    assert spanish_problems({"en": {"what_it_means": "The landlord must return the security deposit.",
                                    "who_it_covers": "x", "what_you_can_do": "x"},
                             "es": {"what_it_means": "Tu casero debe devolver el depósito de seguridad.",
                                    "who_it_covers": "x", "what_you_can_do": "x"}})


def test_lookup_fair_act_in_force_2027_at_hoboken(client):
    body = client.get("/lookup/A0489", params={"as_of": "2027-07-02"}).json()
    r = {x["team_rule_id"]: x for g in body["results"].values() for x in g}
    assert r["NJ-ALG-01"]["result"] == "applies" and r["NJ-ALG-01"]["conflict_flag"]
    assert r["HOB-ALG-A1"]["attested"]


@pytest.mark.parametrize("q, code", [("2031-01-01", 422), ("01/10/2026", 422), ("2026-02-30", 422)])
def test_lookup_validates_as_of(client, q, code):
    assert client.get("/lookup/A0016", params={"as_of": q}).status_code == code
    assert client.get("/lookup/A9999").status_code == 404


def test_changes(client):
    r = client.get("/changes").json()
    assert set(r["changes"]) >= {"T1", "T2", "T3", "T4", "T5"} and r["summary"]["T3"]["conflict_flagged"] == 90
    d = client.get("/changes/T1").json()
    assert len(d["affected_address_ids"]) == 250 and d["addresses"]
    assert client.get("/changes/T9").status_code == 404


def test_rules_with_status_at_date(client):
    before = client.get("/rules", params={"jurisdiction": "CA", "category": "algorithmic_rent_setting",
                                          "as_of": "2025-12-31"}).json()
    after = client.get("/rules", params={"jurisdiction": "CA", "category": "algorithmic_rent_setting"}).json()
    assert [r["status"] for r in before["rules"]] == ["not_yet_effective"]
    assert [r["status"] for r in after["rules"]] == ["in_force"] and after["rules"][0]["citation"]


def test_conflicts_and_audit(client):
    c = client.get("/conflicts").json()
    assert ["JC-ALG-A1", "NJ-ALG-01"] in c["preemption_pairs"] and len(c["open_questions"]) == 4
    assert {r["id"] for r in c["human_review"]} >= {"HR-001", "HR-002", "HR-003", "HR-004"}
    a = client.get("/audit").json()
    assert a["extraction"]["model"] and a["extraction"]["documents"] == 54 and a["rules"]["exported"] == 65


def test_cors_allows_lovable(client):
    r = client.get("/health", headers={"Origin": "https://my-app.lovable.app"})
    assert r.headers.get("access-control-allow-origin") == "https://my-app.lovable.app"
    assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": "https://evil.example"}).headers


def test_no_llm_in_routes(client, monkeypatch):
    from extractor import llm

    monkeypatch.setattr(llm, "get_client", lambda: (_ for _ in ()).throw(AssertionError("LLM called")))
    assert client.get("/lookup/A0001", params={"as_of": "2026-11-15", "lang": "es"}).status_code == 200


def test_plain_language_validator():
    from api.plain_language import problems

    fields = {"requirement": "A deposit may not exceed one month's rent after July 1, 2024.", "key_value": None,
              "coverage_text": None, "exemptions": None, "effective_date": "2024-07-01"}
    ok = {lang: {"what_it_means": "Deposit max is 1 month of rent since July 1, 2024.", "who_it_covers": "Renters.",
                 "what_you_can_do": "Ask for a receipt."} for lang in ("en", "es")}
    assert problems(ok, fields) == []
    bad = json.loads(json.dumps(ok))
    bad["es"]["what_it_means"] = "El depósito máximo es 2 meses desde marzo de 2025."
    bad["en"]["what_you_can_do"] = "You can avoid this by signing a short lease."
    msgs = " ".join(problems(bad, fields))
    assert "['2', '2025']" in msgs and "marzo" in msgs and "avoid" in msgs
