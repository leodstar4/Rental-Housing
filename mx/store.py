"""Stores for listings and contracts (demo).

Two backends with the SAME public interface (``get``/``list``/``count``/``put``, ``caps``,
``started_at``, ``kind``, ``ephemeral``, invalid-id handling, corrupt-record filtering,
thread-safety):

* ``JsonStore`` — one file per record (``<dir>/<collection>/<id>.json``), written atomically
  (temp file in the same directory -> fsync -> os.replace). Default; ephemeral on Render free.
* ``SqlStore`` — one row per record in a single ``mx_store(collection, id, record, created_at)``
  table, on SQLite (stdlib ``sqlite3``) or PostgreSQL (``psycopg``, imported lazily). Persistent
  when the database is (e.g. Render managed Postgres).

``make_store()`` picks the backend from ``DATABASE_URL`` (see ``render.yaml``):
``postgres://`` / ``postgresql://`` -> Postgres, ``sqlite:///path`` -> SQLite, unset -> JSON.
A process-wide lock serializes writes; one uvicorn worker only (several workers need the SQL
backend or a file lock).
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
    a bare string/number) are dropped so one bad file/row cannot 500 a route that iterates the store."""
    return isinstance(record, dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class StoreFull(Exception):
    pass


class JsonStore:
    kind = "efimero"
    ephemeral = True

    def __init__(self, root: Path, caps: dict[str, int] | None = None):
        self.root = Path(root)
        self.caps = dict(CAPS if caps is None else caps)
        self.lock = threading.Lock()
        self.started_at = _now_iso()
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


class SqlStore:
    """Same interface as ``JsonStore`` over one SQL table ``mx_store(collection, id, record,
    created_at)``. ``record`` is the record serialized as JSON text (parsed back on read; a row
    whose JSON is corrupt or not an object is skipped, like a bad JSON file). ``fresh`` always
    reads the row, since there is no in-process cache.

    Backend from ``database_url``: ``sqlite:///path`` (stdlib ``sqlite3``) or ``postgres://`` /
    ``postgresql://`` (``psycopg``, imported lazily). ``caps`` and ``StoreFull`` behave as in the
    JSON store (counted per collection under the write lock)."""

    def __init__(self, database_url: str, caps: dict[str, int] | None = None):
        self.database_url = database_url
        self.caps = dict(CAPS if caps is None else caps)
        self.lock = threading.Lock()
        self.started_at = _now_iso()
        if database_url.startswith("sqlite:///"):
            self.kind, self.ephemeral = "sqlite", True
            self._backend = _SqliteBackend(database_url[len("sqlite:///"):])
        elif database_url.startswith(("postgres://", "postgresql://")):
            self.kind, self.ephemeral = "postgres", False
            self._backend = _PostgresBackend(database_url)
        else:
            raise ValueError(f"unsupported DATABASE_URL scheme: {database_url!r}")
        self._backend.init_schema()

    def get(self, collection: str, rid: str, *, fresh: bool = False) -> dict | None:
        if not _ID.match(rid):
            return None
        with self.lock:
            raw = self._backend.get(collection, rid)
        return _parse(raw)

    def list(self, collection: str) -> list[dict]:
        with self.lock:
            rows = self._backend.list(collection)
        return [r for r in (_parse(raw) for raw in rows) if r is not None]

    def count(self, collection: str) -> int:
        with self.lock:
            return self._usable_count(collection)

    def put(self, collection: str, rid: str, record: dict, *, new: bool = True) -> None:
        if not _ID.match(rid):
            raise ValueError("invalid id")
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self.lock:
            if new and self._backend.get(collection, rid) is None \
                    and self._usable_count(collection) >= self.caps.get(collection, 10**9):
                raise StoreFull(collection)
            self._backend.upsert(collection, rid, payload, _now_iso())

    def _usable_count(self, collection: str) -> int:
        """Count rows whose stored JSON is a usable record (mirrors JsonStore, which drops bad files)."""
        return sum(1 for raw in self._backend.list(collection) if _parse(raw) is not None)


def _parse(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if _is_record(rec) else None


class _SqliteBackend:
    """A SQLite connection per thread (sqlite3 objects are not shareable across threads)."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _conn(self):
        import sqlite3

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        self._conn().execute(
            "CREATE TABLE IF NOT EXISTS mx_store ("
            "collection TEXT NOT NULL, id TEXT NOT NULL, record TEXT NOT NULL, created_at TEXT NOT NULL, "
            "PRIMARY KEY (collection, id))")
        self._conn().commit()

    def get(self, collection: str, rid: str) -> str | None:
        cur = self._conn().execute(
            "SELECT record FROM mx_store WHERE collection = ? AND id = ?", (collection, rid))
        row = cur.fetchone()
        return row[0] if row else None

    def list(self, collection: str) -> list[str]:
        cur = self._conn().execute(
            "SELECT record FROM mx_store WHERE collection = ? ORDER BY created_at, id", (collection,))
        return [r[0] for r in cur.fetchall()]

    def upsert(self, collection: str, rid: str, record: str, created_at: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO mx_store (collection, id, record, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (collection, id) DO UPDATE SET record = excluded.record",
            (collection, rid, record, created_at))
        conn.commit()


class _PostgresBackend:
    """psycopg (imported lazily) with a small connection pool-free, lock-serialized connection.

    All access is already serialized by SqlStore.lock, so one connection is enough; it reconnects
    on a dropped connection."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn = None

    def _connect(self):
        import psycopg

        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def init_schema(self) -> None:
        with self._connect().cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS mx_store ("
                "collection TEXT NOT NULL, id TEXT NOT NULL, record TEXT NOT NULL, created_at TEXT NOT NULL, "
                "PRIMARY KEY (collection, id))")

    def get(self, collection: str, rid: str) -> str | None:
        with self._connect().cursor() as cur:
            cur.execute("SELECT record FROM mx_store WHERE collection = %s AND id = %s", (collection, rid))
            row = cur.fetchone()
            return row[0] if row else None

    def list(self, collection: str) -> list[str]:
        with self._connect().cursor() as cur:
            cur.execute(
                "SELECT record FROM mx_store WHERE collection = %s ORDER BY created_at, id", (collection,))
            return [r[0] for r in cur.fetchall()]

    def upsert(self, collection: str, rid: str, record: str, created_at: str) -> None:
        with self._connect().cursor() as cur:
            cur.execute(
                "INSERT INTO mx_store (collection, id, record, created_at) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (collection, id) DO UPDATE SET record = EXCLUDED.record",
                (collection, rid, record, created_at))


def make_store(root: Path, *, database_url: str | None = None, caps: dict[str, int] | None = None):
    """The store the app should use: ``SqlStore`` when ``DATABASE_URL`` is set (sqlite/postgres),
    otherwise the default ``JsonStore`` at ``root``. Reads ``DATABASE_URL`` from the environment
    when ``database_url`` is not given explicitly (tests)."""
    url = database_url if database_url is not None else os.getenv("DATABASE_URL", "").strip()
    if url:
        return SqlStore(url, caps=caps)
    return JsonStore(root, caps=caps)
