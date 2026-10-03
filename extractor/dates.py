"""Date helpers: value-in-quote verification and date-kind classification.

``value_in_text`` checks that a date's ISO value appears in its quote in any
common US format ("October 6, 2025", "Oct. 6, 2025", "10/06/2025", "3/01/26",
"6-24-2023", "2025-10-06"...), instead of requiring the model's ``raw`` string.

``classify_kind`` assigns ``effective`` / ``operative`` / ``amendment`` / ``enacted``
from the wording of the quote, the model's ``raw`` and the raw text just before the
quote (e.g. a statute history note "(Amended by Stats. 2025, Ch. 203 ...) Effective
January 1, 2026."). It returns ``None`` when the wording is ambiguous; the caller
may then ask a small LLM (``llm.classify_date_kind``).
"""

from __future__ import annotations

import re
from datetime import date

from .models import DateKind

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def date_formats(d: date) -> set[str]:
    """Common renderings of ``d`` (lower-cased, single-spaced)."""
    m, dd, y = d.month, d.day, d.year
    out: set[str] = {d.isoformat()}
    for mon in {_MONTHS[m - 1], _ABBR[m - 1], _ABBR[m - 1] + ".", "Sept" if m == 9 else _ABBR[m - 1],
                "Sept." if m == 9 else _ABBR[m - 1] + "."}:
        for day in {str(dd), f"{dd:02d}"}:
            out |= {f"{mon} {day}, {y}", f"{mon} {day} {y}", f"{day} {mon} {y}"}
    for mm in {str(m), f"{m:02d}"}:
        for day in {str(dd), f"{dd:02d}"}:
            for yy in {str(y), f"{y % 100:02d}"}:
                out |= {f"{mm}/{day}/{yy}", f"{mm}-{day}-{yy}", f"{mm}.{day}.{yy}"}
    return {s.lower() for s in out}


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip().lower()


def value_in_text(d: date, text: str) -> bool:
    """True if any common rendering of ``d`` occurs in ``text`` as a whole token."""
    t = _fold(text)
    for f in date_formats(d):
        for m in re.finditer(re.escape(f), t):
            before = t[m.start() - 1] if m.start() else " "
            after = t[m.end()] if m.end() < len(t) else " "
            if not before.isalnum() and not after.isdigit():
                return True
    return False


# --------------------------------------------------------------------------- #
# Kind classification
# --------------------------------------------------------------------------- #

_AMENDMENT = re.compile(r"\bamended by\b|\bas amended\b|\bamendment\b", re.I)
_OPERATIVE = re.compile(
    r"occurring on or after|\bbase (rent|date|year)\b|lowest (gross )?rent|"
    r"rent (in effect|charged|paid) (on|as of)|\blook-?back\b", re.I)
_EFFECTIVE = re.compile(
    r"\btake[s]? effect\b|\btook effect\b|\b(go|goes|went) into effect\b|\bbecome[s]? operative\b|"
    r"\bshall be operative\b|\bnot effective until\b|\bin force\b|\beffective\b|\bstarting\b|\bbeginning\b", re.I)
_PERIOD = re.compile(r"\bthrough\b|\s[–—-]\s|\buntil\b", re.I)
_ENACTED = re.compile(r"\bapproved\b|\badopted\b|\bpassed\b|\bsigned\b|\benacted\b", re.I)
_HISTORY_NOTE = re.compile(r"\(\s*(amended|added|repealed\b[^\n]*?\band added) by stats\.", re.I)


def classify_kind(quote: str, raw: str | None, context_before: str, *, derived: bool,
                  administrative: bool = False) -> DateKind | None:
    """Rule-based kind for an ``effective_dates`` claim; ``None`` if ambiguous.

    Args:
        quote: The claim's verified quote.
        raw: The model's ``raw`` rendering (may hold extra words like "Amended by").
        context_before: ~250 chars of raw text before the quote.
        derived: Claim computed from a relative formula ("take effect on the first
            day of the ... month next following enactment") -> effective.
        administrative: Rule is an agency figure; a period start ("March 1, 2026
            through February 28, 2027") is its effective date.
    """
    text = f"{quote} {raw or ''}"
    if derived:
        return "effective"
    if _OPERATIVE.search(text):
        return "operative"
    # A statute history note applies only to the date on its own line:
    # "(Amended by Stats. 2025, Ch. 203, Sec. 1. (AB 1529)  Effective January 1, 2026.)"
    # "Repealed ... and added by Stats." re-enacts the section (an amendment), and an
    # "Added by Stats. ... Effective X. Operative Y" note: Y is when the section applies.
    same_line = context_before.rsplit("\n", 1)[-1] + " " + text
    note = _HISTORY_NOTE.search(same_line)
    if _AMENDMENT.search(text) or (note and (
            note.group(1).lower() != "added" or re.search(r"\bOperative\b", same_line[note.end():]))):
        return "amendment"
    # Municipal code history notes: "(Amended 2-27-2024 by O-21769 N.S.; effective 3-28-2024.)"
    # vs "("Exemptions" added 5-25-2023 by O-21647 N.S.; effective 6-24-2023.)" (= the section's own date).
    paren = same_line[same_line.rfind("(") :] if "(" in same_line else ""
    if paren and re.search(r"\b(amended|repealed)\b", paren, re.I) and re.search(r"\beffective\b", paren, re.I):
        return "amendment"
    if _EFFECTIVE.search(text):
        return "effective"
    if administrative and _PERIOD.search(text):
        return "effective"
    if _ENACTED.search(text):
        return "enacted"
    return None
