"""Honest per-zone listing price summary (no LLM, no network, deterministic).

The only figures Renta MX publishes about price come from the listings that USERS posted
(``basis = "viviendas_publicadas"``) — never a scraped portal, never an invented number. INEGI
``pct_viviendas_alquiladas`` is a statistic, not a price, and is handled elsewhere (zones.json
stats), with a visually distinct treatment in the UI.

``listing_price_summary`` is pure: given a list of listing records (store dicts), it returns the
count and, only when there are at least ``MIN_COUNT_FOR_STATS`` sound records, the min / median /
max monthly rent in MXN. With a smaller sample it exposes only ``count`` and a ``reason`` so the
UI never shows a price built from one or two listings. Corrupt records (missing or non-numeric
``monthly_rent_mxn``, zero or negative, NaN/inf) are ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

#: A price summary is published only from this many sound listings or more (team decision: a
#: min/median/max over one or two user posts is noise, not a market signal).
MIN_COUNT_FOR_STATS = 3
CURRENCY = "MXN"
BASIS = "viviendas_publicadas"


def _rent(record: object) -> Decimal | None:
    """The monthly rent of one listing record as a positive, finite Decimal, or None if the
    record is corrupt (not a dict, missing/empty field, non-numeric, NaN/inf, or <= 0)."""
    if not isinstance(record, dict):
        return None
    raw = record.get("monthly_rent_mxn")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def _median(values: list[Decimal]) -> Decimal:
    """Median of a non-empty sorted-insensitive list; even length averages the two middle values."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _num(value: Decimal) -> float | int:
    """JSON-friendly number: int when the amount is whole, else float (medians can be .5)."""
    return int(value) if value == value.to_integral_value() else float(value)


def listing_price_summary(listings: list[dict] | None, *, now: datetime | None = None) -> dict:
    """Deterministic price summary over user-published listings.

    Always returns ``count`` (sound records only), ``currency``, ``basis``, ``min_count_for_stats``
    and ``as_of`` (UTC ISO of the computation). ``min`` / ``median`` / ``max`` are present only when
    ``count >= MIN_COUNT_FOR_STATS``; otherwise ``has_stats`` is False and ``reason`` explains why,
    so no price is published from too small a sample.
    """
    rents = [r for r in (_rent(x) for x in (listings or [])) if r is not None]
    as_of = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z")
    out = {"count": len(rents), "currency": CURRENCY, "basis": BASIS,
           "min_count_for_stats": MIN_COUNT_FOR_STATS, "as_of": as_of}
    if len(rents) < MIN_COUNT_FOR_STATS:
        out["has_stats"] = False
        out["reason"] = "insufficient_sample"
        return out
    out["has_stats"] = True
    out["min"] = _num(min(rents))
    out["median"] = _num(_median(rents))
    out["max"] = _num(max(rents))
    return out
