"""Cross-document normalization (no LLM calls).

Pipeline (``normalize_rules``), in order:

1. ``canonicalize``      citation style ("§ " with a space, code abbreviations) and the alias
                         table ``data/citation_aliases.yaml`` ("Rent Ordinance" de SF ->
                         "S.F. Admin. Code ch. 37"). ``law_keys`` gives the law-level identity.
2. ``resolve_citations`` held/no_citation rules take the citation of another rule of the SAME
                         law and jurisdiction (alias or law name found in the text);
                         ``citation_resolved_from`` = that rule's team_rule_id; confidence x0.9.
3. ``apply_defaults``    ``data/jurisdiction_defaults.yaml`` (CA: January 1 after enactment,
                         Cal. Const. art. IV, § 8(c)) for enacted rules with no effective date.
4. ``merge_rules``       same (jurisdiction, category, stage, base citation without subsection)
                         AND same coverage thresholds, compatible key_value and same effective
                         dates -> one rule; requirement summarizes, every literal quote is kept
                         in ``evidence``.
5. ``link_administrative`` an administrative figure is folded into the enacted rule of the same
                         jurisdiction and category (preferring the same law) as a
                         ``key_value_details`` entry; otherwise held/administrative_unlinked.
6. ``assign_ids``        ``{JUR}-{CAT}-{NN}`` (P = pending, F = failed, H = held), deterministic.
7. ``apply_precedence``  state rules that yield to stricter local rules (e.g. Civ. Code
                         § 1947.12 vs local rent control) or preempt them get ``overrides``.

Cross-document conflicts are detected afterwards in ``conflicts.py``.
"""

from __future__ import annotations

import functools
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import yaml
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from . import config
from .corpus import Document
from .models import DateClaim, Evidence, LegalStage, RuleInternal, ValueDetail

JUR_CODES: dict[str, str] = {
    "CA": "CA", "NJ": "NJ", "MA": "MA",
    "Berkeley, CA": "BRK", "Los Angeles, CA": "LA", "San Diego, CA": "SD", "San Francisco, CA": "SF",
    "Santa Ana, CA": "SNA", "Hoboken, NJ": "HOB", "Jersey City, NJ": "JC", "Newark, NJ": "NWK",
    "Boston, MA": "BOS", "Cambridge, MA": "CAM",
}
CAT_CODES: dict[str, str] = {
    "rent_increase_limits": "RENT", "just_cause_eviction": "JUST", "security_deposits": "DEP",
    "application_screening_fees": "FEE", "screening_restrictions": "SCRN", "algorithmic_rent_setting": "ALGO",
}
RESOLVED_CITATION_FACTOR = 0.9
TITLE_SIMILARITY = 70  # rapidfuzz token_set_ratio for "same provision" checks
ADMIN_MIN_SIMILARITY = 60  # admin figure naming no law, several candidate rules
ADMIN_MIN_MARGIN = 10
_LAW_WORD = re.compile(r"\b(ordinance|act|code|chapter|statute|law|regulation|section)\b|§|\([A-Z]{2,6}\)", re.I)

_YIELDS = re.compile(
    r"does not apply to [^.]{0,120}(local|rent control|ordinance|RSO)|more (restrictive|protective)|"
    r"local [^.]{0,60}applies instead|\byields? to\b", re.I)
_PREEMPTS = re.compile(
    r"(?<!not )(?<!n't )\bpreempts?\b|prohibits? local|municipalit(y|ies) (are|is) prohibited|"
    r"overrides? municipal|may not (enact|adopt) [^.]{0,40}ordinance", re.I)
_NEGATED_PREEMPT = re.compile(r"\b(not|n't|nor)\b[^.]{0,20}\bpreempt", re.I)


def preempts(text: str | None) -> bool:
    """Interaction says the rule preempts/prohibits local rules (negations excluded)."""
    if not text:
        return False
    stripped = _NEGATED_PREEMPT.sub(" ", text)
    return bool(_PREEMPTS.search(stripped))


# --------------------------------------------------------------------------- #
# Alias table / citations
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def alias_table() -> dict:
    return yaml.safe_load(config.CITATION_ALIASES_PATH.read_text(encoding="utf-8"))


def _fmt(citation: str) -> str:
    s = re.sub(r"\s+", " ", citation.replace(" ", " ")).strip()
    for pat, repl in alias_table()["formatting"]:
        s = re.sub(pat, repl, s, flags=re.I)
    return s.strip()


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9§.]+", " ", s.lower()).strip()


def _law_for(text: str, jurisdiction: str) -> dict | None:
    """The alias-table law that ``text`` (a citation or alias) designates, if any."""
    s = _fmt(text)
    n = _norm_name(s)
    for law in alias_table()["laws"]:
        if law["jurisdiction"] != jurisdiction:
            continue
        if n == _norm_name(law["canonical"]) or n in {_norm_name(x) for x in law["names"]}:
            return law
        if law.get("section_pattern") and re.search(law["section_pattern"], s, re.I):
            return law
    return None


def normalize_citation(citation: str | None, jurisdiction: str) -> str | None:
    """Schema style; a bare law name from the alias table becomes its canonical citation."""
    if not citation:
        return citation
    s = _fmt(citation)
    law = _law_for(s, jurisdiction)
    if law and _norm_name(s) in {_norm_name(x) for x in law["names"]}:
        return law["canonical"]
    return s


def base_citation(citation: str | None) -> str | None:
    """Drop trailing subsection markers: "§ 16729(a)" -> "§ 16729", "2A:18-61.1(f)" -> "2A:18-61.1"."""
    if not citation:
        return citation
    s = re.sub(r"(\s*\([0-9A-Za-z]{1,4}\))+$", "", citation).strip()
    return re.sub(r"(?<=\d)(\.[A-Z](?:\.[0-9A-Za-z]+)*)$", "", s)  # LAMC style "§ 151.09.G" -> "§ 151.09"


def law_keys(rule: RuleInternal) -> set[str]:
    """Law-level identities of a rule: canonical law of its citation and of each alias."""
    keys: set[str] = set()
    for text in [rule.citation, *rule.citation_aliases]:
        if not text:
            continue
        law = _law_for(text, rule.jurisdiction)
        if law:
            keys.add(law["canonical"])
        elif text == rule.citation:
            keys.add(base_citation(_fmt(text)))
    return keys


def _law_names(rule: RuleInternal) -> set[str]:
    """Normalized names (>= 2 tokens or containing digits) a rule uses for its law."""
    out = set()
    for text in [rule.citation, *rule.citation_aliases]:
        if not text:
            continue
        n = _norm_name(text)
        if len(n) >= 6 and (len(n.split()) >= 2 or any(c.isdigit() for c in n)):
            out.add(n)
        # acronym given in parentheses: "Just Cause Ordinance (JCO)" -> "jco"
        out |= {a.lower() for a in re.findall(r"\(([A-Z]{2,6})\)", text)}
        law = _law_for(text, rule.jurisdiction)
        if law:
            out |= {_norm_name(x) for x in [law["canonical"], *law["names"]] if len(x) >= 3}
    return out


_STATE_BILL = re.compile(r"^(CA|NJ|MA) (AB|SB|ACA|SCA|A|S|H)\.? ?\d+", re.I)


def canonicalize(rules: list[RuleInternal]) -> None:
    """Citation style + consistency: a state bill (``MA H.3744``, ``CA AB 325``) is enacted
    by the state legislature, so its jurisdiction/level are the state's even when the bill
    concerns one city (a home-rule petition for Boston is still MA law)."""
    for r in rules:
        r.citation = normalize_citation(r.citation, r.jurisdiction)
        m = _STATE_BILL.match(r.citation or "")
        if m and r.level == "city":
            state = m.group(1).upper()
            r.validation_errors.append(
                f"jurisdiction {r.jurisdiction!r} -> {state!r}: {r.citation} is a state bill")
            r.jurisdiction, r.level = state, "state"


# --------------------------------------------------------------------------- #
# Citation resolution for held/no_citation
# --------------------------------------------------------------------------- #


def _text(rule: RuleInternal) -> str:
    cov = rule.coverage.notes if rule.coverage and rule.coverage.notes else ""
    return _norm_name(" ".join(filter(None, [rule.title, rule.requirement, rule.quoted_span,
                                             rule.coverage_text, cov, " ".join(rule.citation_aliases)])))


def _names_match(names: set[str], text: str, aliases: list[str]) -> int:
    """How many of ``names`` the other rule uses (alias token-set match or name inside text)."""
    hits = 0
    alias_norm = [_norm_name(a) for a in aliases]
    for n in names:
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", text):
            hits += 1
        elif any(len(a.split()) >= 2 and fuzz.token_set_ratio(n, a) == 100 for a in alias_norm):
            hits += 1
    return hits


def resolve_citations(rules: list[RuleInternal]) -> list[tuple[str, str]]:
    """Give held/no_citation (non-administrative) rules the citation of a same-law rule."""
    sources = [r for r in rules if r.disposition == "accepted" and r.citation
               and r.stage != LegalStage.ADMINISTRATIVE]
    resolved = []
    for h in rules:
        if h.disposition != "held" or h.disposition_reason != "no_citation" or h.stage == LegalStage.ADMINISTRATIVE:
            continue
        own = {_norm_name(a) for a in h.citation_aliases if len(a) >= 3}
        title = _norm_name(h.title)
        scored: list[tuple[float, RuleInternal]] = []
        for s in sources:
            if s.jurisdiction != h.jurisdiction:
                continue
            if own:
                # The held rule names its own law: match ONLY on those names (the source's
                # citation/aliases) and the title; other laws mentioned in its body (e.g. "units
                # not regulated by the RSO") must not pull the citation toward them.
                hits = _names_match(own, " ".join(_law_names(s)), s.citation_aliases)
                hits += _names_match(_law_names(s), title, [])
            else:
                hits = _names_match(_law_names(s), _text(h), [])
            if hits:
                score = 3 * hits + (0.5 if s.category == h.category else 0) - 0.01 * len(s.citation_aliases)
                scored.append((score, s))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], x[1].uid or ""))
        best = scored[0][1]
        if not own:
            # Text-only evidence must point to ONE law; "applies to RSO and JCO units" is ambiguous.
            top = [s for sc, s in scored if sc >= scored[0][0] - 0.5]
            if len({frozenset(law_keys(s)) for s in top}) > 1:
                h.validation_errors.append("citation not resolved: text names several laws")
                continue
        # The held rule shares the LAW with the source, not its section: use the law-level
        # canonical citation when the alias table knows it (e.g. SF "Rent Ordinance" matched
        # via S.F. Admin. Code § 37.10C -> "S.F. Admin. Code ch. 37").
        law = _law_for(best.citation, best.jurisdiction)
        h.citation = law["canonical"] if law else base_citation(best.citation)
        h.citation_resolved_from = best.uid  # translated to team_rule_id in assign_ids
        h.disposition, h.disposition_reason = "accepted", None
        h.confidence = round((h.confidence or 0) * RESOLVED_CITATION_FACTOR, 3)
        h.evidence.append(Evidence(source_doc_id=best.source_doc_id, source_url=best.source_url,
                                   retrieved_at=best.retrieved_at, citation=best.citation,
                                   quoted_span=best.quoted_span, role="citation_source", uid=best.uid))
        resolved.append((h.uid, best.uid))
    return resolved


# --------------------------------------------------------------------------- #
# Jurisdiction calendar defaults
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def defaults_table() -> list[dict]:
    return yaml.safe_load(config.JURISDICTION_DEFAULTS_PATH.read_text(encoding="utf-8"))["defaults"]


def apply_defaults(rules: list[RuleInternal], docs: dict[str, Document]) -> list[tuple[str, str]]:
    applied = []
    for r in rules:
        if r.disposition in ("rejected", "merged"):
            continue
        for d in defaults_table():
            if (r.jurisdiction, r.level, r.stage.value) != (d["jurisdiction"], d["level"], d["stage"]):
                continue
            if not (r.enacted_date and r.enacted_date.verified and r.enacted_date.value):
                continue
            if any(x.kind == "effective" and x.value for x in r.effective_dates):
                continue
            raw = docs[r.source_doc_id].raw_text if r.source_doc_id in docs else ""
            if any(re.search(p, raw, re.I) for p in d.get("skip_if_text_matches", [])):
                continue
            if d["effective"] != "january_1_next_year":
                raise ValueError(f"unknown default {d['effective']!r}")
            value = date(r.enacted_date.value.year + 1, 1, 1)
            r.effective_dates.append(DateClaim(
                value=value, raw=f"January 1 following enactment ({d['source']})", derived=True,
                verified=True, source_doc_id=r.source_doc_id, quoted_span=r.enacted_date.quoted_span,
                kind="effective", kind_source="default", rule_applied=d["id"]))
            applied.append((r.uid, f"{d['id']} -> {value}"))
    return applied


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #


def _signature(r: RuleInternal) -> tuple:
    c = r.coverage
    if c is None:
        return (None,) * 6
    return (c.units_min, c.units_max, c.year_built_min, c.year_built_max,
            c.certificate_of_occupancy_on_or_before, c.building_age_min_years)


def _numbers(s: str) -> set[float]:
    """Numeric values in a key value ("$8,245.00" and "$8,245" -> {8245.0})."""
    return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))}


def kv_equal(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is b
    na, nb = _norm_name(a), _norm_name(b)
    if na == nb:
        return True
    # Same figures (one set may add a detail, e.g. "...; 0% if CPI negative") AND similar wording;
    # a lone shared number ("0% freeze" vs "0% utility add-on") is not enough.
    xa, xb = _numbers(a), _numbers(b)
    return bool(xa and xb) and (xa <= xb or xb <= xa) and fuzz.token_set_ratio(na, nb) >= 60


def kv_compatible(a: str | None, b: str | None) -> bool:
    return a is None or b is None or kv_equal(a, b)


def _eff_set(r: RuleInternal) -> frozenset:
    return frozenset(d.value for d in r.effective_dates if d.kind == "effective" and d.value)


#: Most advanced legislative stage wins when one law appears at several stages
#: (e.g. a bill page saying "pending" and the chaptered text saying "enacted").
STAGE_RANK = {LegalStage.ENACTED: 4, LegalStage.ADMINISTRATIVE: 3, LegalStage.BILL_FAILED: 2,
              LegalStage.BILL_PENDING: 1, LegalStage.UNKNOWN: 0}


def _priority(r: RuleInternal) -> tuple:
    return (-STAGE_RANK[r.stage], r.is_secondary_source, -(r.confidence or 0), r.uid or "")


def _dedupe_text(parts: list[str | None], threshold: int = 85) -> list[str]:
    out: list[str] = []
    for p in parts:
        if p and not any(fuzz.ratio(p, q) >= threshold for q in out):
            out.append(p)
    return out


def _stage_history(cluster: list[RuleInternal]) -> list:
    from .models import StageClaim

    out, seen = [], set()
    for r in cluster:
        for c in (r.stage_history or [StageClaim(stage=r.stage.value, source_doc_id=r.source_doc_id, uid=r.uid,
                                                  enacted_date=r.enacted_date.value if r.enacted_date else None)]):
            if (c.stage, c.source_doc_id) not in seen:
                seen.add((c.stage, c.source_doc_id))
                out.append(c)
    return out


def _merge_cluster(cluster: list[RuleInternal]) -> RuleInternal:
    cluster = sorted(cluster, key=_priority)
    head = cluster[0]
    if len(cluster) == 1:
        head.stage_history = _stage_history(cluster)
        if not head.evidence or head.evidence[0].role != "primary":
            head.evidence.insert(0, _evidence(head, "primary"))
        return head
    m = head.model_copy(deep=True)
    others = cluster[1:]
    m.requirement = " ".join(_dedupe_text([r.requirement for r in cluster]))
    m.key_value = next((r.key_value for r in cluster if r.key_value), None)
    cites = {r.citation for r in cluster}
    if len(cites) > 1:
        m.citation = base_citation(head.citation)
    aliases = [*head.citation_aliases]
    for r in others:
        for a in [*r.citation_aliases, *([r.citation] if r.citation not in cites - {m.citation} else [])]:
            if a and a.lower() not in {x.lower() for x in aliases} and a != m.citation:
                aliases.append(a)
    m.citation_aliases = aliases
    seen = set()
    dates = []
    for r in cluster:
        for d in r.effective_dates:
            k = (d.value, d.kind, d.source_doc_id)
            if k not in seen:
                seen.add(k)
                dates.append(d)
    m.effective_dates = dates
    m.enacted_date = next((r.enacted_date for r in cluster if r.enacted_date), None)
    # A sunset survives only if every member shares it (an old text version's repeal date
    # must not expire the merged, current rule).
    sunsets = {r.sunset_date.value if r.sunset_date else None for r in cluster}
    m.sunset_date = head.sunset_date if len(sunsets) == 1 else None
    if m.coverage is not None:
        ex, keys = [], set()
        for r in cluster:
            for e in (r.coverage.exemption_conditions if r.coverage else []):
                k = (e.field, e.op, str(e.value))
                if k not in keys:
                    keys.add(k)
                    ex.append(e)
        m.coverage.exemption_conditions = ex
    m.coverage_text = next((r.coverage_text for r in cluster if r.coverage_text), None)
    m.exemptions = " ".join(_dedupe_text([r.exemptions for r in cluster])) or None
    m.interaction = " ".join(_dedupe_text([r.interaction for r in cluster])) or None
    m.is_secondary_source = all(r.is_secondary_source for r in cluster)
    m.confidence = max((r.confidence or 0) for r in cluster)
    m.conflict_flag = any(r.conflict_flag for r in cluster)
    m.conflict_note = "; ".join(_dedupe_text([r.conflict_note for r in cluster])) or None
    m.validation_errors = list(dict.fromkeys(e for r in cluster for e in r.validation_errors))
    # stage: the head is the most advanced verified stage (see _priority); keep every claim
    m.stage = head.stage
    m.stage_history = _stage_history(cluster)
    m.evidence = [_evidence(head, "primary")] + [e for e in head.evidence if e.role != "primary"]
    for r in others:
        m.evidence.append(_evidence(r, "merged"))
        m.evidence += [e for e in r.evidence if e.role != "primary"]
        r.disposition, r.disposition_reason, r.merged_into = "merged", "duplicate_merged", head.uid
        m.merged_uids.append(r.uid)
        m.merged_uids += r.merged_uids
    return m


def _evidence(r: RuleInternal, role: str) -> Evidence:
    return Evidence(source_doc_id=r.source_doc_id, source_url=r.source_url, retrieved_at=r.retrieved_at,
                    citation=r.citation, quoted_span=r.quoted_span, role=role, uid=r.uid)


def merge_rules(rules: list[RuleInternal]) -> list[RuleInternal]:
    """Merge same-law duplicates among accepted non-administrative rules (see module doc)."""
    groups: dict[tuple, list[RuleInternal]] = defaultdict(list)
    passthrough = []
    for r in rules:
        if r.disposition == "accepted" and r.stage != LegalStage.ADMINISTRATIVE and r.citation:
            # stage is NOT part of the key: the same law at different stages merges, and the
            # most advanced verified stage wins (stage_history keeps every document's claim)
            groups[(r.jurisdiction, r.category, base_citation(r.citation))].append(r)
        else:
            passthrough.append(r)
    out = []
    for key in sorted(groups, key=str):
        clusters: list[list[RuleInternal]] = []
        for r in sorted(groups[key], key=_priority):
            for c in clusters:
                h = c[0]
                # no date / no key value = unknown, compatible with anything
                if _signature(h) == _signature(r) and all(
                        kv_compatible(x.key_value, r.key_value)
                        and (not _eff_set(x) or not _eff_set(r) or _eff_set(x) == _eff_set(r)) for x in c):
                    c.append(r)
                    break
            else:
                clusters.append([r])
        out += [_merge_cluster(c) for c in clusters]
    merged_away = [r for g in groups.values() for r in g if r.disposition == "merged"]
    return out + passthrough + merged_away


# --------------------------------------------------------------------------- #
# Administrative figures
# --------------------------------------------------------------------------- #


def link_administrative(rules: list[RuleInternal]) -> list[tuple[str, str | None]]:
    """Fold each administrative rule into an enacted rule (same jurisdiction & category)."""
    targets = [r for r in rules if r.disposition == "accepted" and r.stage == LegalStage.ENACTED]
    links = []
    for a in rules:
        if a.stage != LegalStage.ADMINISTRATIVE or a.disposition in ("rejected", "merged"):
            continue
        cands = [t for t in targets if (t.jurisdiction, t.category) == (a.jurisdiction, a.category)]
        akeys = law_keys(a)
        law_aliases = {_norm_name(x) for x in a.citation_aliases if _LAW_WORD.search(x)}
        same_law = [t for t in cands if law_keys(t) & akeys
                    or (law_aliases and _names_match(law_aliases, " ".join(_law_names(t)), t.citation_aliases))]
        names_a_law = bool(akeys or law_aliases)
        tgt = None
        if same_law:
            cands = same_law
        elif names_a_law:  # names a law that has no enacted rule here: do not attach to another law
            cands = []
        if len(cands) == 1:
            tgt = cands[0]
        elif cands:
            sims = sorted(((fuzz.token_set_ratio(a.title, t.title, processor=default_process), t) for t in cands),
                          key=lambda x: (-x[0], x[1].uid or ""))
            # No law named and several candidates: attach only on a clear title match.
            if names_a_law or (sims[0][0] >= ADMIN_MIN_SIMILARITY
                               and sims[0][0] - sims[1][0] >= ADMIN_MIN_MARGIN):
                tgt = sims[0][1]
        if tgt is None:
            a.disposition, a.disposition_reason = "held", "administrative_unlinked"
            if cands:
                a.validation_errors.append("administrative link ambiguous: several candidate rules, no law named")
            links.append((a.uid, None))
            continue
        start = next((d.value for d in a.effective_dates if d.value), None)
        tgt.key_value_details.append(ValueDetail(
            key_value=a.key_value or a.title, effective_from=start,
            effective_until=a.sunset_date.value if a.sunset_date else None,
            source_doc_id=a.source_doc_id, citation=a.citation, quoted_span=a.quoted_span, uid=a.uid))
        tgt.evidence.append(_evidence(a, "administrative"))
        a.disposition, a.disposition_reason, a.merged_into = "merged", "administrative_linked", tgt.uid
        links.append((a.uid, tgt.uid))
    return links


# --------------------------------------------------------------------------- #
# IDs and precedence
# --------------------------------------------------------------------------- #


def assign_ids(rules: list[RuleInternal], existing: dict[str, str] | None = None) -> dict[str, str]:
    """Deterministic ``{JUR}-{CAT}-{NN}`` for accepted/held rules; returns uid -> team_rule_id
    (merged uids map to the id of the rule that absorbed them).

    ``existing`` (uid -> id from a frozen snapshot) keeps published ids stable in incremental
    runs: a rule reuses the id of its own uid or of any uid it absorbed when that id still fits
    its cell; genuinely new rules get the next free number in the cell."""
    cells: dict[tuple, list[RuleInternal]] = defaultdict(list)
    for r in rules:
        if r.disposition in ("accepted", "held"):
            if r.disposition == "held":
                prefix = "H"
            elif r.stage == LegalStage.BILL_PENDING:
                prefix = "P"
            elif r.stage == LegalStage.BILL_FAILED:
                prefix = "F"
            else:
                prefix = ""
            cells[(r.jurisdiction, r.category, prefix)].append(r)
    ids: dict[str, str] = {}
    for (jur, cat, prefix), rs in sorted(cells.items(), key=lambda kv: str(kv[0])):
        rs.sort(key=lambda r: (base_citation(r.citation) or "~", r.title, r.uid or ""))
        jc = JUR_CODES.get(jur) or re.sub(r"[^A-Z]", "", jur.upper())[:4]
        stem = f"{jc}-{CAT_CODES[cat]}-{prefix}"
        if not existing:
            for i, r in enumerate(rs, 1):
                r.team_rule_id = f"{stem}{i:02d}"
                ids[r.uid] = r.team_rule_id
            continue
        taken: set[str] = set()
        pending: list[RuleInternal] = []
        for r in rs:
            prior = [existing[u] for u in [r.uid, *r.merged_uids] if u in existing]
            pick = next((p for p in prior if re.fullmatch(re.escape(stem) + r"\d{2}", p) and p not in taken), None)
            if pick:
                r.team_rule_id = pick
                taken.add(pick)
                ids[r.uid] = pick
            else:
                pending.append(r)
        used = {int(x[-2:]) for x in existing.values() if re.fullmatch(re.escape(stem) + r"\d{2}", x)} | {
            int(x[-2:]) for x in taken}
        n = max(used, default=0)
        for r in pending:
            n += 1
            r.team_rule_id = f"{stem}{n:02d}"
            ids[r.uid] = r.team_rule_id
    by_uid = {r.uid: r for r in rules}
    for r in rules:  # merged -> absorbing rule's id (follow chains)
        if r.disposition == "merged":
            tgt = r.merged_into
            while tgt in by_uid and by_uid[tgt].disposition == "merged":
                tgt = by_uid[tgt].merged_into
            if tgt in ids:
                ids[r.uid] = ids[tgt]
    for r in rules:
        if r.citation_resolved_from:
            r.citation_resolved_from = ids.get(r.citation_resolved_from, r.citation_resolved_from)
    return ids


def apply_precedence(rules: list[RuleInternal]) -> list[tuple[str, str, str]]:
    """Fill ``overrides``/``interaction`` for state rules that yield to or preempt local rules."""
    live = [r for r in rules if r.disposition in ("accepted", "held") and r.team_rule_id]
    out = []
    for s in live:
        if s.level != "state" or not s.interaction:
            continue
        yields, preempt = bool(_YIELDS.search(s.interaction)), preempts(s.interaction)
        if not (yields or preempt):
            continue
        state = s.jurisdiction
        # only exported (accepted) local law: overrides must point at team_rule_ids in rules.json
        locals_ = [l for l in live if l.disposition == "accepted" and l.level == "city"
                   and l.jurisdiction.endswith(f", {state}") and l.category == s.category
                   and l.stage == LegalStage.ENACTED]
        if not locals_:
            continue
        verb = "Yields to" if yields else "Preempts"
        ids = sorted(l.team_rule_id for l in locals_)
        s.overrides = sorted(set(s.overrides) | set(ids))
        s.interaction = f"{s.interaction} [{verb}: {', '.join(ids)}]"
        for l in locals_:
            l.overrides = sorted(set(l.overrides) | {s.team_rule_id})
            note = (f"Takes precedence over {s.team_rule_id} where more protective" if yields
                    else f"Subject to preemption by {s.team_rule_id}")
            l.interaction = f"{l.interaction} [{note}]" if l.interaction else f"[{note}]"
            out.append((s.team_rule_id, verb, l.team_rule_id))
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


@dataclass
class NormalizationReport:
    resolved_citations: list[tuple[str, str]] = field(default_factory=list)
    defaults_applied: list[tuple[str, str]] = field(default_factory=list)
    admin_links: list[tuple[str, str | None]] = field(default_factory=list)
    precedence: list[tuple[str, str, str]] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)
    cells: Counter = field(default_factory=Counter)


def normalize_rules(
    rules: list[RuleInternal], docs: dict[str, Document], existing_ids: dict[str, str] | None = None
) -> tuple[list[RuleInternal], NormalizationReport]:
    """Run steps 1-7 on validated rules (rejected rules pass through untouched).

    ``existing_ids``: uid -> team_rule_id of a frozen snapshot, to keep ids stable."""
    rep = NormalizationReport()
    rules = [r.model_copy(deep=True) for r in rules]
    canonicalize(rules)
    rep.resolved_citations = resolve_citations(rules)
    rep.defaults_applied = apply_defaults(rules, docs)
    rules = merge_rules(rules)
    rep.admin_links = link_administrative(rules)
    rep.ids = assign_ids(rules, existing_ids)
    rep.precedence = apply_precedence(rules)
    rep.cells = Counter((r.jurisdiction, r.category) for r in rules if r.disposition == "accepted")
    # report merges/links with final ids
    rep.admin_links = [(a, rep.ids.get(a, a), rep.ids.get(t) if t else None) for a, t in rep.admin_links]
    rep.resolved_citations = [(rep.ids.get(h, h), rep.ids.get(s, s)) for h, s in rep.resolved_citations]
    return rules, rep
