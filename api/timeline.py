"""GET /timeline/{address_id}: dated changes in the rules that reach an address (no LLM).

Candidate dates are the effective, enactment and sunset dates of every rule in the address's
jurisdiction stack (corpus, manifest-attested and hour-16 increments alike) plus the days a
building-age cutoff flips for this building. For each date d in [from, to], every rule's
/lookup result at d-1 is compared with its result at d (``Engine.lookup``, no duplicated
logic); a difference is an event. Pending bills that would cover the address have no date and
are listed apart.
"""

from __future__ import annotations

import functools
import re
from datetime import date, timedelta

from extractor import config
from resolver.coverage import jurisdiction_match
from resolver.results import CATEGORY_LABEL

from . import i18n
from .explain import date_origin

DEFAULT_FROM = date(config.DEFAULT_AS_OF.year - 2, config.DEFAULT_AS_OF.month, config.DEFAULT_AS_OF.day)
DEFAULT_TO = date(2028, 12, 31)


def _attested_date(s: str | None) -> date | None:
    if not s:
        return None
    parts = [int(x) for x in s.split("-")] + [1, 1]
    return date(parts[0], parts[1], parts[2])


def _ages(p: dict) -> list[int]:
    if "and" in p or "or" in p:
        return [a for x in p.get("and") or p["or"] for a in _ages(x)]
    if "not" in p:
        return _ages(p["not"])
    if p.get("fact") == "building_age":
        return [v for v in (p["value"] if isinstance(p["value"], list) else [p["value"]]) if isinstance(v, int)]
    return []


def candidates(eng, aid: str) -> dict[date, dict[str, str]]:
    """{date: {rule_id: date_origin}} for the rules in the address's stack."""
    stack, facts = eng.stacks[aid], eng.facts[aid]
    out: dict[date, dict[str, str]] = {}

    def add(d: date | None, rid: str, origin: str) -> None:
        if d:
            out.setdefault(d, {}).setdefault(rid, origin)

    y = facts["year_built"]["value"]
    for rule in eng.rules:
        rid = rule["team_rule_id"]
        if not jurisdiction_match(rule, stack):
            continue
        if rule.get("evidence_type") == "manifest_only":
            add(_attested_date(rule.get("effective_date")), rid, "literal")
        elif rid in eng.internal:
            r = eng.internal[rid]
            for c in r.effective_dates:
                if c.kind == "effective" and c.value:
                    add(c.value, rid, date_origin(c))
            for c in (r.enacted_date, r.sunset_date):
                if c and c.value:
                    add(c.value, rid, date_origin(c))
        if y:  # rolling building-age cutoffs: the age interval [lo, hi] moves on Jan 1 and Dec 31
            comp = eng.compiled[rid]
            for n in {a for it in comp["conditions"] + comp["exemptions"] if it["scope"] == "building"
                      for a in _ages(it["predicate"])}:
                add(date(y + n, 1, 1), rid, "derived")
                add(date(y + n, 12, 31), rid, "derived")
    return out


def _by_rule(lk: dict) -> dict[str, dict]:
    out = {r["team_rule_id"]: r for r in lk["results"]}
    for o in lk["omitted"]:
        out[o["team_rule_id"]] = {"team_rule_id": o["team_rule_id"], "result": "omitted", "status": None,
                                  "effective_date": None, "superseded_by": None, "conflict_flag": False,
                                  "conflict_notes": [], "omitted_reason": o["reason"]}
    return out


@functools.lru_cache(maxsize=64)
def _changes(aid: str, frm: date, to: date) -> tuple[list[tuple], dict]:
    """Language-independent part: [(date, rule_id, before, after, after_entry, origin)], candidates."""
    from . import main as M

    base = M.engine(config.DEFAULT_AS_OF)
    cands = candidates(base, aid)
    out = []
    for d in sorted(x for x in cands if frm <= x <= to):
        before = _by_rule(base.at(d - timedelta(days=1)).lookup(aid))
        after = _by_rule(base.at(d).lookup(aid))
        for rid in sorted(set(before) | set(after)):
            b, a = before.get(rid, {}).get("result", "omitted"), after.get(rid, {}).get("result", "omitted")
            if b != a:
                out.append((d, rid, b, a, after.get(rid) or before[rid], cands[d].get(rid, "derived")))
    return out, cands


def build(aid: str, frm: date, to: date, lang: str) -> dict:
    from . import main as M

    base = M.engine(config.DEFAULT_AS_OF)
    rules = {r["team_rule_id"]: r for r in base.rules}
    changes, _ = _changes(aid, frm, to)
    events = []
    for d, rid, b, a, ra, origin in changes:
        rule = rules[rid]
        notes = [n for n in [rule.get("conflict_note"), *ra.get("conflict_notes", [])] if n]
        if lang == "es":
            notes = [re.sub(r"^possible preemption conflict with (.+), flagged for human review$",
                            r"posible conflicto de preempción con \1, marcado para revisión humana", n) for n in notes]
        label = CATEGORY_LABEL[rule["category"]]
        events.append({
            "date": d.isoformat(), "team_rule_id": rid, "title": rule["title"], "category": rule["category"],
            "category_label": M.CATEGORY_ES[label] if lang == "es" else label, "level": rule["level"],
            "attested": rule.get("evidence_type") == "manifest_only",
            "before": b, "after": a,
            "before_label": i18n.result_label(b, lang), "after_label": i18n.result_label(a, lang),
            "status_line": M.status_line(ra.get("status") or "in_force", ra.get("effective_date"), lang, a,
                                         ra.get("superseded_by")) if a != "omitted"
            else i18n.result_label("omitted", lang),
            "date_origin": origin,
            "conflict_flag": bool(ra.get("conflict_flag")), "conflict_note": "; ".join(notes) or None,
            "past": d <= config.DEFAULT_AS_OF,
        })
    events.sort(key=lambda e: (e["date"], list(CATEGORY_LABEL).index(e["category"]), e["team_rule_id"]))
    by_year: dict[str, list] = {}
    for e in events:
        by_year.setdefault(e["date"][:4], []).append(e)
    pending = []
    for r in base.lookup(aid)["results"]:
        if r["result"] != "pending":
            continue
        rule = rules[r["team_rule_id"]]
        pending.append({"team_rule_id": r["team_rule_id"], "title": rule["title"], "category": rule["category"],
                        "level": rule["level"], "coverage": r["coverage"],
                        "status_line": M.status_line("pending", None, lang),
                        "note": "sin fecha: proyecto de ley, no es ley" if lang == "es" else "no date: pending bill, not law",
                        "citation": rule.get("citation")})
    nxt = next((e for e in events if not e["past"]), None)
    return {"address": M.address_info(aid), "from": frm.isoformat(), "to": to.isoformat(),
            "reference_date": config.DEFAULT_AS_OF.isoformat(), "lang": lang, "disclaimer": M.DISCLAIMER[lang],
            "events": events, "by_year": by_year, "next_change": nxt, "pending": pending, "count": len(events)}
