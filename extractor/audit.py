"""Append-only audit log: ``out/audit.jsonl``, one JSON object per line.

Never rewritten or truncated; each line carries a UTC timestamp and a run id.
Events: ``run_start``, ``doc_loaded`` (incl. clean removals/warnings),
``llm_call`` (model, prompt_version, cache hit, usage), ``rule_rejected``
(reason), ``rule_merged``, ``conflict_flagged``, ``export``, ``run_end``.
Secrets and full document text are never logged.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_LOCK = threading.Lock()  # extraction runs in a thread pool


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
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def append(event: AuditEvent, path: Path | None = None) -> None:
    """Append one JSON line (open with ``"a"``, flush + fsync)."""
    path = path or config.AUDIT_PATH
    record = asdict(event)
    record["ts"] = (event.ts or datetime.now(timezone.utc)).isoformat()
    line = json.dumps(record, ensure_ascii=False, default=str, sort_keys=True)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


def read_events(path: Path | None = None, run_id: str | None = None) -> list[AuditEvent]:
    """Read back events, optionally for one run (for the demo / smoke-check)."""
    path = path or config.AUDIT_PATH
    if not path.exists():
        return []
    events: list[AuditEvent] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if run_id and d.get("run_id") != run_id:
                continue
            d["ts"] = datetime.fromisoformat(d["ts"]) if d.get("ts") else None
            events.append(AuditEvent(**d))
    return events
