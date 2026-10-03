"""Validation: literal-quote verification, dispositions, final confidence, JSON Schema.

Quote cascade (rule ``quoted_span``), recorded as ``quote_location.match_type``:

a) ``exact``       substring of ``raw_text``.
b) ``normalized``  whitespace/line breaks, curly quotes, dashes, NBSP folded
                   (``clean.locate_quote``); the span is replaced by the literal raw text.
c) ``fuzzy``       rapidfuzz ``partial_ratio`` >= 95 on the normalized texts; the span
                   is replaced by the aligned raw fragment (widened to word boundaries).
d) ``retry``       ONE LLM call asks for a literal quote for that rule; a-c re-run on it.
e) otherwise       ``rejected`` / ``citation_unverified`` (out/rejected.json + audit).

Date quotes (``effective_dates``, ``enacted_date``, ``sunset_date``) run a-c (no LLM
retry). A date whose quote does not verify is dropped, not the rule. A non-derived date
must also have its VALUE inside its quote in some common format (``dates.value_in_text``:
"October 6, 2025", "Oct. 6, 2025", "10/06/2025", "3/01/26"...). A ``derived`` date
additionally needs a verified ``enacted_date`` (its base date); otherwise it is dropped.

Each verified ``effective_dates`` claim gets a ``kind`` (effective / operative /
amendment / enacted): rules first (``dates.classify_kind``), then, only for ambiguous
wording, a small LLM (``classify`` callable). Date conflicts and the "enacted without
date" factor only look at ``kind == "effective"``.

Dispositions here: ``accepted``, ``held`` (``no_citation``), ``rejected``
(``citation_unverified``). Administrative rules are linked or held later, across
documents, in ``normalize.py`` (``administrative_unlinked``).

Final confidence (also documented in README)::

    model confidence
      x match factor   exact 1.0 | normalized 0.97 | fuzzy 0.85 | retry 0.8
      x 0.8            if is_secondary_source
      x 0.9            if stage == enacted and no verified (or derived) date of kind effective
      x 0.85           if >1 distinct verified dates of kind effective (also conflict_flag)
    capped at 0.5      if stage == unknown (also conflict_flag, note "stage unclear")
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator
from rapidfuzz import fuzz

from . import config
from .clean import _normalize_with_map, locate_quote
from .corpus import Document
from .dates import classify_kind, value_in_text
from .models import DateClaim, LegalStage, MatchType, QuoteLocation, RuleInternal, RuleOut

MATCH_FACTOR: dict[str, float] = {"exact": 1.0, "normalized": 0.97, "fuzzy": 0.85, "retry": 0.8}
FUZZY_MIN_SCORE = 95.0
FUZZY_MIN_CHARS = 20  # below this, partial_ratio is too permissive
SECONDARY_FACTOR = 0.8
ENACTED_NO_DATE_FACTOR = 0.9
DATE_CONFLICT_FACTOR = 0.85
UNKNOWN_STAGE_CAP = 0.5

#: ``(rule, doc) -> literal quote or None``; one LLM call (llm.retry_quote) in production.
Requote = Callable[[RuleInternal, Document], "str | None"]
#: ``(claim, rule, context) -> kind or None`` for ambiguous dates; llm.classify_date_kind in production.
ClassifyDate = Callable[[DateClaim, RuleInternal, str], "str | None"]
CONTEXT_CHARS = 250


# --------------------------------------------------------------------------- #
# Span matching
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SpanMatch:
    """A verified span: ``text == raw_text[raw_start:raw_end]``."""

    match_type: MatchType
    raw_start: int
    raw_end: int
    text: str
    score: float | None = None


def _widen_to_words(raw: str, a: int, b: int) -> tuple[int, int]:
    while a > 0 and raw[a - 1].isalnum():
        a -= 1
    while b < len(raw) and raw[b].isalnum():
        b += 1
    return a, b


def match_span(raw: str, span: str, *, allow_fuzzy: bool = True) -> SpanMatch | None:
    """Cascade a) exact, b) normalized, c) fuzzy. Returns the literal raw fragment."""
    span = span.strip()
    if not span:
        return None
    k = raw.find(span)
    if k >= 0:
        return SpanMatch("exact", k, k + len(span), span)
    m = locate_quote(raw, span)
    if m is not None:
        return SpanMatch("normalized", m.raw_start, m.raw_end, raw[m.raw_start : m.raw_end])
    if not allow_fuzzy:
        return None
    norm_q, _ = _normalize_with_map(span, fold=True)
    if len(norm_q) < FUZZY_MIN_CHARS:
        return None
    norm_raw, idx = _normalize_with_map(raw, fold=True)
    al = fuzz.partial_ratio_alignment(norm_q, norm_raw, score_cutoff=FUZZY_MIN_SCORE)
    if al is None or al.dest_end <= al.dest_start:
        return None
    a, b = _widen_to_words(raw, idx[al.dest_start], idx[al.dest_end - 1] + 1)
    return SpanMatch("fuzzy", a, b, raw[a:b], round(al.score, 1))


# --------------------------------------------------------------------------- #
# Per-rule validation
# --------------------------------------------------------------------------- #


def _verify_date(
    claim: DateClaim, raw: str, *, base_ok: bool
) -> tuple[DateClaim | None, str | None, SpanMatch | None]:
    """Return ``(verified claim, None, match)`` or ``(None, reason, None)``."""
    if not claim.quoted_span:
        return None, "no quote", None
    m = match_span(raw, claim.quoted_span)
    if m is None:
        return None, "quote not found", None
    if claim.derived:
        if not base_ok:
            return None, "derived but base (enacted) date not verified", None
    elif claim.value is not None and not value_in_text(claim.value, m.text):
        return None, f"date value {claim.value} not found in its quote", None
    return claim.model_copy(update={"quoted_span": m.text, "verified": True}), None, m


def _set_conflict(rule: RuleInternal, note: str) -> None:
    rule.conflict_flag = True
    rule.conflict_note = f"{rule.conflict_note}; {note}" if rule.conflict_note else note


def validate_rule(
    rule: RuleInternal, doc: Document, requote: Requote | None = None, classify: ClassifyDate | None = None
) -> RuleInternal:
    """Verify quotes/dates, classify date kinds, set disposition and final confidence."""
    r = rule.model_copy(deep=True)
    raw = doc.raw_text

    # 1. Rule quote: a-c, then d (one LLM retry), else reject.
    m = match_span(raw, r.quoted_span)
    match_type: MatchType | None = m.match_type if m else None
    if m is None and requote is not None:
        new_span = requote(r, doc)
        if new_span:
            m = match_span(raw, new_span)
            match_type = "retry" if m else None
        r.validation_errors.append(f"quote retry: {'verified' if m else 'failed'}")
    if m is None:
        r.disposition, r.disposition_reason = "rejected", "citation_unverified"
        r.validation_errors.append(f"quoted_span not found in {doc.doc_id}")
        return r
    r.quoted_span = m.text
    r.quote_location = QuoteLocation(raw_start=m.raw_start, raw_end=m.raw_end, match_type=match_type, score=m.score)

    # 2. Dates (enacted first: it is the base of derived dates).
    if r.enacted_date is not None:
        r.enacted_date, why, _ = _verify_date(r.enacted_date, raw, base_ok=False)
        if why:
            r.validation_errors.append(f"enacted_date dropped: {why}")
        else:
            r.enacted_date.kind, r.enacted_date.kind_source = "enacted", "rule"
    base_ok = bool(r.enacted_date and r.enacted_date.verified)
    if r.sunset_date is not None:
        r.sunset_date, why, _ = _verify_date(r.sunset_date, raw, base_ok=base_ok)
        if why:
            r.validation_errors.append(f"sunset_date dropped: {why}")
    kept: list[DateClaim] = []
    for claim in r.effective_dates:
        v, why, dm = _verify_date(claim, raw, base_ok=base_ok)
        if v is None:
            r.validation_errors.append(f"effective_date {claim.raw!r} dropped: {why}")
            continue
        before = raw[max(0, dm.raw_start - CONTEXT_CHARS) : dm.raw_start]
        kind = classify_kind(v.quoted_span, v.raw, before, derived=v.derived,
                             administrative=r.stage == LegalStage.ADMINISTRATIVE)
        source = "rule"
        if kind is None and classify is not None:
            kind = classify(v, r, raw[max(0, dm.raw_start - CONTEXT_CHARS) : dm.raw_end + CONTEXT_CHARS])
            source = "llm"
        if kind is None:  # still ambiguous: keep as effective, but say so
            kind, source = "effective", "rule"
            r.validation_errors.append(f"date kind ambiguous for {v.raw!r}; assumed effective")
        v.kind, v.kind_source = kind, source
        kept.append(v)
    r.effective_dates = kept

    # 3. Dispositions (administrative rules are linked or held in normalize.py).
    if not r.citation:
        r.disposition, r.disposition_reason = "held", "no_citation"

    # 4. Final confidence + conflict flags (effective-kind dates only).
    effective = [d for d in r.effective_dates if d.kind == "effective"]
    conf = (r.model_confidence if r.model_confidence is not None else 1.0) * MATCH_FACTOR[match_type]
    if r.is_secondary_source:
        conf *= SECONDARY_FACTOR
    if r.stage == LegalStage.ENACTED and not any(d.value for d in effective):
        conf *= ENACTED_NO_DATE_FACTOR
    distinct = sorted({d.value for d in effective if d.value is not None})
    if len(distinct) > 1:
        conf *= DATE_CONFLICT_FACTOR
        _set_conflict(r, "conflicting effective dates: " + ", ".join(map(str, distinct)))
    if r.stage == LegalStage.UNKNOWN:
        conf = min(conf, UNKNOWN_STAGE_CAP)
        _set_conflict(r, "stage unclear")
    r.confidence = round(conf, 3)
    return r


# --------------------------------------------------------------------------- #
# Per-document validation + report
# --------------------------------------------------------------------------- #


@dataclass
class ValidationReport:
    """Counts for one document (or the whole run, via ``merge``)."""

    candidates: int = 0
    match_types: Counter = field(default_factory=Counter)  # exact/normalized/fuzzy/retry
    dispositions: Counter = field(default_factory=Counter)  # accepted/held/rejected
    reasons: Counter = field(default_factory=Counter)  # disposition_reason for held/rejected
    retries: int = 0
    dates_dropped: int = 0

    def merge(self, other: ValidationReport) -> ValidationReport:
        return ValidationReport(
            self.candidates + other.candidates,
            self.match_types + other.match_types,
            self.dispositions + other.dispositions,
            self.reasons + other.reasons,
            self.retries + other.retries,
            self.dates_dropped + other.dates_dropped,
        )

    def to_dict(self) -> dict:
        return {
            "candidates": self.candidates,
            "match_types": dict(self.match_types),
            "dispositions": dict(self.dispositions),
            "reasons": dict(self.reasons),
            "quote_retries": self.retries,
            "dates_dropped": self.dates_dropped,
        }


def validate_document(
    rules: list[RuleInternal], doc: Document, requote: Requote | None = None, classify: ClassifyDate | None = None
) -> tuple[list[RuleInternal], ValidationReport]:
    """Validate every candidate of one document."""
    rep = ValidationReport(candidates=len(rules))
    out = []
    for rule in rules:
        v = validate_rule(rule, doc, requote, classify)
        out.append(v)
        if v.quote_location:
            rep.match_types[v.quote_location.match_type] += 1
        rep.dispositions[v.disposition] += 1
        if v.disposition_reason:
            rep.reasons[v.disposition_reason] += 1
        rep.retries += sum(e.startswith("quote retry") for e in v.validation_errors)
        rep.dates_dropped += sum(" dropped: " in e for e in v.validation_errors)
    return out, rep


# --------------------------------------------------------------------------- #
# JSON Schema (export)
# --------------------------------------------------------------------------- #


def load_schema(path: Path | None = None) -> dict:
    """Load ``rule_record.schema.json`` (defaults to ``config.SCHEMA_PATH``)."""
    return json.loads((path or config.SCHEMA_PATH).read_text(encoding="utf-8"))


def validate_schema(record: RuleOut | dict, schema: dict | None = None) -> list[str]:
    """Validate one exported record with ``jsonschema`` (Draft 2020-12).

    Returns human-readable error strings; empty list = valid.
    """
    data = record.model_dump(mode="json") if isinstance(record, RuleOut) else record
    validator = Draft202012Validator(schema or load_schema())
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in validator.iter_errors(data)]
