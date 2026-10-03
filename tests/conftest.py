"""Shared fixtures. All tests are offline: the Anthropic client is never built."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import pytest

from extractor import config, llm
from extractor.clean import clean
from extractor.corpus import Document
from extractor.models import DateClaim, LegalStage, RuleInternal


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Cache/audit/output go to tmp; any real API client use fails loudly."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")

    def _no_network():
        raise AssertionError("tests must not build a real Anthropic client")

    monkeypatch.setattr(llm, "get_client", _no_network)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def make_doc(raw: str, doc_id: str = "DTEST", url: str = "https://example.gov/x") -> Document:
    cr = clean(raw, url)
    return Document(
        doc_id=doc_id, jurisdictions=["CA"], url=url,
        retrieved_at=datetime(2026, 10, 1, 22, 35, tzinfo=timezone.utc), sha256="0" * 64,
        raw_text=raw, clean_text=cr.clean_text, source_type="official",
        text_sha256=hashlib.sha256(raw.encode()).hexdigest(), clean_result=cr,
    )


def make_rule(quote: str, **kw) -> RuleInternal:
    base = dict(
        jurisdiction="CA", level="state", category="algorithmic_rent_setting", title="t",
        requirement="r", citation="Cal. Bus. & Prof. Code § 16729", source_doc_id="DTEST",
        source_url="https://example.gov/x", retrieved_at="2026-10-01T22:35:00+00:00",
        quoted_span=quote, stage=LegalStage.ENACTED, model_confidence=0.9, confidence=0.9,
    )
    base.update(kw)
    return RuleInternal(**base)


def claim(value: str | None, raw: str, quote: str, derived: bool = False) -> DateClaim:
    return DateClaim(value=date.fromisoformat(value) if value else None, raw=raw,
                     quoted_span=quote, derived=derived, source_doc_id="DTEST")
