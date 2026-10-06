"""Honest per-zone price summary (mx/prices.py) and its /mx integration. Offline, deterministic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from mx_support import LISTING, client, make_client, mx_env  # noqa: F401  (pytest fixtures)

from mx.prices import MIN_COUNT_FOR_STATS, listing_price_summary

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def _listings(*rents, cve_ent="09", cve_mun="015") -> list[dict]:
    return [{"id": f"L{i}", "cve_ent": cve_ent, "cve_mun": cve_mun, "created_at": "2026-10-05T00:00:00Z",
             "monthly_rent_mxn": r, "bedrooms": 2} for i, r in enumerate(rents)]


# --------------------------------------------------------------------------- #
# Pure function
# --------------------------------------------------------------------------- #


def test_empty_has_count_zero_and_no_figures():
    s = listing_price_summary([], now=NOW)
    assert s["count"] == 0 and s["has_stats"] is False and s["reason"] == "insufficient_sample"
    assert not ({"min", "median", "max"} & set(s))
    assert s["currency"] == "MXN" and s["basis"] == "viviendas_publicadas"
    assert s["min_count_for_stats"] == MIN_COUNT_FOR_STATS == 3
    assert s["as_of"] == "2026-10-05T12:00:00Z"


def test_none_is_treated_as_empty():
    assert listing_price_summary(None, now=NOW)["count"] == 0


def test_two_listings_have_no_figures():
    s = listing_price_summary(_listings(8000, 12000), now=NOW)
    assert s["count"] == 2 and s["has_stats"] is False
    assert not ({"min", "median", "max"} & set(s))


def test_three_listings_exact_min_median_max():
    s = listing_price_summary(_listings(8000, 12000, 10000), now=NOW)
    assert s["count"] == 3 and s["has_stats"] is True
    assert (s["min"], s["median"], s["max"]) == (8000, 10000, 12000)


def test_four_listings_median_averages_two_middle():
    s = listing_price_summary(_listings(8000, 12000, 10000, 16000), now=NOW)
    # sorted: 8000, 10000, 12000, 16000 -> median = (10000 + 12000) / 2 = 11000
    assert s["count"] == 4 and (s["min"], s["median"], s["max"]) == (8000, 11000, 16000)


def test_median_can_be_fractional():
    s = listing_price_summary(_listings(8000, 9001, 10000, 11000), now=NOW)
    # (9001 + 10000) / 2 = 9500.5
    assert s["median"] == 9500.5


def test_corrupt_records_are_ignored():
    good = _listings(8000, 10000, 12000)
    bad = ["not a dict", {}, {"monthly_rent_mxn": None}, {"monthly_rent_mxn": "abc"},
           {"monthly_rent_mxn": 0}, {"monthly_rent_mxn": -500}, {"monthly_rent_mxn": "NaN"},
           {"monthly_rent_mxn": "Infinity"}, {"monthly_rent_mxn": True}]
    s = listing_price_summary(good + bad, now=NOW)
    assert s["count"] == 3 and (s["min"], s["median"], s["max"]) == (8000, 10000, 12000)


def test_string_and_decimal_rents_parse():
    s = listing_price_summary(_listings("8000", "10000.00", 12000), now=NOW)
    assert s["count"] == 3 and (s["min"], s["median"], s["max"]) == (8000, 10000, 12000)


# --------------------------------------------------------------------------- #
# API integration (fixture data, NOW clock)
# --------------------------------------------------------------------------- #


def _post(c, rent, cve_mun="015"):
    assert c.post("/mx/listings", json={**LISTING, "cve_mun": cve_mun, "monthly_rent_mxn": rent}).status_code == 201


def test_zone_price_summary_empty_then_three(client):
    z = client.get("/mx/zones/09/015").json()
    assert z["price_summary"]["count"] == 0 and z["price_summary"]["has_stats"] is False
    assert "min" not in z["price_summary"]
    for rent in (8000, 12000, 10000):
        _post(client, rent)
    z = client.get("/mx/zones/09/015").json()["price_summary"]
    assert z["count"] == 3 and (z["min"], z["median"], z["max"]) == (8000, 10000, 12000)


def test_other_zone_listings_do_not_count(client):
    for rent in (8000, 12000, 10000):
        _post(client, rent, cve_mun="015")
    _post(client, 50000, cve_mun="002")  # Azcapotzalco: a different zone
    z15 = client.get("/mx/zones/09/015").json()["price_summary"]
    assert z15["count"] == 3 and z15["max"] == 12000  # 50000 of 09/002 excluded
    z02 = client.get("/mx/zones/09/002").json()["price_summary"]
    assert z02["count"] == 1 and z02["has_stats"] is False


def test_zones_list_item_carries_price_summary(client):
    for rent in (8000, 12000, 10000):
        _post(client, rent, cve_mun="015")
    zones = {z["cve_mun"]: z for z in client.get("/mx/zones", params={"cve_ent": "09"}).json()["zones"]}
    assert zones["015"]["price_summary"]["median"] == 10000
    assert zones["002"]["price_summary"]["count"] == 0 and "median" not in zones["002"]["price_summary"]


def test_states_carry_a_price_summary(client):
    for rent in (8000, 12000, 10000):
        _post(client, rent, cve_mun="015")
    states = {s["cve_ent"]: s for s in client.get("/mx/states").json()["states"]}
    assert states["09"]["price_summary"]["count"] == 3 and states["09"]["price_summary"]["median"] == 10000
    assert states["31"]["price_summary"]["count"] == 0  # another state, no listings


def test_price_summary_as_of_uses_the_clock(client):
    assert client.get("/mx/zones/09/015").json()["price_summary"]["as_of"] == "2026-10-05T12:00:00Z"
