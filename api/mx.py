"""Renta MX routes (/mx/*). Mounted by api/main.py. docs/MX_SPEC.md, docs/MX_ARCHITECTURE.md, docs/API.md.

Read-only except listings, contracts and signatures, which go to a JSON-file store
(ephemeral on Render free). No LLM, no network. Only verified requirements are ever served.
"""

from __future__ import annotations

import functools
import hmac
import secrets
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.responses import JSONResponse

from mx import data as mx_data
from mx import paths
from mx.contracts import build_contract, check_violations, missing_fields, plan_clauses
from mx.models import ContractCreate, ListingCreate, ListingPublic, SignRequest
from mx.prices import listing_price_summary
from mx.ratelimit import RateLimiter
from mx.requirements import SOLO_FEDERAL_NOTICE, coverage, item, view
from mx.signatures import (EVIDENCE_NOTES, EVIDENCE_TITLE, SignatureError, make_evidence, mask_email, same_name,
                           sha256_hex, signature_status, validate_png)
from mx.sources import public_doc
from mx.store import JsonStore, StoreFull, make_store

MAX_BODY = 256 * 1024
DISCLAIMER = {
    "es": "No es asesoría legal. Renta MX es un prototipo que muestra fuentes oficiales con su cita literal; "
          "revise la fuente citada y consulte a un profesional antes de firmar o actuar.",
    "en": "Not legal advice. Renta MX is a prototype that shows official sources with their literal quote; "
          "check the cited source and consult a professional before signing or acting.",
}
STORE_NOTICE = {
    "es": "Demo: los anuncios y contratos se guardan en un disco efímero y se borran al reiniciar el servidor; "
          "descargue su constancia.",
    "en": "Demo: listings and contracts live on an ephemeral disk and are erased when the server restarts; "
          "download your record.",
}
PERSISTENT_STORE_NOTICE = {
    "es": "Los anuncios y contratos se guardan en una base de datos; aun así, descargue su constancia de firma.",
    "en": "Listings and contracts are kept in a database; even so, download your signature record.",
}


def store_notice(store, lang: str) -> str:
    """The honest storage notice for the active backend: ephemeral disk vs persistent database."""
    return STORE_NOTICE[lang] if getattr(store, "ephemeral", True) else PERSISTENT_STORE_NOTICE[lang]
LISTING_NOTICE = {
    "es": "Anuncio publicado por un usuario. Renta MX no verifica la identidad de quien publica ni la titularidad "
          "del inmueble: verifique al arrendador y no realice pagos fuera de un acuerdo por escrito.",
    "en": "Listing published by a user. Renta MX does not verify the publisher's identity or ownership: verify "
          "the landlord and make no payments outside a written agreement.",
}
_SIGN_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests via app.dependency_overrides)
# --------------------------------------------------------------------------- #


def get_data() -> mx_data.MxData:
    return mx_data.current()


@functools.lru_cache(maxsize=1)
def _default_store() -> JsonStore:
    # make_store picks SqlStore (sqlite/postgres) when DATABASE_URL is set, else the JSON store.
    return make_store(paths.store_dir())


def get_store() -> JsonStore:
    return _default_store()


@functools.lru_cache(maxsize=1)
def _default_limiter() -> RateLimiter:
    return RateLimiter()


def get_limiter() -> RateLimiter:
    return _default_limiter()


def get_clock():
    return lambda: datetime.now(timezone.utc)


def rate_limit(request: Request, limiter: RateLimiter = Depends(get_limiter)) -> None:
    ip = request.client.host if request.client else "?"
    wait = limiter.check(ip, request.method)
    if wait is not None:
        raise HTTPException(429, "demasiadas solicitudes; intente más tarde", headers={"Retry-After": str(wait)})


router = APIRouter(prefix="/mx", tags=["mx"], dependencies=[Depends(rate_limit)])


class MxBodyLimit:
    """ASGI middleware: POST /mx/* bodies over MAX_BODY get 413 (FastAPI has no body limit)."""

    def __init__(self, app, max_body: int = MAX_BODY):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/mx/"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        cl = headers.get(b"content-length")
        too_big = JSONResponse({"detail": f"cuerpo mayor a {self.max_body // 1024} KB"}, status_code=413)
        if cl is not None and (not cl.isdigit() or int(cl) > self.max_body):
            return await too_big(scope, receive, send)
        chunks, total = [], 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            chunks.append(msg.get("body", b""))
            total += len(chunks[-1])
            if total > self.max_body:
                return await too_big(scope, receive, send)
            if not msg.get("more_body"):
                break
        body, sent = b"".join(chunks), False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def lang_of(lang: str) -> str:
    if lang not in ("es", "en"):
        raise HTTPException(422, "lang debe ser 'es' o 'en'")
    return lang


def need_zones(d: mx_data.MxData):
    if d.zones is None:
        raise HTTPException(503, f"datos MX no disponibles: {d.zones_error}")
    return d.zones


def need_state(d: mx_data.MxData, cve_ent: str):
    s = need_zones(d).state(cve_ent)
    if s is None:
        raise HTTPException(404, f"entidad desconocida {cve_ent!r}")
    return s


def need_municipio(d: mx_data.MxData, cve_ent: str, cve_mun: str):
    s = need_state(d, cve_ent)
    m = s.municipios.get(cve_mun)
    if m is None:
        raise HTTPException(404, f"municipio desconocido {cve_ent}-{cve_mun}")
    return s, m


_NUMERIC = ("monthly_rent_mxn", "deposit_mxn", "bathrooms", "area_m2")


_LISTING_KEYS = ("id", "cve_ent", "cve_mun", "created_at", "monthly_rent_mxn", "bedrooms")


def _usable_listing(r: dict) -> bool:
    return isinstance(r, dict) and all(k in r for k in _LISTING_KEYS)


def listing_public(rec: dict) -> dict:
    out = ListingPublic(**{k: v for k, v in rec.items() if k in ListingPublic.model_fields}).model_dump(mode="json")
    for k in _NUMERIC:
        if out.get(k) is not None:
            out[k] = float(out[k])
    return out


def _listings(store: JsonStore, cve_ent: str | None = None, cve_mun: str | None = None) -> list[dict]:
    items = [r for r in store.list("listings") if _usable_listing(r)
             and (cve_ent is None or r["cve_ent"] == cve_ent) and (cve_mun is None or r["cve_mun"] == cve_mun)]
    return sorted(items, key=lambda r: r["created_at"], reverse=True)


def _counts(store: JsonStore) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for r in store.list("listings"):
        if not _usable_listing(r):
            continue  # a malformed record never breaks the counts shown on /mx/states and /mx/zones
        out[(r["cve_ent"], r["cve_mun"])] = out.get((r["cve_ent"], r["cve_mun"]), 0) + 1
    return out


def _by_zone(store: JsonStore) -> dict[tuple[str, str], list[dict]]:
    """Usable listings grouped by (cve_ent, cve_mun) in one pass (for price summaries)."""
    out: dict[tuple[str, str], list[dict]] = {}
    for r in store.list("listings"):
        if _usable_listing(r):
            out.setdefault((r["cve_ent"], r["cve_mun"]), []).append(r)
    return out


def _price_summary(listings: list[dict] | None, clock) -> dict:
    return listing_price_summary(listings or [], now=clock())


def _state_row(s, d: mx_data.MxData, counts: dict, price: dict | None = None) -> dict:
    n = sum(v for (e, _), v in counts.items() if e == s.cve_ent)
    row = {"cve_ent": s.cve_ent, "name": s.name, "abbr": s.abbr, **s.extra,
           "legal_coverage": coverage(s.abbr, d.verified), "listings_count": n, "municipios": len(s.municipios),
           "stats": s.stats}
    if price is not None:
        row["price_summary"] = price
    return row


def _requirements_summary(abbr: str | None, d: mx_data.MxData, lang: str) -> dict:
    v = view(abbr, d.verified, lang)
    return {"legal_coverage": v["legal_coverage"], "notice": v["notice"], "count": v["count"],
            "counts": v["counts"], "category_counts": v["category_counts"]}


def _http_422(errors: list[dict] | str):
    raise HTTPException(422, errors)


# --------------------------------------------------------------------------- #
# Read-only routes
# --------------------------------------------------------------------------- #


@router.get("/health")
def mx_health(lang: str = "es", d: mx_data.MxData = Depends(get_data), store: JsonStore = Depends(get_store)) -> dict:
    lang = lang_of(lang)
    data = {"documents": len(d.docs), "documents_ok": sum(c.ok for c in d.docs.values()),
            "requirements_verified": len(d.verified),
            "requirements_failed": sum(r.status != "verified" for r in d.report.results),
            "zones_states": len(d.zones.states) if d.zones else 0, "zones_error": d.zones_error,
            "clauses": len(d.clauses), "clauses_error": d.clauses_error}
    status = "ok" if d.zones and not d.clauses_error and d.report.ok else "degradado"
    return {"status": status, "store": getattr(store, "kind", "efimero"), "store_started_at": store.started_at,
            "store_notice": store_notice(store, lang), "listings": store.count("listings"),
            "contracts": store.count("contracts"), "data": data, "disclaimer": DISCLAIMER[lang]}


@router.get("/privacy")
def mx_privacy(lang: str = "es", d: mx_data.MxData = Depends(get_data)) -> dict:
    lang = lang_of(lang)
    basis = [item(v, lang) for v in d.verified.values()
             if v.req.jurisdiction == "FED" and v.req.category == "datos_personales"]
    es = lang == "es"
    return {
        "title": "Aviso de privacidad (demo)" if es else "Privacy notice (demo)",
        "responsable": "Equipo Infinity Tokens, prototipo Renta MX (sin fines comerciales)" if es else
        "Infinity Tokens team, Renta MX prototype (non-commercial)",
        "finalidades": (["Publicar anuncios de vivienda que usted envía.",
                         "Generar contratos de arrendamiento y registrar la evidencia de firma electrónica simple."]
                        if es else ["Publish the housing listings you submit.",
                                    "Generate lease contracts and record simple electronic signature evidence."]),
        "datos_recabados": (["Anuncio: nombre de contacto y correo (el correo nunca se muestra públicamente).",
                             "Contrato: nombre y correo de cada parte; domicilio del inmueble.",
                             "Firma: imagen o nombre tecleado, huella del correo (SHA-256), navegador (user-agent) "
                             "y huella de la IP con sal; nunca la IP en claro.",
                             "No se piden CURP, RFC, INE ni teléfono."] if es else
                            ["Listing: contact name and e-mail (the e-mail is never shown publicly).",
                             "Contract: each party's name and e-mail; the property address.",
                             "Signature: image or typed name, e-mail fingerprint (SHA-256), browser user-agent and a "
                             "salted IP fingerprint; never the plain IP.",
                             "No CURP, RFC, INE or phone number is requested."]),
        "conservacion": STORE_NOTICE[lang],
        "transferencias": "Ninguna. No se comparten datos con terceros." if es else
        "None. No data is shared with third parties.",
        "legal_basis": basis,
        "legal_basis_status": "verificada" if basis else "sin fuente verificada",
        "disclaimer": DISCLAIMER[lang]}


@router.get("/states")
def mx_states(lang: str = "es", d: mx_data.MxData = Depends(get_data), store: JsonStore = Depends(get_store),
              clock=Depends(get_clock)) -> dict:
    lang = lang_of(lang)
    z, counts, by_zone = need_zones(d), _counts(store), _by_zone(store)
    states = []
    for s in sorted(z.states.values(), key=lambda s: s.cve_ent):
        listings = [r for (e, _), rs in by_zone.items() if e == s.cve_ent for r in rs]
        states.append(_state_row(s, d, counts, _price_summary(listings, clock)))
    return {"count": len(states), "states": states, "disclaimer": DISCLAIMER[lang]}


@router.get("/zones")
def mx_zones(cve_ent: str = Query(..., pattern=r"^\d{2}$"), q: str | None = Query(None, max_length=80),
             limit: int = Query(50, ge=1, le=600), lang: str = "es", d: mx_data.MxData = Depends(get_data),
             store: JsonStore = Depends(get_store), clock=Depends(get_clock)) -> dict:
    lang = lang_of(lang)
    s = need_state(d, cve_ent)
    counts, by_zone = _counts(store), _by_zone(store)
    zones = []
    for m in need_zones(d).search(cve_ent, q, limit):
        n = counts.get((cve_ent, m.cve_mun), 0)
        zones.append({**m.public(), "listings_count": n, "empty_state": n == 0,
                      "price_summary": _price_summary(by_zone.get((cve_ent, m.cve_mun)), clock)})
    return {"cve_ent": cve_ent, "state": s.name, "legal_coverage": coverage(s.abbr, d.verified), "q": q,
            "count": len(zones), "zones": zones, "disclaimer": DISCLAIMER[lang]}


@router.get("/zones/{cve_ent}/{cve_mun}")
def mx_zone(cve_ent: str, cve_mun: str, lang: str = "es", d: mx_data.MxData = Depends(get_data),
            store: JsonStore = Depends(get_store), clock=Depends(get_clock)) -> dict:
    lang = lang_of(lang)
    s, m = need_municipio(d, cve_ent, cve_mun)
    raw = _listings(store, cve_ent, cve_mun)
    listings = [listing_public(r) for r in raw]
    return {"state": _state_row(s, d, _counts(store)), "zone": m.public(), "listings": listings,
            "listings_count": len(listings), "empty_state": not listings,
            "price_summary": _price_summary(raw, clock),
            "requirements_summary": _requirements_summary(s.abbr, d, lang),
            "listing_notice": LISTING_NOTICE[lang], "disclaimer": DISCLAIMER[lang]}


@router.get("/requirements")
def mx_requirements(cve_ent: str = Query(..., pattern=r"^\d{2}$"), lang: str = "es",
                    category: str | None = None, d: mx_data.MxData = Depends(get_data)) -> dict:
    lang = lang_of(lang)
    s = need_state(d, cve_ent)
    v = view(s.abbr, d.verified, lang)
    if category:
        v["categories"] = {k: x for k, x in v["categories"].items() if k == category}
    return {"cve_ent": cve_ent, "state": s.name, "abbr": s.abbr, "lang": lang, **v, "disclaimer": DISCLAIMER[lang]}


@router.get("/sources")
def mx_sources(lang: str = "es", d: mx_data.MxData = Depends(get_data)) -> dict:
    lang = lang_of(lang)
    docs = [{**public_doc(c), "verification": c.status, "warnings": c.warnings}
            if c.doc else {"doc_id": did, "verification": c.status, "errors": c.errors}
            for did, c in sorted(d.docs.items())]
    no_source = []
    if d.zones:
        no_source = [{"cve_ent": s.cve_ent, "name": s.name, "abbr": s.abbr}
                     for s in sorted(d.zones.states.values(), key=lambda s: s.cve_ent)
                     if coverage(s.abbr, d.verified) == "solo_federal"]
    return {"count": len(docs), "docs": docs, "verification": {x["doc_id"]: x["verification"] for x in docs},
            "requirements": {"verified": len(d.verified),
                             "failed": sum(r.status != "verified" for r in d.report.results)},
            "states_without_state_source": no_source, "disclaimer": DISCLAIMER[lang]}


# --------------------------------------------------------------------------- #
# Listings
# --------------------------------------------------------------------------- #


@router.get("/listings")
def mx_listings(cve_ent: str | None = Query(None, pattern=r"^\d{2}$"),
                cve_mun: str | None = Query(None, pattern=r"^\d{3}$"),
                max_rent: float | None = Query(None, gt=0), bedrooms: int | None = Query(None, ge=0, le=20),
                lang: str = "es", d: mx_data.MxData = Depends(get_data),
                store: JsonStore = Depends(get_store)) -> dict:
    lang = lang_of(lang)
    if cve_mun and not cve_ent:
        raise HTTPException(422, "cve_mun requiere cve_ent")
    if cve_ent and cve_mun:
        need_municipio(d, cve_ent, cve_mun)
    elif cve_ent:
        need_state(d, cve_ent)
    base = _listings(store, cve_ent, cve_mun)
    items = [r for r in base if (max_rent is None or Decimal(r["monthly_rent_mxn"]) <= Decimal(str(max_rent)))
             and (bedrooms is None or r["bedrooms"] >= bedrooms)]
    return {"count": len(items), "total_unfiltered": len(base), "empty_state": not items,
            "listings": [listing_public(r) for r in items], "listing_notice": LISTING_NOTICE[lang],
            "disclaimer": DISCLAIMER[lang]}


@router.post("/listings", status_code=201)
def mx_create_listing(body: ListingCreate, d: mx_data.MxData = Depends(get_data),
                      store: JsonStore = Depends(get_store), clock=Depends(get_clock)) -> dict:
    zones = need_zones(d)
    if zones.municipio(body.cve_ent, body.cve_mun) is None:
        _http_422([{"loc": ["body", "cve_mun"], "msg": "municipio inexistente para esa entidad",
                    "type": "value_error"}])
    rid = uuid.uuid4().hex
    rec = {**body.model_dump(mode="json"), "id": rid,
           "created_at": clock().isoformat(timespec="seconds").replace("+00:00", "Z")}
    try:
        store.put("listings", rid, rec)
    except StoreFull:
        raise HTTPException(507, "la demo alcanzó el máximo de anuncios") from None
    return {**listing_public(rec), "store_notice": STORE_NOTICE["es"]}


@router.get("/listings/{listing_id}")
def mx_listing(listing_id: str, lang: str = "es", store: JsonStore = Depends(get_store)) -> dict:
    lang = lang_of(lang)
    rec = store.get("listings", listing_id)
    if rec is None or not _usable_listing(rec):
        raise HTTPException(404, "anuncio no encontrado")
    return {**listing_public(rec), "listing_notice": LISTING_NOTICE[lang], "disclaimer": DISCLAIMER[lang]}


# --------------------------------------------------------------------------- #
# Contracts and signatures
# --------------------------------------------------------------------------- #


def _need_clauses(d: mx_data.MxData):
    if d.clauses_error:
        raise HTTPException(503, f"datos MX no disponibles: {d.clauses_error}")
    return d.clauses


@router.get("/contract-form")
def mx_contract_form(cve_ent: str = Query(..., pattern=r"^\d{2}$"), fiador: bool = False, deposit: bool = True,
                     lang: str = "es", d: mx_data.MxData = Depends(get_data)) -> dict:
    """What the contract form needs before creating a contract: clauses, legally required fields, roles."""
    lang = lang_of(lang)
    s = need_state(d, cve_ent)
    cov = coverage(s.abbr, d.verified)
    plan = plan_clauses(_need_clauses(d), s.abbr, cov, d.verified, has_fiador=fiador, deposit_zero=not deposit)
    return {"cve_ent": cve_ent, "state": s.name, "legal_coverage": cov,
            "notice": SOLO_FEDERAL_NOTICE[lang] if cov == "solo_federal" else None,
            "requires_acknowledgement": cov == "solo_federal",
            "roles": {"arrendador": "requerido", "arrendatario": "requerido",
                      "fiador": "requerido" if fiador else "opcional"},
            "required_fields": plan.required_fields(),
            "clauses": [{"key": c.key, "title": c.title_es if lang == "es" else c.title_en, "basis": c.basis,
                         "requirement_ids": [v.req.id for v in reqs]} for c, reqs in plan.included],
            "omitted_clauses": plan.omitted, "disclaimer": DISCLAIMER[lang]}


def _public_signature(s: dict, status: str) -> dict:
    """Signature projection for public GET: never expose the raw user-agent (PII); keep a hash."""
    ev = s["evidence"]
    out = {k: ev[k] for k in ("role", "full_name", "email_masked", "signed_at", "signature_kind",
                              "signature_sha256", "contract_sha256", "evidence_sha256", "prev_evidence_sha256")}
    out["user_agent_sha256"] = sha256_hex(ev.get("user_agent", ""))
    out |= {"status": status, "signature_png_base64": s.get("png_b64"), "typed_signature": s.get("typed")}
    return out


def _public_contract(rec: dict, lang: str = "es") -> dict:
    st = signature_status(rec)
    sigs = [_public_signature(s, per) for s, per in zip(rec["signatures"], st["per_signature"])]
    c = rec["contract"]
    return {**c, "sha256": st["sha256_current"], "sha256_at_creation": c["sha256"],
            "parties": rec["parties"], "signatures": sigs, "status": st, "store_notice": STORE_NOTICE[lang],
            "disclaimer": DISCLAIMER[lang]}


@router.post("/contracts", status_code=201)
def mx_create_contract(body: ContractCreate, d: mx_data.MxData = Depends(get_data),
                       store: JsonStore = Depends(get_store), clock=Depends(get_clock)) -> dict:
    zones = need_zones(d)
    s = zones.state(body.cve_ent)
    m = s.municipios.get(body.cve_mun) if s else None
    if s is None:
        _http_422([{"loc": ["body", "cve_ent"], "msg": "entidad inexistente", "type": "value_error"}])
    if m is None:
        _http_422([{"loc": ["body", "cve_mun"], "msg": "municipio inexistente para esa entidad", "type": "value_error"}])
    if body.listing_id:
        lst = store.get("listings", body.listing_id)
        if lst is None:
            _http_422([{"loc": ["body", "listing_id"], "msg": "anuncio inexistente", "type": "value_error"}])
        if (lst["cve_ent"], lst["cve_mun"]) != (body.cve_ent, body.cve_mun):
            _http_422([{"loc": ["body", "cve_mun"], "msg": "no coincide con la zona del anuncio", "type": "value_error"}])
    cov = coverage(s.abbr, d.verified)
    if cov == "solo_federal" and not body.acknowledge_solo_federal:
        _http_422([{"loc": ["body", "acknowledge_solo_federal"], "type": "value_error",
                    "msg": SOLO_FEDERAL_NOTICE["es"] + " Marque acknowledge_solo_federal: true para continuar."}])
    plan = plan_clauses(_need_clauses(d), s.abbr, cov, d.verified, has_fiador=body.fiador is not None,
                        deposit_zero=body.deposit_mxn == 0)
    missing = missing_fields(body, plan)
    if missing:
        _http_422([{"loc": ["body", *x["field"].split(".")], "msg": "campo obligatorio", "type": "missing",
                    "requirement_ids": x["requirement_ids"]} for x in missing])
    violations = check_violations(body, plan)
    if violations:
        _http_422([{"loc": ["body", x["field"]], "msg": f"no cumple {x['requirement_id']} ({x['citation']})",
                    "type": "legal_check", "requirement_ids": [x["requirement_id"]], **x} for x in violations])
    cid = uuid.uuid4().hex
    doc = build_contract(body, plan, estado=s.name, municipio=m.name, now=clock(), contract_id=cid)
    parties, tokens = {}, {}
    for role in doc["required_roles"]:
        p = getattr(body, role)
        parties[role] = {"full_name": p.full_name, "email_masked": mask_email(p.email),
                         "email_sha256": sha256_hex(p.email.strip().lower())}
        tokens[role] = secrets.token_urlsafe(24)
    rec = {"contract": doc, "parties": parties,
           "token_sha256": {r: sha256_hex(t) for r, t in tokens.items()}, "signatures": []}
    try:
        store.put("contracts", cid, rec)
    except StoreFull:
        raise HTTPException(507, "la demo alcanzó el máximo de contratos") from None
    return {**_public_contract(rec, body.lang), "sign_tokens": tokens,
            "sign_tokens_notice": "Los tokens se muestran una sola vez; compártalos solo con cada parte."}


def _need_contract(store: JsonStore, cid: str) -> dict:
    rec = store.get("contracts", cid, fresh=True)
    # A corrupt record (valid JSON but missing the keys the signature logic needs) is a 404, not a 500.
    if rec is None or not all(k in rec for k in ("contract", "parties", "token_sha256", "signatures")):
        raise HTTPException(404, "contrato no encontrado")
    return rec


@router.get("/contracts/{contract_id}")
def mx_contract(contract_id: str, lang: str = "es", store: JsonStore = Depends(get_store)) -> dict:
    return _public_contract(_need_contract(store, contract_id), lang_of(lang))


@router.post("/contracts/{contract_id}/sign")
def mx_sign(contract_id: str, body: SignRequest, request: Request, store: JsonStore = Depends(get_store),
            clock=Depends(get_clock)) -> dict:
    with _SIGN_LOCK:
        rec = _need_contract(store, contract_id)
        expected = rec["token_sha256"].get(body.role)
        if expected is None:
            _http_422([{"loc": ["body", "role"], "msg": "ese rol no forma parte de este contrato", "type": "value_error"}])
        if not hmac.compare_digest(expected, sha256_hex(body.token)):
            raise HTTPException(403, "token de firma inválido para ese rol")
        st = signature_status(rec)
        if body.contract_sha256 != st["sha256_current"]:
            raise HTTPException(409, {"code": "hash_changed", "msg": "el contrato cambió; revise la versión actual",
                                      "sha256_current": st["sha256_current"]})
        if st["roles"].get(body.role) == "valida":
            raise HTTPException(409, {"code": "already_signed", "msg": f"el rol {body.role} ya firmó"})
        if not same_name(body.full_name, rec["parties"][body.role]["full_name"]):
            _http_422([{"loc": ["body", "full_name"], "type": "value_error",
                        "msg": "el nombre no coincide con el registrado para ese rol en el contrato"}])
        if body.signature_png_base64 is not None:
            try:
                sig = validate_png(body.signature_png_base64)
            except SignatureError as e:
                _http_422([{"loc": ["body", "signature_png_base64"], "msg": str(e), "type": "value_error"}])
            kind = body.method or "trazo"
        else:
            sig, kind = body.typed_signature.encode("utf-8"), "tecleada"
        ev = make_evidence(rec, role=body.role, full_name=body.full_name, email=body.email, signature=sig,
                           kind=kind, user_agent=request.headers.get("user-agent"),
                           ip=request.client.host if request.client else None, now=clock())
        rec["signatures"].append({"evidence": ev, "png_b64": body.signature_png_base64,
                                  "typed": body.typed_signature})
        store.put("contracts", contract_id, rec, new=False)
    out = _public_contract(rec)
    return {"status": out["status"], "signatures": out["signatures"], "evidence": ev}


@router.get("/contracts/{contract_id}/evidence")
def mx_evidence(contract_id: str, lang: str = "es", store: JsonStore = Depends(get_store)) -> dict:
    lang = lang_of(lang)
    rec = _need_contract(store, contract_id)
    st = signature_status(rec)
    c = rec["contract"]
    return {"title": EVIDENCE_TITLE[lang], "contract_id": contract_id, "template_version": c["template_version"],
            "created_at": c["created_at"], "sha256_current": st["sha256_current"],
            "sha256_at_creation": c["sha256"], "text": c["text"], "status": st,
            "signatures": [_public_signature(s, per)
                           for s, per in zip(rec["signatures"], st["per_signature"])],
            "verify_hint": "sha256(canonicalize(text)) debe ser igual a contract_sha256 de cada firma; "
                           "canonicalize: NFC, LF, sin espacios finales, máx. 2 líneas vacías, un LF final.",
            "notes": EVIDENCE_NOTES[lang], "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "disclaimer": DISCLAIMER[lang]}
