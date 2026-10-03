"""normalize.py, status.py, conflicts.py, export.py (offline, synthetic rules)."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import claim, make_doc, make_rule

from extractor.conflicts import detect_conflicts
from extractor.export import _key_value
from extractor.models import Coverage, LegalStage
from extractor.normalize import (
    apply_defaults, base_citation, kv_equal, normalize_citation, normalize_rules, preempts,
)
from extractor.status import compute_status

COV = dict(units_min=None, units_max=None, year_built_min=None, year_built_max=None,
           certificate_of_occupancy_on_or_before=None, building_age_min_years=None,
           property_types_covered=[], exemption_conditions=[], notes=None)
DOCS = {d: make_doc("Approved October 6, 2025. Some text.", doc_id=d) for d in ("D1", "D2", "D3", "D4")}
Q = "It shall be unlawful for a landlord to do the regulated thing described here."


def rule(uid, **kw):
    kw.setdefault("source_doc_id", uid.split("#")[0])
    return make_rule(Q, uid=uid, **kw)


# --- citations ----------------------------------------------------------------------


@pytest.mark.parametrize("raw, jur, expected", [
    ("California Civil Code Section 1950.6", "CA", "Cal. Civ. Code § 1950.6"),
    ("Cal. Civ. Code §1947.12", "CA", "Cal. Civ. Code § 1947.12"),
    ("Rent Ordinance", "San Francisco, CA", "S.F. Admin. Code ch. 37"),
    ("RSO", "Los Angeles, CA", "L.A. Mun. Code ch. XV"),
    ("Rent Ordinance", "Berkeley, CA", "Berkeley Mun. Code ch. 13.76"),
    ("Berkeley Mun. Code Ch. 13.106", "Berkeley, CA", "Berkeley Mun. Code ch. 13.106"),
    ("P.L. 2025, c.405", "NJ", "P.L.2025, c.405"),
    ("Rent Ordinance", "Los Angeles, CA", "Rent Ordinance"),  # alias is jurisdiction-scoped
])
def test_normalize_citation(raw, jur, expected):
    assert normalize_citation(raw, jur) == expected


def test_base_citation_strips_subsections():
    assert base_citation("Cal. Bus. & Prof. Code § 16729(a)") == "Cal. Bus. & Prof. Code § 16729"
    assert base_citation("N.J.S.A. 2A:18-61.1(f)") == "N.J.S.A. 2A:18-61.1"


def test_kv_equal_and_preempts():
    assert kv_equal("1 month's rent", "1 month’s rent")
    assert kv_equal("lesser of 3% or 80% of CPI", "Lower of 3% or 80% of CPI change; 0% if CPI negative")
    assert not kv_equal("0% (rent increases prohibited)", "0% additional for utilities")
    assert not kv_equal("$30 per applicant", "$68.96 (2026 maximum)")
    assert preempts("Municipalities are prohibited from enacting ordinances that conflict")
    assert not preempts("The section does not preempt rules on deposits")


# --- merge / admin / citation resolution / ids ---------------------------------------


def test_merge_same_law_keeps_all_quotes_but_not_different_values_or_coverage():
    rules = [
        rule("D1#0", citation="Cal. Civ. Code § 1950.5(b)", category="security_deposits", key_value="1 month's rent",
             coverage=Coverage(**COV)),
        rule("D2#0", citation="Cal. Civ. Code § 1950.5", category="security_deposits", key_value="1 month’s rent",
             coverage=Coverage(**COV), is_secondary_source=True),
        rule("D1#1", citation="Cal. Civ. Code § 1950.5", category="security_deposits", key_value="2 months' rent",
             coverage=Coverage(**{**COV, "units_max": 4})),
    ]
    out, rep = normalize_rules(rules, DOCS)
    acc = [r for r in out if r.disposition == "accepted"]
    assert len(acc) == 2
    merged = next(r for r in acc if "D2#0" in r.merged_uids)
    assert merged.citation == "Cal. Civ. Code § 1950.5" and len(merged.evidence) == 2
    assert {e.source_doc_id for e in merged.evidence} == {"D1", "D2"}
    assert sorted(r.team_rule_id for r in acc) == ["CA-DEP-01", "CA-DEP-02"]


def test_administrative_linked_or_unlinked():
    legal = rule("D1#0", jurisdiction="Los Angeles, CA", level="city", category="rent_increase_limits",
                 citation="Rent Stabilization Ordinance", title="RSO annual allowable rent increase")
    admin = rule("D2#0", jurisdiction="Los Angeles, CA", level="city", category="rent_increase_limits",
                 stage="administrative", citation="RSO", key_value="3%", title="RSO annual allowable increase 2025-26",
                 effective_dates=[claim("2025-07-01", "July 1, 2025", "July 1, 2025")],
                 sunset_date=claim("2026-06-30", "June 30, 2026", "June 30, 2026"))
    orphan = rule("D3#0", jurisdiction="San Francisco, CA", level="city", category="rent_increase_limits",
                  stage="administrative", citation=None, disposition="held", disposition_reason="no_citation",
                  key_value="1.6%")
    out, rep = normalize_rules([legal, admin, orphan], DOCS)
    by = {r.uid: r for r in out}
    assert by["D2#0"].disposition == "merged" and by["D2#0"].merged_into == "D1#0"
    assert by["D1#0"].key_value_details[0].key_value == "3%"
    assert (by["D3#0"].disposition, by["D3#0"].disposition_reason) == ("held", "administrative_unlinked")
    assert "current" in _key_value(by["D1#0"], date(2026, 1, 1))
    assert _key_value(by["D1#0"], date(2026, 10, 1)) is None  # figure expired, legal rule has no kv


def test_citation_resolved_from_same_law_alias():
    src = rule("D1#0", jurisdiction="Santa Ana, CA", level="city", category="just_cause_eviction",
               citation="Santa Ana Rent Stabilization and Just Cause Eviction Ordinance", confidence=0.9)
    held = rule("D2#0", jurisdiction="Santa Ana, CA", level="city", category="just_cause_eviction",
                citation=None, citation_aliases=["Just Cause Eviction Ordinance"], key_value="3 months relocation",
                disposition="held", disposition_reason="no_citation", confidence=0.8)
    lonely = rule("D3#0", jurisdiction="Santa Ana, CA", level="city", category="security_deposits",
                  citation=None, disposition="held", disposition_reason="no_citation", title="Something else")
    out, rep = normalize_rules([src, held, lonely], DOCS)
    by = {r.uid: r for r in out}
    h = by["D2#0"] if by["D2#0"].disposition == "accepted" else by[by["D2#0"].merged_into]
    assert h.citation == "Santa Ana Rent Stabilization and Just Cause Eviction Ordinance"
    assert by["D3#0"].disposition == "held"
    assert rep.resolved_citations and rep.resolved_citations[0][1] == by["D1#0"].team_rule_id


def test_ids_pending_failed_prefixes():
    rules = [rule("D1#0", jurisdiction="MA", stage="bill_pending", citation="MA S.2983"),
             rule("D2#0", jurisdiction="MA", stage="bill_failed", citation="MA H.3744"),
             rule("D3#0", jurisdiction="MA", stage="enacted", citation="M.G.L. c. 186, § 15B")]
    out, _ = normalize_rules(rules, DOCS)
    assert sorted(r.team_rule_id for r in out) == ["MA-ALGO-01", "MA-ALGO-F01", "MA-ALGO-P01"]


# --- defaults & status (T1 / T3) -----------------------------------------------------------


def test_ca_default_january_1_and_t1():
    ab325 = rule("D1#0", enacted_date=claim("2025-10-06", "October 06, 2025", "October 6, 2025").model_copy(
        update={"verified": True, "kind": "enacted"}))
    apply_defaults([ab325], DOCS)
    [d] = ab325.effective_dates
    assert (d.value, d.derived, d.kind_source, d.rule_applied) == (date(2026, 1, 1), True, "default", "CA-const-art-IV-8c")
    assert compute_status(ab325, date(2025, 12, 31)) == "not_yet_effective"
    assert compute_status(ab325, date(2026, 1, 2)) == "in_force"


def test_ca_default_skipped_for_urgency_and_other_states():
    urgent_doc = {"D1": make_doc("This act is an urgency statute and shall take effect immediately.", doc_id="D1")}
    enacted = claim("2025-10-06", "October 06, 2025", "x").model_copy(update={"verified": True})
    r = rule("D1#0", enacted_date=enacted)
    apply_defaults([r], urgent_doc)
    nj = rule("D2#0", jurisdiction="NJ", enacted_date=enacted)
    apply_defaults([nj], DOCS)
    assert r.effective_dates == [] and nj.effective_dates == []


def test_t3_fair_act_derived_date():
    fair = rule("D1#0", jurisdiction="NJ", effective_dates=[
        claim("2027-07-01", "first day of the twelfth month next following the date of enactment",
              "This act shall take effect on the first day of", derived=True).model_copy(update={"kind": "effective"})])
    assert compute_status(fair, date(2026, 10, 1)) == "not_yet_effective"
    assert compute_status(fair, date(2027, 7, 2)) == "in_force"


def test_status_bills_and_expiry():
    assert compute_status(rule("D1#0", stage="bill_pending"), date(2026, 10, 1)) == "pending"
    assert compute_status(rule("D1#0", stage="bill_failed"), date(2026, 10, 1)) == "failed"
    expired = rule("D1#0", sunset_date=claim("2024-01-31", "January 31, 2024", "x"))
    assert compute_status(expired, date(2026, 10, 1)) == "failed"


# --- conflicts ------------------------------------------------------------------------------


def test_conflicts_key_value_preemption_and_pending():
    a = rule("D1#0", category="application_screening_fees", citation="Cal. Civ. Code § 1950.6",
             title="Application screening fee cap", key_value="$30 per applicant, CPI-adjusted")
    b = rule("D2#0", category="application_screening_fees", citation="California Civil Code Section 1950.6",
             title="Screening fee cap", key_value="$68.96 (2026 maximum)", is_secondary_source=True)
    state = rule("D3#0", jurisdiction="NJ", category="algorithmic_rent_setting", citation="P.L.2026, c.43",
                 interaction="Municipalities are prohibited from enacting ordinances that conflict with this act.")
    local = rule("D4#0", jurisdiction="Jersey City, NJ", level="city", category="algorithmic_rent_setting",
                 citation="Jersey City Mun. Code ch. 260", title="Local algorithm ban")
    tbd = rule("D4#1", source_doc_id="D4", category="rent_increase_limits", citation="Cal. Civ. Code § 1947.12",
               key_value="2026 figure to be determined by HCD")
    out, _ = normalize_rules([a, b, state, local, tbd], DOCS)
    conflicts = detect_conflicts(out)
    kinds = sorted(c["type"] for c in conflicts)
    assert kinds == ["key_value", "preemption", "value_pending"]
    flagged = {r.uid for r in out if r.conflict_flag}
    assert {"D3#0", "D4#0", "D4#1"} <= flagged and ({"D1#0", "D2#0"} & flagged)


def test_no_cross_document_conflict_for_different_provisions():
    a = rule("D1#0", jurisdiction="Los Angeles, CA", level="city", category="rent_increase_limits",
             citation="RSO", title="RSO rent increase freeze (COVID-19)", key_value="0% (rent increases prohibited)",
             effective_dates=[claim("2020-03-30", "March 30, 2020", "x").model_copy(update={"kind": "effective"})])
    b = rule("D2#0", jurisdiction="Los Angeles, CA", level="city", category="rent_increase_limits",
             citation="RSO", title="RSO: no additional percentage increase for utilities",
             key_value="0% additional for utilities",
             effective_dates=[claim("2026-02-02", "February 2, 2026", "x").model_copy(update={"kind": "effective"})])
    out, _ = normalize_rules([a, b], DOCS)
    assert detect_conflicts(out) == []


# --- a-0.4.0 follow-ups -------------------------------------------------------------------


def test_lamc_subsection_and_citation_formats():
    assert base_citation("L.A. Mun. Code § 151.09.G") == "L.A. Mun. Code § 151.09"
    assert normalize_citation("LAMC § 165.03", "Los Angeles, CA") == "L.A. Mun. Code § 165.03"
    assert normalize_citation("S.D. Mun. Code § 98.0704", "San Diego, CA") == "San Diego Mun. Code § 98.0704"


def test_state_bill_is_state_jurisdiction():
    r = rule("D1#0", jurisdiction="Boston, MA", level="city", stage="bill_failed", citation="MA H.3744")
    out, _ = normalize_rules([r], DOCS)
    assert (out[0].jurisdiction, out[0].level) == ("MA", "state")
    assert out[0].team_rule_id.startswith("MA-")


def test_resolved_citation_is_law_level_not_source_section():
    src = rule("D1#0", jurisdiction="San Francisco, CA", level="city", category="algorithmic_rent_setting",
               citation="S.F. Admin. Code § 37.10C", citation_aliases=["Rent Ordinance § 37.10C"])
    held = rule("D2#0", jurisdiction="San Francisco, CA", level="city", category="rent_increase_limits",
                citation=None, citation_aliases=["Rent Ordinance"], disposition="held", disposition_reason="no_citation")
    out, _ = normalize_rules([src, held], DOCS)
    h = next(r for r in out if r.uid == "D2#0")
    assert h.disposition == "accepted" and h.citation == "S.F. Admin. Code ch. 37"


def test_admin_without_law_and_several_candidates_stays_unlinked():
    base = dict(jurisdiction="Los Angeles, CA", level="city", category="just_cause_eviction")
    t1 = rule("D1#0", citation="L.A. Mun. Code § 165.06", title="JCO single-family dwellings owned by natural persons", **base)
    t2 = rule("D1#1", citation="L.A. Mun. Code § 151.09", title="RSO no-fault eviction grounds", **base)
    rpo = rule("D2#0", stage="administrative", citation=None, citation_aliases=["Resident Protections Ordinance"],
               title="RPO standardized relocation payments (Chart B)", key_value="ELI $115,480", **base)
    vague = rule("D2#1", stage="administrative", citation=None, title="Relocation amounts 2026-27",
                 key_value="$10,000", **base)
    out, _ = normalize_rules([t1, t2, rpo, vague], DOCS)
    by = {r.uid: r for r in out}
    assert by["D2#0"].disposition_reason == "administrative_unlinked"  # names a law with no enacted rule
    assert by["D2#1"].disposition_reason == "administrative_unlinked"  # ambiguous: two candidates


def test_municipal_history_note_is_amendment():
    from extractor.dates import classify_kind
    assert classify_kind("effective 3-28-2024", "effective 3-28-2024",
                         "notice.\n(Amended 2-27-2024 by O-21769 N.S.; ", derived=False) == "amendment"
    assert classify_kind("effective 6-24-2023.)", "effective 6-24-2023",
                         "(“Exemptions” added 5-25-2023 by O-21647 N.S.; ", derived=False) == "effective"
