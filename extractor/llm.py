"""Anthropic client wrapper: record_rules tool call, retries, on-disk cache.

Cache: ``.cache/<key>.json`` with ``key = sha256(text_sha256 | PROMPT_VERSION |
prompt fingerprint | model | effort)``. The fingerprint (hash of the system
prompt + tool schema) makes a forgotten ``PROMPT_VERSION`` bump harmless.
Re-running with unchanged inputs makes zero API calls. Entries hold the raw
tool input and usage, never the API key.

API notes (Claude Opus 5.5):
* Forced ``tool_choice`` (``any``/``tool``) is rejected with a 400 on this
  model, so we send ``auto`` + ``strict: true`` + a prompt instruction, and
  retry when the model does not call ``record_rules`` exactly once.
* Thinking is always on (adaptive); depth via ``output_config.effort``. No
  ``temperature``, no prefill.
* Streaming (``get_final_message``) because ``max_tokens`` is large.
* No refusal fallback (reproducibility): a refusal raises
  ``ExtractionLLMError``, is audited, and the document yields no rules.
  ``served_model`` still records ``msg.model``.
* Prompt caching: ``cache_control`` on the system block caches tools + system
  (tools render first). Shared by every document of a run.
* Transport errors (408/409/429/5xx, connection) are retried by the SDK with
  exponential backoff (``max_retries``); bad output is retried here.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from anthropic.lib._parse._transform import transform_schema
from pydantic import BaseModel

from . import config
from .models import EXEMPTION_WIRE_SCHEMA, RecordRulesInput

TOOL_NAME = "record_rules"
OUTPUT_ATTEMPTS = 3  # model answered but not with exactly one valid record_rules call

#: USD per million tokens: (input, output). Cache writes (5 min TTL) bill at
#: 1.25x input; cache reads at the listed rate.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cache_read": 0.50},
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10},
}


@dataclass(frozen=True)
class LLMUsage:
    """Token accounting for one extraction (summed over attempts)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cached: bool = False  # served from .cache/, no API call

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cached and other.cached,
        )


@dataclass(frozen=True)
class LLMResult:
    """Raw ``record_rules`` input plus provenance for the audit log.

    ``tool_input`` is validated per rule by ``extract.py`` (one bad rule must
    not discard the rest of the document).
    """

    tool_input: dict[str, Any]
    model: str  # requested
    served_model: str  # msg.model as reported by the API
    prompt_version: str
    cache_key: str
    usage: LLMUsage
    stop_reason: str | None
    attempts: int


class ExtractionLLMError(RuntimeError):
    """Refusal, truncation (max_tokens), API error, or no valid tool call after retries."""


# --------------------------------------------------------------------------- #
# Prompt + tool
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def system_prompt() -> str:
    """``prompts/extract_system.md`` without its version comment line."""
    text = config.EXTRACT_PROMPT_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("<!--"):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def _strip_defaults(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_defaults(v) for k, v in schema.items() if k != "default"}
    if isinstance(schema, list):
        return [_strip_defaults(v) for v in schema]
    return schema


@functools.lru_cache(maxsize=1)
def record_rules_tool() -> dict[str, Any]:
    """Tool definition; ``input_schema`` generated from ``RecordRulesInput``.

    ``transform_schema`` (the SDK's own strict-mode transform) sets
    ``additionalProperties: false`` and moves unsupported constraints
    (``minLength``, ``minimum``...) into descriptions; pydantic re-checks them.
    """
    schema = transform_schema(_strip_defaults(RecordRulesInput.model_json_schema()))
    # Swap the typed exemption union for its flat wire shape (grammar size limit;
    # see models.EXEMPTION_WIRE_SCHEMA). Pydantic still validates the typed union.
    defs = schema["$defs"]
    for name in ("ExemptionBool", "ExemptionInt", "ExemptionDate", "ExemptionText"):
        defs.pop(name)
    defs["ExemptionCondition"] = EXEMPTION_WIRE_SCHEMA
    defs["Coverage"]["properties"]["exemption_conditions"]["items"] = {"$ref": "#/$defs/ExemptionCondition"}
    return {
        "name": TOOL_NAME,
        "description": "Record every rule found in the document (empty list if none). Call exactly once.",
        "input_schema": schema,
        "strict": True,
    }


def prompt_fingerprint() -> str:
    """Short hash of system prompt + tool schema (part of the cache key)."""
    blob = system_prompt() + json.dumps(record_rules_tool(), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def cache_key(text_sha256: str, prompt_version: str, model: str, effort: str) -> str:
    """Deterministic cache key for one document extraction."""
    parts = [text_sha256, prompt_version, prompt_fingerprint(), model, effort]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def cache_get(key: str, cache_dir: Path | None = None) -> LLMResult | None:
    """Return the cached result for ``key`` (usage marked ``cached``), or ``None``."""
    path = (cache_dir or config.CACHE_DIR) / f"{key}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    d["usage"] = LLMUsage(**{**d["usage"], "cached": True})
    d.pop("created_at", None)
    return LLMResult(**d)


def cache_put(key: str, result: LLMResult, cache_dir: Path | None = None) -> None:
    """Atomically write ``result`` (write tmp + rename)."""
    cache_dir = cache_dir or config.CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    d = asdict(result)
    d["created_at"] = datetime.now(timezone.utc).isoformat()
    tmp = cache_dir / f"{key}.{os.getpid()}.{random.randrange(1 << 30)}.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, cache_dir / f"{key}.json")


# --------------------------------------------------------------------------- #
# Calls
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """Shared, thread-safe client from ``ANTHROPIC_API_KEY`` with SDK retries."""
    if config.OFFLINE:
        raise ExtractionLLMError("offline (snapshot mode): API calls are disabled")
    return anthropic.Anthropic(api_key=config.require_api_key(), max_retries=config.LLM_MAX_RETRIES)


# --------------------------------------------------------------------------- #
# Frozen snapshots (snapshot.py writes them)
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=4)
def _snapshot_index(snapshot_dir: str) -> dict[str, str]:
    """text_sha256 -> llm/<doc_id>.json for a snapshot."""
    manifest = json.loads((Path(snapshot_dir) / "MANIFEST.json").read_text(encoding="utf-8"))
    return {d["text_sha256"]: d["llm_file"] for d in manifest["documents"].values()}


def snapshot_get(text_sha256: str) -> LLMResult | None:
    """The frozen extraction for a document text, if the active snapshot has it."""
    snap = config.SNAPSHOT_DIR
    rel = _snapshot_index(str(snap)).get(text_sha256)
    if rel is None:
        return None
    d = json.loads((snap / rel).read_text(encoding="utf-8"))
    d["usage"] = LLMUsage(**{**d["usage"], "cached": True})
    d.pop("created_at", None)
    return LLMResult(**d)


def _aux_cache_path(name: str) -> Path:
    """Look for a quote-retry / date-kind cache entry in .cache, then in the snapshot."""
    path = config.CACHE_DIR / name
    if not path.exists() and config.SNAPSHOT_DIR is not None:
        snap = config.SNAPSHOT_DIR / "aux_cache" / name
        if snap.exists():
            return snap
    return path


def _usage_of(msg: Any) -> LLMUsage:
    u = msg.usage
    return LLMUsage(
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
    )


def estimate_cost(usage: LLMUsage, model: str) -> float | None:
    """USD estimate from list prices (``None`` if the model is not in ``PRICING``)."""
    p = PRICING.get(model)
    if p is None:
        return None
    return (
        usage.input_tokens * p["input"]
        + usage.cache_creation_input_tokens * p["input"] * 1.25
        + usage.cache_read_input_tokens * p["cache_read"]
        + usage.output_tokens * p["output"]
    ) / 1_000_000


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
        ExtractionLLMError: refusal, truncation, API error, or no valid
            ``record_rules`` call after ``OUTPUT_ATTEMPTS``.
    """
    model = model or config.EXTRACT_MODEL
    effort = effort or config.EXTRACT_EFFORT
    key = cache_key(text_sha256, config.PROMPT_VERSION, model, effort)
    if config.SNAPSHOT_DIR is not None and (snap := snapshot_get(text_sha256)) is not None:
        return snap
    if use_cache and (hit := cache_get(key)) is not None:
        return hit
    if config.OFFLINE:
        raise ExtractionLLMError("offline (snapshot mode): document not in the snapshot and not cached")

    client = get_client()
    usage = LLMUsage()
    problem = ""
    for attempt in range(1, OUTPUT_ATTEMPTS + 1):
        try:
            with client.messages.stream(
                model=model,
                max_tokens=config.EXTRACT_MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[record_rules_tool()],
                tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": user_content}],
                output_config={"effort": effort},
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.APIStatusError as e:  # SDK already retried 408/409/429/5xx
            raise ExtractionLLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ExtractionLLMError(f"connection error: {e}") from e

        usage = usage + _usage_of(msg)
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise ExtractionLLMError(f"refused: {getattr(details, 'category', None)}")
        if msg.stop_reason == "max_tokens":
            raise ExtractionLLMError(f"truncated at max_tokens={config.EXTRACT_MAX_TOKENS}")

        calls = [b for b in msg.content if b.type == "tool_use" and b.name == TOOL_NAME]
        if len(calls) == 1 and isinstance(calls[0].input, dict) and isinstance(calls[0].input.get("rules"), list):
            result = LLMResult(
                tool_input=calls[0].input,
                model=model,
                served_model=msg.model,
                prompt_version=config.PROMPT_VERSION,
                cache_key=key,
                usage=usage,
                stop_reason=msg.stop_reason,
                attempts=attempt,
            )
            cache_put(key, result)
            return result

        problem = f"{len(calls)} record_rules calls, stop_reason={msg.stop_reason}"
        time.sleep(2**attempt + random.random())  # 2s, 4s (+ jitter)

    raise ExtractionLLMError(f"no valid record_rules call after {OUTPUT_ATTEMPTS} attempts ({problem})")


# --------------------------------------------------------------------------- #
# Quote retry (validate.py step d)
# --------------------------------------------------------------------------- #


class QuoteReply(BaseModel):
    """Structured output of the quote-retry call."""

    quoted_span: str | None


@functools.lru_cache(maxsize=1)
def quote_prompt() -> tuple[str, str]:
    """``(version, text)`` of ``prompts/quote_retry.md``."""
    text = config.QUOTE_PROMPT_PATH.read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    m = re.search(r"PROMPT_VERSION:\s*([\w.\-]+)", first)
    return (m.group(1) if m else "unversioned"), rest.strip() + "\n"


def retry_quote(
    document_text: str,
    *,
    text_sha256: str,
    rule_brief: dict[str, Any],
    failed_span: str,
    use_cache: bool = True,
) -> tuple[str | None, LLMUsage]:
    """Ask the model for ONE literal supporting quote for an extracted rule.

    Returns ``(quote or None, usage)``. Never raises for model/API failures
    (they return ``None`` and the caller rejects the rule).
    """
    version, system = quote_prompt()
    model = config.EXTRACT_MODEL
    effort = config.QUOTE_RETRY_EFFORT
    blob = "|".join([text_sha256, version, system, model, effort,
                     json.dumps(rule_brief, sort_keys=True, ensure_ascii=False), failed_span])
    key = "quote-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
    path = config.CACHE_DIR / f"{key}.json"
    hit = _aux_cache_path(f"{key}.json")
    if use_cache and hit.exists():
        d = json.loads(hit.read_text(encoding="utf-8"))
        return d["quoted_span"], LLMUsage(cached=True)
    if config.OFFLINE:
        return None, LLMUsage()

    user = (
        "<document>\n" + document_text + "\n</document>\n\n<rule>\n"
        + json.dumps(rule_brief, ensure_ascii=False, indent=1)
        + "\n</rule>\n\n<failed_quote>\n" + failed_span + "\n</failed_quote>"
    )
    try:
        msg = get_client().messages.parse(
            model=model,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=QuoteReply,
            output_config={"effort": effort},
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        return None, LLMUsage()
    usage = _usage_of(msg)
    if msg.stop_reason in ("refusal", "max_tokens") or msg.parsed_output is None:
        return None, usage
    quote = msg.parsed_output.quoted_span
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"quoted_span": quote, "usage": asdict(usage)}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return quote, usage


# --------------------------------------------------------------------------- #
# Date-kind classification (validate.py, ambiguous dates only)
# --------------------------------------------------------------------------- #

DATE_KIND_SYSTEM = """You classify ONE date mentioned in a US housing-law document.
Answer with exactly one kind:
- effective: the date the rule (or this version of it) generally enters into force or starts to apply.
- operative: a calculation or reference date inside the rule (e.g. a base-rent date, a look-back date,
  "rent increases occurring on or after March 15, 2019"), not when the rule starts to apply.
- amendment: the effective date of an amendment to a previously existing rule.
- enacted: the date it was signed, approved, adopted or passed.
Use only the text given."""


class DateKindReply(BaseModel):
    """Structured output of the date classifier."""

    kind: str  # validated against DateKind by the caller


def classify_date_kind(*, quote: str, raw: str | None, context: str, rule_title: str,
                       use_cache: bool = True) -> tuple[str | None, LLMUsage]:
    """Ask a small model for the kind of one ambiguous date. ``(kind or None, usage)``."""
    model = config.DATE_CLASSIFIER_MODEL
    blob = "|".join([DATE_KIND_SYSTEM, model, quote, raw or "", context, rule_title])
    key = "datekind-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
    path = config.CACHE_DIR / f"{key}.json"
    hit = _aux_cache_path(f"{key}.json")
    if use_cache and hit.exists():
        return json.loads(hit.read_text(encoding="utf-8"))["kind"], LLMUsage(cached=True)
    if config.OFFLINE:
        return None, LLMUsage()
    user = (f"<rule_title>{rule_title}</rule_title>\n<context>\n{context}\n</context>\n"
            f"<date_quote>{quote}</date_quote>\n<date_as_written>{raw or ''}</date_as_written>\n"
            "Kind (effective | operative | amendment | enacted)?")
    try:
        msg = get_client().messages.parse(
            model=model, max_tokens=1000, system=DATE_KIND_SYSTEM,
            messages=[{"role": "user", "content": user}], output_format=DateKindReply,
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        return None, LLMUsage()
    usage = _usage_of(msg)
    kind = msg.parsed_output.kind.strip().lower() if msg.parsed_output else None
    if kind not in ("effective", "operative", "amendment", "enacted"):
        return None, usage
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"kind": kind, "model": model, "usage": asdict(usage)}), encoding="utf-8")
    os.replace(tmp, path)
    return kind, usage
