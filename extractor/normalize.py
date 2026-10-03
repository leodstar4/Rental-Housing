"""Normalisation across documents: citations, IDs, deduplication, conflicts."""

from __future__ import annotations

from .models import RuleInternal


def normalize_citation(citation: str, jurisdiction: str) -> str:
    """Canonicalise a cite, e.g. ``"CIV 1947.12"`` -> ``"Cal. Civ. Code § 1947.12"``,
    ``"Chapter 186, Section 15B"`` -> ``"Mass. Gen. Laws ch. 186, § 15B"``,
    ``"P.L. 2025, c.405"`` stays. Unknown formats are returned stripped."""
    raise NotImplementedError


def normalize_jurisdiction(value: str) -> str:
    """``"california"`` -> ``"CA"``; ``"City of Boston"`` -> ``"Boston, MA"``."""
    raise NotImplementedError


def rule_fingerprint(rule: RuleInternal) -> str:
    """Stable identity for dedup: (jurisdiction, category, normalised citation,
    normalised key_value). Independent of wording/order of extraction."""
    raise NotImplementedError


def deduplicate(rules: list[RuleInternal]) -> list[RuleInternal]:
    """Merge rules with the same fingerprint (e.g. D046/D047 are the same bill).

    Keeps the best-supported record: official > secondary source, primary text
    (statute/bill) > agency summary, then highest confidence. Merges
    ``effective_dates`` claims from all duplicates so disagreements survive.
    """
    raise NotImplementedError


def assign_ids(rules: list[RuleInternal]) -> list[RuleInternal]:
    """Assign ``r-0001``... deterministically (sorted by fingerprint), so IDs are
    stable across runs with the same inputs."""
    raise NotImplementedError


def detect_conflicts(rules: list[RuleInternal]) -> list[RuleInternal]:
    """Set ``conflict_flag``/``conflict_note`` and ``overrides``/``interaction``.

    Flags: (1) a rule with ≥2 distinct ``effective_dates`` claims (Berkeley
    13.63, LA RSO formula); (2) state vs city rules in the same category where
    preemption is possible (NJ FAIR Act vs Jersey City/Hoboken, T3); (3) state
    floor vs stricter local rule (CA 1947.12 vs local rent control ->
    ``superseded`` downstream).
    """
    raise NotImplementedError
