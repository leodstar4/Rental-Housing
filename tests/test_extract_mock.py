"""End-to-end extraction + validation with a mocked Anthropic client (offline, a-0.3.0 shape)."""

from __future__ import annotations

import types

from extractor import audit, llm
from extractor.corpus import load_documents
from extractor.extract import extract_all

D081_QUOTE = (
    "The law prohibits the sale or use of algorithmic devices to set rents or manage "
    "occupancy levels for residential units in San Francisco."
)

GOOD = {
    "jurisdiction": "San Francisco, CA", "level": "city", "category": "algorithmic_rent_setting",
    "title": "Algorithmic device ban", "requirement": "Landlords may not use algorithmic devices to set rents.",
    "key_value": None, "citation": "S.F. Admin. Code § 37.10C", "citation_aliases": ["Rent Ordinance § 37.10C"],
    "quoted_span": D081_QUOTE, "stage": "enacted", "enacted_date": None,
    "effective_dates": [{"value": "2024-10-14", "raw": "October 14, 2024", "derived": False,
                         "quoted_span": "went into effect on October 14, 2024"}],
    "sunset_date": None,
    "coverage": {"units_min": None, "units_max": None, "year_built_min": None, "year_built_max": None,
                 "certificate_of_occupancy_on_or_before": None, "building_age_min_years": None,
                 "property_types_covered": ["residential"],
                 "exemption_conditions": [{"condition": "owner-occupied", "field": "owner_occupied", "op": "==", "value": True}],
                 "notes": None},
    "coverage_text": "Residential units in SF", "exemptions": None, "interaction": None,
    "is_secondary_source": False, "confidence": 0.9,
}
SCHEMA_BAD = dict(GOOD, quoted_span="too short", confidence=1.7)
INVENTED = dict(GOOD, title="Invented", quoted_span="Landlords shall cap application fees at fifty dollars per applicant.")


def _fake_client(calls):
    def msg(content, stop):
        u = types.SimpleNamespace(input_tokens=100, output_tokens=50, cache_creation_input_tokens=3000,
                                  cache_read_input_tokens=0)
        return types.SimpleNamespace(content=content, stop_reason=stop, model="claude-opus-5-5", usage=u)

    class Stream:
        def __init__(self, kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            kw = self.kw
            calls.append(kw)
            assert kw["tool_choice"] == {"type": "auto"} and kw["tools"][0]["strict"] is True
            assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
            assert "fallbacks" not in kw and "betas" not in kw  # fallback disabled
            if len(calls) == 1:  # first attempt: text only, no tool call -> retried
                return msg([types.SimpleNamespace(type="text", text="hmm")], "end_turn")
            tu = types.SimpleNamespace(type="tool_use", name="record_rules",
                                       input={"rules": [GOOD, SCHEMA_BAD, INVENTED], "notes": None})
            return msg([tu], "tool_use")

    return types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: Stream(kw)))


def test_extract_validate_cache_audit(monkeypatch):
    calls, retries = [], []
    monkeypatch.setattr(llm, "get_client", lambda: _fake_client(calls))

    def fake_retry(document_text, **kw):
        retries.append(kw["rule_brief"]["title"])
        return None, llm.LLMUsage(input_tokens=10, output_tokens=5)

    monkeypatch.setattr(llm, "retry_quote", fake_retry)
    docs = load_documents(["D081"])

    [r] = extract_all(docs)
    assert r.result.attempts == 2 and r.result.usage.input_tokens == 200  # usage summed over attempts
    assert len(r.rejected) == 1  # schema-invalid candidate
    by_title = {x.title: x for x in r.rules}
    good, invented = by_title["Algorithmic device ban"], by_title["Invented"]
    assert good.disposition == "accepted" and good.quote_location.match_type == "exact"
    assert good.effective_dates[0].verified and good.source_doc_id == "D081"
    assert good.coverage.exemption_conditions[0].value is True
    assert good.confidence == 0.9
    assert (invented.disposition, invented.disposition_reason) == ("rejected", "citation_unverified")
    assert retries == ["Invented"]  # one quote retry, only for the failing rule
    assert dict(r.validation.reasons) == {"citation_unverified": 1, "schema_invalid": 1}
    assert r.retry_usage.input_tokens == 10

    n = len(calls)
    [r2] = extract_all(docs)
    assert len(calls) == n and r2.result.usage.cached  # extraction served from .cache/

    events = [e.event for e in audit.read_events()]
    for ev in ("run_start", "doc_loaded", "llm_call", "quote_retry", "rule_rejected", "validated", "run_end"):
        assert ev in events
