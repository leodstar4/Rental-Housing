"""Paths and runtime settings. Everything overridable via environment / ``.env``.

The API key is read **only** from ``ANTHROPIC_API_KEY``; it is never written to
config objects, cache entries, or the audit log.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent


def load_dotenv_if_present() -> None:
    """Load ``ROOT/.env`` into ``os.environ`` (does not override existing vars).

    Runs at import, before the settings below are read from the environment.
    """
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)


load_dotenv_if_present()

#: Unzipped starter pack (folder name contains a space; override with STARTER_DIR).
STARTER_DIR: Path = Path(os.getenv("STARTER_DIR", ROOT / "participant-final-no-hour16 3"))
CORPUS_DIR: Path = STARTER_DIR / "corpus"
MANIFEST_PATH: Path = CORPUS_DIR / "corpus_manifest.csv"
LINKS_ONLY_PATH: Path = CORPUS_DIR / "links_only.csv"
TEXT_DIR: Path = CORPUS_DIR / "text"
SCHEMA_PATH: Path = STARTER_DIR / "schema" / "rule_record.schema.json"

OUT_DIR: Path = Path(os.getenv("OUT_DIR", ROOT / "out"))
RULES_PATH: Path = OUT_DIR / "rules.json"
AUDIT_PATH: Path = OUT_DIR / "audit.jsonl"
CACHE_DIR: Path = Path(os.getenv("CACHE_DIR", ROOT / ".cache"))

#: Default query date (participant guide §1).
DEFAULT_AS_OF: date = date.fromisoformat(os.getenv("AS_OF", "2026-10-01"))

#: Model used for extraction.
EXTRACT_MODEL: str = os.getenv("EXTRACT_MODEL", "claude-opus-5-5")
#: Effort for extraction calls (Opus 5.5 defaults to "medium"; set explicitly).
EXTRACT_EFFORT: str = os.getenv("EXTRACT_EFFORT", "high")
EXTRACT_MAX_TOKENS: int = int(os.getenv("EXTRACT_MAX_TOKENS", "32000"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "4"))

PROMPTS_DIR: Path = ROOT / "prompts"
EXTRACT_PROMPT_PATH: Path = PROMPTS_DIR / "extract_system.md"
QUOTE_PROMPT_PATH: Path = PROMPTS_DIR / "quote_retry.md"
#: Effort for the single quote-retry call in validation (a lookup, not reasoning).
QUOTE_RETRY_EFFORT: str = os.getenv("QUOTE_RETRY_EFFORT", "medium")
#: Small model for classifying ambiguous date kinds (validate.py).
DATE_CLASSIFIER_MODEL: str = os.getenv("DATE_CLASSIFIER_MODEL", "claude-haiku-4-5")
DATA_DIR: Path = ROOT / "data"
CITATION_ALIASES_PATH: Path = DATA_DIR / "citation_aliases.yaml"
JURISDICTION_DEFAULTS_PATH: Path = DATA_DIR / "jurisdiction_defaults.yaml"
NORMALIZED_PATH: Path = OUT_DIR / "rules_normalized.json"
CONFLICTS_PATH: Path = OUT_DIR / "conflicts.json"
REJECTED_PATH: Path = OUT_DIR / "rejected.json"
VALIDATION_REPORT_PATH: Path = OUT_DIR / "validation_report.json"
EXTRACT_CONCURRENCY: int = int(os.getenv("EXTRACT_CONCURRENCY", "4"))

SNAPSHOTS_DIR: Path = ROOT / "snapshots"
#: Frozen extraction used for reproduction / incremental runs (set by the CLI).
SNAPSHOT_DIR: Path | None = None
#: True = never call the API (reproduce from snapshot); a cache/snapshot miss is an error.
OFFLINE: bool = False
NEW_DOCS_DIR: Path = ROOT / "corpus" / "new"


def _read_prompt_version(path: Path) -> str:
    """``PROMPT_VERSION: x`` from the prompt file's first line (an HTML comment)."""
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (FileNotFoundError, IndexError):
        return "missing"
    m = re.search(r"PROMPT_VERSION:\s*([\w.\-]+)", first)
    return m.group(1) if m else "unversioned"


#: Declared in prompts/extract_system.md. Bump it whenever the prompt or the
#: record_rules schema changes; it is part of the cache key.
PROMPT_VERSION: str = _read_prompt_version(EXTRACT_PROMPT_PATH)


@dataclass(frozen=True)
class Settings:
    """Snapshot of settings recorded in each audit event (no secrets)."""

    model: str = EXTRACT_MODEL
    effort: str = EXTRACT_EFFORT
    prompt_version: str = PROMPT_VERSION
    as_of: date = DEFAULT_AS_OF


def require_api_key() -> str:
    """Return ``ANTHROPIC_API_KEY`` or raise ``RuntimeError`` with setup help.

    Only ``llm.py`` should call this; the key must never be logged or cached.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in, "
            "or export it in your shell."
        )
    return key
