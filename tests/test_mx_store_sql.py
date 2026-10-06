"""Store backends (mx/store.py): the same battery against JsonStore and SqlStore(sqlite).

Offline, no network. SQLite uses the stdlib; Postgres is not exercised here (it is imported
lazily and only when DATABASE_URL points at it)."""

from __future__ import annotations

import json
import threading

import pytest

from mx.store import CAPS, JsonStore, SqlStore, StoreFull, make_store

HEX = "0123456789abcdef"


def rid(i: int) -> str:
    """A valid 32-hex id derived from an integer."""
    return f"{i:032x}"


def make_json(tmp_path, caps=None):
    return JsonStore(tmp_path / "json_store", caps=caps)


def make_sqlite(tmp_path, caps=None):
    return SqlStore(f"sqlite:///{tmp_path / 'store.db'}", caps=caps)


BACKENDS = [pytest.param(make_json, id="json"), pytest.param(make_sqlite, id="sqlite")]


@pytest.fixture(params=BACKENDS)
def store(request, tmp_path):
    return request.param(tmp_path)


# --------------------------------------------------------------------------- #
# Shared public interface
# --------------------------------------------------------------------------- #


def test_put_get_list_count(store):
    assert store.count("listings") == 0 and store.list("listings") == []
    assert store.get("listings", rid(1)) is None
    rec = {"id": rid(1), "cve_ent": "09", "title": "x"}
    store.put("listings", rid(1), rec)
    assert store.get("listings", rid(1)) == rec
    assert store.count("listings") == 1 and store.list("listings") == [rec]
    # collections are independent
    assert store.count("contracts") == 0


def test_put_overwrite_not_new(store):
    store.put("listings", rid(1), {"v": 1})
    store.put("listings", rid(1), {"v": 2}, new=False)
    assert store.get("listings", rid(1)) == {"v": 2}
    assert store.count("listings") == 1


def test_invalid_ids_rejected(store):
    for bad in ("", "x", "ZZZ", rid(1)[:-1], rid(1) + "0", "../../etc", "A" * 32, "g" * 32):
        assert store.get("listings", bad) is None
        with pytest.raises(ValueError):
            store.put("listings", bad, {"v": 1})
    assert store.count("listings") == 0


def test_caps_enforced(tmp_path):
    for make in (make_json, make_sqlite):
        s = make(tmp_path / make.__name__, caps={"listings": 3, "contracts": 1})
        for i in range(3):
            s.put("listings", rid(i), {"i": i})
        with pytest.raises(StoreFull):
            s.put("listings", rid(99), {"i": 99})
        # overwriting an existing id never trips the cap
        s.put("listings", rid(0), {"i": 0, "v": 2}, new=False)
        assert s.count("listings") == 3
        # a different collection has its own cap
        s.put("contracts", rid(0), {"c": 1})
        with pytest.raises(StoreFull):
            s.put("contracts", rid(1), {"c": 2})


def test_fresh_get(store):
    store.put("contracts", rid(1), {"v": 1})
    assert store.get("contracts", rid(1), fresh=True) == {"v": 1}
    assert store.get("contracts", rid(2), fresh=True) is None


# --------------------------------------------------------------------------- #
# Concurrency: 20 threads, no corruption, cap respected
# --------------------------------------------------------------------------- #


def test_concurrent_puts_respect_cap(store):
    cap = store.caps["listings"] = 5
    results: list[object] = []

    def worker(i: int):
        try:
            store.put("listings", rid(i), {"i": i})
            results.append("ok")
        except StoreFull:
            results.append("full")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == cap and results.count("full") == 20 - cap
    assert store.count("listings") == cap
    # every stored record is intact (a valid object with its own i)
    stored = store.list("listings")
    assert len(stored) == cap and all(isinstance(r, dict) and "i" in r for r in stored)


# --------------------------------------------------------------------------- #
# Persistence after reopen (same backend path)
# --------------------------------------------------------------------------- #


def test_json_persists_after_reopen(tmp_path):
    root = tmp_path / "store"
    s1 = JsonStore(root)
    s1.put("listings", rid(1), {"i": 1})
    s2 = JsonStore(root)
    assert s2.get("listings", rid(1)) == {"i": 1} and s2.count("listings") == 1


def test_sqlite_persists_after_reopen(tmp_path):
    url = f"sqlite:///{tmp_path / 'store.db'}"
    s1 = SqlStore(url)
    s1.put("listings", rid(1), {"i": 1})
    s1.put("contracts", rid(2), {"c": 2})
    s2 = SqlStore(url)
    assert s2.get("listings", rid(1)) == {"i": 1}
    assert s2.get("contracts", rid(2)) == {"c": 2}
    assert s2.count("listings") == 1 and s2.count("contracts") == 1


# --------------------------------------------------------------------------- #
# Corrupt records are dropped, not served (parity with JsonStore)
# --------------------------------------------------------------------------- #


def test_sqlite_corrupt_or_non_object_rows_are_dropped(tmp_path):
    import sqlite3

    db = tmp_path / "store.db"
    s = SqlStore(f"sqlite:///{db}")
    s.put("listings", rid(1), {"i": 1})
    # inject rows that are valid-JSON-but-not-object and invalid JSON directly
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO mx_store VALUES (?, ?, ?, ?)", ("listings", rid(2), "[]", "2026-01-01T00:00:00Z"))
    conn.execute("INSERT INTO mx_store VALUES (?, ?, ?, ?)", ("listings", rid(3), "null", "2026-01-01T00:00:00Z"))
    conn.execute("INSERT INTO mx_store VALUES (?, ?, ?, ?)", ("listings", rid(4), "{bad", "2026-01-01T00:00:00Z"))
    conn.commit()
    conn.close()
    s2 = SqlStore(f"sqlite:///{db}")
    assert s2.list("listings") == [{"i": 1}]
    assert s2.count("listings") == 1
    assert s2.get("listings", rid(2)) is None and s2.get("listings", rid(4)) is None


def test_json_record_round_trips_unicode(store):
    rec = {"nombre": "Ana Pérez", "colonia": "Roma Norte", "renta": 15000}
    store.put("listings", rid(7), rec)
    assert store.get("listings", rid(7)) == rec
    assert store.get("listings", rid(7), fresh=True) == rec


# --------------------------------------------------------------------------- #
# make_store factory: backend selection by DATABASE_URL
# --------------------------------------------------------------------------- #


def test_make_store_defaults_to_json(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = make_store(tmp_path / "store")
    assert isinstance(s, JsonStore) and s.kind == "efimero" and s.ephemeral is True


def test_make_store_uses_sqlite_from_env(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'store.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    s = make_store(tmp_path / "store")
    assert isinstance(s, SqlStore) and s.kind == "sqlite" and s.ephemeral is True
    s.put("listings", rid(1), {"i": 1})
    assert s.count("listings") == 1


def test_make_store_explicit_url_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://should-not-be-used")
    s = make_store(tmp_path / "store", database_url=f"sqlite:///{tmp_path / 'db.sqlite'}")
    assert isinstance(s, SqlStore) and s.kind == "sqlite"


def test_sqlstore_reports_postgres_kind_without_connecting(tmp_path, monkeypatch):
    """postgres:// / postgresql:// select the postgres backend (kind='postgres', not ephemeral);
    we do not connect here, so init_schema is stubbed. psycopg stays a lazy import."""
    import mx.store as store_mod

    created = {}

    class FakeBackend:
        def __init__(self, dsn):
            created["dsn"] = dsn

        def init_schema(self):
            created["init"] = True

    monkeypatch.setattr(store_mod, "_PostgresBackend", FakeBackend)
    s = store_mod.SqlStore("postgresql://user:pass@host/db")
    assert s.kind == "postgres" and s.ephemeral is False and created["init"] is True


def test_default_caps_match_json(tmp_path):
    s = SqlStore(f"sqlite:///{tmp_path / 'store.db'}")
    assert s.caps == CAPS
