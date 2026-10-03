"""Validation: JSON Schema conformance and literal-quote verification.

A rule whose ``quoted_span`` cannot be found in its document's ``raw_text`` is
rejected (guide §8: never invent citations). Matching is whitespace-tolerant
and, as a second pass, typographic-folding-tolerant (``clean.locate_quote``);
the exported span is then *re-sliced from raw_text* so it is verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .corpus import Document
from .models import RuleInternal, RuleOut


@dataclass
class ValidationReport:
    """Outcome for one rule."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_schema(path: Path | None = None) -> dict:
    """Load ``rule_record.schema.json`` (defaults to ``config.SCHEMA_PATH``)."""
    raise NotImplementedError


def validate_schema(record: RuleOut | dict, schema: dict | None = None) -> list[str]:
    """Validate one exported record with ``jsonschema`` (Draft 2020-12).

    Returns human-readable error strings; empty list = valid.
    """
    raise NotImplementedError


def verify_quote(rule: RuleInternal, doc: Document) -> ValidationReport:
    """Check ``rule.quoted_span`` occurs in ``doc.raw_text``.

    On success sets ``rule.quote_location`` and replaces ``rule.quoted_span``
    with the exact raw substring (whitespace-normalised to single spaces only
    if it spans a line break). Warns when the match needed typographic folding
    or crosses a boilerplate cut (``CleanResult.to_raw_span`` is None).
    """
    raise NotImplementedError


def validate_rule(rule: RuleInternal, doc: Document) -> ValidationReport:
    """Quote check + internal sanity (dates parse, jurisdiction is in
    ``doc.jurisdictions``, level matches jurisdiction shape)."""
    raise NotImplementedError
