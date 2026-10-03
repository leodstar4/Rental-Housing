"""resolver/compile_exemptions.py: code translation and safeguards (offline, no LLM)."""

from __future__ import annotations

import pytest

from resolver.compile_exemptions import (
    assemble, check_results, contradicts, scope_hint, structured_exemption, use_type_predicate,
)
from resolver.predicates import PredicateError, render, validate


@pytest.mark.parametrize("values, rendered", [
    (["dormitory"], 'use_class == "dormitory"'),
    (["condominium", "townhome"], '(use.condo == true OR use.condo == true)'),
    (["public housing", "Section 8"], '(owner_type == "government" OR use.section8 == true)'),
    (["room in owner-occupied single home"], '(use.single_family == true AND owner_occupied == true)'),
    (["single-sex residence"], "MISSING[use type: single-sex residence]"),
])
def test_use_type_terms(values, rendered):
    assert render(use_type_predicate(values)[0]) == rendered


def test_roommate_is_unit_level():
    pred, _, unit = use_type_predicate(["transient hotel", "owner's roommate"])
    assert render(pred) == 'use_class == "hotel_transient"' and unit == ["owner's roommate"]


def test_owner_portfolio_threshold_is_not_building_units():
    e = {"condition": "may not apply to any rental unit owned by a person or entity owning less than ten rental units",
         "field": "units", "op": "<", "value": 10}
    pred, qualify, _ = structured_exemption(e)
    assert render(pred) == "(units < 10 AND MISSING[owner's total rental units (portfolio)])" and not qualify


def test_owner_exemption_needs_llm_qualifier():
    pred, qualify, _ = structured_exemption({"condition": "Owner-occupied two- or three-family dwellings",
                                             "field": "owner_occupied", "op": "==", "value": True})
    assert render(pred) == "owner_occupied == true" and qualify


ITEMS = [{"ref": "E0", "kind": "exemption", "text": "x"}, {"ref": "NOTES", "kind": "free_text", "text": "y"}]


@pytest.mark.parametrize("results, problem", [
    ([], "E0 needs exactly one result"),
    ([{"ref": "E0", "kind": "exemption", "predicate": {"not": {"fact": "use_class", "op": "==", "value": "detention"}}}],
     "do not negate"),
    ([{"ref": "E0", "kind": "exemption", "predicate": {"const": True}}], "do not return TRUE"),
    ([{"ref": "E0", "kind": "exemption", "predicate": {"fact": "units", "op": "<=", "value": "four"}}], "not a int"),
    ([{"ref": "E0", "kind": "exemption", "predicate": None},
      {"ref": "NOTES", "kind": "qualifier", "predicate": {"const": True}}], "kind exemption or condition"),
])
def test_llm_answers_rejected(results, problem):
    assert any(problem in b for b in check_results(ITEMS, results))


def test_grammar_validation():
    validate({"and": [{"fact": "units", "op": ">=", "value": 5}, {"missing": "owner type"}]})
    with pytest.raises(PredicateError):
        validate({"fact": "owner_occupied", "op": "<", "value": True})
    with pytest.raises(PredicateError):
        validate({"fact": "parking", "op": "==", "value": True})


@pytest.mark.parametrize("text, scope", [
    ("Property subject to a local just cause ordinance adopted on or before September 1, 2019", "other_law"),
    ("Tenant shares bathroom or kitchen facilities with an owner", "unit_or_tenancy"),
    ("Coordinator does not include a government entity setting rents", "unit_or_tenancy"),
    ("Replacement units are covered by the RSO even if built later", "other_law"),
    ("Owner-occupied two- or three-family dwellings", None),
])
def test_scope_hints(text, scope):
    assert (scope_hint(text) or (None,))[0] == scope


def test_free_text_condition_negating_structured_is_flagged():
    code = [{"predicate": {"fact": "co_date", "op": "<=", "value": "1979-06-13"}}]
    assert contradicts({"fact": "co_date", "op": ">", "value": "1979-06-13"}, code)
    assert not contradicts({"fact": "co_date", "op": "<=", "value": "1979-06-13"}, code)


def test_assemble_free_text_conditions_go_to_review_and_restated_scope_is_dropped():
    rule = {"team_rule_id": "NJ-RENT-03", "jurisdiction": "NJ", "category": "rent_increase_limits", "title": "t",
            "requirement": "r", "exemptions": None,
            "coverage_conditions": {"property_types_covered": ["newly constructed multiple dwellings"],
                                    "notes": "Exemption lasts 30 years from completion of construction."}}
    age = {"fact": "building_age", "op": "<=", "value": 30}
    out = {"model": "m", "prompt_version": "v", "results": [
        {"ref": "PT", "kind": "property_types", "scope": "building", "text": "new",
         "predicate": {"and": [{"fact": "units", "op": ">=", "value": 2}, age]}, "irreducible": False},
        {"ref": "NOTES", "kind": "exemption", "scope": "building", "text": "Exemption lasts 30 years",
         "predicate": age, "irreducible": False},
        {"ref": "NOTES", "kind": "condition", "scope": "building", "text": "only new", "predicate": age,
         "irreducible": False}]}
    c = assemble(rule, out)
    assert [x["scope"] for x in c["conditions"]] == ["building", "review"]
    assert [x["scope"] for x in c["exemptions"]] == ["review"]
