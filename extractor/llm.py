"""Anthropic client wrapper: structured output, retries, on-disk cache.

Cache: ``.cache/<key>.json`` where ``key = sha256(text_sha256 | PROMPT_VERSION |
model | effort)``. Entries store the parsed response plus usage, never the key.
Re-running the pipeline with unchanged inputs makes zero API calls.

Implementation notes (current API, see claude-api skill):
* ``client.messages.parse(..., output_format=ExtractionResponse)`` for
  schema-validated output; check ``stop_reason`` (``max_tokens``/``refusal``)
  before trusting ``parsed_output``.
* Opus 5.5: thinking is always on; control depth with
  ``output_config={"effort": ...}``. No ``temperature``, no prefill, no forced
  ``tool_choice``.
* Stream (``.stream(...).get_final_message()``) when ``max_tokens`` is large.
* SDK retries 408/409/429/5xx itself (``max_retries``); we only add a retry
  for schema-invalid output.
* Server-side refusal fallback (``fallbacks="default"`` + beta
  ``server-side-fallback-2026-07-01``) is enabled by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ExtractionResponse


@dataclass(frozen=True)
class LLMUsage:
    """Token accounting for one call (from ``response.usage``)."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cached: bool = False  # served from .cache/, no API call


@dataclass(frozen=True)
class LLMResult:
    """Parsed extraction plus provenance for the audit log."""

    response: ExtractionResponse
    model: str
    prompt_version: str
    cache_key: str
    usage: LLMUsage
    stop_reason: str | None


class ExtractionLLMError(RuntimeError):
    """Refusal, truncation (max_tokens), or output that never validated."""


def cache_key(text_sha256: str, prompt_version: str, model: str, effort: str) -> str:
    """Deterministic cache key for one document extraction."""
    raise NotImplementedError


def cache_get(key: str, cache_dir: Path | None = None) -> LLMResult | None:
    """Return the cached result for ``key``, or ``None``."""
    raise NotImplementedError


def cache_put(key: str, result: LLMResult, cache_dir: Path | None = None) -> None:
    """Atomically write ``result`` (write tmp + rename)."""
    raise NotImplementedError


def get_client():  # -> anthropic.Anthropic
    """Build a client from ``ANTHROPIC_API_KEY`` with ``max_retries=LLM_MAX_RETRIES``."""
    raise NotImplementedError


def extract_structured(
    system: str,
    user_content: str,
    *,
    text_sha256: str,
    model: str | None = None,
    effort: str | None = None,
    use_cache: bool = True,
) -> LLMResult:
    """Run one extraction call (or serve it from cache).

    Args:
        system: Stable system prompt (versioned by ``PROMPT_VERSION``).
        user_content: Document metadata + ``clean_text``.
        text_sha256: ``Document.text_sha256`` (cache key component).

    Raises:
        ExtractionLLMError: refusal, truncation, or invalid output after retry.
    """
    raise NotImplementedError
