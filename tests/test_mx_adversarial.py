"""Adversarial tests for the /mx backend (The Tester). Offline, on FIXTURE data unless stated.

Tests here are meant to FAIL while the bug they describe exists. Passing tests in this file are
regression guards for attacks that the current code already resists.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from pathlib import Path

import pytest
import yaml
from mx_support import ROOT, client, contract_body, make_client, mx_env, png  # noqa: F401  (fixtures)

from mx import contracts as C
from mx import verify
from mx.ratelimit import RateLimiter, TokenBucket
from mx.store import JsonStore

EMAILS = ("ana@example.com", "luis@example.com", "eva@example.com")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(env) -> tuple[Path, dict]:
    p = env.corpus / "manifest_fixture.json"
    return p, json.loads(p.read_text(encoding="utf-8"))


def _add_req(env, file: str, **item):
    p = env.data / "requirements" / file
    items = yaml.safe_load(p.read_text(encoding="utf-8"))
    items.append(item)
    p.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _base_req(**kw) -> dict:
    r = {"id": "MX-FED-ATAQUE-01", "jurisdiction": "FED", "category": "otro", "kind": "ley",
         "title_es": "t", "title_en": "t", "summary_es": "s", "summary_en": "s", "doc_id": "D-MX-FED-01",
         "citation": "FIXTURE art. 10", "quote": "x", "applies_to_contract": False, "reviewed_by": "FIXTURE"}
    r.update(kw)
    return r


def _edit_zones(env, fn):
    p = env.data / "zones.json"
    z = json.loads(p.read_text(encoding="utf-8"))
    fn(z)
    p.write_text(json.dumps(z, ensure_ascii=False), encoding="utf-8")


def _raw_client():
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _sign(c, contract, role, **kw):
    party = {"arrendador": ("Ana Pérez", "ana@example.com"), "arrendatario": ("Luis Gómez", "luis@example.com"),
             "fiador": ("Eva Ruiz", "eva@example.com")}[role]
    body = {"role": role, "full_name": party[0], "email": party[1], "consent": True,
            "contract_sha256": contract["sha256"], "token": contract["sign_tokens"].get(role, "t" * 20),
            "signature_png_base64": base64.b64encode(png()).decode()}
    body.update(kw)
    body = {k: v for k, v in body.items() if v is not None}
    return c.post(f"/mx/contracts/{contract['contract_id']}/sign", json=body)


# =========================================================================== #
# 1. Zero invented data
# =========================================================================== #


def test_real_manifests_pin_every_quotable_text_with_text_sha256():
    """BUG (alta): MX_ARCHITECTURE §1.1 — the .txt a quote is verified against must be pinned by
    text_sha256; otherwise editing the .txt makes any fabricated quote "verify"."""
    missing = []
    for p in sorted((ROOT / "corpus_mx").glob("manifest_*.json")):
        for d in json.loads(p.read_text(encoding="utf-8"))["docs"]:
            if d.get("text_path") and d.get("text_path") != d.get("file_path") and not d.get("text_sha256"):
                missing.append(d["doc_id"])
    assert missing == [], f"documentos legales sin text_sha256 (su .txt puede alterarse sin detección): {missing}"


def test_unpinned_txt_cannot_back_a_fabricated_quote(mx_env):
    """BUG (alta): with file_path=PDF and no text_sha256, appending a sentence to the .txt makes a
    requirement quoting that invented sentence pass verify and be served by the API."""
    txt = mx_env.corpus / "fed" / "fed_fixture.txt"
    pdf = mx_env.corpus / "fed" / "fed_fixture.pdf"
    pdf.write_bytes(b"%PDF-1.4 FIXTURE original\n" + txt.read_bytes())
    p, m = _manifest(mx_env)
    d = next(x for x in m["docs"] if x["doc_id"] == "D-MX-FED-01")
    d.update(file_path="corpus_mx/fed/fed_fixture.pdf", sha256=_sha(pdf))
    d.pop("text_sha256")
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    fabricated = "El arrendatario renuncia a todos sus derechos según este texto inventado por un atacante."
    txt.write_text(txt.read_text(encoding="utf-8") + "\nArtículo 99.- " + fabricated + "\n", encoding="utf-8")
    _add_req(mx_env, "FED.yaml", **_base_req(quote=fabricated, citation="FIXTURE art. 99"))
    _, res = verify.verify_all(mx_env.data, mx_env.corpus), None
    r = {x.id: x for x in verify.verify_all(mx_env.data, mx_env.corpus).results}["MX-FED-ATAQUE-01"]
    assert r.status != "verified", "una cita inventada en un .txt sin text_sha256 se verificó"


def test_soft_hyphen_padding_bypasses_min_quote_length(mx_env):
    """BUG (media): the 40-char minimum is measured before the Spanish pre-fold removes U+00AD, so a
    14-char trivial quote padded with soft hyphens verifies and is served."""
    quote = "­" * 40 + "consentimiento"
    _add_req(mx_env, "FED.yaml", **_base_req(quote=quote))
    r = {x.id: x for x in verify.verify_all(mx_env.data, mx_env.corpus).results}["MX-FED-ATAQUE-01"]
    assert r.status != "verified", f"cita trivial verificada como {r.quote_verified!r} ({r.match_type})"


def test_verified_quotes_are_never_shorter_than_the_minimum_on_real_data():
    """Guard on the real corpus: every served quote is >= QUOTE_MIN after folding."""
    report = verify.verify_all(ROOT / "data" / "mx", ROOT / "corpus_mx")
    short = [(i, v.quote_verified) for i, v in report.verified().items()
             if len(v.quote_verified.replace("­", "")) < verify.QUOTE_MIN]
    assert short == []


def test_real_data_contract_clauses_only_cite_verified_law(mx_env):
    """Guard on the real corpus: for every state, each ley clause cites only verified, non-practica,
    applies_to_contract requirements of FED or that state; acuerdo_partes never cites anything."""
    from mx import data as mx_data
    from mx.requirements import LAW_KINDS, coverage

    d = mx_data.load(ROOT / "data" / "mx", ROOT / "corpus_mx")
    assert d.zones is not None and not d.clauses_error
    for s in d.zones.states.values():
        cov = coverage(s.abbr, d.verified)
        plan = C.plan_clauses(d.clauses, s.abbr, cov, d.verified, has_fiador=True, deposit_zero=False)
        for c, reqs in plan.included:
            if c.basis == "acuerdo_partes":
                assert reqs == []
            for v in reqs:
                assert v.req.id in d.verified and v.req.kind in LAW_KINDS and v.req.applies_to_contract
                assert v.req.jurisdiction in ("FED", s.abbr)
                if cov == "solo_federal":
                    assert v.req.jurisdiction == "FED"


def test_practica_requirement_never_feeds_a_clause(mx_env):
    """Guard: a verified kind=practica requirement in a clause category is shown but never cited."""
    q = "Los datos personales del texto de prueba se tratarán solo para la finalidad informada"
    _add_req(mx_env, "FED.yaml", **_base_req(id="MX-FED-PRACTICA-01", kind="practica", category="datos_personales",
                                            quote=q))
    c = make_client(mx_env)
    try:
        assert "MX-FED-PRACTICA-01" in c.data.verified
        r = c.post("/mx/contracts", json=contract_body()).json()
        assert all("MX-FED-PRACTICA-01" not in x["requirement_ids"] for x in r["clauses"])
        assert "MX-FED-PRACTICA-01" not in {x["id"] for x in r["legal_basis"]}
        assert "MX-FED-PRACTICA-01" not in r["text"]
    finally:
        from api.main import app
        app.dependency_overrides.clear()


@pytest.mark.parametrize("template", [
    "El depósito no podrá exceder de dos meses de renta.",
    "Conforme al artículo dos mil cuatrocientos cuarenta y ocho del código civil.",
    "La renta solo podrá incrementarse hasta el diez por ciento anual.",
], ids=["meses_en_letra", "articulo_en_letra", "porcentaje_en_letra"])
def test_clause_template_rejects_legal_facts_written_in_words(template):
    """BUG (media): the 'no legal facts in templates' guard only rejects digits and 'art.'; a
    legal cap or article written in words loads and would be printed as an unsourced legal fact."""
    with pytest.raises(ValueError):
        C.ClauseTemplate(key="x", title_es="t", title_en="t", basis="ley", categories=["deposito"],
                         template_es=template)


def test_zone_scalar_figure_without_source_is_not_served(mx_env):
    """BUG (baja): any scalar key on a municipio outside 'stats' is passed through by Municipio.public()
    without a source check (and mx.verify does not flag it)."""
    def fn(z):
        z["states"][0]["municipios"][0]["viviendas_alquiladas"] = 54321
    _edit_zones(mx_env, fn)
    c = make_client(mx_env)
    try:
        zone = c.get("/mx/zones/09/015").json()["zone"]
        assert "viviendas_alquiladas" not in zone, "cifra sin fuente servida en la zona"
        z2 = c.get("/mx/zones", params={"cve_ent": "09", "q": "cuauh"}).json()["zones"][0]
        assert "viviendas_alquiladas" not in z2
    finally:
        from api.main import app
        app.dependency_overrides.clear()


def test_coordinates_without_coord_source_are_not_served(mx_env):
    """BUG (baja-media): lat/lon are dropped only when a 'coord' block with an unknown source exists;
    lat/lon with NO coord block at all are served (has_coords: true) with no source."""
    def fn(z):
        m = z["states"][0]["municipios"][1]           # Azcapotzalco: no coord in the fixture
        m["lat"], m["lon"] = 19.48, -99.18
    _edit_zones(mx_env, fn)
    c = make_client(mx_env)
    try:
        zone = c.get("/mx/zones/09/002").json()["zone"]
        assert zone["has_coords"] is False and "lat" not in zone, f"coordenada sin fuente: {zone}"
    finally:
        from api.main import app
        app.dependency_overrides.clear()


def test_listings_only_come_from_posts(client):
    """Guard: empty inventory everywhere until a POST; after one POST exactly one listing."""
    assert all(s["listings_count"] == 0 for s in client.get("/mx/states").json()["states"])
    assert client.get("/mx/listings").json()["count"] == 0
    from mx_support import LISTING
    assert client.post("/mx/listings", json=LISTING).status_code == 201
    assert client.get("/mx/listings").json()["count"] == 1


# =========================================================================== #
# 2. Integrity of sources
# =========================================================================== #


def test_wrong_manifest_sha256_invalidates_doc_and_api_serves_none_of_it(mx_env):
    p, m = _manifest(mx_env)
    m["docs"][1]["sha256"] = "0" * 64               # D-MX-CDMX-01
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    c = make_client(mx_env)
    try:
        r = c.get("/mx/requirements", params={"cve_ent": "09"}).json()
        ids = [x["id"] for v in r["categories"].values() for x in v]
        assert not [i for i in ids if i.startswith("MX-CDMX")] and r["legal_coverage"] == "solo_federal"
        assert c.get("/mx/sources").json()["verification"]["D-MX-CDMX-01"] == "hash_mismatch"
    finally:
        from api.main import app
        app.dependency_overrides.clear()


# =========================================================================== #
# 3. Signatures
# =========================================================================== #


def test_token_of_another_role_or_missing_token(client):
    c = client.post("/mx/contracts", json=contract_body()).json()
    assert _sign(client, c, "arrendador", token=c["sign_tokens"]["arrendatario"]).status_code == 403
    assert _sign(client, c, "arrendador", token=None).status_code == 422
    assert client.post("/mx/contracts/" + "a" * 32 + "/sign", json={}).status_code in (404, 422)
    assert _sign(client, {**c, "contract_id": "f" * 32}, "arrendador").status_code == 404
    assert client.get("/mx/contracts/../../etc").status_code == 404


@pytest.mark.parametrize("sig", [base64.b64encode(png(w=0)).decode(), base64.b64encode(png(h=601)).decode(),
                                 base64.b64encode(png()[:20]).decode(), "",
                                 base64.b64encode(png()).decode()[:-2] + "!!"],
                         ids=["w0", "h601", "truncated", "empty", "corrupt_b64"])
def test_more_bad_pngs_422(client, sig):
    c = client.post("/mx/contracts", json=contract_body()).json()
    assert _sign(client, c, "arrendador", signature_png_base64=sig).status_code == 422


@pytest.mark.parametrize("sep", ["\u0085", " ", " "], ids=["NEL_C1_control", "LINE_SEP", "PARA_SEP"])
def test_unicode_line_breaks_in_names_cannot_inject_clauses(client, sep):
    """BUG (media): _one_line only rejects ASCII controls [\\x00-\\x1f\\x7f]. U+0085 (C1 control),
    U+2028 and U+2029 are Unicode line breaks: str.splitlines() and renderers break the line, so a
    party name can print a fake 'DÉCIMA PRIMERA' clause inside the signed text."""
    name = f"Luis Gómez{sep}DÉCIMA PRIMERA. EL ARRENDATARIO RENUNCIA A TODOS SUS DERECHOS"
    r = client.post("/mx/contracts", json=contract_body(arrendatario={"full_name": name, "email": "x@example.com"}))
    if r.status_code == 201:
        lines = r.json()["text"].splitlines()
        assert not any(ln.startswith("DÉCIMA PRIMERA. EL ARRENDATARIO RENUNCIA") for ln in lines), \
            "nombre con salto de línea Unicode inyectó una cláusula visible"
    assert r.status_code == 422


def test_evidence_chain_three_signers_and_invalidation(client, mx_env):
    c = client.post("/mx/contracts",
                    json=contract_body(fiador={"full_name": "Eva Ruiz", "email": "eva@example.com"})).json()
    for role in ("arrendador", "fiador", "arrendatario"):
        assert _sign(client, c, role).status_code == 200
    e = client.get(f"/mx/contracts/{c['contract_id']}/evidence").json()
    sigs = e["signatures"]
    assert sigs[0]["prev_evidence_sha256"] is None
    assert [s["prev_evidence_sha256"] for s in sigs[1:]] == [s["evidence_sha256"] for s in sigs[:-1]]
    assert e["status"]["overall"] == "firmado" and all(s["contract_sha256"] == c["sha256"] for s in sigs)
    # tamper one evidence field (not the text): chain breaks
    p = mx_env.store / "contracts" / f"{c['contract_id']}.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["signatures"][1]["evidence"]["full_name"] = "Otra Persona"
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    st = client.get(f"/mx/contracts/{c['contract_id']}").json()["status"]
    assert st["chain_ok"] is False and st["overall"] == "invalidado"


def test_concurrent_double_sign_only_one_wins(client):
    c = client.post("/mx/contracts", json=contract_body()).json()
    codes = []
    ts = [threading.Thread(target=lambda: codes.append(_sign(client, c, "arrendador").status_code))
          for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200] + [409] * 7
    assert len(client.get(f"/mx/contracts/{c['contract_id']}").json()["signatures"]) == 1


# =========================================================================== #
# 4. Inputs
# =========================================================================== #


@pytest.mark.parametrize("rent", [0, -1, "NaN", "Infinity", 10_000_000.01, 0.001, "1e400", "abc"])
def test_rent_bounds_422(client, rent):
    assert client.post("/mx/contracts", json=contract_body(monthly_rent_mxn=rent)).status_code == 422


def test_rent_at_max_builds(client):
    r = client.post("/mx/contracts", json=contract_body(monthly_rent_mxn=10_000_000, deposit_mxn=0))
    assert r.status_code == 201 and "DIEZ MILLONES DE PESOS 00/100 M.N." in r.json()["text"]


def test_unknown_cve_ent_in_contract_body_is_422_like_listings(client):
    """BUG (baja): POST /mx/listings answers 422 for an unknown entity in the body, POST /mx/contracts
    answers 404 (need_state), as if the /mx/contracts resource did not exist."""
    from mx_support import LISTING
    assert client.post("/mx/listings", json={**LISTING, "cve_ent": "99"}).status_code == 422
    assert client.post("/mx/contracts", json=contract_body(cve_ent="99")).status_code == 422


@pytest.mark.parametrize("raw", [b"{", b"null", b"[]", b'{"cve_ent": "09"}', b"\xff\xfe"])
def test_malformed_or_incomplete_json_422(client, raw):
    for url in ("/mx/listings", "/mx/contracts"):
        assert client.post(url, content=raw, headers={"Content-Type": "application/json"}).status_code == 422


@pytest.mark.parametrize("email", ["a@b", "a b@example.com", "@example.com", "a@example.c", "a" * 65 + "@example.com"])
def test_invalid_emails_422(client, email):
    body = contract_body(arrendador={"full_name": "Ana Pérez", "email": email})
    assert client.post("/mx/contracts", json=body).status_code == 422


def test_chunked_body_over_limit_is_413(client):
    def gen():
        yield b'{"x": "'
        for _ in range(300):
            yield b"a" * 1024
        yield b'"}'
    r = client.post("/mx/listings", content=gen(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_get_rate_limit_429_with_retry_after(mx_env):
    t = [0.0]
    c = make_client(mx_env, limiter=RateLimiter(10, 3, clock=lambda: t[0]))
    try:
        codes = [c.get("/mx/health").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        r = c.get("/mx/health")
        assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    finally:
        from api.main import app
        app.dependency_overrides.clear()


def test_rate_limiter_memory_is_bounded_when_all_requests_are_allowed():
    """BUG (media): TokenBucket trims _state only on a *rejected* request. With distinct client IPs
    (e.g. a spoofed X-Forwarded-For: render.yaml runs --forwarded-allow-ips='*') every request is
    allowed and the dict grows without bound."""
    b = TokenBucket(10, clock=lambda: 0.0)
    for i in range(25_000):
        assert b.take(f"10.{i >> 16}.{(i >> 8) & 255}.{i & 255}") is None
    assert len(b._state) <= 10_000, f"{len(b._state)} entradas en memoria"


# =========================================================================== #
# 5. Store
# =========================================================================== #


def test_concurrent_posts_respect_cap(mx_env):
    from mx_support import LISTING
    c = make_client(mx_env, store=JsonStore(mx_env.store, caps={"listings": 5, "contracts": 5}))
    try:
        codes = []
        ts = [threading.Thread(target=lambda: codes.append(c.post("/mx/listings", json=LISTING).status_code))
              for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sorted(codes) == [201] * 5 + [507] * 15
        files = list((mx_env.store / "listings").iterdir())
        assert len(files) == 5 and all(json.loads(f.read_text(encoding="utf-8"))["id"] for f in files)
    finally:
        from api.main import app
        app.dependency_overrides.clear()


@pytest.mark.parametrize("payload", ["{}", "[]", "null", '{"id": "x", "cve_ent": "09"}'],
                         ids=["empty_obj", "list", "null", "partial"])
def test_corrupt_listing_record_does_not_break_every_listing_route(mx_env, payload):
    """BUG (media): JsonStore._load skips only undecodable JSON. A valid-JSON but malformed record
    (empty object, list, partial) makes _counts/_listings raise -> 500 on /mx/states, /mx/zones and
    /mx/listings for everybody."""
    d = mx_env.store / "listings"
    d.mkdir(parents=True)
    (d / ("e" * 32 + ".json")).write_text(payload, encoding="utf-8")
    make_client(mx_env)
    try:
        c = _raw_client()
        for url in ("/mx/states", "/mx/zones?cve_ent=09", "/mx/listings", "/mx/zones/09/015"):
            assert c.get(url).status_code == 200, url
    finally:
        from api.main import app
        app.dependency_overrides.clear()


def test_corrupt_contract_record_is_not_a_500(client, mx_env):
    """BUG (baja): a contract file with valid JSON but missing keys gives 500 instead of 404/409."""
    cid = "d" * 32
    d = mx_env.store / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cid}.json").write_text('{"contract": {}}', encoding="utf-8")
    c = _raw_client()
    assert c.get(f"/mx/contracts/{cid}").status_code != 500
    assert c.get(f"/mx/contracts/{cid}/evidence").status_code != 500


def test_truncated_store_file_is_ignored(mx_env):
    d = mx_env.store / "listings"
    d.mkdir(parents=True)
    (d / ("e" * 32 + ".json")).write_text('{"id": "', encoding="utf-8")
    (d / ("f" * 32 + ".json")).write_bytes(b"\xff\xfe\x00")
    assert JsonStore(mx_env.store).count("listings") == 0


# =========================================================================== #
# 6. Privacy
# =========================================================================== #


def test_no_plain_email_or_ip_in_any_get_or_evidence(client):
    from mx_support import LISTING
    lid = client.post("/mx/listings", json=LISTING).json()["id"]
    c = client.post("/mx/contracts", json=contract_body(
        listing_id=lid, fiador={"full_name": "Eva Ruiz", "email": "eva@example.com"})).json()
    for role in ("arrendador", "arrendatario", "fiador"):
        assert _sign(client, c, role).status_code == 200
    cid = c["contract_id"]
    urls = ["/mx/listings", f"/mx/listings/{lid}", "/mx/zones/09/015", f"/mx/contracts/{cid}",
            f"/mx/contracts/{cid}/evidence", "/mx/states", "/mx/health"]
    for u in urls:
        body = client.get(u).text
        assert not any(e in body for e in EMAILS), u
        assert "testclient" not in body, u          # TestClient's client.host
    assert not any(e in json.dumps(c) for e in EMAILS)
