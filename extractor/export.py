"""``RuleInternal[]`` -> ``out/rules.json`` (``{"rules": [...]}``).

Only ``accepted`` rules are exported (``held``, ``rejected`` and ``merged`` stay internal).
Every record is validated with ``jsonschema`` against the official schema; the export fails
(no file written) if any record is invalid.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import config
from .models import LegalStage, RuleInternal, RuleOut
from .normalize import kv_equal
from .status import compute_status, effective_date_for
from .validate import load_schema, validate_schema


def coverage_to_out(rule: RuleInternal) -> str | dict | None:
    """Non-null coverage tests (+ text) as an object, or the text alone, or None."""
    c = rule.coverage
    d: dict = {}
    if c is not None:
        for k in ("units_min", "units_max", "year_built_min", "year_built_max",
                  "certificate_of_occupancy_on_or_before", "building_age_min_years"):
            v = getattr(c, k)
            if v is not None:
                d[k] = v.isoformat() if isinstance(v, date) else v
        if c.property_types_covered:
            d["property_types_covered"] = c.property_types_covered
        if c.exemption_conditions:
            d["exemption_conditions"] = [e.model_dump(mode="json") for e in c.exemption_conditions]
        if c.notes:
            d["notes"] = c.notes
    if rule.coverage_text:
        d["text"] = rule.coverage_text
    return d or None


def _key_value(rule: RuleInternal, as_of: date) -> str | None:
    """Legal key value plus the linked administrative figure in force at ``as_of``."""
    current = [d for d in rule.key_value_details
               if (d.effective_from is None or d.effective_from <= as_of)
               and (d.effective_until is None or as_of <= d.effective_until)]
    current.sort(key=lambda d: (d.effective_from or date.min, d.citation or "", d.key_value))
    parts = [rule.key_value] if rule.key_value else []
    seen: list[str] = []
    for d in current:  # several figures can apply at once (e.g. SF § 37.9C and § 37.9A amounts)
        if any(kv_equal(d.key_value, s) for s in seen):  # same figure from another document
            continue
        seen.append(d.key_value)
        period = f"{d.effective_from or '…'} to {d.effective_until or '…'}"
        cite = f"{d.citation}, " if d.citation else ""
        parts.append(f"current ({period}; {cite}{d.source_doc_id}): {d.key_value}")
    return " | ".join(parts) or None


def _conflict_note(rule: RuleInternal, status: str, as_of: date) -> str | None:
    """Existing note, plus "expired on <sunset>" for an enacted rule exported as failed."""
    note = rule.conflict_note
    s = rule.sunset_date.value if rule.sunset_date else None
    if status == "failed" and rule.stage != LegalStage.BILL_FAILED and s and s <= as_of:
        note = f"{note}; expired on {s.isoformat()}" if note else f"expired on {s.isoformat()}"
    return note


def to_rule_out(rule: RuleInternal, as_of: date) -> RuleOut:
    eff = effective_date_for(rule, as_of)
    status = compute_status(rule, as_of)
    return RuleOut(
        team_rule_id=rule.team_rule_id,
        jurisdiction=rule.jurisdiction,
        level=rule.level,
        category=rule.category,
        status=status,
        title=rule.title,
        requirement=rule.requirement,
        key_value=_key_value(rule, as_of),
        coverage_conditions=coverage_to_out(rule),
        exemptions=rule.exemptions,
        overrides=rule.overrides,
        interaction=rule.interaction,
        effective_date=eff.isoformat() if eff else None,
        citation=rule.citation,
        source_doc_id=rule.source_doc_id,
        source_url=rule.source_url,
        quoted_span=rule.quoted_span,
        confidence=rule.confidence,
        conflict_flag=rule.conflict_flag,
        conflict_note=_conflict_note(rule, status, as_of),
    )


def export_rules(rules: list[RuleInternal], as_of: date, path: Path | None = None) -> Path:
    """Write ``{"rules": [...]}`` (accepted only, sorted by ``team_rule_id``).

    Raises:
        ValueError: listing every schema error, before anything is written.
    """
    path = path or config.RULES_PATH
    schema = load_schema()
    records = [to_rule_out(r, as_of) for r in rules if r.disposition == "accepted"]
    records.sort(key=lambda r: r.team_rule_id)
    data = [r.model_dump(mode="json") for r in records]
    errors = [f"{d['team_rule_id']}: {e}" for d in data for e in validate_schema(d, schema)]
    if errors:
        raise ValueError("schema validation failed:\n" + "\n".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rules": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_internal(path: Path | None = None) -> list[RuleInternal]:
    """Reload ``out/rules_normalized.json`` so ``export --as-of`` re-runs without the LLM."""
    data = json.loads((path or config.NORMALIZED_PATH).read_text(encoding="utf-8"))
    return [RuleInternal.model_validate(r) for r in data["rules"]]
