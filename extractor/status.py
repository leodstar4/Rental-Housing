"""Status as of a query date. Derived, never extracted, so ``--as-of`` changes it.

Stage -> status:

==================  ===========================================================
stage               status
==================  ===========================================================
bill_pending        ``pending``
bill_failed         ``failed``
enacted             ``pending`` if its enacted_date is after as_of (not yet law);
                    ``failed`` if its sunset_date <= as_of (repealed / expired);
                    else by effective dates (below)
administrative      as ``enacted`` (only linked figures reach export, inside an enacted rule)
unknown             as ``enacted`` (validation capped confidence at 0.5, conflict_flag set)
==================  ===========================================================

Effective dates: only claims of ``kind == "effective"`` with a value count, i.e. verified
quotes, dates derived from a formula in the text, and calendar defaults from
``data/jurisdiction_defaults.yaml`` (applied in normalize.py, e.g. CA statutes: January 1
after enactment, Cal. Const. art. IV, § 8(c)). If every such date is after ``as_of`` ->
``not_yet_effective``; if every one is on/before -> ``in_force``; if they straddle
``as_of`` -> ``in_force`` (the conflict is flagged by validate.py / conflicts.py). An
enacted rule with no effective date is ``in_force``.
"""

from __future__ import annotations

from datetime import date

from .models import LegalStage, RuleInternal, Status


def effective_values(rule: RuleInternal) -> list[date]:
    """Sorted values of the rule's effective-kind dates."""
    return sorted({d.value for d in rule.effective_dates if d.kind == "effective" and d.value})


def compute_status(rule: RuleInternal, as_of: date) -> Status:
    """Apply the table above."""
    if rule.stage == LegalStage.BILL_FAILED:
        return "failed"
    if rule.stage == LegalStage.BILL_PENDING:
        return "pending"
    if rule.enacted_date and rule.enacted_date.value and rule.enacted_date.value > as_of:
        return "pending"
    if rule.sunset_date and rule.sunset_date.value and rule.sunset_date.value <= as_of:
        return "failed"
    values = effective_values(rule)
    if values and all(v > as_of for v in values):
        return "not_yet_effective"
    return "in_force"


def status_is_ambiguous(rule: RuleInternal, as_of: date) -> bool:
    """True when effective dates straddle ``as_of`` (status depends on which source is right)."""
    values = effective_values(rule)
    return any(v > as_of for v in values) and any(v <= as_of for v in values)


def effective_date_for(rule: RuleInternal, as_of: date) -> date | None:
    """The effective date that decides the status: the earliest future one if not yet
    effective, else the latest one on/before ``as_of``."""
    values = effective_values(rule)
    if not values:
        return None
    past = [v for v in values if v <= as_of]
    return past[-1] if past else values[0]
