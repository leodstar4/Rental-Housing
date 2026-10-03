"""Pydantic models.

* ``RuleCandidate`` / ``RecordRulesInput``: what the model returns through the
  ``record_rules`` tool. The tool's ``input_schema`` is generated from
  ``RecordRulesInput`` (``llm.record_rules_tool``). No provenance fields: the
  pipeline fills those from the document, never the model.
* ``RuleInternal``: our rich record (structured dates, coverage, provenance,
  quote offsets). Everything downstream (Module B/C) reads this.
* ``RuleOut``: exactly ``schema/rule_record.schema.json``; produced only by
  ``export.to_rule_out`` and validated again with ``jsonschema`` on export.

Field docs in the candidate models become the tool schema descriptions the
model sees, so keep them short and consistent with ``prompts/extract_system.md``.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

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


DateKind = Literal["effective", "operative", "amendment", "enacted"]


class DateClaim(BaseModel):
    """A date asserted by a specific source; several may disagree (guide §9).

    ``kind`` (dates.py): ``effective`` = general entry into force; ``operative`` =
    calculation/base date (e.g. rent base of 2019-03-15); ``amendment`` = effective
    date of an amendment; ``enacted`` = signing/adoption. Only ``effective`` dates
    drive status and date conflicts.
    """

    value: date | None = None
    raw: str | None = None  # as written, e.g. "January 1, 2026", "Nov. 19"
    derived: bool = False  # value computed from a relative formula or a calendar rule
    verified: bool = False  # quoted_span found in raw_text (validate.py)
    source_doc_id: str | None = None
    quoted_span: str | None = None
    kind: DateKind | None = None
    kind_source: Literal["rule", "llm", "default"] | None = None
    rule_applied: str | None = None  # jurisdiction_defaults.yaml rule id, if any


class Evidence(BaseModel):
    """A literal supporting quote kept when rules are merged or linked."""

    source_doc_id: str
    source_url: str
    retrieved_at: str
    citation: str | None
    quoted_span: str
    role: Literal["primary", "merged", "administrative", "citation_source"] = "primary"
    uid: str | None = None


class StageClaim(BaseModel):
    """A legislative stage asserted by one document for a law (kept when rules merge)."""

    stage: str
    source_doc_id: str
    uid: str | None = None
    enacted_date: date | None = None


class ValueDetail(BaseModel):
    """An administrative figure (e.g. annual allowable increase) linked to a legal rule."""

    key_value: str
    effective_from: date | None = None
    effective_until: date | None = None
    source_doc_id: str
    citation: str | None = None
    quoted_span: str
    uid: str | None = None


ExemptionOp = Literal["<", "<=", "==", ">=", ">", "in"]


# One machine-testable exemption (the rule does NOT apply when it holds). Typed by
# ``field`` so the strict tool schema itself enforces the value type: a plain
# union (anyOf) of variants, each pinning its ``field`` values and ``value`` type.
class ExemptionBool(BaseModel):
    """``owner_occupied == true/false``."""

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(description="The exemption as stated, in plain English.")
    field: Literal["owner_occupied"]
    op: Literal["=="]
    value: bool


class ExemptionInt(BaseModel):
    """Numeric threshold on unit count or construction year."""

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(description="The exemption as stated, in plain English.")
    field: Literal["units", "year_built"]
    op: Literal["<", "<=", "==", ">=", ">"]
    value: int


class ExemptionDate(BaseModel):
    """Threshold on the certificate-of-occupancy date."""

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(description="The exemption as stated, in plain English.")
    field: Literal["co_date"]
    op: Literal["<", "<=", "==", ">=", ">"]
    value: date


class ExemptionText(BaseModel):
    """Categorical test (owner/use type) or anything else ('other')."""

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(description="The exemption as stated, in plain English.")
    field: Literal["owner_type", "use_type", "other"]
    op: ExemptionOp
    value: str | list[str] | None = Field(description="Value or set; null if the text gives none.")


ExemptionCondition = ExemptionBool | ExemptionInt | ExemptionDate | ExemptionText

_EXEMPTION_ADAPTER: TypeAdapter[ExemptionCondition] = TypeAdapter(ExemptionCondition)

#: Wire schema of one exemption inside the strict ``record_rules`` tool. The typed
#: 4-variant union above exceeds the API's compiled-grammar limit for strict tools,
#: so the grammar enforces this flat shape (value is a JSON bool/int/string/list,
#: never a stringified bool) and pydantic enforces the per-field type afterwards.
EXEMPTION_WIRE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["condition", "field", "op", "value"],
    "properties": {
        "condition": {"type": "string", "description": "The exemption as stated, in plain English."},
        "field": {
            "type": "string",
            "enum": ["units", "year_built", "co_date", "owner_type", "owner_occupied", "use_type", "other"],
        },
        "op": {"type": "string", "enum": ["<", "<=", "==", ">=", ">", "in"]},
        "value": {
            "description": "owner_occupied: boolean; units/year_built: integer; co_date: ISO date "
            "string; owner_type/use_type/other: string or list of strings; null if none.",
            "anyOf": [
                {"type": "boolean"},
                {"type": "integer"},
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ],
        },
    },
}


class Coverage(BaseModel):
    """Structured coverage tests Module B can evaluate. ``None`` = no condition.

    All bounds are inclusive. ``year_built_*`` are construction years;
    ``certificate_of_occupancy_on_or_before`` is a certificate date and is a
    different fact (guide §4.1).
    """

    model_config = ConfigDict(extra="forbid")

    units_min: int | None = Field(description="Covered only if units >= this.")
    units_max: int | None = Field(description="Covered only if units <= this.")
    year_built_min: int | None = Field(description="Covered only if built in or after this year.")
    year_built_max: int | None = Field(
        description="Covered only if built in or before this year ('built before 1979' -> 1978)."
    )
    certificate_of_occupancy_on_or_before: date | None = Field(
        description="Covered only if first certificate of occupancy issued on or before this date."
    )
    building_age_min_years: int | None = Field(
        description="Rolling cutoff: covered only if the building/CO is at least this many years old."
    )
    property_types_covered: list[str] = Field(
        description="Use types the rule is limited to (e.g. 'residential rental'); [] = not limited."
    )
    exemption_conditions: list[ExemptionCondition]
    notes: str | None = Field(description="Coverage conditions not expressible in the fields above.")

    @model_validator(mode="before")
    @classmethod
    def _quarantine_bad_exemptions(cls, data: object) -> object:
        """Move exemptions whose value type does not match their field into
        ``notes`` instead of rejecting the whole rule (Module B -> "unknown")."""
        if not isinstance(data, dict) or not isinstance(data.get("exemption_conditions"), list):
            return data
        good, bad = [], []
        for item in data["exemption_conditions"]:
            try:
                good.append(_EXEMPTION_ADAPTER.validate_python(item))
            except ValidationError:
                bad.append(item)
        if not bad:
            return data
        extra = "; ".join(
            f"UNVERIFIABLE exemption ({b.get('field')} {b.get('op')} {b.get('value')!r}): {b.get('condition')}"
            if isinstance(b, dict) else f"UNVERIFIABLE exemption: {b!r}"
            for b in bad
        )
        notes = data.get("notes")
        return {**data, "exemption_conditions": good, "notes": f"{notes}; {extra}" if notes else extra}


MatchType = Literal["exact", "normalized", "fuzzy", "retry"]
Disposition = Literal["accepted", "held", "rejected", "merged"]


class QuoteLocation(BaseModel):
    """Where ``quoted_span`` was found in the document's ``raw_text``."""

    raw_start: int
    raw_end: int
    match_type: MatchType
    score: float | None = None  # rapidfuzz partial_ratio for "fuzzy"


# --------------------------------------------------------------------------- #
# LLM output (record_rules tool input)
# --------------------------------------------------------------------------- #


class DateClaimCandidate(BaseModel):
    """A date the document states, with the literal fragment that states it."""

    model_config = ConfigDict(extra="forbid")

    value: date | None = Field(description="ISO date; null if the text gives no full day and it cannot be derived.")
    raw: str = Field(description="The date as written; if derived, the relative formula as written.")
    derived: bool = Field(description="True if value was computed from a relative date and a date in this document.")
    quoted_span: str = Field(description="Literal fragment of the document stating this date.")


class RuleCandidate(BaseModel):
    """One rule as extracted by the model (strict tool schema: every field required)."""

    model_config = ConfigDict(extra="forbid")

    jurisdiction: str = Field(description="Who ENACTS the rule: 'CA','NJ','MA' or 'City, ST'.")
    level: Level
    category: Category
    title: str
    requirement: str = Field(description="1-2 plain-English sentences.")
    key_value: str | None
    citation: str | None = Field(description="Official cite of the section containing the rule; null if the text names no law.")
    citation_aliases: list[str] = Field(
        description="Other ways the text refers to the same law (bill number, chapter, ordinance name)."
    )
    quoted_span: str = Field(
        min_length=20,
        description="LITERAL contiguous copy from the document, starting at a sentence or enumerated subsection, containing the operative verb.",
    )
    stage: Literal["enacted", "bill_pending", "bill_failed", "administrative", "unknown"]
    enacted_date: DateClaimCandidate | None = Field(description="Signing/approval/adoption date.")
    effective_dates: list[DateClaimCandidate] = Field(
        description="EVERY effective date the text gives for this rule; keep contradicting ones."
    )
    sunset_date: DateClaimCandidate | None
    coverage: Coverage
    coverage_text: str | None = Field(description="Faithful summary of who/what is covered.")
    exemptions: str | None = Field(description="Faithful summary of exemptions.")
    interaction: str | None = Field(description="Yields to / preempts / prohibits another rule.")
    is_secondary_source: bool = Field(description="Document describes a rule enacted by ANOTHER body.")
    confidence: float = Field(ge=0, le=1)


class RecordRulesInput(BaseModel):
    """Input of the ``record_rules`` tool: all rules found in ONE document."""

    model_config = ConfigDict(extra="forbid")

    rules: list[RuleCandidate]
    notes: str | None = Field(description="Optional remarks, e.g. why no rules were found.")


# --------------------------------------------------------------------------- #
# Internal record
# --------------------------------------------------------------------------- #


class RuleInternal(BaseModel):
    """Rich internal rule record."""

    model_config = ConfigDict(extra="forbid")

    # Identity / classification
    uid: str | None = None  # stable pre-ID key "<doc_id>#<index>" (extract.py)
    team_rule_id: str | None = None  # assigned in normalize.assign_ids
    jurisdiction: str  # "CA" or "San Francisco, CA"
    level: Level
    category: Category
    title: str
    requirement: str
    key_value: str | None = None

    # Coverage
    coverage: Coverage | None = None
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

    # Provenance. citation may be None (the text names no law); export decides.
    citation: str | None
    citation_aliases: list[str] = Field(default_factory=list)
    source_doc_id: str
    source_url: str
    retrieved_at: str
    is_secondary_source: bool = False
    quoted_span: str = Field(min_length=20)
    quote_location: QuoteLocation | None = None  # set by validate.validate_rule
    model_confidence: float | None = Field(default=None, ge=0, le=1)  # as returned by the LLM
    confidence: float | None = Field(default=None, ge=0, le=1)  # final, see README

    # Extraction metadata
    model: str | None = None
    prompt_version: str | None = None
    validation_errors: list[str] = Field(default_factory=list)

    # Normalization (normalize.py)
    citation_resolved_from: str | None = None  # team_rule_id the citation was taken from
    evidence: list[Evidence] = Field(default_factory=list)  # all supporting quotes
    key_value_details: list[ValueDetail] = Field(default_factory=list)  # linked admin figures
    merged_uids: list[str] = Field(default_factory=list)  # uids folded into this rule
    merged_into: str | None = None  # uid of the rule that absorbed this one
    stage_history: list[StageClaim] = Field(default_factory=list)  # stages seen across merged docs

    # Validation outcome: accepted -> exported; held -> kept internally (e.g.
    # no_citation, administrative_unlinked; used for conflicts/interactions);
    # rejected -> out/rejected.json; merged -> folded into ``merged_into``.
    disposition: Disposition = "accepted"
    disposition_reason: str | None = None


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
