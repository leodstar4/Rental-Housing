"""Paths and runtime settings. Everything overridable via environment / ``.env``.

The API key is read **only** from ``ANTHROPIC_API_KEY``; it is never written to
config objects, cache entries, or the audit log.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent

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

#: Bump whenever the extraction prompt or the output schema sent to the model
#: changes; it is part of the cache key, so a bump invalidates cached extractions.
PROMPT_VERSION: str = "a-0.1.0"


@dataclass(frozen=True)
class Settings:
    """Snapshot of settings recorded in each audit event (no secrets)."""

    model: str = EXTRACT_MODEL
    effort: str = EXTRACT_EFFORT
    prompt_version: str = PROMPT_VERSION
    as_of: date = DEFAULT_AS_OF


def load_dotenv_if_present() -> None:
    """Load ``ROOT/.env`` into ``os.environ`` (does not override existing vars).

    Call before importing modules that read settings at import time (cli does).
    """
    raise NotImplementedError


def require_api_key() -> str:
    """Return ``ANTHROPIC_API_KEY`` or raise ``RuntimeError`` with setup help.

    Only ``llm.py`` should call this; the key must never be logged or cached.
    """
    raise NotImplementedError
