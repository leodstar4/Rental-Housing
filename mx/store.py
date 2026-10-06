"""JSON-file store for listings and contracts (demo; ephemeral on Render free).

One file per record (<dir>/<collection>/<id>.json), written atomically: temp file in the same
directory -> fsync -> os.replace. A process-wide lock serializes writes; one uvicorn worker only
(several workers would need a file lock or a database).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

CAPS = {"listings": 1000, "contracts": 500}
_ID = re.compile(r"^[0-9a-f]{32}$")


def _is_record(record: object) -> bool:
    """A usable stored record is a JSON object. Valid-JSON but non-object payloads (``[]``, ``null``,
    a bare string/number) are dropped so one bad file cannot 500 a route that iterates the store."""
    return isinstance(record, dict)


class StoreFull(Exception):
    pass


class JsonStore:
    def __init__(self, root: Path, caps: dict[str, int] | None = None):
        self.root = Path(root)
        self.caps = dict(CAPS if caps is None else caps)
        self.lock = threading.Lock()
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        self._cache: dict[str, dict[str, dict]] = {}

    def _dir(self, collection: str) -> Path:
        return self.root / collection

    def _load(self, collection: str) -> dict[str, dict]:
        if collection not in self._cache:
            items = {}
            d = self._dir(collection)
            for p in sorted(d.glob("*.json")) if d.exists() else []:
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except ValueError:
                    continue  # never serve a corrupt record
                if _is_record(rec):
                    items[p.stem] = rec  # drop valid-JSON but non-object records ([], null, string...)
            self._cache[collection] = items
        return self._cache[collection]

    def get(self, collection: str, rid: str, *, fresh: bool = False) -> dict | None:
        """``fresh`` re-reads the file (contracts: detect edits made on disk)."""
        if not _ID.match(rid):
            return None
        with self.lock:
            if fresh:
                p = self._dir(collection) / f"{rid}.json"
                if not p.exists():
                    return None
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except ValueError:
                    return None
                return rec if _is_record(rec) else None
            return self._load(collection).get(rid)

    def list(self, collection: str) -> list[dict]:
        with self.lock:
            return list(self._load(collection).values())

    def count(self, collection: str) -> int:
        with self.lock:
            return len(self._load(collection))

    def put(self, collection: str, rid: str, record: dict, *, new: bool = True) -> None:
        if not _ID.match(rid):
            raise ValueError("invalid id")
        with self.lock:
            items = self._load(collection)
            if new and rid not in items and len(items) >= self.caps.get(collection, 10**9):
                raise StoreFull(collection)
            d = self._dir(collection)
            d.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{rid}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, d / f"{rid}.json")
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            items[rid] = record
