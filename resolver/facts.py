"""Building facts per address: value + source + certainty (``data/building_facts.json``).

* ``units``: ``range`` [min, max] (max null = open-ended) with a certainty:
  ``exact`` (units column), ``parsed`` (count written in a NJ use_description, e.g.
  ``3S-F-D-6U-NH``), ``range`` (implied by the use code, ``data/use_code_map.yaml``) or
  ``unknown``. A units column that contradicts the description or the code is reported as a
  warning; the column wins, except when it equals the description's commercial-unit count
  (Hoboken A0227: units=2 next to ``13B-93U-2C-G`` -> 93 units, 2 commercial).
* ``year_built``: integer or unknown.
* ``co_year_approx``: year_built standing in for the certificate-of-occupancy date, which the
  data does not have (guide §4.1); always marked approximate.
* ``use_flags``: section8, coop, affordable, tic, elderly, mixed_use, luxury, single_family,
  condo — each true / false / null (``data/use_code_map.yaml``: matches, ``flag_domains`` and
  the apartment-building class).
* ``use_class``: apartment_building for every row (assessor class), so hotel, dormitory,
  care-facility... exemptions are refuted.
* ``owner_type`` / ``owner_occupied``: always unknown (no owner data in the sample).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from extractor import config

from .addresses import Address, addresses_sha256, load_addresses, use_code_map

FACTS_PATH: Path = config.DATA_DIR / "building_facts.json"
NJ_DATASET = "NJOGIS Parcels & MOD-IV Composite"

# "21U" = 21 dwelling units; "16UG" / "3UG" is not (garage), "2C" = 2 commercial units.
_UNITS_TOKEN = re.compile(r"(?<![\d.])(\d+)\s*U(?![A-Z])")
_UG_TOKEN = re.compile(r"(?<![\d.])\d+UG\b")
_COMMERCIAL = re.compile(r"(?<![\d.])(\d+)C\b")
_LETTER_O = re.compile(r"(?<=\d)O(?=U\b|U-)")  # "5B-1OU" -> "5B-10U"


def parse_nj_units(desc: str) -> tuple[int | None, list[str]]:
    """Dwelling units written in a MOD-IV building description; several buildings separated by
    "/" are summed. Returns (units or None, notes)."""
    notes = []
    fixed = _LETTER_O.sub("0", desc)
    if fixed != desc:
        notes.append(f"letter O read as zero: {desc!r} -> {fixed!r}")
    counts = [int(n) for part in fixed.split("/") for n in _UNITS_TOKEN.findall(part)]
    if "/" in fixed and len(counts) > 1:
        notes.append(f"{len(counts)} buildings summed: {' + '.join(map(str, counts))}")
    if _UG_TOKEN.search(fixed):
        notes.append(f"'{_UG_TOKEN.search(fixed).group(0)}' not read as dwelling units (garage)")
    return (sum(counts) if counts else None), notes


def _matches(entry: dict, a: Address) -> bool:
    if entry.get("dataset") and entry["dataset"] != a.source_dataset:
        return False
    if "use_code" in entry and not re.fullmatch(entry["use_code"], a.use_code):
        return False
    if "use_description" in entry and not re.search(entry["use_description"], a.use_description, re.I):
        return False
    return True


def _code_range(a: Address) -> dict | None:
    return next((e for e in use_code_map()["unit_ranges"] if _matches(e, a)), None)


def _within(n: int, lo: int | None, hi: int | None) -> bool:
    return (lo is None or n >= lo) and (hi is None or n <= hi)


def units_fact(a: Address, warnings: list[dict]) -> dict:
    def warn(code: str, msg: str) -> None:
        warnings.append({"address_id": a.address_id, "field": "units", "code": code, "message": msg})

    code = _code_range(a)
    lo, hi = code["units"] if code else (None, None)
    column = int(a.units) if a.units.isdigit() else None
    parsed, notes = parse_nj_units(a.use_description) if a.source_dataset == NJ_DATASET else (None, [])
    for n in notes:
        warn("description_parse", n)

    if column is not None and parsed is not None and column != parsed:
        commercial = [int(x) for x in _COMMERCIAL.findall(a.use_description)]
        if column in commercial:
            warn("column_is_commercial_count",
                 f"units column {column} equals the commercial count in {a.use_description!r}; "
                 f"using {parsed} dwelling units from the description")
            column = None
        else:
            warn("column_vs_description", f"units column {column} != description {a.use_description!r} ({parsed})")

    if column is not None:
        fact = {"range": [column, column], "certainty": "exact", "source": "units column"}
        n = column
    elif parsed is not None:
        fact = {"range": [parsed, parsed], "certainty": "parsed", "source": f"use_description {a.use_description!r}"}
        n = parsed
    elif code:
        return {"range": [lo, hi], "certainty": "range", "source": f"use_code {a.use_code!r}", "basis": code["basis"]}
    else:
        return {"range": None, "certainty": "unknown", "source": None,
                "basis": f"no units column, no count in the description, use_code {a.use_code!r} implies no range"}
    if code and not _within(n, lo, hi):
        warn("value_vs_use_code", f"{fact['certainty']} value {n} outside use_code {a.use_code!r} range "
                                  f"[{lo}, {hi}] ({code['basis']}); value kept")
    return fact


def use_flags(a: Address) -> dict:
    """Every flag of ``all_flags``: true (matched), false (the dataset's codes distinguish it, or
    the apartment-building class rules it out) or null (unknown)."""
    m = use_code_map()
    out: dict = {f: {"value": None, "source": None, "basis": "the use code does not say"} for f in m["all_flags"]}
    domain = m["flag_domains"].get(a.source_dataset)
    for f in domain["flags"] if domain else []:
        out[f] = {"value": False, "source": "use_code", "basis": domain["basis"]}
    for f in m["apartment_class"]["false_flags"]:
        out[f] = {"value": False, "source": "use_code", "basis": m["apartment_class"]["basis"]}
    for e in m["flags"]:
        if _matches(e, a):
            out[e["flag"]] = {"value": True, "source": "use_code" if "use_code" in e else "use_description",
                              "basis": e["basis"]}
    return out


def building_facts(a: Address, warnings: list[dict]) -> dict:
    year = int(a.year_built) if a.year_built.isdigit() else None
    unknown_owner = {"value": None, "certainty": "unknown",
                     "basis": "the sample has no owner data (owner names deliberately excluded, guide §4.1)"}
    return {
        "address_id": a.address_id,
        "dataset_city": a.dataset_city,
        "state": a.state,
        "units": units_fact(a, warnings),
        "year_built": ({"value": year, "certainty": "exact", "source": "year_built column"} if year
                       else {"value": None, "certainty": "unknown", "source": None}),
        "co_year_approx": ({"value": year, "certainty": "approximate",
                            "basis": "year_built as a proxy; the certificate-of-occupancy date is not in the data "
                                     "(guide §4.1): a cutoff falling inside this year is unknown"} if year
                           else {"value": None, "certainty": "unknown", "basis": "no year_built"}),
        "use_flags": use_flags(a),
        "use_class": {"value": use_code_map()["apartment_class"]["use_class"], "certainty": "inferred",
                      "basis": use_code_map()["apartment_class"]["basis"]},
        "owner_type": unknown_owner,
        "owner_occupied": unknown_owner,
    }


def build_facts(addresses: list[Address] | None = None) -> dict:
    addresses = addresses if addresses is not None else load_addresses()
    warnings: list[dict] = []
    facts = {a.address_id: building_facts(a, warnings) for a in addresses}
    return {"source": "participant-final-no-hour16 3/data/sample_addresses.csv",
            "source_sha256": addresses_sha256(), "facts": facts, "warnings": warnings}


def write_facts(path: Path | None = None) -> dict:
    data = build_facts()
    (path or FACTS_PATH).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return data


def summary(data: dict) -> list[dict]:
    """Per city: share of addresses with exact / parsed / range / unknown units, and year_built."""
    by: dict[str, list[dict]] = {}
    for f in data["facts"].values():
        by.setdefault(f["dataset_city"], []).append(f)
    rows = []
    for city, fs in sorted(by.items(), key=lambda kv: (kv[0][-2:], kv[0])):
        c = Counter(f["units"]["certainty"] for f in fs)
        flags = Counter(k for f in fs for k, v in f["use_flags"].items() if v["value"])
        rows.append({"city": city, "n": len(fs), **{k: c.get(k, 0) for k in ("exact", "parsed", "range", "unknown")},
                     "year_built": sum(1 for f in fs if f["year_built"]["value"]), "flags": dict(flags)})
    return rows
