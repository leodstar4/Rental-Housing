"""/mx read routes, listings, CORS, body limit and rate limit, on FIXTURE data. Offline."""

from __future__ import annotations

import json

import pytest
import yaml
from mx_support import LISTING, client, make_client, mx_env  # noqa: F401  (pytest fixtures)

from mx.ratelimit import RateLimiter, TokenBucket


def test_health_reports_ephemeral_store(client):
    r = client.get("/mx/health").json()
    assert r["store"] == "efimero" and r["listings"] == 0 and r["data"]["requirements_verified"] == 6
    assert r["disclaimer"].startswith("No es asesoría legal")


def test_states_coverage_is_computed_not_read(client):
    states = {s["cve_ent"]: s for s in client.get("/mx/states").json()["states"]}
    # the fixture file says the opposite on purpose
    assert states["09"]["legal_coverage"] == "estatal_verificada"
    assert states["31"]["legal_coverage"] == "solo_federal"
    assert states["09"]["listings_count"] == 0


def test_zone_search_is_accent_insensitive_and_stats_need_a_source(client):
    r = client.get("/mx/zones", params={"cve_ent": "09", "q": "cuauhtemoc"}).json()
    assert [z["name"] for z in r["zones"]] == ["Cuauhtémoc"]
    z = r["zones"][0]
    assert set(z["stats"]) == {"poblacion_total", "pct_viviendas_alquiladas"}
    assert all(v["source"] for v in z["stats"].values())
    assert z["stats"]["pct_viviendas_alquiladas"]["precision_baja"] is True
    assert z["empty_state"] is True and z["listings_count"] == 0
    azc = client.get("/mx/zones/09/002").json()["zone"]
    assert azc["has_stats"] is False and azc["has_coords"] is False and "lat" not in azc


@pytest.mark.parametrize("url", ["/mx/zones/09/999", "/mx/zones/99/001", "/mx/requirements?cve_ent=99",
                                 "/mx/zones?cve_ent=77"])
def test_unknown_ids_404(client, url):
    assert client.get(url).status_code == 404


def test_missing_zones_gives_503_but_us_routes_unaffected(mx_env):
    from api.main import app

    (mx_env.data / "zones.json").unlink()
    c = make_client(mx_env)
    try:
        assert c.get("/mx/states").status_code == 503
        assert c.get("/mx/sources").status_code == 200
        assert c.get("/mx/health").json()["status"] == "degradado"
    finally:
        app.dependency_overrides.clear()


def test_requirements_only_verified_and_grouped(mx_env):
    from api.main import app

    p = mx_env.data / "requirements" / "CDMX.yaml"
    items = yaml.safe_load(p.read_text(encoding="utf-8"))
    items.append({**items[1], "id": "MX-CDMX-ROTO-01", "quote": "Esta frase no existe en el texto ficticio de la fixture."})
    p.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")
    c = make_client(mx_env)
    try:
        r = c.get("/mx/requirements", params={"cve_ent": "09"}).json()
        ids = [x["id"] for v in r["categories"].values() for x in v]
        assert "MX-CDMX-ROTO-01" not in ids and len(ids) == 6
        x = r["categories"]["deposito"][0]
        assert x["level"] == "estatal" and x["quote"] and x["url"] and x["retrieved_at"] and x["citation"]
        assert r["legal_coverage"] == "estatal_verificada" and r["notice"] is None
        yuc = c.get("/mx/requirements", params={"cve_ent": "31", "lang": "en"}).json()
        assert yuc["legal_coverage"] == "solo_federal" and yuc["notice"]
        assert {x["level"] for v in yuc["categories"].values() for x in v} == {"federal"}
    finally:
        app.dependency_overrides.clear()


def test_sources_and_privacy(client):
    s = client.get("/mx/sources").json()
    assert s["verification"] == {"D-MX-CDMX-01": "ok", "D-MX-FED-01": "ok", "D-MX-INEGI-01": "ok"}
    assert [x["cve_ent"] for x in s["states_without_state_source"]] == ["31"]
    p = client.get("/mx/privacy").json()
    assert p["legal_basis_status"] == "verificada" and p["legal_basis"][0]["id"] == "MX-FED-DATOS-01"


def test_listings_empty_then_published_without_email(client):
    r = client.get("/mx/listings", params={"cve_ent": "09", "cve_mun": "015"}).json()
    assert r == {**r, "count": 0, "empty_state": True, "listings": []}
    created = client.post("/mx/listings", json=LISTING)
    assert created.status_code == 201
    lid = created.json()["id"]
    assert len(lid) == 32 and "contact_email" not in created.json()
    got = client.get(f"/mx/listings/{lid}").json()
    assert got["monthly_rent_mxn"] == 10000.0 and "contact_email" not in got and "ana@example.com" not in json.dumps(got)
    r = client.get("/mx/listings", params={"cve_ent": "09", "cve_mun": "015", "max_rent": 5000}).json()
    assert r["count"] == 0 and r["total_unfiltered"] == 1 and r["empty_state"] is True
    assert client.get("/mx/zones/09/015").json()["listings_count"] == 1
    assert client.get("/mx/listings/" + "0" * 32).status_code == 404


@pytest.mark.parametrize("change", [{"monthly_rent_mxn": 0}, {"cp": "0670"}, {"cve_mun": "999"},
                                    {"contact_email": "no-es-correo"}, {"contact_name": "Ana\nCLÁUSULA"},
                                    {"extra": 1}, {"privacy_consent": False}, {"cve_ent": "9"}])
def test_listing_validation_422(client, change):
    assert client.post("/mx/listings", json={**LISTING, **change}).status_code == 422


def test_cors_preflight_allows_post(client):
    r = client.options("/mx/listings", headers={"Origin": "https://foo.lovable.app",
                                                "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and "POST" in r.headers["access-control-allow-methods"]


def test_body_over_256kb_is_413(client):
    r = client.post("/mx/listings", content=b"{" + b" " * (300 * 1024) + b"}",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_rate_limit_11th_post_is_429(mx_env):
    from api.main import app

    t = [0.0]
    c = make_client(mx_env, limiter=RateLimiter(10, 120, clock=lambda: t[0]))
    try:
        codes = [c.post("/mx/listings", json=LISTING).status_code for _ in range(11)]
        assert codes[:10] == [201] * 10 and codes[10] == 429
        r = c.post("/mx/listings", json=LISTING)
        assert int(r.headers["Retry-After"]) >= 1
        t[0] += 60
        assert c.post("/mx/listings", json=LISTING).status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_token_bucket_refills():
    t = [0.0]
    b = TokenBucket(2, clock=lambda: t[0])
    assert b.take("ip") is None and b.take("ip") is None and b.take("ip") == pytest.approx(30.0)
    t[0] = 30.0
    assert b.take("ip") is None
