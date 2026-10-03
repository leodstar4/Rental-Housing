"""validate.py: quote cascade, dates, dispositions, confidence (offline)."""

from __future__ import annotations

import pytest
from conftest import claim, make_doc, make_rule

from extractor.validate import match_span, validate_document, validate_rule

RAW = (
    "Bill Text\n"
    "16729.\n"
    "(a) It shall be unlawful for a person to use or distribute a common pricing algorithm as part of a\n"
    "contract, combination in the form of a trust, or conspiracy to restrain trade or commerce.\n"
    "(3) “Common pricing algorithm” means any\n"
    "methodology, including a computer, software, or other technology, used by two or more persons.\n"
    "Housing providers are also prohibited from having “blanket bans” of all people with a criminal history.\n"
    "Approved by Governor October 06, 2025.\n"
    "This act shall take effect on the first day of\n"
    "the twelfth month next following the date of enactment.\n"
    "The ordinance takes effect March 1, 2026. Another notice says it takes effect January 15, 2026.\n"
    "(Amended by Stats. 2025, Ch. 203, Sec. 1. (AB 1529) Effective January 1, 2026.)\n"
    "This section shall apply to all rent increases occurring on or after March 15, 2019.\n"
    "For tenancies that begin on or after July 1, 2025, the landlord shall take photographs.\n"
)
DOC = make_doc(RAW)
OPERATIVE = "(a) It shall be unlawful for a person to use or distribute a common pricing algorithm"


# --- the four requested cases -------------------------------------------------


def test_curly_quotes_normalized_and_replaced_by_literal():
    span = 'Housing providers are also prohibited from having "blanket bans" of all people'
    r = validate_rule(make_rule(span), DOC)
    assert r.disposition == "accepted"
    assert r.quote_location.match_type == "normalized"
    assert "“blanket bans”" in r.quoted_span and r.quoted_span in RAW


def test_quote_crossing_line_break():
    span = "“Common pricing algorithm” means any methodology, including a computer, software"
    r = validate_rule(make_rule(span), DOC)
    assert r.quote_location.match_type == "normalized"
    assert "any\nmethodology" in r.quoted_span and r.quoted_span in RAW


def test_paraphrased_quote_recovered_by_retry():
    paraphrase = "Using a shared pricing algorithm in a conspiracy to restrain trade is unlawful."
    calls = []

    def requote(rule, doc):
        calls.append(rule.quoted_span)
        return OPERATIVE

    r = validate_rule(make_rule(paraphrase, model_confidence=1.0), DOC, requote)
    assert calls == [paraphrase]  # exactly one retry
    assert r.disposition == "accepted"
    assert r.quote_location.match_type == "retry"
    assert r.quoted_span == OPERATIVE
    assert r.confidence == pytest.approx(0.8 * 0.9)  # retry x enacted-without-date


def test_paraphrased_quote_rejected_when_retry_fails():
    r = validate_rule(make_rule("Shared pricing algorithms are banned in a conspiracy."), DOC, lambda rule, doc: None)
    assert (r.disposition, r.disposition_reason) == ("rejected", "citation_unverified")


def test_invented_quote_rejected_even_if_retry_also_invents():
    invented = "Landlords must cap application fees at fifty dollars per applicant."
    r = validate_rule(make_rule(invented), DOC, lambda rule, doc: "Application fees shall not exceed $50.")
    assert (r.disposition, r.disposition_reason) == ("rejected", "citation_unverified")
    assert any("retry: failed" in e for e in r.validation_errors)


# --- cascade details ------------------------------------------------------------


def test_exact_match():
    r = validate_rule(make_rule(OPERATIVE), DOC)
    assert r.quote_location.match_type == "exact"
    assert RAW[r.quote_location.raw_start : r.quote_location.raw_end] == OPERATIVE


def test_fuzzy_match_replaced_by_literal_fragment():
    typo = "(a) It shall be unlawfull for a person to use or distribute a common pricing algorithm as part of a"
    m = match_span(RAW, typo)
    assert m is not None and m.match_type == "fuzzy" and m.score >= 95
    assert m.text in RAW and "unlawful for" in m.text


def test_short_unrelated_span_never_fuzzy():
    assert match_span(RAW, "algorithm ban") is None


# --- dates -----------------------------------------------------------------------


def test_unverified_date_dropped_rule_kept():
    rule = make_rule(OPERATIVE, effective_dates=[claim("2026-01-01", "January 1, 2026", "takes effect January 1, 2026")])
    r = validate_rule(rule, DOC)
    assert r.disposition == "accepted" and r.effective_dates == []
    assert any("dropped" in e for e in r.validation_errors)


def test_date_text_must_be_inside_its_quote():
    rule = make_rule(OPERATIVE, effective_dates=[claim("2026-04-01", "April 1, 2026", "The ordinance takes effect March 1, 2026.")])
    assert validate_rule(rule, DOC).effective_dates == []


def test_derived_date_needs_verified_base_date():
    formula = claim("2026-10-01", "first day of the twelfth month next following the date of enactment",
                    "This act shall take effect on the first day of the twelfth month next following", derived=True)
    enacted = claim("2025-10-06", "October 06, 2025", "Approved by Governor October 06, 2025.")
    ok = validate_rule(make_rule(OPERATIVE, enacted_date=enacted, effective_dates=[formula]), DOC)
    assert [d.verified for d in ok.effective_dates] == [True] and ok.enacted_date.verified
    no_base = validate_rule(make_rule(OPERATIVE, effective_dates=[formula]), DOC)
    assert no_base.effective_dates == []
    bad_base = validate_rule(
        make_rule(OPERATIVE, enacted_date=claim("2025-10-06", "October 06, 2025", "Signed October 06, 2025"),
                  effective_dates=[formula]), DOC)
    assert bad_base.enacted_date is None and bad_base.effective_dates == []


def test_conflicting_effective_dates_flag_and_factor():
    d1 = claim("2026-03-01", "March 1, 2026", "The ordinance takes effect March 1, 2026.")
    d2 = claim("2026-01-15", "January 15, 2026", "Another notice says it takes effect January 15, 2026.")
    r = validate_rule(make_rule(OPERATIVE, model_confidence=1.0, effective_dates=[d1, d2]), DOC)
    assert r.conflict_flag and "conflicting effective dates" in r.conflict_note
    assert r.confidence == pytest.approx(0.85)


# --- dispositions & confidence ----------------------------------------------------


def test_no_citation_is_held_not_rejected():
    r = validate_rule(make_rule(OPERATIVE, citation=None), DOC)
    assert (r.disposition, r.disposition_reason) == ("held", "no_citation")


def test_administrative_not_rejected_in_validation():
    # Linking (or administrative_unlinked) happens across documents in normalize.py.
    r = validate_rule(make_rule(OPERATIVE, stage="administrative"), DOC)
    assert (r.disposition, r.disposition_reason) == ("accepted", None)
    r = validate_rule(make_rule(OPERATIVE, stage="administrative", citation=None), DOC)
    assert (r.disposition, r.disposition_reason) == ("held", "no_citation")


# --- date value formats & kinds (prompt 4 decisions) ---------------------------------


def test_date_value_found_in_any_common_format():
    # The model's raw was a longer phrase ("Approved by Governor October 06, 2025.") but the
    # quote holds the date: verification now checks the VALUE, not the raw string.
    enacted = claim("2025-10-06", "Approved by Governor October 06, 2025.", "October 06, 2025.")
    r = validate_rule(make_rule(OPERATIVE, enacted_date=enacted), DOC)
    assert r.enacted_date is not None and r.enacted_date.verified and r.enacted_date.kind == "enacted"


def test_date_value_absent_from_quote_dropped():
    wrong = claim("2026-02-01", "February 1, 2026", "The ordinance takes effect March 1, 2026.")
    assert validate_rule(make_rule(OPERATIVE, effective_dates=[wrong]), DOC).effective_dates == []


def test_date_kinds_by_rule_and_conflict_only_between_effective():
    eff = claim("2026-03-01", "March 1, 2026", "The ordinance takes effect March 1, 2026.")
    amend = claim("2026-01-01", "Effective January 1, 2026", "Effective January 1, 2026.")
    oper = claim("2019-03-15", "on or after March 15, 2019",
                 "This section shall apply to all rent increases occurring on or after March 15, 2019.")
    r = validate_rule(make_rule(OPERATIVE, effective_dates=[eff, amend, oper]), DOC)
    assert [d.kind for d in r.effective_dates] == ["effective", "amendment", "operative"]
    assert not r.conflict_flag  # three distinct dates, but only one is of kind effective


def test_ambiguous_date_goes_to_classifier_once():
    amb = claim("2025-07-01", "July 1, 2025", "For tenancies that begin on or after July 1, 2025")
    seen = []

    def classify(c, rule, context):
        seen.append(c.raw)
        assert "photographs" in context
        return "operative"

    r = validate_rule(make_rule(OPERATIVE, effective_dates=[amb]), DOC, classify=classify)
    assert seen == ["July 1, 2025"]
    assert (r.effective_dates[0].kind, r.effective_dates[0].kind_source) == ("operative", "llm")


def test_unknown_stage_capped_and_flagged():
    r = validate_rule(make_rule(OPERATIVE, stage="unknown", model_confidence=1.0), DOC)
    assert r.confidence <= 0.5 and r.conflict_flag and "stage unclear" in r.conflict_note


def test_secondary_source_factor():
    d = claim("2026-03-01", "March 1, 2026", "The ordinance takes effect March 1, 2026.")
    r = validate_rule(make_rule(OPERATIVE, is_secondary_source=True, model_confidence=1.0, effective_dates=[d]), DOC)
    assert r.confidence == pytest.approx(0.8)


def test_document_report_counts():
    rules = [make_rule(OPERATIVE), make_rule('prohibited from having "blanket bans" of all people'),
             make_rule("totally invented text that is not there at all"), make_rule(OPERATIVE, citation=None)]
    _, rep = validate_document(rules, DOC, requote=lambda r, d: None)
    assert rep.candidates == 4 and rep.retries == 1
    assert dict(rep.match_types) == {"exact": 2, "normalized": 1}
    assert dict(rep.dispositions) == {"accepted": 2, "rejected": 1, "held": 1}
    assert dict(rep.reasons) == {"citation_unverified": 1, "no_citation": 1}


def test_real_corpus_d022_quote_across_line_break():
    from extractor.corpus import load_documents

    d = load_documents(["D022"])[0]
    r = validate_rule(make_rule("“Common pricing algorithm” means any methodology, including a computer, software, or other technology"), d)
    assert r.quote_location.match_type == "normalized" and r.quoted_span in d.raw_text
