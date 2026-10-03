"""Document -> LLM (``record_rules``) -> ``RuleInternal[]``.

One call per document: ``clean_text`` plus manifest metadata. The model never
outputs ``status`` (computed in ``status.py``), ``team_rule_id`` or provenance
(``source_doc_id``/``source_url``/``retrieved_at``); those come from the
``Document``. Each rule in the tool input is validated on its own, so one
malformed rule is rejected (and audited) without discarding the others.

With ``validate=True`` (default) every candidate then goes through
``validate.validate_document`` (quote cascade incl. one LLM quote retry, dates,
dispositions, final confidence); each held/rejected rule is audited.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from . import audit, config, llm
from .corpus import Document
from .validate import ValidationReport, validate_document
from .models import DateClaim, DateClaimCandidate, LegalStage, RuleCandidate, RuleInternal


@dataclass
class DocExtraction:
    """Outcome for one document."""

    doc_id: str
    rules: list[RuleInternal] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)  # {"index", "errors", "raw"}
    result: llm.LLMResult | None = None
    error: str | None = None
    validation: ValidationReport | None = None
    retry_usage: llm.LLMUsage = field(default_factory=llm.LLMUsage)  # quote-retry calls
    classifier_usage: llm.LLMUsage = field(default_factory=llm.LLMUsage)  # date-kind calls (small model)


def build_user_content(doc: Document) -> str:
    """Render doc metadata (doc_id, jurisdictions, url, retrieved_at, source_type)
    and ``doc.clean_text`` into the user message."""
    meta = {
        "doc_id": doc.doc_id,
        "url": doc.url,
        "retrieved_at": doc.retrieved_at.strftime("%Y-%m-%d %H:%M UTC"),
        "jurisdictions": doc.jurisdictions,
        "source_type": doc.source_type,
    }
    return (
        "<document_metadata>\n"
        + json.dumps(meta, ensure_ascii=False, indent=1)
        + "\n</document_metadata>\n\n<document>\n"
        + doc.clean_text
        + "\n</document>"
    )


def _claim(c: DateClaimCandidate | None, doc_id: str) -> DateClaim | None:
    if c is None:
        return None
    return DateClaim(value=c.value, raw=c.raw, derived=c.derived, source_doc_id=doc_id, quoted_span=c.quoted_span)


def candidate_to_internal(
    c: RuleCandidate, doc: Document, result: llm.LLMResult, index: int = 0
) -> RuleInternal:
    """Map a validated candidate to the internal record, adding provenance."""
    return RuleInternal(
        uid=f"{doc.doc_id}#{index}",
        jurisdiction=c.jurisdiction,
        level=c.level,
        category=c.category,
        title=c.title,
        requirement=c.requirement,
        key_value=c.key_value,
        coverage=c.coverage,
        coverage_text=c.coverage_text,
        exemptions=c.exemptions,
        stage=LegalStage(c.stage),
        enacted_date=_claim(c.enacted_date, doc.doc_id),
        effective_dates=[d for d in (_claim(x, doc.doc_id) for x in c.effective_dates) if d],
        sunset_date=_claim(c.sunset_date, doc.doc_id),
        interaction=c.interaction,
        citation=c.citation,
        citation_aliases=c.citation_aliases,
        source_doc_id=doc.doc_id,
        source_url=doc.url,
        retrieved_at=doc.retrieved_at.isoformat(),
        is_secondary_source=c.is_secondary_source,
        quoted_span=c.quoted_span,
        model_confidence=c.confidence,
        confidence=c.confidence,
        model=result.served_model,
        prompt_version=result.prompt_version,
    )


def extract_document(
    doc: Document, *, use_cache: bool = True, run_id: str | None = None, validate: bool = True
) -> DocExtraction:
    """Extract rules from one document; never raises for LLM/validation failures."""
    run_id = run_id or audit.new_run_id()
    out = DocExtraction(doc.doc_id)
    cr = doc.clean_result
    audit.append(audit.AuditEvent(
        "doc_loaded", run_id, doc.doc_id,
        data={
            "text_sha256": doc.text_sha256,
            "raw_chars": len(doc.raw_text),
            "clean_chars": len(doc.clean_text),
            "clean_profile": cr.profile if cr else None,
            "removed_blocks": [(b.first_line, b.last_line, b.reason) for b in cr.removed] if cr else [],
            "clean_warnings": cr.warnings if cr else [],
        },
    ))
    try:
        result = llm.extract_structured(
            llm.system_prompt(), build_user_content(doc), text_sha256=doc.text_sha256, use_cache=use_cache
        )
    except llm.ExtractionLLMError as e:
        out.error = str(e)
        audit.append(audit.AuditEvent("llm_error", run_id, doc.doc_id, data={"error": out.error}))
        return out

    out.result = result
    for i, raw in enumerate(result.tool_input.get("rules", [])):
        try:
            cand = RuleCandidate.model_validate(raw)
            out.rules.append(candidate_to_internal(cand, doc, result, i))
        except ValidationError as e:
            errs = [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
            out.rejected.append({"index": i, "errors": errs, "raw": raw})
            audit.append(audit.AuditEvent("rule_rejected", run_id, doc.doc_id, data={"index": i, "errors": errs}))

    audit.append(audit.AuditEvent(
        "llm_call", run_id, doc.doc_id,
        data={
            "model": result.model,
            "served_model": result.served_model,
            "prompt_version": result.prompt_version,
            "effort": config.EXTRACT_EFFORT,
            "cache_key": result.cache_key,
            "cache_hit": result.usage.cached,
            "attempts": result.attempts,
            "usage": {k: v for k, v in vars(result.usage).items() if k != "cached"},
            "rules_returned": len(result.tool_input.get("rules", [])),
            "rules_valid": len(out.rules),
            "notes": result.tool_input.get("notes"),
        },
    ))
    if validate:
        _validate(out, doc, run_id, use_cache)
    return out


def _brief(rule: RuleInternal) -> dict[str, Any]:
    return {k: getattr(rule, k) for k in ("jurisdiction", "category", "title", "requirement", "citation")}


def _validate(out: DocExtraction, doc: Document, run_id: str, use_cache: bool) -> None:
    """Run validation on ``out.rules`` in place, with one LLM quote retry per failing rule."""

    def requote(rule: RuleInternal, d: Document) -> str | None:
        quote, usage = llm.retry_quote(
            d.clean_text, text_sha256=d.text_sha256, rule_brief=_brief(rule),
            failed_span=rule.quoted_span, use_cache=use_cache,
        )
        out.retry_usage = out.retry_usage + usage
        audit.append(audit.AuditEvent(
            "quote_retry", run_id, d.doc_id,
            data={"title": rule.title, "found": quote is not None, "cache_hit": usage.cached,
                  "usage": {k: v for k, v in vars(usage).items() if k != "cached"}},
        ))
        return quote

    def classify(claim, rule: RuleInternal, context: str) -> str | None:
        kind, usage = llm.classify_date_kind(
            quote=claim.quoted_span or "", raw=claim.raw, context=context, rule_title=rule.title,
            use_cache=use_cache,
        )
        out.classifier_usage = out.classifier_usage + usage
        audit.append(audit.AuditEvent(
            "date_kind_llm", run_id, doc.doc_id,
            data={"title": rule.title, "raw": claim.raw, "kind": kind, "model": config.DATE_CLASSIFIER_MODEL,
                  "cache_hit": usage.cached},
        ))
        return kind

    out.rules, out.validation = validate_document(out.rules, doc, requote, classify)
    if out.rejected:  # schema-invalid candidates (pydantic) count as rejected too
        out.validation.reasons["schema_invalid"] += len(out.rejected)
        out.validation.dispositions["rejected"] += len(out.rejected)
        out.validation.candidates += len(out.rejected)
    for r in out.rules:
        if r.disposition != "accepted":
            audit.append(audit.AuditEvent(
                "rule_held" if r.disposition == "held" else "rule_rejected", run_id, doc.doc_id,
                data={"reason": r.disposition_reason, "title": r.title, "category": r.category,
                      "errors": r.validation_errors},
            ))
    audit.append(audit.AuditEvent("validated", run_id, doc.doc_id, data=out.validation.to_dict()))


def extract_all(
    docs: list[Document],
    *,
    use_cache: bool = True,
    concurrency: int | None = None,
    run_id: str | None = None,
    validate: bool = True,
) -> list[DocExtraction]:
    """Extract every document with a thread pool; failures are audited, not fatal.

    The first document runs alone so its request writes the prompt cache
    (tools + system) before the parallel requests, which then read it.
    Results are returned in input order.
    """
    run_id = run_id or audit.new_run_id()
    concurrency = concurrency or config.EXTRACT_CONCURRENCY
    audit.append(audit.AuditEvent(
        "run_start", run_id,
        data={"doc_ids": [d.doc_id for d in docs], "model": config.EXTRACT_MODEL,
              "effort": config.EXTRACT_EFFORT, "prompt_version": config.PROMPT_VERSION,
              "concurrency": concurrency, "use_cache": use_cache},
    ))
    if not docs:
        return []
    results = [extract_document(docs[0], use_cache=use_cache, run_id=run_id, validate=validate)]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results += list(pool.map(lambda d: extract_document(d, use_cache=use_cache, run_id=run_id, validate=validate), docs[1:]))
    audit.append(audit.AuditEvent(
        "run_end", run_id,
        data={"rules": sum(len(r.rules) for r in results),
              "rejected": sum(len(r.rejected) for r in results),
              "failed_docs": [r.doc_id for r in results if r.error]},
    ))
    return results
