"""Document -> LLM -> ``RuleInternal[]``.

The prompt asks for rules in the six schema categories only, with
``quoted_span`` copied verbatim from the supplied text, dates as written
(``DateClaim.raw``) plus ISO, and the legislative ``stage``. The model never
outputs ``status`` (computed in ``status.py``) or ``team_rule_id``.
"""

from __future__ import annotations

from .corpus import Document
from .llm import LLMResult
from .models import RuleInternal

SYSTEM_PROMPT: str = ""  # TODO: write; bump config.PROMPT_VERSION on every change.


def build_user_content(doc: Document) -> str:
    """Render doc metadata (doc_id, jurisdictions, url, retrieved_at, source_type)
    and ``doc.clean_text`` into the user message."""
    raise NotImplementedError


def extract_document(doc: Document, *, use_cache: bool = True) -> tuple[list[RuleInternal], LLMResult]:
    """Extract rules from one document.

    Fills provenance the model must not invent (``source_doc_id``,
    ``source_url``, ``retrieved_at``, ``model``, ``prompt_version``) from
    ``doc``/the call, overriding anything the model returned for them.
    """
    raise NotImplementedError


def extract_all(docs: list[Document], *, use_cache: bool = True) -> list[RuleInternal]:
    """Extract every document; failures are audited and skipped, not fatal."""
    raise NotImplementedError
