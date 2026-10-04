"""resolver/coverage.py: Kleene logic and coverage of the compiled rules (offline).

Uses the versioned data/compiled_exemptions.json (real compiled rules) and synthetic building
facts built with resolver.facts.building_facts, so no API and no out/ files are needed.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from extractor import config
from resolver.addresses import Address
from resolver.coverage import Context, Tri, cmp_interval, evaluate
from resolver.facts import building_facts

COMPILED = json.loads((config.DATA_DIR / "compiled_exemptions.json").read_text(encoding="utf-8"))["rules"]
AS_OF = date(2026, 10, 1)
T, F, U = Tri.T, Tri.F, Tri.U

DATASETS = {
    "San Francisco": ("CA", "DataSF wv5m-vpq2 (2025 roll)", "A15", "Apartment 15 Units or more"),
    "Los Angeles": ("CA", "LA County eGIS parcels", "0500", "Five or more apartments"),
    "Berkeley": ("CA", "Alameda County parcels", "7700", "Alameda County use code (5+ units)"),
    "Hoboken": ("NJ", "NJOGIS Parcels & MOD-IV Composite", "4C", "4-S-BT-21U-H"),
    "Boston": ("MA", "Boston Property Assessment FY2026", "A/125", "SUBSD HOUSING S- 8"),
}


def facts(city: str, year: int | None = None, units: int | None = None, **flags) -> dict:
    state, ds, code, desc = DATASETS[city]
    a = Address(address_id="A9999", street_address="1 MAIN ST", postal_city=city, state=state, zip="",
                year_built=str(year or ""), units=str(units or ""), use_code=code, use_description=desc,
                source_dataset=ds, retrieved_at="2026-10-01T22:50Z")
    f = building_facts(a, [])
    for k, v in flags.items():
        f["use_flags"][k] = {"value": v, "source": "test", "basis": "test override"}
    return f


def stack(city: str, source: str = "census") -> dict:
    if city in ("CA", "NJ", "MA"):
        return {"state": city, "city": None, "source": source}
    return {"state": DATASETS[city][0], "city": f"{city}, {DATASETS[city][0]}", "source": source}


def rule(rid: str) -> dict:
    jur = {"SF": "San Francisco, CA", "LA": "Los Angeles, CA", "BRK": "Berkeley, CA", "HOB": "Hoboken, NJ",
           "CAM": "Cambridge, MA"}.get(rid.split("-")[0], rid.split("-")[0])
    return {"team_rule_id": rid, "jurisdiction": jur, "level": "city" if ", " in jur else "state"}


def cov(rid: str, f: dict, city: str, as_of: date = AS_OF, source: str = "census") -> dict:
    return evaluate(rule(rid), COMPILED[rid], f, stack(city, source), as_of)


# --- Kleene logic ---------------------------------------------------------------------------


def test_kleene_tables():
    assert (F & U, T & U, T & T, U & U) == (F, U, T, U)
    assert (T | U, F | U, F | F, U | U) == (T, U, F, U)
    assert (~T, ~F, ~U) == (F, T, U)


@pytest.mark.parametrize("lo, hi, op, v, want", [
    (5, None, ">=", 5, T), (2, 4, ">=", 5, F), (3, 8, ">=", 5, U),
    (7, 30, "<=", 4, F), (1, 4, "<=", 4, T), (4, 8, "<=", 4, U),
    (2, 2, "==", 2, T), (5, None, "==", 2, F), (1, 4, "==", 2, U),
    (5, None, "in", [2, 3], F),
])
def test_interval_comparisons(lo, hi, op, v, want):
    assert cmp_interval(lo, hi, op, v) == want


# --- guide cases ----------------------------------------------------------------------------


@pytest.mark.parametrize("year, want", [(1962, "covered"), (1979, "unknown"), (1985, "not_covered")])
def test_sf_rent_certificate_cutoff(year, want):
    r = cov("SF-RENT-01", facts("San Francisco", year, 20), "San Francisco")
    assert r["coverage"] == want
    if want == "unknown":
        assert r["missing_facts"] == ["certificate of occupancy date (built in cutoff year)"]
    assert r["confidence_coverage"] == 0.8  # certificate date approximated by year_built


@pytest.mark.parametrize("year, want", [(1978, "unknown"), (1960, "covered"), (1990, "not_covered")])
def test_la_rso_certificate_cutoff(year, want):
    assert cov("LA-RENT-01", facts("Los Angeles", year, 20), "Los Angeles")["coverage"] == want


def test_berkeley_without_year_built_is_unknown():
    r = cov("BRK-RENT-01", facts("Berkeley"), "Berkeley")
    assert r["coverage"] == "unknown" and r["missing_facts"][0] == "year_built"
    assert r["confidence_coverage"] == 0.9  # Berkeley units: range 5+ from the use code


@pytest.mark.parametrize("year, age_result, want", [(2011, "U", "unknown"), (2020, "F", "not_covered"),
                                                   (1960, "T", "covered")])
def test_ab1482_rolling_15_years(year, age_result, want):
    # affordable = False: the deed-restriction status is not in the sample data (see next test)
    r = cov("CA-RENT-01", facts("Los Angeles", year, 20, affordable=False), "Los Angeles")
    [age] = [x for x in r["reasons"] if x["predicate"] == "building_age >= 15"]
    assert age["result"] == age_result and r["coverage"] == want


def test_ab1482_affordable_status_presumed_absent():
    f = facts("Los Angeles", 1960, 20)
    r = cov("CA-RENT-01", f, "Los Angeles")
    assert r["coverage"] == "covered"
    assert r["presumptions"] == ["presumed: no evidence of an affordability restriction in assessor data"]
    assert r["confidence_coverage"] == pytest.approx(0.8 * 0.9)
    off = evaluate(rule("CA-RENT-01"), COMPILED["CA-RENT-01"], f, stack("Los Angeles"), AS_OF, presume=False)
    assert off["coverage"] == "unknown" and off["missing_facts"] == ["use.affordable"]


def test_presumption_never_overrides_a_flag_in_the_data():
    # Hoboken CO-OP description: coop flag true -> the co-op conversion rule covers it
    f = facts("Hoboken")
    f["use_flags"]["coop"] = {"value": True, "source": "use_description", "basis": "CO-OP"}
    assert cov("NJ-JUST-02", f, "NJ")["coverage"] == "covered"
    assert cov("NJ-JUST-02", facts("Hoboken"), "NJ")["coverage"] == "not_covered"  # presumed not converted


def test_presumption_scope():
    """Only special-status items presume; owner occupancy, units and year stay unknown in them too."""
    ctx = Context(facts("Berkeley"), stack("Berkeley"), AS_OF, presume=True)
    owner_type = {"fact": "owner_type", "op": "in", "value": ["natural person"]}
    assert ctx.eval(owner_type, []) == U  # generic owner test outside a special-status item
    ctx.special = True
    assert ctx.eval({"fact": "owner_type", "op": "==", "value": "university"}, []) == F
    assert ctx.eval({"missing": "HUD Section 202 subsidy"}, []) == F
    assert ctx.eval({"fact": "use.affordable", "op": "==", "value": True}, []) == F
    assert ctx.eval({"fact": "owner_occupied", "op": "==", "value": True}, []) == U
    assert ctx.eval({"fact": "year_built", "op": "<=", "value": 1978}, []) == U
    assert len(ctx.presumed) == 3


def test_berkeley_status_exemptions_presumed_so_rent_rule_covers_old_building():
    r = cov("BRK-RENT-01", facts("Berkeley", 1960), "Berkeley")
    assert r["coverage"] == "covered" and len(r["presumptions"]) == 3


@pytest.mark.parametrize("rid, city", [("CA-RENT-01", "Los Angeles"), ("CA-JUST-02", "Los Angeles")])
def test_owner_exemptions_refuted_by_building_facts(rid, city):
    """owner-occupied duplex / single-family or condo owned by a natural person, at a 20-unit
    building: the building term is false, so the owner term cannot leave the rule unknown."""
    r = cov(rid, facts(city, 1960, 20, affordable=False), city)
    owner = [x for x in r["reasons"] if x["kind"] == "exemption" and ("owner_occupied" in x["predicate"]
                                                                      or "owner_type" in x["predicate"])]
    assert owner and all(x["result"] == "F" for x in owner)
    assert not {"owner_type", "owner_occupied"} & set(r["missing_facts"])


def test_hoboken_parsed_units_attested_ban_covered():
    f = facts("Hoboken")
    assert f["units"] == {"range": [21, 21], "certainty": "parsed", "source": "use_description '4-S-BT-21U-H'"}
    r = cov("HOB-ALG-A1", f, "Hoboken")
    assert r["coverage"] == "covered" and r["confidence_coverage"] == 1.0


def test_boston_subsidized_without_units_unknown_on_unit_conditions():
    """No Boston/MA rule tests units any more (MA-RENT-01's exemptions are other_law), so the
    unit conditions of JC-RENT-01 (units >= 5, exempt if <= 4) are evaluated on Boston A/125 facts."""
    f = facts("Boston", 1930)
    assert f["units"]["certainty"] == "unknown" and f["use_flags"]["section8"]["value"] is True
    r = evaluate({"team_rule_id": "JC-RENT-01", "jurisdiction": "MA", "level": "state"}, COMPILED["JC-RENT-01"],
                 f, stack("Boston"), AS_OF)
    assert r["coverage"] == "unknown" and r["missing_facts"] == ["units"]
    assert cov("MA-RENT-01", f, "MA")["coverage"] == "covered"  # exemptions deferred (other_law)


def test_rule_outside_the_stack_is_not_evaluated():
    assert cov("SF-RENT-01", facts("Los Angeles", 1960, 20), "Los Angeles") is None
    assert evaluate(rule("CA-RENT-01"), COMPILED["CA-RENT-01"], facts("Boston", 1960), stack("Boston"), AS_OF) is None


def test_fallback_city_lowers_confidence():
    r = cov("SF-RENT-01", facts("San Francisco", 1962, 20), "San Francisco", source="dataset_fallback")
    assert r["coverage"] == "covered" and r["confidence_coverage"] == pytest.approx(0.72)
