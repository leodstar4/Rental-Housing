"""Pydantic models.

* ``RuleInternal``: our rich record (structured dates, coverage, provenance,
  quote offsets). Everything downstream (Module B/C) reads this.
* ``RuleOut``: exactly ``schema/rule_record.schema.json``; produced only by
  ``export.to_rule_out`` and validated again with ``jsonschema`` on export.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["state", "city"]
Category = Literal[
    "rent_increase_limits",
    "just_cause_eviction",
    "security_deposits",
    "application_screening_fees",
    "screening_restrictions",
    "algorithmic_rent_setting",
]
Status = Literal["in_force", "not_yet_effective", "pending", "failed"]


class LegalStage(str, Enum):
    """Where the source instrument is in the legislative process (input to ``status``)."""

    ENACTED = "enacted"  # statute/ordinance/chaptered bill
    BILL_PENDING = "bill_pending"  # introduced, in committee, etc.
    BILL_FAILED = "bill_failed"  # died, vetoed, struck (e.g. MA ballot question, T5)
    ADMINISTRATIVE = "administrative"  # agency rates/bulletins (e.g. annual allowable increase)
    UNKNOWN = "unknown"


class DateClaim(BaseModel):
    """A date asserted by a specific source; several may disagree (guide §9)."""

    value: date | None = None
    raw: str | None = None  # as written, e.g. "January 1, 2026", "Nov. 19"
    source_doc_id: str | None = None
    quoted_span: str | None = None


class Coverage(BaseModel):
    """Structured coverage tests Module B can evaluate. ``None`` = no condition."""

    year_built_max: int | None = None
    certificate_of_occupancy_before: date | None = None  # inclusive cutoff, e.g. 1979-06-13
    building_age_min_years: int | None = None  # rolling cutoffs (e.g. CA 15-year rule)
    units_min: int | None = None
    units_max: int | None = None
    owner_types_excluded: list[str] = Field(default_factory=list)
    property_types_excluded: list[str] = Field(default_factory=list)
    notes: str | None = None  # anything not expressible above (forces "unknown" in B)


class QuoteLocation(BaseModel):
    """Where ``quoted_span`` was found in the document's ``raw_text``."""

    raw_start: int
    raw_end: int
    exact: bool  # False = matched only after typographic folding


class RuleInternal(BaseModel):
    """Rich internal rule record."""

    model_config = ConfigDict(extra="forbid")

    # Identity / classification
    team_rule_id: str | None = None  # assigned in normalize.assign_ids
    jurisdiction: str  # "CA" or "San Francisco, CA"
    level: Level
    category: Category
    title: str
    requirement: str
    key_value: str | None = None

    # Coverage
    coverage: Coverage = Field(default_factory=Coverage)
    coverage_text: str | None = None
    exemptions: str | None = None

    # Law lifecycle (status is derived, never extracted)
    stage: LegalStage = LegalStage.UNKNOWN
    enacted_date: DateClaim | None = None
    effective_dates: list[DateClaim] = Field(default_factory=list)
    sunset_date: DateClaim | None = None

    # Interactions
    overrides: list[str] = Field(default_factory=list)
    interaction: str | None = None
    conflict_flag: bool = False
    conflict_note: str | None = None

    # Provenance
    citation: str
    source_doc_id: str
    source_url: str
    retrieved_at: str
    quoted_span: str = Field(min_length=20)
    quote_location: QuoteLocation | None = None  # set by validate.verify_quote
    confidence: float | None = Field(default=None, ge=0, le=1)

    # Extraction metadata
    model: str | None = None
    prompt_version: str | None = None
    validation_errors: list[str] = Field(default_factory=list)


class RuleOut(BaseModel):
    """Mirror of ``rule_record.schema.json``. No extra keys allowed."""

    model_config = ConfigDict(extra="forbid")

    team_rule_id: str
    jurisdiction: str
    level: Level
    category: Category
    status: Status
    title: str
    requirement: str
    key_value: str | None = None
    coverage_conditions: str | dict | None = None
    exemptions: str | None = None
    overrides: list[str] = Field(default_factory=list)
    interaction: str | None = None
    effective_date: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")
    citation: str
    source_doc_id: str | None = None
    source_url: str
    quoted_span: str = Field(min_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    conflict_flag: bool = False
    conflict_note: str | None = None


class ExtractionResponse(BaseModel):
    """What the model returns for one document (structured output schema)."""

    rules: list[RuleInternal]
    notes: str | None = None  # e.g. "document is a FAQ with no operative rules"
