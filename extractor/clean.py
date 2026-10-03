"""Boilerplate removal for corpus documents, without altering legal text.

Design rules (non-negotiable):

* **Line-granular, never intra-line.** The cleaner only *drops whole lines*.
  Every line that survives is byte-identical to the raw line, so any span
  that lies inside a single kept line is guaranteed to exist verbatim in
  ``raw_text``.
* **Every cut is mapped.** ``CleanResult.segments`` maps each kept line back to
  its offset in ``raw_text`` (``to_raw_span``), and ``removed`` records what
  was dropped and why (for the audit log).
* **Cuts are guarded.** A header/footer cut is refused if it would remove a
  line that looks like operative legal text (``_looks_legal``); the refusal is
  reported in ``warnings`` and the text is kept.

``raw_text`` here always means the document body *after* the
``SOURCE:/RETRIEVED:`` header that ``corpus.py`` strips off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# --------------------------------------------------------------------------- #
# Site profiles
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SiteProfile:
    """How to find the main content of pages from one publisher template.

    Attributes:
        name: Short label used in audit output.
        url_pattern: Regex matched (``re.search``) against the source URL.
        start_after: Content begins on the line *after* the first line that
            fully matches one of these regexes (searched in the first
            ``start_window`` fraction of the document).
        end_at: Content ends *before* the first line (after the start) that
            fully matches one of these regexes.
        drop_lines: Exact stripped lines removed anywhere in the content.
        drop_patterns: Regexes; fully matching stripped lines are removed anywhere.
        drop_blocks: ``(first, last)`` regex pairs; the first line matching
            ``first`` through the next line matching ``last`` is removed (guarded).
        start_window: Fraction of lines in which a start marker may be found.
    """

    name: str
    url_pattern: str
    start_after: tuple[str, ...] = ()
    end_at: tuple[str, ...] = ()
    drop_lines: frozenset[str] = frozenset()
    drop_patterns: tuple[str, ...] = ()
    drop_blocks: tuple[tuple[str, str], ...] = ()
    start_window: float = 0.7


# Lines that are navigation chrome on every site we have seen.
GLOBAL_DROP_LINES: frozenset[str] = frozenset(
    {
        "Skip to main content",
        "Skip to Main Content",
        "Skip to Content",
        "skip to content",
        "Skip to Navigation",
        "Skip to Footer",
        "Skip to site search",
        "﻿",
    }
)

_MA_ACCOUNT_CHROME = frozenset(
    {
        "Search the Legislature",
        "Search The Legislature",
        "Search",
        "Sign in",
        "Sign In",
        "with Facebook",
        "with Google",
        "Register",
        "×",
    }
)

PROFILES: tuple[SiteProfile, ...] = (
    SiteProfile(
        name="leginfo-code",
        url_pattern=r"leginfo\.legislature\.ca\.gov/faces/codes_display",
        start_after=(r"Code Text",),
        start_window=0.95,  # short sections: nav chrome is most of the page
    ),
    SiteProfile(
        name="leginfo-bill",
        url_pattern=r"leginfo\.legislature\.ca\.gov/faces/billNav",
        start_after=(r"Bill Start",),
        start_window=0.95,
    ),
    SiteProfile(
        name="malegislature-law",
        url_pattern=r"malegislature\.gov/Laws/",
        start_after=(r"Next",),
        end_at=(r"×",),
        drop_lines=_MA_ACCOUNT_CHROME,
    ),
    SiteProfile(
        name="malegislature-bill",
        url_pattern=r"malegislature\.gov/Bills/",
        start_after=(r"Search",),
        end_at=(
            r"The information contained in this website is for general information purposes only.*",
            r"Update Testimony",
            r"×",
        ),
        drop_lines=_MA_ACCOUNT_CHROME
        | frozenset({"View Text", "Print Preview", "Download PDF", "Tabs"}),
    ),
    SiteProfile(
        name="boston.gov",
        url_pattern=r"boston\.gov/(?!sites/default/files)",
        # The "Popular questions" widget rotates its 3 questions, so start after
        # its heading and drop the question lines by pattern.
        start_after=(r"Popular questions",),
        end_at=(r"Provide Your Feedback",),
        drop_lines=frozenset({"Toggle", "Page Sections"}),
        drop_patterns=(r"(How do I|What is my) [^.]{5,60}\?",),
        start_window=0.5,
    ),
    SiteProfile(
        name="cambridgema.gov",
        url_pattern=r"cambridgema\.gov",
        start_after=(r"secure websites\.",),
        end_at=(r"Contact Us",),
    ),
    SiteProfile(
        name="lahd",
        url_pattern=r"housing\.lacity\.gov/(?!wp-content)",
        start_after=(r"Website Feedback",),
        end_at=(r"\(Visited [\d,]+ times.*", r"Comments are closed\.", r"Supported Browsers"),
        drop_lines=frozenset({"Back", "Print", "|"}),
    ),
    SiteProfile(
        name="ca-crd",
        url_pattern=r"calcivilrights\.ca\.gov",
        end_at=(r"\d+ Bannon Street.*",),
        # In-page tab strip ("What Discrimination Looks Like ... Fact Sheets").
        drop_blocks=((r"What Discrimination Looks Like", r"Fact Sheets"),),
    ),
    SiteProfile(
        name="jersey-city",
        url_pattern=r"jerseycitynj\.gov",
        start_after=(r"Last item for navigation",),
    ),
    SiteProfile(
        name="berkeley-rentboard",
        url_pattern=r"rentboard\.berkeleyca\.gov/(?!sites/default/files)",
        start_after=(r"Print",),
        end_at=(r"News",),
        drop_lines=frozenset({"Share"}),
    ),
    SiteProfile(
        name="sf.gov",
        url_pattern=r"(?:^|//|\.)(?:sf\.gov|sf-hrc\.org)",
        start_after=(r"Skip to main content",),
        end_at=(r"Tags: .*", r"Archived website", r"Print version"),
        drop_lines=frozenset({"Info Page", "news", "Report", "Agency"}),
    ),
    SiteProfile(
        name="santa-ana",
        url_pattern=r"santa-ana\.gov",
        end_at=(r"This content is for decoration only",),
    ),
)

# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Segment:
    """One kept line: ``clean_text[clean_start:clean_start+length]`` equals
    ``raw_text[raw_start:raw_start+length]``."""

    clean_start: int
    raw_start: int
    length: int


@dataclass(frozen=True)
class RemovedBlock:
    """A contiguous run of dropped raw lines (1-based, inclusive)."""

    first_line: int
    last_line: int
    reason: str
    preview: str


@dataclass
class CleanResult:
    """Output of ``clean``. ``clean_text`` is what the LLM sees."""

    clean_text: str
    segments: list[Segment]
    removed: list[RemovedBlock]
    profile: str
    warnings: list[str] = field(default_factory=list)
    raw_line_count: int = 0
    kept_line_count: int = 0

    def to_raw_span(self, clean_start: int, clean_end: int) -> tuple[int, int] | None:
        """Map a ``[start, end)`` span of ``clean_text`` to ``raw_text`` offsets.

        Returns ``None`` when the span crosses a point where lines were removed
        (then the clean span does not exist contiguously in the raw text).
        """
        first = _segment_at(self.segments, clean_start)
        last = _segment_at(self.segments, max(clean_start, clean_end - 1))
        if first is None or last is None:
            return None
        i, j = self.segments.index(first), self.segments.index(last)
        for a, b in zip(self.segments[i:j], self.segments[i + 1 : j + 1]):
            # Adjacent kept lines must be adjacent in raw too (separated by one "\n").
            if b.raw_start != a.raw_start + a.length + 1:
                return None
        raw_start = first.raw_start + (clean_start - first.clean_start)
        raw_end = last.raw_start + (clean_end - last.clean_start)
        return raw_start, raw_end


def _segment_at(segments: list[Segment], pos: int) -> Segment | None:
    lo, hi = 0, len(segments) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        s = segments[mid]
        if pos < s.clean_start:
            hi = mid - 1
        elif pos > s.clean_start + s.length:  # "+length" allows the joining "\n"
            lo = mid + 1
        else:
            return s
    return None


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #

# A line "looks legal" if it is substantive prose with operative language or a
# statutory enumerator. Header/footer cuts that would remove one are refused.
_LEGAL_SIGNAL = re.compile(
    r"\bshall\b|\bmay not\b|\bmust not\b|\bunlawful\b|§|^\s*\(\w{1,5}\)\s|^\s*SEC(?:TION)?\.?\s+\d",
)


def _looks_legal(line: str) -> bool:
    return len(line.strip()) >= 40 and bool(_LEGAL_SIGNAL.search(line))


def profile_for(url: str) -> SiteProfile | None:
    """Return the first profile whose ``url_pattern`` matches ``url``."""
    for p in PROFILES:
        if re.search(p.url_pattern, url):
            return p
    return None


def _first_full_match(lines: list[str], patterns: Iterable[str], lo: int, hi: int) -> int | None:
    compiled = [re.compile(p) for p in patterns]
    for i in range(lo, hi):
        s = lines[i].strip()
        if any(c.fullmatch(s) for c in compiled):
            return i
    return None


def clean(raw_text: str, url: str = "") -> CleanResult:
    """Remove navigation/boilerplate lines from ``raw_text``.

    Args:
        raw_text: Document body (header already stripped).
        url: Source URL, used to pick a ``SiteProfile``.

    Returns:
        A ``CleanResult`` whose ``clean_text`` is a subsequence of whole raw lines.
    """
    lines = raw_text.split("\n")
    n = len(lines)
    profile = profile_for(url)
    reason: list[str | None] = [None] * n  # None = keep
    warnings: list[str] = []

    def guarded_cut(lo: int, hi: int, why: str) -> None:
        legal = [i + 1 for i in range(lo, hi) if _looks_legal(lines[i])]
        if legal:
            warnings.append(f"refused {why} (lines {lo + 1}-{hi}): would drop legal-looking line(s) {legal[:5]}")
            return
        for i in range(lo, hi):
            reason[i] = reason[i] or why

    start, end = 0, n
    if profile:
        if profile.start_after:
            k = _first_full_match(lines, profile.start_after, 0, max(1, int(n * profile.start_window)))
            if k is not None:
                guarded_cut(0, k + 1, f"header<{profile.name}>")
                if reason[k] is not None:
                    start = k + 1
        if profile.end_at:
            k = _first_full_match(lines, profile.end_at, start, n)
            if k is not None:
                guarded_cut(k, n, f"footer<{profile.name}>")
                if reason[k] is not None:
                    end = k

    # Keep the page title (first non-blank line) even inside a header cut: it is
    # often the only place carrying citation context, e.g. "General Law - Part II,
    # Title I, Chapter 186, Section 11" or "California Code, CIV 1947.12".
    title = next((i for i in range(n) if lines[i].strip()), None)
    if title is not None and (reason[title] or "").startswith("header<"):
        reason[title] = None

    if profile:
        for first, last in profile.drop_blocks:
            a = _first_full_match(lines, (first,), start, end)
            b = _first_full_match(lines, (last,), a + 1, end) if a is not None else None
            if a is not None and b is not None:
                guarded_cut(a, b + 1, f"block<{profile.name}>")

    drop_exact = GLOBAL_DROP_LINES | (profile.drop_lines if profile else frozenset())
    drop_re = [re.compile(p) for p in (profile.drop_patterns if profile else ())]
    for i in range(start, end):
        s = lines[i].strip()
        if reason[i] is None and (s in drop_exact or any(r.fullmatch(s) for r in drop_re)):
            reason[i] = "nav-line"

    # Collapse blank runs (and leading/trailing blanks): never legal content.
    prev_blank = True
    for i in range(n):
        if reason[i] is not None:
            continue
        blank = not lines[i].strip()
        if blank and prev_blank:
            reason[i] = "blank"
        prev_blank = blank
    for i in range(n - 1, -1, -1):
        if reason[i] is None:
            if not lines[i].strip():
                reason[i] = "blank"
            else:
                break

    # Build clean text + map.
    raw_offsets = []
    off = 0
    for line in lines:
        raw_offsets.append(off)
        off += len(line) + 1
    segments: list[Segment] = []
    parts: list[str] = []
    pos = 0
    for i, line in enumerate(lines):
        if reason[i] is None:
            segments.append(Segment(pos, raw_offsets[i], len(line)))
            parts.append(line)
            pos += len(line) + 1
    clean_text = "\n".join(parts)

    removed: list[RemovedBlock] = []
    i = 0
    while i < n:
        if reason[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and reason[j + 1] == reason[i]:
            j += 1
        if reason[i] != "blank":
            preview = " / ".join(l.strip() for l in lines[i : j + 1] if l.strip())[:160]
            removed.append(RemovedBlock(i + 1, j + 1, reason[i] or "", preview))
        i = j + 1

    return CleanResult(
        clean_text=clean_text,
        segments=segments,
        removed=removed,
        profile=profile.name if profile else "generic",
        warnings=warnings,
        raw_line_count=n,
        kept_line_count=len(segments),
    )


def explain(raw_text: str, result: CleanResult) -> str:
    """Render a line-by-line before/after view for human review.

    Kept lines are prefixed ``"  "``; dropped lines ``"- "`` followed by the
    drop reason. Raw line numbers are 1-based.
    """
    kept_starts = {s.raw_start for s in result.segments}
    reasons: dict[int, str] = {}
    for b in result.removed:
        for ln in range(b.first_line, b.last_line + 1):
            reasons[ln] = b.reason
    out: list[str] = []
    off = 0
    for ln, line in enumerate(raw_text.split("\n"), start=1):
        if off in kept_starts:
            out.append(f"{ln:5d}   {line}")
        elif line.strip():
            out.append(f"{ln:5d} - {line}    [{reasons.get(ln, 'nav-line')}]")
        off += len(line) + 1
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Quote verification against raw text
# --------------------------------------------------------------------------- #

_QUOTE_FOLD = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", " ": " ", "–": "-", "—": "-"})


@dataclass(frozen=True)
class QuoteMatch:
    """Where a quoted span was found in ``raw_text``.

    ``exact`` is True when it matched with only whitespace normalisation;
    False when typographic folding (curly quotes, dashes, NBSP) was also needed.
    """

    raw_start: int
    raw_end: int
    exact: bool


def _normalize_with_map(text: str, fold: bool) -> tuple[str, list[int]]:
    """Collapse whitespace runs to one space; return (normalized, index map to original)."""
    if fold:
        text = text.translate(_QUOTE_FOLD)
    out: list[str] = []
    idx: list[int] = []
    in_ws = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_ws and out:
                out.append(" ")
                idx.append(i)
            in_ws = True
        else:
            out.append(ch)
            idx.append(i)
            in_ws = False
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def locate_quote(raw_text: str, quote: str) -> QuoteMatch | None:
    """Find ``quote`` in ``raw_text`` tolerating line breaks / spacing differences.

    Line breaks in the corpus often fall mid-sentence (PDF and HTML extraction),
    so a model-copied span must be matched whitespace-insensitively.
    Returns raw offsets so the exact source substring can be re-extracted.
    """
    for fold in (False, True):
        norm_raw, idx = _normalize_with_map(raw_text, fold)
        norm_q, _ = _normalize_with_map(quote.strip(), fold)
        if not norm_q:
            return None
        k = norm_raw.find(norm_q)
        if k >= 0:
            return QuoteMatch(idx[k], idx[k + len(norm_q) - 1] + 1, exact=not fold)
    return None
