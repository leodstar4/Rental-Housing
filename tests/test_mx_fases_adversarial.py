"""Adversarial audit of the Renta MX phases 0-4 (The Tester). Offline, deterministic.

Scope (new/changed in fases 0-4): mx/store.py (SqlStore + make_store), mx/prices.py,
api/main.py (US-tolerance + CORS regex), the new states GTO/DGO/CHIH (coverage, ids, citations,
contract clauses + annex) and the signature token secrecy.

These tests try to BREAK the code. A passing test here is a regression guard proving the attack
is already resisted; any failing test documents a real bug (file + root cause) and must be left
failing. Nothing in production is modified.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from mx_support import client, mx_env  # noqa: F401  (pytest fixtures)

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def rid(i: int) -> str:
    return f"{i:032x}"


# =========================================================================== #
# 1. SqlStore: SQL injection, corrupt rows, concurrency, caps, parity, bad URL
# =========================================================================== #


def test_sql_injection_in_collection_and_id_is_inert(tmp_path):
    """collection/id are bound parameters, never interpolated into SQL: an injection payload is a
    literal lookup (miss), never a DROP, and the table survives."""
    from mx.store import SqlStore

    db = tmp_path / "s.db"
    s = SqlStore(f"sqlite:///{db}")
    s.put("listings", rid(1), {"ok": 1})
    assert s.get("listings'); DROP TABLE mx_store;--", rid(1)) is None
    # an injected id is not 32-hex -> rejected before any query
    assert s.get("listings", "' OR '1'='1") is None
    assert s.count("listings") == 1 and s.get("listings", rid(1)) == {"ok": 1}
    # a weird collection name is stored/retrieved verbatim, isolated from "listings"
    s.put("x'; DELETE FROM mx_store;--", rid(2), {"v": 2})
    assert s.get("x'; DELETE FROM mx_store;--", rid(2)) == {"v": 2}
    assert s.get("listings", rid(1)) == {"ok": 1}  # untouched


def test_sqlstore_malformed_database_url_fails_loud_not_silent():
    """An unsupported scheme raises ValueError (never silently drops to an in-memory store that
    would lose data). The empty/whitespace env case falls back to JsonStore via make_store."""
    from mx.store import JsonStore, SqlStore, make_store

    for bad in ("mysql://x", "http://x", "redis://x", "sqlite://missing-third-slash", "postgres", "garbage"):
        with pytest.raises(ValueError):
            SqlStore(bad)
    # make_store from env: empty / whitespace-only DATABASE_URL -> default JsonStore (stripped)
    import os
    import mx.store as store_mod

    def with_env(val):
        old = os.environ.get("DATABASE_URL")
        if val is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = val
        try:
            return make_store(Path("/tmp/x"))
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old

    assert isinstance(with_env(""), JsonStore)
    assert isinstance(with_env("   "), JsonStore)
    assert isinstance(with_env(None), JsonStore)


def test_sqlstore_corrupt_or_non_object_rows_never_served(tmp_path):
    """Valid-JSON-but-not-object rows ([], null, scalar) and invalid JSON are dropped on read, so
    one poisoned row cannot 500 a route that iterates the store, nor inflate the cap count."""
    from mx.store import SqlStore

    db = tmp_path / "s.db"
    s = SqlStore(f"sqlite:///{db}")
    s.put("listings", rid(1), {"i": 1})
    conn = sqlite3.connect(db)
    for i, payload in ((2, "[]"), (3, "null"), (4, "{bad json"), (5, '"a string"'), (6, "123")):
        conn.execute("INSERT INTO mx_store VALUES (?,?,?,?)", ("listings", rid(i), payload, "2026-01-01T00:00:00Z"))
    conn.commit()
    conn.close()
    s2 = SqlStore(f"sqlite:///{db}")
    assert s2.list("listings") == [{"i": 1}]
    assert s2.count("listings") == 1
    for i in (2, 3, 4, 5, 6):
        assert s2.get("listings", rid(i)) is None


def test_sqlstore_concurrent_puts_keep_cap_and_no_corruption(tmp_path):
    from mx.store import SqlStore, StoreFull

    s = SqlStore(f"sqlite:///{tmp_path / 's.db'}", caps={"listings": 5})
    results: list[str] = []

    def worker(i):
        try:
            s.put("listings", rid(i), {"i": i})
            results.append("ok")
        except StoreFull:
            results.append("full")

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count("ok") == 5 and results.count("full") == 15
    rows = s.list("listings")
    assert len(rows) == 5 and all(isinstance(r, dict) and "i" in r for r in rows)


def test_json_and_sql_backends_behave_identically(tmp_path):
    """Byte-for-byte behavioural parity on get/put/list/count/caps/invalid-id across both backends."""
    from mx.store import JsonStore, SqlStore, StoreFull

    js = JsonStore(tmp_path / "j", caps={"listings": 2})
    sq = SqlStore(f"sqlite:///{tmp_path / 's.db'}", caps={"listings": 2})
    for store in (js, sq):
        assert store.count("listings") == 0 and store.list("listings") == []
        assert store.get("listings", rid(0)) is None
        assert store.get("listings", "nope") is None
        with pytest.raises(ValueError):
            store.put("listings", "nope", {"v": 1})
        store.put("listings", rid(0), {"v": 0})
        store.put("listings", rid(1), {"v": 1})
        with pytest.raises(StoreFull):
            store.put("listings", rid(2), {"v": 2})
        store.put("listings", rid(0), {"v": 99}, new=False)  # overwrite never trips cap
        assert store.get("listings", rid(0)) == {"v": 99}
        assert store.count("listings") == 2
        assert sorted(r["v"] for r in store.list("listings")) == [1, 99]


def test_postgres_backend_selected_without_connecting(tmp_path, monkeypatch):
    """postgres:// / postgresql:// pick the non-ephemeral backend and psycopg stays a lazy import
    (we never actually connect here)."""
    import mx.store as store_mod

    seen = {}

    class Fake:
        def __init__(self, dsn):
            seen["dsn"] = dsn

        def init_schema(self):
            seen["init"] = True

    monkeypatch.setattr(store_mod, "_PostgresBackend", Fake)
    for scheme in ("postgres://u:p@h/db", "postgresql://u:p@h/db"):
        s = store_mod.SqlStore(scheme)
        assert s.kind == "postgres" and s.ephemeral is False and seen["init"] is True


# =========================================================================== #
# 2. api/main.py tolerant to a missing out/: US routes 503, /mx intact
# =========================================================================== #


@pytest.fixture
def no_us(monkeypatch):
    from api import main

    monkeypatch.setattr(main, "US_DATA_FILES", (Path("out/__nope__.json"),))
    main.store.cache_clear()
    main.engine.cache_clear()
    yield
    main.store.cache_clear()
    main.engine.cache_clear()


@pytest.mark.parametrize("url", ["/lookup/A0016", "/rules", "/changes", "/changes/T1", "/conflicts",
                                 "/explain/A0016/CA-RENT-01", "/timeline/A0016"])
def test_us_routes_give_clean_503_not_500_when_out_absent(no_us, url):
    from api.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get(url)
        assert r.status_code == 503, f"{url} -> {r.status_code}"
        assert "US (legacy) data is not available" in r.json()["detail"]


def test_us_lookup_bad_params_still_resolve_before_503_or_422(no_us):
    """A malformed as_of must be a clean 422, an unknown address a clean 404 or 503 — never 500."""
    from api.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/lookup/A0016", params={"as_of": "2031-01-01"}).status_code in (422, 503)
        assert c.get("/lookup/A0016", params={"as_of": "not-a-date"}).status_code in (422, 503)
        assert c.get("/health").status_code == 200


# =========================================================================== #
# 3. CORS: anchored regex, attacker look-alikes denied, *.pages.dev allowed
# =========================================================================== #


@pytest.mark.parametrize("origin, allowed", [
    ("https://renta-mx.pages.dev", True),
    ("https://a.b.c.pages.dev", True),
    ("https://pages.dev", True),
    ("https://my-app.lovable.app", True),
    ("http://localhost:5173", True),
    ("http://127.0.0.1:3000", True),
    # look-alikes / suffix & prefix attacks must be denied
    ("https://pages.dev.evil.com", False),
    ("https://evil-pages.dev.attacker.com", False),
    ("https://pages.dev.attacker.com", False),
    ("https://notpages.dev", False),     # NOT a subdomain of pages.dev: correctly denied
    ("https://lovable.app.evil.com", False),
    ("https://evil.com/?x=pages.dev", False),
    ("http://localhost.evil.com", False),
])
def test_cors_regex_fullmatch_anchoring(origin, allowed):
    """Starlette matches allow_origin_regex with fullmatch, so a trailing '.evil.com' can never
    piggy-back on pages.dev / lovable.app."""
    from api.main import ORIGIN_REGEX

    assert bool(re.compile(ORIGIN_REGEX).fullmatch(origin)) is allowed


def test_cors_header_reflected_only_for_allowed_origin():
    """End-to-end through the real middleware: the ACAO header is echoed only for allowed origins."""
    from api.main import app, store

    store.cache_clear()
    with TestClient(app) as c:
        ok = c.get("/mx/health", headers={"Origin": "https://x.pages.dev"})
        assert ok.headers.get("access-control-allow-origin") == "https://x.pages.dev"
        evil = c.get("/mx/health", headers={"Origin": "https://pages.dev.evil.com"})
        assert "access-control-allow-origin" not in evil.headers


# =========================================================================== #
# 4. listing_price_summary: n<3 hides figures, corrupt ignored, parity in API
# =========================================================================== #


def _rows(*rents, cve_mun="015"):
    return [{"id": f"L{i}", "cve_ent": "09", "cve_mun": cve_mun, "created_at": "2026-10-05T00:00:00Z",
             "monthly_rent_mxn": r, "bedrooms": 2} for i, r in enumerate(rents)]


@pytest.mark.parametrize("n", [0, 1, 2])
def test_price_summary_never_publishes_figures_below_three(n):
    from mx.prices import listing_price_summary

    s = listing_price_summary(_rows(*([10000] * n)), now=NOW)
    assert s["count"] == n and s["has_stats"] is False
    assert not ({"min", "median", "max"} & set(s))
    assert s["reason"] == "insufficient_sample"


def test_price_summary_corrupt_records_dropped_and_cannot_drop_below_three():
    """Mixing one sound listing with corrupt ones must NOT produce figures (sound count < 3)."""
    from mx.prices import listing_price_summary

    corrupt = [{}, {"monthly_rent_mxn": None}, {"monthly_rent_mxn": "abc"}, {"monthly_rent_mxn": 0},
               {"monthly_rent_mxn": -1}, {"monthly_rent_mxn": "NaN"}, {"monthly_rent_mxn": "Infinity"},
               {"monthly_rent_mxn": True}, "a string", 123]
    s = listing_price_summary(_rows(10000) + corrupt, now=NOW)
    assert s["count"] == 1 and s["has_stats"] is False


def test_price_summary_even_median_and_large_decimals():
    from mx.prices import listing_price_summary

    s = listing_price_summary(_rows(8000, 9001, 10000, 11000), now=NOW)
    assert s["median"] == 9500.5  # (9001+10000)/2
    big = listing_price_summary(_rows("1000000000", "2000000000", "3000000000", "4000000000"), now=NOW)
    assert (big["min"], big["median"], big["max"]) == (1000000000, 2500000000, 4000000000)


def test_api_zone_detail_states_and_list_never_leak_small_sample_figures(client):
    """Across /mx/zones/{e}/{m}, /mx/zones and /mx/states, a zone with 1-2 listings exposes only a
    count, never min/median/max."""
    from mx_support import LISTING

    # two listings in 09/015 -> still no figures anywhere
    for rent in (8000, 12000):
        assert client.post("/mx/listings", json={**LISTING, "monthly_rent_mxn": rent}).status_code == 201
    detail = client.get("/mx/zones/09/015").json()["price_summary"]
    assert detail["count"] == 2 and detail["has_stats"] is False and "median" not in detail
    zlist = {z["cve_mun"]: z for z in client.get("/mx/zones", params={"cve_ent": "09"}).json()["zones"]}
    assert zlist["015"]["price_summary"]["count"] == 2 and "median" not in zlist["015"]["price_summary"]
    st = {s["cve_ent"]: s for s in client.get("/mx/states").json()["states"]}
    assert st["09"]["price_summary"]["count"] == 2 and "median" not in st["09"]["price_summary"]
    # a third one unlocks the figures
    assert client.post("/mx/listings", json={**LISTING, "monthly_rent_mxn": 10000}).status_code == 201
    assert client.get("/mx/zones/09/015").json()["price_summary"]["median"] == 10000


def test_api_corrupt_stored_listing_does_not_break_price_summary(mx_env):
    """A corrupt listing file on disk is ignored by both the store and the price summary."""
    from mx_support import LISTING, make_client

    d = mx_env.store / "listings"
    d.mkdir(parents=True, exist_ok=True)
    (d / ("e" * 32 + ".json")).write_text("[]", encoding="utf-8")
    (d / ("f" * 32 + ".json")).write_text("{bad", encoding="utf-8")
    c = make_client(mx_env)
    try:
        for rent in (8000, 10000, 12000):
            assert c.post("/mx/listings", json={**LISTING, "monthly_rent_mxn": rent}).status_code == 201
        ps = c.get("/mx/zones/09/015").json()["price_summary"]
        assert ps["count"] == 3 and ps["median"] == 10000  # corrupt files excluded
    finally:
        from api.main import app
        app.dependency_overrides.clear()


# =========================================================================== #
# 5. Regla cero on the map (backend): lat/lon without a coord source not served
# =========================================================================== #


def test_zone_with_coords_without_source_not_marked_mappable(client):
    """A zone served with has_coords=true must carry a coord.source; a point with no source block
    is reported has_coords=false (see api/mx fixture guard test). We assert the real CDMX zones
    that DO expose coords also expose a source."""
    zones = client.get("/mx/zones", params={"cve_ent": "09"}).json()["zones"]
    for z in zones:
        if z.get("has_coords"):
            assert z.get("coord") and z["coord"].get("source"), f"{z['cve_mun']} has coords but no source"


# =========================================================================== #
# 6. New states GTO/DGO/CHIH: verified citations, ids, coverage, contract annex
# =========================================================================== #


def test_new_states_manifest_has_integrity_fields():
    man = json.loads((ROOT / "corpus_mx" / "manifest_estados.json").read_text(encoding="utf-8"))
    docs = man["docs"] if isinstance(man, dict) and "docs" in man else man
    found = {}
    for d in docs:
        for code in ("GTO", "DGO", "CHIH"):
            if f"-{code}-" in d.get("doc_id", ""):
                found[code] = d
    assert set(found) == {"GTO", "DGO", "CHIH"}
    for code, d in found.items():
        for key in ("url", "retrieved_at", "sha256", "text_sha256"):
            assert d.get(key), f"{code} missing {key}"


@pytest.mark.parametrize("code", ["GTO", "DGO", "CHIH"])
def test_new_state_requirement_ids_prefixed_and_laws(code):
    items = yaml.safe_load((ROOT / "data" / "mx" / "requirements" / f"{code}.yaml").read_text(encoding="utf-8"))
    assert items, f"{code}.yaml empty"
    for it in items:
        assert it["id"].startswith(f"MX-{code}-"), it["id"]
        assert it["jurisdiction"] == code
        assert it.get("quote") and len(it["quote"]) >= 40


def test_new_states_all_quotes_verify_offline():
    """Every requirement quote of the whole corpus (incl. the 3 new states) verifies, and no
    document fails its hash."""
    from mx.verify import verify_all

    rep = verify_all()
    j = rep.as_json()
    assert rep.ok is True, j["counts"]
    assert j["counts"]["failed"] == 0
    assert j["counts"]["verified"] == j["counts"]["requirements"]
    assert j["counts"]["documents_ok"] == j["counts"]["documents"]


@pytest.mark.parametrize("cve_ent, code", [("11", "GTO"), ("10", "DGO"), ("08", "CHIH")])
def test_new_states_coverage_is_estatal_verificada(cve_ent, code):
    from api.main import app, store

    store.cache_clear()
    with TestClient(app) as c:
        r = c.get("/mx/requirements", params={"cve_ent": cve_ent})
        assert r.status_code == 200
        j = r.json()
        assert j["legal_coverage"] == "estatal_verificada"
        ids = [x["id"] for cat in j["categories"].values() for x in cat] if "categories" in j else []
        assert any(i.startswith(f"MX-{code}-") for i in ids)


def test_gto_contract_generates_state_clauses_and_cited_annex():
    """A GTO contract (estatal_verificada) cites MX-GTO-* requirements in its clauses and prints an
    annex; every cited id is a verified requirement of GTO or FED (never invented)."""
    from api.main import app, store

    store.cache_clear()
    body = {"cve_ent": "11", "cve_mun": "020",
            "inmueble": {"calle": "Calle X", "num_ext": "1", "colonia": "Centro", "cp": "36000"},
            "arrendador": {"full_name": "Ana Perez", "email": "ana@example.com"},
            "arrendatario": {"full_name": "Luis Gomez", "email": "luis@example.com"},
            "monthly_rent_mxn": 10000, "deposit_mxn": 10000, "start_date": "2026-11-01",
            "term_months": 12, "payment_day": 5}
    with TestClient(app) as c:
        r = c.post("/mx/contracts", json=body)
        assert r.status_code == 201, r.text
        j = r.json()
        assert j["coverage"] == "estatal_verificada"
        cited = {i for cl in j["clauses"] for i in cl["requirement_ids"]}
        assert any(i.startswith("MX-GTO-") for i in cited), "no state clause cited"
        assert all(i.startswith(("MX-GTO-", "MX-FED-")) for i in cited), cited
        assert "ANEXO" in j["text"] and "MX-GTO" in str(j["legal_basis"])


# =========================================================================== #
# 7. Signature: the token / its hash never leak in any GET response
# =========================================================================== #


def test_sign_token_and_hash_never_leak_in_get_or_evidence(client):
    from mx_support import contract_body

    created = client.post("/mx/contracts", json=contract_body()).json()
    cid = created["contract_id"]
    plaintext_tokens = list(created["sign_tokens"].values())
    # the server-side hash is never returned at creation either
    assert "token_sha256" not in created
    for url in (f"/mx/contracts/{cid}", f"/mx/contracts/{cid}/evidence"):
        body = client.get(url).text
        for tok in plaintext_tokens:
            assert tok not in body, f"plaintext sign token leaked in {url}"
        # the stored hash dict key must not surface
        assert "token_sha256" not in body


def test_sign_rejects_oversized_or_malformed_png(client):
    from mx_support import contract_body, png
    import base64

    c = client.post("/mx/contracts", json=contract_body()).json()
    role = "arrendador"
    base = {"role": role, "full_name": "Ana Pérez", "email": "ana@example.com", "consent": True,
            "contract_sha256": c["sha256"], "token": c["sign_tokens"][role]}
    too_big = base64.b64encode(png(pad=200 * 1024)).decode()
    not_png = base64.b64encode(b"GIF89a" + b"\x00" * 40).decode()
    for sig in (too_big, not_png, "%%%bad-base64%%%"):
        r = client.post(f"/mx/contracts/{c['contract_id']}/sign", json={**base, "signature_png_base64": sig})
        assert r.status_code in (413, 422), f"{sig[:12]} -> {r.status_code}"
