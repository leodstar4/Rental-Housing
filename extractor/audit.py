"""Append-only audit log: ``out/audit.jsonl``, one JSON object per line.

Never rewritten or truncated; each line carries a UTC timestamp and a run id.
Events: ``run_start``, ``doc_loaded`` (incl. clean removals/warnings),
``llm_call`` (model, prompt_version, cache hit, usage), ``rule_rejected``
(reason), ``rule_merged``, ``conflict_flagged``, ``export``, ``run_end``.
Secrets and full document text are never logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    """One log line."""

    event: str
    run_id: str
    doc_id: str | None = None
    rule_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ts: datetime | None = None  # filled by ``append`` when None


def new_run_id() -> str:
    """Sortable unique id for this pipeline run (UTC timestamp + random suffix)."""
    raise NotImplementedError


def append(event: AuditEvent, path: Path | None = None) -> None:
    """Append one JSON line (open with ``"a"``, flush + fsync)."""
    raise NotImplementedError


def read_events(path: Path | None = None, run_id: str | None = None) -> list[AuditEvent]:
    """Read back events, optionally for one run (for the demo / smoke-check)."""
    raise NotImplementedError
