"""Phase 0 foundations: the service tolerates a missing out/ (US legacy data), /health and
/mx/health always answer, US routes give a clear 503, and *.pages.dev is a CORS origin.

Offline. These tests simulate "out/ absent" by pointing main.US_DATA_FILES at non-existent paths
(so the real out/ on disk is never touched)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mx_support import make_client, mx_env  # noqa: F401  (pytest fixtures)

from api import main


@pytest.fixture
def no_us(monkeypatch):
    """Make us_data_ready() report False without deleting anything on disk."""
    monkeypatch.setattr(main, "US_DATA_FILES", (Path("out/__does_not_exist__.json"),))
    main.store.cache_clear()
    main.engine.cache_clear()
    yield
    main.store.cache_clear()
    main.engine.cache_clear()


def test_health_ok_when_us_data_present():
    main.store.cache_clear()
    with TestClient(main.app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["us_data"] is True


def test_health_200_when_us_data_absent(no_us):
    with TestClient(main.app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["us_data"] is False
        # MX health answers regardless of US data
        assert c.get("/mx/health").status_code == 200


@pytest.mark.parametrize("url", ["/lookup/A0016", "/rules", "/changes", "/changes/T1",
                                 "/conflicts", "/explain/A0016/CA-RENT-01", "/timeline/A0016"])
def test_us_routes_503_when_data_absent(no_us, url):
    with TestClient(main.app) as c:
        r = c.get(url)
        assert r.status_code == 503
        assert "US (legacy) data is not available" in r.json()["detail"]


def test_mx_health_works_when_us_absent(no_us, mx_env):
    from api.main import app

    c = make_client(mx_env)
    try:
        assert c.get("/mx/health").status_code == 200
        assert c.get("/mx/states").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_pages_dev_cors_preflight_allowed():
    """OPTIONS /mx/listings from a *.pages.dev origin is allowed (CORS preflight)."""
    main.store.cache_clear()
    with TestClient(main.app) as c:
        r = c.options("/mx/listings", headers={
            "Origin": "https://renta-mx.pages.dev",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "https://renta-mx.pages.dev"
