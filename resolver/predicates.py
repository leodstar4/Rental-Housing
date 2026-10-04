"""Predicate trees over building facts (shared by compile_exemptions.py and coverage.py).

Grammar (JSON)::

    {"and": [P, ...]}  {"or": [P, ...]}  {"not": P}
    {"const": true|false}
    {"fact": F, "op": "<"|"<="|"=="|"!="|">="|">"|"in", "value": V}
    {"missing": "<fact the data does not have, in plain words>"}      # always unknown

Facts ``F`` and their value types are in ``FACTS``.
"""

from __future__ import annotations

import json
from datetime import date

USE_FLAGS = ["section8", "coop", "affordable", "tic", "elderly", "mixed_use", "luxury", "single_family", "condo"]
USE_CLASSES = ["apartment_building", "hotel_transient", "dormitory", "care_facility", "hospital",
               "religious_facility", "detention", "mobilehome", "shelter_transitional"]
OWNER_TYPES = ["natural_person", "family_trust", "llc_natural_persons", "llc_corporate_member", "corporation",
               "reit", "nonprofit", "nonprofit_cooperative", "government", "university", "religious_organization",
               "real_estate_licensee", "other"]

#: fact -> (value type, description for the LLM prompt)
FACTS: dict[str, tuple[str, str]] = {
    "units": ("int", "number of dwelling units in the building / property"),
    "year_built": ("int", "year the building was built"),
    "co_date": ("date", "date of the first certificate of occupancy (ISO date)"),
    "building_age": ("int", "years since the certificate of occupancy / construction, at the query date"),
    **{f"use.{f}": ("bool", f"the property is {f.replace('_', ' ')}" + {
        "section8": " (project-based Section 8 / HUD-subsidized building)",
        "coop": " (a housing cooperative)", "affordable": " (deed- or regulatory-restricted affordable housing)",
        "tic": " (tenancy-in-common building)", "elderly": " (housing for the elderly)",
        "mixed_use": " (residential over commercial)", "luxury": " (luxury apartments)",
        "single_family": " (a single-family home, one dwelling unit on its own)",
        "condo": " (a condominium unit / condominium-owned)"}[f]) for f in USE_FLAGS},
    "use_class": ("enum", "what the property is: " + ", ".join(USE_CLASSES)),
    "owner_type": ("enum", "legal type of the owner: " + ", ".join(OWNER_TYPES)),
    "owner_occupied": ("bool", "an owner lives on the property as principal residence"),
}
OPS = {"<", "<=", "==", "!=", ">=", ">", "in"}


class PredicateError(ValueError):
    pass


def validate(p: object) -> None:
    """Raise ``PredicateError`` unless ``p`` follows the grammar."""
    if not isinstance(p, dict) or len(p) == 0:
        raise PredicateError(f"not a predicate: {p!r}")
    if "and" in p or "or" in p:
        args = p.get("and", p.get("or"))
        if len(p) != 1 or not isinstance(args, list) or not args:
            raise PredicateError(f"bad and/or: {p!r}")
        for a in args:
            validate(a)
    elif "not" in p:
        if len(p) != 1:
            raise PredicateError(f"bad not: {p!r}")
        validate(p["not"])
    elif "const" in p:
        if len(p) != 1 or not isinstance(p["const"], bool):
            raise PredicateError(f"bad const: {p!r}")
    elif "missing" in p:
        if len(p) != 1 or not isinstance(p["missing"], str) or not p["missing"].strip():
            raise PredicateError(f"bad missing: {p!r}")
    elif "fact" in p:
        if set(p) != {"fact", "op", "value"}:
            raise PredicateError(f"comparison needs exactly fact/op/value: {p!r}")
        f, op, v = p["fact"], p["op"], p["value"]
        if f not in FACTS:
            raise PredicateError(f"unknown fact {f!r}")
        if op not in OPS:
            raise PredicateError(f"unknown op {op!r}")
        kind = FACTS[f][0]
        vals = v if op == "in" else [v]
        if op == "in" and not isinstance(v, list):
            raise PredicateError(f"'in' needs a list: {p!r}")
        for x in vals:
            ok = {"int": isinstance(x, int) and not isinstance(x, bool), "bool": isinstance(x, bool),
                  "date": isinstance(x, str) and _is_date(x), "enum": isinstance(x, str)}[kind]
            if not ok:
                raise PredicateError(f"value {x!r} is not a {kind} for {f}")
        if kind == "bool" and op not in ("==", "!="):
            raise PredicateError(f"{f} is boolean: use == or !=")
    else:
        raise PredicateError(f"unknown node: {p!r}")


def _is_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def render(p: dict) -> str:
    """Compact human-readable form: ``units <= 3 AND owner_occupied == true``."""
    if "and" in p or "or" in p:
        k = "and" if "and" in p else "or"
        parts = [render(a) for a in p[k]]
        return parts[0] if len(parts) == 1 else "(" + f" {k.upper()} ".join(parts) + ")"
    if "not" in p:
        return f"NOT {render(p['not'])}"
    if "const" in p:
        return "TRUE" if p["const"] else "FALSE"
    if "missing" in p:
        return f"MISSING[{p['missing']}]"
    return f"{p['fact']} {p['op']} {json.dumps(p['value'])}"


def facts_used(p: dict) -> set[str]:
    if "and" in p or "or" in p:
        return set().union(*(facts_used(a) for a in p.get("and", p.get("or"))))
    if "not" in p:
        return facts_used(p["not"])
    return {p["fact"]} if "fact" in p else set()


#: JSON schema of a predicate for the LLM tool (recursive via $defs).
PREDICATE_SCHEMA_DEFS = {
    "predicate": {
        "description": "Predicate tree over building facts.",
        "anyOf": [
            {"type": "object", "properties": {"and": {"type": "array", "items": {"$ref": "#/$defs/predicate"}}},
             "required": ["and"], "additionalProperties": False},
            {"type": "object", "properties": {"or": {"type": "array", "items": {"$ref": "#/$defs/predicate"}}},
             "required": ["or"], "additionalProperties": False},
            {"type": "object", "properties": {"not": {"$ref": "#/$defs/predicate"}},
             "required": ["not"], "additionalProperties": False},
            {"type": "object", "properties": {"const": {"type": "boolean"}}, "required": ["const"],
             "additionalProperties": False},
            {"type": "object", "properties": {"missing": {"type": "string"}}, "required": ["missing"],
             "additionalProperties": False},
            {"type": "object", "properties": {
                "fact": {"type": "string", "enum": sorted(FACTS)},
                "op": {"type": "string", "enum": sorted(OPS)},
                "value": {"anyOf": [{"type": "integer"}, {"type": "boolean"}, {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}}]}},
             "required": ["fact", "op", "value"], "additionalProperties": False},
        ],
    }
}
