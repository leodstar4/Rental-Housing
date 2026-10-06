"""Simple electronic signature evidence (firma electrónica simple). Not an advanced signature,
not a NOM-151 conservation record, not a trusted timestamp: the time is the server clock and
identity is not verified (the token only proves possession of the link)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
from datetime import datetime

from .contracts import contract_hash
from .zones import fold

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_MAX_BYTES = 150 * 1024
PNG_MAX_W, PNG_MAX_H = 1200, 600
_PROCESS_SALT = secrets.token_hex(16)
EVIDENCE_TITLE = {
    "es": "Constancia de evidencia de firma electrónica simple (no es constancia de conservación NOM-151)",
    "en": "Simple electronic signature evidence record (not a NOM-151 conservation record)",
}
EVIDENCE_NOTES = {
    "es": ["La identidad de los firmantes no fue verificada: el correo no se confirmó y el enlace de firma solo "
           "prueba que se tuvo acceso a él.",
           "La fecha y hora provienen del reloj del servidor; no es un sello de tiempo emitido por un tercero.",
           "La demo no emite firma electrónica avanzada ni constancias de un Prestador de Servicios de Certificación.",
           "Una firma es válida solo si la huella SHA-256 que firmó coincide con la huella actual del texto."],
    "en": ["Signer identity was not verified: the e-mail was not confirmed and the signing link only proves access "
           "to it.",
           "Date and time come from the server clock; this is not a third-party timestamp.",
           "The demo does not issue advanced electronic signatures or records from a certification provider.",
           "A signature is valid only if the SHA-256 it signed matches the current fingerprint of the text."],
}


class SignatureError(ValueError):
    pass


def validate_png(b64: str) -> bytes:
    try:
        png = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError("signature_png_base64 no es base64 válido") from None
    if len(png) > PNG_MAX_BYTES:
        raise SignatureError(f"la imagen de firma supera {PNG_MAX_BYTES // 1024} KB")
    if not png.startswith(PNG_MAGIC) or png[12:16] != b"IHDR" or len(png) < 24:
        raise SignatureError("la firma debe ser una imagen PNG")
    w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    if not (0 < w <= PNG_MAX_W and 0 < h <= PNG_MAX_H):
        raise SignatureError(f"la imagen de firma debe medir como máximo {PNG_MAX_W}x{PNG_MAX_H} px")
    return png


def sha256_hex(b: bytes | str) -> str:
    return hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b).hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def mask_email(email: str) -> str:
    user, _, domain = email.partition("@")
    return f"{user[:1]}***@{domain}"


def ip_hash(ip: str | None) -> str:
    return sha256_hex((ip or "") + os.getenv("MX_IP_SALT", _PROCESS_SALT))


def consent_text(contract_id: str, sha: str, role: str) -> str:
    return (f"Declaro que leí el contrato {contract_id} cuya huella SHA-256 es {sha} y consiento firmarlo como "
            f"{role} mediante firma electrónica simple en esta plataforma.")


def same_name(a: str, b: str) -> bool:
    return " ".join(fold(a).split()) == " ".join(fold(b).split())


def _evidence_hash(ev: dict) -> str:
    return sha256_hex(canonical_json({k: v for k, v in ev.items() if k != "evidence_sha256"}))


def make_evidence(record: dict, *, role: str, full_name: str, email: str, signature: bytes, kind: str,
                  user_agent: str | None, ip: str | None, now: datetime) -> dict:
    c = record["contract"]
    sha = contract_hash(c["text"])
    prev = record["signatures"][-1]["evidence"]["evidence_sha256"] if record["signatures"] else None
    consent = consent_text(c["contract_id"], sha, role)
    ev = {"role": role, "full_name": full_name, "email_sha256": sha256_hex(email.strip().lower()),
          "email_masked": mask_email(email), "contract_id": c["contract_id"], "contract_sha256": sha,
          "signature_sha256": sha256_hex(signature), "signature_kind": kind,
          "signed_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
          "user_agent": (user_agent or "")[:300], "ip_hash": ip_hash(ip), "consent": True,
          "consent_text": consent, "consent_text_sha256": sha256_hex(consent), "prev_evidence_sha256": prev}
    ev["evidence_sha256"] = _evidence_hash(ev)
    return ev


def signature_status(record: dict) -> dict:
    """Recomputes the text hash and the evidence chain on every read."""
    c = record["contract"]
    current = contract_hash(c["text"])
    prev, chain_ok, per = None, True, []
    for s in record["signatures"]:
        ev = s["evidence"]
        intact = _evidence_hash(ev) == ev.get("evidence_sha256") and ev.get("prev_evidence_sha256") == prev
        chain_ok = chain_ok and intact
        prev = ev.get("evidence_sha256")
        per.append("valida" if chain_ok and ev.get("contract_sha256") == current else "invalida")
    roles = {}
    for r in c["required_roles"]:
        mine = [st for s, st in zip(record["signatures"], per) if s["evidence"].get("role") == r]
        roles[r] = "valida" if "valida" in mine else "invalida" if mine else "pendiente"
    valid = sum(v == "valida" for v in roles.values())
    if "invalida" in per or not chain_ok:
        overall = "invalidado"
    elif valid == len(roles):
        overall = "firmado"
    elif valid:
        overall = "parcial"
    else:
        overall = "pendiente"
    return {"overall": overall, "roles": roles, "per_signature": per, "chain_ok": chain_ok,
            "valid_count": valid, "required_count": len(roles), "sha256_current": current,
            "sha256_at_creation": c["sha256"], "text_changed": current != c["sha256"]}
