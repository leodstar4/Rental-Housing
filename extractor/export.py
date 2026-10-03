"""``RuleInternal[]`` -> ``out/rules.json`` (``{"rules": [...]}``).

Every record is validated with ``jsonschema`` against the official schema; the
export fails (no partial file written) if any record is invalid.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import RuleInternal, RuleOut


def coverage_to_out(rule: RuleInternal) -> str | dict | None:
    """Render ``rule.coverage`` for the ``coverage_conditions`` field (object
    with only the non-null tests, falling back to ``coverage_text``)."""
    raise NotImplementedError


def to_rule_out(rule: RuleInternal, as_of: date) -> RuleOut:
    """Project one internal rule to the official shape, computing ``status``
    for ``as_of`` and formatting ``effective_date`` as ``YYYY[-MM[-DD]]``."""
    raise NotImplementedError


def export_rules(rules: list[RuleInternal], as_of: date, path: Path | None = None) -> Path:
    """Write ``{"rules": [...]}`` (sorted by ``team_rule_id``, UTF-8, indent 2).

    Raises:
        ValueError: listing every schema error, before anything is written.
    """
    raise NotImplementedError


def load_internal(path: Path) -> list[RuleInternal]:
    """Reload the internal snapshot (``out/rules_internal.json``) so ``export
    --as-of`` can re-run without calling the LLM."""
    raise NotImplementedError
