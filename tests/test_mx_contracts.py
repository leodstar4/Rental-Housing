"""Contract generation, signatures and the JSON store on FIXTURE data. Offline."""

from __future__ import annotations

import base64
import json
import threading

import pytest
from mx_support import NOW, ROOT, client, contract_body, make_client, mx_env, png  # noqa: F401

from mx import contracts as C
from mx.models import ContractCreate
from mx.store import JsonStore, StoreFull

# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n,words", [(1, "un"), (21, "veintiún"), (100, "cien"), (101, "ciento un"),
                                     (1000, "mil"), (15500, "quince mil quinientos"),
                                     (21000, "veintiún mil"), (1_000_000, "un millón"),
                                     (2_345_678, "dos millones trescientos cuarenta y cinco mil seiscientos setenta y ocho")])
def test_number_to_words(n, words):
    assert C.number_to_words(n) == words


def test_money_words():
    from decimal import Decimal

    assert C.money_words(Decimal("12500.50")) == "DOCE MIL QUINIENTOS PESOS 50/100 M.N."
    assert C.money_words(Decimal("1000000")) == "UN MILLÓN DE PESOS 00/100 M.N."


def test_canonicalize_idempotent_and_crlf_equivalent():
    t = "A  \r\nB\r\n\r\n\r\n\r\n\r\nC"
    assert C.canonicalize(C.canonicalize(t)) == C.canonicalize(t) == "A\nB\n\n\nC\n"
    assert C.contract_hash("A\r\nB") == C.contract_hash("A\nB\n")


def test_real_clause_templates_load_and_carry_no_legal_numbers():
    clauses = C.load_clauses(ROOT / "data" / "mx" / "contract_clauses.yaml")
    assert clauses and all(c.basis == "ley" or not c.categories for c in clauses)
    with pytest.raises(ValueError):
        C.ClauseTemplate(key="x", title_es="t", title_en="t", basis="ley", categories=["deposito"],
                         template_es="El depósito no excede de 1 mes.")
    with pytest.raises(ValueError):
        C.ClauseTemplate(key="x", title_es="t", title_en="t", basis="acuerdo_partes", categories=["deposito"],
                         template_es="Pacto.")


def test_build_is_deterministic(client):
    d = client.data
    body = ContractCreate(**contract_body())
    plan = C.plan_clauses(d.clauses, "CDMX", "estatal_verificada", d.verified, has_fiador=False, deposit_zero=False)
    a = C.build_contract(body, plan, estado="E", municipio="M", now=NOW, contract_id="a" * 32)
    b = C.build_contract(body, plan, estado="E", municipio="M", now=NOW, contract_id="a" * 32)
    assert a["text"] == b["text"] and a["sha256"] == b["sha256"] == C.contract_hash(a["text"])


# --------------------------------------------------------------------------- #
# POST /mx/contracts
# --------------------------------------------------------------------------- #


def test_contract_cdmx_links_clauses_to_verified_requirements(client):
    r = client.post("/mx/contracts", json=contract_body())
    assert r.status_code == 201, r.text
    c = r.json()
    by_key = {x["key"]: x for x in c["clauses"]}
    assert by_key["deposito"]["requirement_ids"] == ["MX-CDMX-DEPOSITO-01"]
    assert by_key["forma_contenido"]["requirement_ids"] == ["MX-CDMX-FORMA-01"]
    assert by_key["renta"]["requirement_ids"] == [] and by_key["renta"]["basis"] == "acuerdo_partes"
    basis = {x["id"] for x in c["legal_basis"]}
    assert {i for x in c["clauses"] for i in x["requirement_ids"]} == basis
    omitted = {x["key"]: x["reason"] for x in c["omitted_clauses"]}
    assert omitted["fiscal"] == "sin_requisito_verificado" and omitted["fiador_pacto"] == "sin_fiador"
    assert c["required_roles"] == ["arrendador", "arrendatario"] and set(c["sign_tokens"]) == {"arrendador", "arrendatario"}
    assert c["required_fields"]["deposit_mxn"] == ["MX-CDMX-DEPOSITO-01"]
    assert "DIEZ MIL PESOS 00/100 M.N." in c["text"] and "ANEXO. FUNDAMENTO LEGAL" in c["text"]
    assert c["status"]["overall"] == "pendiente" and len(c["contract_id"]) == 32
    assert "ana@example.com" not in json.dumps(c) and c["parties"]["arrendador"]["email_masked"] == "a***@example.com"
    stored = client.store.get("contracts", c["contract_id"], fresh=True)
    assert all(len(h) == 64 for h in stored["token_sha256"].values())
    assert c["sign_tokens"]["arrendador"] not in json.dumps(stored)
    got = client.get(f"/mx/contracts/{c['contract_id']}").json()
    assert "sign_tokens" not in got and got["sha256"] == c["sha256"]


def test_verified_check_blocks_contract(client):
    r = client.post("/mx/contracts", json=contract_body(deposit_mxn=30000))
    assert r.status_code == 422
    d = r.json()["detail"][0]
    assert d["type"] == "legal_check" and d["requirement_ids"] == ["MX-CDMX-DEPOSITO-01"] and d["quote"]


def test_solo_federal_requires_ack_and_has_no_state_clauses(client):
    body = contract_body(cve_ent="31", cve_mun="050")
    assert client.post("/mx/contracts", json=body).status_code == 422
    c = client.post("/mx/contracts", json={**body, "acknowledge_solo_federal": True}).json()
    assert c["coverage"] == "solo_federal" and "No contamos con el código civil verificado" in c["text"]
    keys = {x["key"] for x in c["clauses"]}
    assert keys == {"partes_objeto", "renta", "plazo", "deposito_monto", "consentimiento_electronico", "datos_personales"}
    assert all(x["jurisdiction"] == "FED" for x in c["legal_basis"])


def test_contract_form_endpoint(client):
    f = client.get("/mx/contract-form", params={"cve_ent": "09", "fiador": "true"}).json()
    assert f["roles"]["fiador"] == "requerido" and f["requires_acknowledgement"] is False
    assert "fiador.full_name" in f["required_fields"]
    assert client.get("/mx/contract-form", params={"cve_ent": "31"}).json()["requires_acknowledgement"] is True


def test_injection_is_plain_text(client):
    body = contract_body(arrendatario={"full_name": "<script>alert(1)</script>", "email": "x@example.com"})
    c = client.post("/mx/contracts", json=body).json()
    assert "<script>alert(1)</script>" in c["text"]
    bad = contract_body(arrendatario={"full_name": "Luis\nDÉCIMA. Renuncio", "email": "x@example.com"})
    assert client.post("/mx/contracts", json=bad).status_code == 422


@pytest.mark.parametrize("change", [{"cve_mun": "999"}, {"listing_id": "f" * 32}, {"term_months": 0},
                                    {"payment_day": 31}, {"monthly_rent_mxn": -1}])
def test_contract_validation_422(client, change):
    assert client.post("/mx/contracts", json=contract_body(**change)).status_code == 422


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #


def _sign(client, c, role, **kw):
    party = {"arrendador": ("Ana Pérez", "ana@example.com"), "arrendatario": ("Luis Gómez", "luis@example.com"),
             "fiador": ("Eva Ruiz", "eva@example.com")}[role]
    body = {"role": role, "full_name": party[0], "email": party[1], "consent": True, "contract_sha256": c["sha256"],
            "token": c["sign_tokens"].get(role, "t" * 20), "signature_png_base64": base64.b64encode(png()).decode()}
    body.update(kw)
    body = {k: v for k, v in body.items() if v is not None}
    return client.post(f"/mx/contracts/{c['contract_id']}/sign", json=body, headers={"User-Agent": "pytest-UA"})


def test_full_signature_flow(client):
    c = client.post("/mx/contracts", json=contract_body()).json()
    assert _sign(client, c, "arrendador", token="x" * 32).status_code == 403
    assert _sign(client, c, "arrendador", consent=False).status_code == 422
    assert _sign(client, c, "arrendador", contract_sha256="0" * 64).status_code == 409
    assert _sign(client, c, "arrendador", full_name="Otra Persona").status_code == 422
    r = _sign(client, c, "arrendador")
    assert r.status_code == 200 and r.json()["status"]["overall"] == "parcial"
    ev = r.json()["evidence"]
    assert ev["signed_at"] == "2026-10-05T12:00:00Z" and ev["user_agent"] == "pytest-UA" and ev["prev_evidence_sha256"] is None
    assert "ana@example.com" not in json.dumps(ev) and len(ev["ip_hash"]) == 64
    assert _sign(client, c, "arrendador").status_code == 409
    r = _sign(client, c, "arrendatario", signature_png_base64=None, typed_signature="Luis Gómez", full_name="luis gomez")
    assert r.status_code == 200 and r.json()["status"]["overall"] == "firmado"
    e = client.get(f"/mx/contracts/{c['contract_id']}/evidence").json()
    assert "no es constancia de conservación NOM-151" in e["title"]
    assert [s["status"] for s in e["signatures"]] == ["valida", "valida"]
    assert e["signatures"][1]["signature_kind"] == "tecleada"
    assert e["signatures"][1]["prev_evidence_sha256"] == e["signatures"][0]["evidence_sha256"]


def test_tampered_text_invalidates_signatures(client, mx_env):
    c = client.post("/mx/contracts", json=contract_body()).json()
    _sign(client, c, "arrendador")
    p = mx_env.store / "contracts" / f"{c['contract_id']}.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["contract"]["text"] = rec["contract"]["text"].replace("DIEZ MIL", "VEINTE MIL")
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    got = client.get(f"/mx/contracts/{c['contract_id']}").json()
    assert got["status"]["overall"] == "invalidado" and got["status"]["text_changed"] is True
    assert got["signatures"][0]["status"] == "invalida" and got["sha256"] != c["sha256"]
    # signing the old fingerprint is refused
    assert _sign(client, c, "arrendatario").status_code == 409


def test_deleting_an_evidence_breaks_the_chain(client, mx_env):
    c = client.post("/mx/contracts", json=contract_body(fiador={"full_name": "Eva Ruiz", "email": "eva@example.com"})).json()
    _sign(client, c, "arrendador")
    _sign(client, c, "arrendatario")
    p = mx_env.store / "contracts" / f"{c['contract_id']}.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    del rec["signatures"][0]
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    st = client.get(f"/mx/contracts/{c['contract_id']}").json()["status"]
    assert st["chain_ok"] is False and st["overall"] == "invalidado"


@pytest.mark.parametrize("sig", [base64.b64encode(png(pad=160 * 1024)).decode(),  # > 150 KB
                                 base64.b64encode(b"GIF89a" + b"\x00" * 40).decode(),  # not a PNG
                                 "%%%no-base64%%%",
                                 base64.b64encode(png(w=5000)).decode()],  # too wide
                         ids=["too_big", "not_png", "bad_base64", "too_wide"])
def test_bad_signature_images_422(client, sig):
    c = client.post("/mx/contracts", json=contract_body()).json()
    assert _sign(client, c, "arrendador", signature_png_base64=sig).status_code in (413, 422)


def test_both_or_no_signature_422(client):
    c = client.post("/mx/contracts", json=contract_body()).json()
    assert _sign(client, c, "arrendador", typed_signature="Ana Pérez").status_code == 422
    assert _sign(client, c, "arrendador", signature_png_base64=None).status_code == 422
    assert _sign(client, c, "fiador", token="t" * 20).status_code == 422  # no fiador in this contract


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


def test_store_atomic_and_thread_safe(tmp_path):
    s = JsonStore(tmp_path)
    ids = [f"{i:032x}" for i in range(20)]
    ts = [threading.Thread(target=s.put, args=("listings", i, {"id": i, "n": "x" * 1000})) for i in ids]
    [t.start() for t in ts]
    [t.join() for t in ts]
    files = list((tmp_path / "listings").iterdir())
    assert len(files) == 20 and not [f for f in files if f.suffix == ".tmp" or f.name.startswith(".")]
    assert all(json.loads(f.read_text(encoding="utf-8"))["n"] for f in files)
    assert JsonStore(tmp_path).count("listings") == 20


def test_store_cap_gives_507(mx_env):
    from api.main import app
    from mx_support import LISTING

    c = make_client(mx_env, store=JsonStore(mx_env.store, caps={"listings": 1, "contracts": 1}))
    try:
        assert c.post("/mx/listings", json=LISTING).status_code == 201
        assert c.post("/mx/listings", json=LISTING).status_code == 507
    finally:
        app.dependency_overrides.clear()
    with pytest.raises(StoreFull):
        JsonStore(mx_env.store, caps={"listings": 1}).put("listings", "b" * 32, {})
