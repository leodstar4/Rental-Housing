"""resolver/facts.py and resolver/geocode.py (offline: no Census calls)."""

from __future__ import annotations

import pytest

from resolver.addresses import Address
from resolver.facts import building_facts, parse_nj_units
from resolver.geocode import batch_input, build_stack, discrepancies, parse_batch, retry_street

NJ = "NJOGIS Parcels & MOD-IV Composite"


def addr(**kw) -> Address:
    base = dict(address_id="A9999", street_address="1 MAIN ST", postal_city="Hoboken", state="NJ", zip="07030",
                year_built="", units="", use_code="4C", use_description="", source_dataset=NJ,
                retrieved_at="2026-10-01T22:50Z")
    return Address(**{**base, **kw})


@pytest.mark.parametrize("desc, units", [
    ("3S-F-D-6U-NH", 6), ("4-S-BT-21U-H", 21), ("3B-7U/4B-24U-G", 31), ("2F-4U/2F-2U", 6),
    ("5B-1OU", 10), ("13B-93U-2C-G", 93), ("2,4B-16U-H-X", 16), ("4 1/2B-10U-BA", 10),
    ("3SF3UG", None), ("USCB16UG", None), ("3SB", None),
])
def test_parse_nj_units(desc, units):
    assert parse_nj_units(desc)[0] == units


def test_units_commercial_count_column_is_ignored():
    w: list = []
    f = building_facts(addr(units="2", use_description="13B-93U-2C-G"), w)
    assert f["units"]["range"] == [93, 93] and f["units"]["certainty"] == "parsed"
    assert [x["code"] for x in w] == ["column_is_commercial_count"]


def test_units_exact_kept_against_use_code_with_warning():
    w: list = []
    f = building_facts(addr(postal_city="San Francisco", state="CA", units="5", use_code="TIC",
                            use_description="TIC Bldg 4 units or less", source_dataset="DataSF wv5m-vpq2 (2025 roll)"), w)
    assert f["units"] == {"range": [5, 5], "certainty": "exact", "source": "units column"}
    assert [x["code"] for x in w] == ["value_vs_use_code"] and f["use_flags"]["tic"]["value"]


@pytest.mark.parametrize("kw, rng, certainty", [
    (dict(postal_city="Boston", state="MA", use_code="A/112", source_dataset="Boston Property Assessment FY2026"),
     [7, 30], "range"),
    (dict(postal_city="Boston", state="MA", use_code="A/125", source_dataset="Boston Property Assessment FY2026"),
     None, "unknown"),
    (dict(postal_city="Newark", use_description="3SB"), [5, None], "range"),
])
def test_units_from_use_code(kw, rng, certainty):
    f = building_facts(addr(**kw), [])
    assert (f["units"]["range"], f["units"]["certainty"]) == (rng, certainty)


def test_owner_facts_always_unknown_and_co_is_approximate():
    f = building_facts(addr(year_built="1978"), [])
    assert f["owner_type"]["certainty"] == f["owner_occupied"]["certainty"] == "unknown"
    assert f["co_year_approx"] == {**f["co_year_approx"], "value": 1978, "certainty": "approximate"}


@pytest.mark.parametrize("street, retried", [
    ("397 05TH AV", "397 5TH AV"), ("5164 03RD ST", "5164 3RD ST"), ("1801 08TH AV", "1801 8TH AV"),
    ("21 GUERRERO ST", "21 GUERRERO ST"), ("100 10TH ST", "100 10TH ST"),
])
def test_retry_street_strips_zero_padded_ordinals(street, retried):
    assert retry_street(street) == retried


def test_batch_input_omits_nj_zip():
    rows = batch_input([addr(), addr(address_id="A1", state="MA", postal_city="Dorchester", zip="02124",
                                     source_dataset="Boston Property Assessment FY2026")])
    assert rows == "A9999,1 MAIN ST,Hoboken,NJ,\nA1,1 MAIN ST,Dorchester,MA,02124\n"


def _geo(place: str | None, basename: str | None):
    return {"lonlat": "-74.03,40.74", "geographies": {
        "States": [{"STUSAB": "NJ", "NAME": "New Jersey"}],
        "Counties": [{"NAME": "Hudson County", "GEOID": "34017"}],
        "Incorporated Places": [{"NAME": place, "BASENAME": basename, "GEOID": "3432250"}] if place else [],
        "County Subdivisions": [], "Census Designated Places": []}}


BATCH = parse_batch('"A9999","1 MAIN ST, Hoboken, NJ, ","Match","Non_Exact","1 MAIN ST, HOBOKEN, NJ, 07030",'
                    '"-74.03,40.74","1","L","34","017","000100","1000"\n')


def test_stack_agrees_differs_and_fallback():
    a = addr()
    s = build_stack(a, BATCH["A9999"], _geo("Hoboken city", "Hoboken"))
    assert (s["city"], s["city_check"], s["match_quality"], s["source"]) == ("Hoboken, NJ", "agrees", "non_exact", "census")
    assert s["county"]["name"] == "Hudson County" and [x["level"] for x in s["levels"]] == ["state", "city"]

    d = build_stack(a, BATCH["A9999"], _geo("Jersey City city", "Jersey City"))
    assert (d["city"], d["city_check"]) == ("Jersey City, NJ", "differs")  # geocoder wins
    assert discrepancies([d])[0]["kind"] == "city_differs"

    f = build_stack(a, {"address_id": "A9999", "match": "No_Match"}, None)
    assert (f["source"], f["city"], f["certainty"], f["match_quality"]) == ("dataset_fallback", "Hoboken, NJ", "low", "no_match")

    u = build_stack(a, BATCH["A9999"], _geo(None, None))
    assert u["city"] is None and u["city_check"] == "no_place" and [x["level"] for x in u["levels"]] == ["state"]
