"""Status as of a query date. Derived, never extracted, so ``--as-of`` changes it.

Decision table (first match wins):

==========================  =========================================
stage                       status
==========================  =========================================
BILL_FAILED                 ``failed``
BILL_PENDING                ``pending``
sunset_date <= as_of        ``failed`` (no longer in force)
effective date > as_of      ``not_yet_effective``
effective date <= as_of     ``in_force``
enacted, no effective date  ``in_force`` (+ note; CA default Jan 1 rule
                            may be applied by the caller)
==========================  =========================================

With conflicting effective-date claims, the *latest* claim decides
``not_yet_effective`` vs ``in_force`` only when all claims agree on the side
of ``as_of``; otherwise the rule is ``in_force`` with ``conflict_flag`` set.
"""

from __future__ import annotations

from datetime import date

from .models import RuleInternal, Status


def effective_date(rule: RuleInternal) -> date | None:
    """Single best effective date (earliest agreed claim), or ``None``."""
    raise NotImplementedError


def compute_status(rule: RuleInternal, as_of: date) -> Status:
    """Apply the decision table above."""
    raise NotImplementedError


def status_is_ambiguous(rule: RuleInternal, as_of: date) -> bool:
    """True when date claims straddle ``as_of`` (status depends on which source is right)."""
    raise NotImplementedError
