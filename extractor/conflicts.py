"""Conflicts BETWEEN documents (after normalize.py). Flags rules for human review.

Types:

a) ``effective_date``  same jurisdiction, category and law, different documents, different
                       effective-kind dates for the same provision (also inside a merged rule
                       whose dates come from different documents).
b) ``key_value``       same jurisdiction, category and law, different documents, same coverage
                       thresholds and same provision, but different key values (numbers differ).
c) ``preemption``      a state rule whose interaction says it preempts / prohibits local rules,
                       against local rules of the same category in that state (held ones too).
d) ``value_pending``   a date or figure the text itself marks as pending, not yet published,
                       or to be determined.

"Same provision" = token_set_ratio of titles >= 70, or equal key values; for (b) also two
figures of the same unit ($, %, months, days) for the same law. Every flagged rule
gets ``conflict_flag = True`` and a ``conflict_note``; the list goes to out/conflicts.json.
"""

from __future__ import annotations

import re
from itertools import combinations

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from .models import RuleInternal
from .normalize import TITLE_SIMILARITY, _signature, kv_equal, law_keys, preempts
from .status import effective_values

_PENDING_VALUE = re.compile(
    r"to be determined|\bTBD\b|not yet (published|available|announced|determined|set)|"
    r"will be (announced|published|determined|set)|pending (publication|approval|adoption)|"
    r"has not (yet )?been (published|announced|set)", re.I)


def _flag(rule: RuleInternal, note: str) -> None:
    rule.conflict_flag = True
    if not rule.conflict_note or note not in rule.conflict_note:
        rule.conflict_note = f"{rule.conflict_note}; {note}" if rule.conflict_note else note


_UNITS = {
    "money": re.compile(r"\$\s?\d"),
    "percent": re.compile(r"\d\s?%|\bpercent\b", re.I),
    "months": re.compile(r"\bmonths?'?s?\b", re.I),
    "days": re.compile(r"\bdays?\b", re.I),
}


def _units(kv: str | None) -> set[str]:
    return {u for u, rx in _UNITS.items() if kv and rx.search(kv)}


def _same_quantity(a: RuleInternal, b: RuleInternal) -> bool:
    """Both key values state the same kind of quantity (e.g. two dollar caps of one law).
    Titles are worded differently from run to run; the unit of the figure is stable."""
    return bool(_units(a.key_value) & _units(b.key_value))


def _same_provision(a: RuleInternal, b: RuleInternal) -> bool:
    return fuzz.token_set_ratio(a.title, b.title, processor=default_process) >= TITLE_SIMILARITY or (
        a.key_value is not None and kv_equal(a.key_value, b.key_value))


def detect_conflicts(rules: list[RuleInternal]) -> list[dict]:
    """Flag rules in place and return conflict records."""
    live = [r for r in rules if r.disposition in ("accepted", "held") and r.team_rule_id]
    out: list[dict] = []

    def record(kind: str, rs: list[RuleInternal], detail: str) -> None:
        ids = [r.team_rule_id for r in rs]
        for r in rs:
            others = [i for i in ids if i != r.team_rule_id]
            _flag(r, f"{kind} conflict" + (f" with {', '.join(others)}" if others else "") + f": {detail}")
        out.append({"type": kind, "rule_ids": ids, "jurisdiction": rs[0].jurisdiction,
                    "category": rs[0].category, "detail": detail,
                    "source_doc_ids": sorted({r.source_doc_id for r in rs})})

    # (a) inside merged rules: effective dates coming from different documents
    for r in live:
        by_doc: dict[str, set] = {}
        for d in r.effective_dates:
            if d.kind == "effective" and d.value:
                by_doc.setdefault(d.source_doc_id, set()).add(d.value)
        if len(by_doc) > 1 and len({v for vs in by_doc.values() for v in vs}) > 1:
            record("effective_date", [r], "; ".join(f"{doc}: {', '.join(map(str, sorted(vs)))}"
                                                    for doc, vs in sorted(by_doc.items())))

    # (a)/(b) across rules of the same law in different documents
    for a, b in combinations(live, 2):
        if (a.jurisdiction, a.category) != (b.jurisdiction, b.category) or a.source_doc_id == b.source_doc_id:
            continue
        if not (law_keys(a) & law_keys(b)):
            continue
        same = _same_provision(a, b)
        ea, eb = effective_values(a), effective_values(b)
        if same and ea and eb and set(ea) != set(eb):
            record("effective_date", [a, b], f"{a.source_doc_id}: {ea[-1]} vs {b.source_doc_id}: {eb[-1]}")
        # same unit counts only if the effective dates do not already tell the provisions apart
        dated_apart = bool(ea and eb and set(ea) != set(eb))
        if ((same or (_same_quantity(a, b) and not dated_apart)) and a.key_value and b.key_value
                and not kv_equal(a.key_value, b.key_value) and _signature(a) == _signature(b)):
            record("key_value", [a, b], f"{a.source_doc_id}: {a.key_value!r} vs {b.source_doc_id}: {b.key_value!r}")

    # (c) state preemption vs local rules of the same category
    for s in live:
        if s.level != "state" or not preempts(s.interaction):
            continue
        locals_ = [l for l in live if l.level == "city" and l.jurisdiction.endswith(f", {s.jurisdiction}")
                   and l.category == s.category]
        for l in locals_:
            record("preemption", [s, l], f"{s.team_rule_id} interaction: {s.interaction[:160]}")
        if not locals_:
            out.append({"type": "preemption_no_local_rule", "rule_ids": [s.team_rule_id],
                        "jurisdiction": s.jurisdiction, "category": s.category,
                        "detail": "state rule preempts/prohibits local rules, but no local rule of this "
                                  "category in this state was extracted from the corpus",
                        "source_doc_ids": [s.source_doc_id]})

    # (d) values the text marks as pending / to be determined
    for r in live:
        texts = [r.key_value, r.requirement, r.quoted_span, r.coverage.notes if r.coverage else None,
                 *(d.key_value for d in r.key_value_details), *(e.quoted_span for e in r.evidence)]
        hit = next((m for t in texts if t for m in [_PENDING_VALUE.search(t)] if m), None)
        if hit:
            record("value_pending", [r], f"text says {hit.group(0)!r}")
    return out
