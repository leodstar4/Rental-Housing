"""Shared helpers for tests/test_mx_*.py. Data comes from tests/fixtures/mx (FIXTURE, not real law)."""

from __future__ import annotations

import shutil
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "mx"
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def make_env(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """Copy the fixture tree (+ the real clause templates) to tmp and point mx.paths at it."""
    env = SimpleNamespace(data=tmp_path / "mxdata", corpus=tmp_path / "corpus_mx", store=tmp_path / "mx_store")
    shutil.copytree(FIX / "data", env.data)
    shutil.copytree(FIX / "corpus_mx", env.corpus)
    shutil.copy(ROOT / "data" / "mx" / "contract_clauses.yaml", env.data / "contract_clauses.yaml")
    monkeypatch.setenv("MX_DATA_DIR", str(env.data))
    monkeypatch.setenv("MX_CORPUS_DIR", str(env.corpus))
    monkeypatch.setenv("MX_STORE_DIR", str(env.store))
    return env


@pytest.fixture
def mx_env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def make_client(env, *, limiter=None, store=None):
    from fastapi.testclient import TestClient

    from api import mx as api_mx
    from api.main import app
    from mx import data as mx_data
    from mx.ratelimit import RateLimiter
    from mx.store import JsonStore

    d = mx_data.load(env.data, env.corpus)
    st = store or JsonStore(env.store)
    lim = limiter or RateLimiter(10_000, 10_000)
    app.dependency_overrides.update({api_mx.get_data: lambda: d, api_mx.get_store: lambda: st,
                                     api_mx.get_limiter: lambda: lim, api_mx.get_clock: lambda: (lambda: NOW)})
    c = TestClient(app)
    c.data, c.store = d, st
    return c


@pytest.fixture
def client(mx_env):
    from api.main import app

    c = make_client(mx_env)
    yield c
    app.dependency_overrides.clear()


def png(w: int = 400, h: int = 150, pad: int = 0) -> bytes:
    """A PNG header (signature + IHDR) the validator accepts; ``pad`` adds trailing bytes."""
    ihdr = struct.pack(">II5B", w, h, 8, 6, 0, 0, 0)
    chunk = struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk + b"\x00" * pad


LISTING = {"cve_ent": "09", "cve_mun": "015", "cp": "06700", "colonia": "Roma Norte", "title": "FIXTURE depto",
           "description": "Línea uno\nLínea dos", "monthly_rent_mxn": 10000, "deposit_mxn": 10000, "bedrooms": 2,
           "bathrooms": 1, "available_from": "2026-11-01", "contact_name": "Ana Pérez",
           "contact_email": "ana@example.com", "truthfulness_consent": True, "privacy_consent": True}


def contract_body(**kw) -> dict:
    body = {"cve_ent": "09", "cve_mun": "015",
            "inmueble": {"calle": "Calle Ficticia", "num_ext": "1", "colonia": "Roma Norte", "cp": "06700"},
            "arrendador": {"full_name": "Ana Pérez", "email": "ana@example.com"},
            "arrendatario": {"full_name": "Luis Gómez", "email": "luis@example.com"},
            "monthly_rent_mxn": 10000, "deposit_mxn": 10000, "start_date": "2026-11-01", "term_months": 12,
            "payment_day": 5}
    body.update(kw)
    return body
