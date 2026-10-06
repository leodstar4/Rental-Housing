"""Deterministic contract generation (templates + data; no LLM). docs/MX_ARCHITECTURE.md §4-§5.

Clause templates (data/mx/contract_clauses.yaml) never carry legal facts: no amounts, terms,
percentages or article numbers (``load_clauses`` rejects digits). Every legal statement in the
contract comes from verified requirement quotes, printed in the "Fundamento legal" annex.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from string import Template
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Category, ContractCreate
from .requirements import LAW_KINDS, SOLO_FEDERAL_NOTICE
from .sources import public_doc
from .verify import VerifiedRequirement

TEMPLATE_VERSION = "mx-contract-1"
TEMPLATE_VARS = {"arrendador_nombre", "arrendatario_nombre", "fiador_nombre", "domicilio", "municipio", "estado",
                 "renta", "renta_letra", "deposito", "deposito_letra", "fecha_inicio", "plazo_meses", "dia_pago"}
FIELDS = {"arrendador.full_name", "arrendatario.full_name", "fiador.full_name", "inmueble.calle", "inmueble.num_ext",
          "inmueble.colonia", "inmueble.cp", "monthly_rent_mxn", "deposit_mxn", "start_date", "term_months",
          "payment_day"}
ORDINALS = ["PRIMERA", "SEGUNDA", "TERCERA", "CUARTA", "QUINTA", "SEXTA", "SÉPTIMA", "OCTAVA", "NOVENA", "DÉCIMA",
            "DÉCIMA PRIMERA", "DÉCIMA SEGUNDA", "DÉCIMA TERCERA", "DÉCIMA CUARTA", "DÉCIMA QUINTA", "DÉCIMA SEXTA",
            "DÉCIMA SÉPTIMA", "DÉCIMA OCTAVA", "DÉCIMA NOVENA", "VIGÉSIMA"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
PACT_LABEL = "Pacto entre las partes (sin fundamento legal citado)."
DISCLAIMER_LINE = ("Documento generado por un prototipo (Renta MX). No es asesoría legal: revise las citas del "
                   "anexo y consulte a un profesional antes de firmar.")
SIGNATURE_LINE = ("Las partes firman con firma electrónica simple registrada por la plataforma Renta MX (nombre, "
                  "trazo o nombre tecleado, consentimiento explícito y huella SHA-256 de este texto). La constancia "
                  "de firma se emite por separado.")

# Spanish number words (units, tens, hundreds, scales) used to catch a legal figure written out in
# letters inside a clause template. "un"/"una" are intentionally excluded (too common as articles).
_NUMBER_WORDS = (
    "dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis dieciseis "
    "diecisiete dieciocho diecinueve veinte veintiún veintiuno veintidós veintidos veintitrés veintitres "
    "veinticuatro treinta cuarenta cincuenta sesenta setenta ochenta noventa cien ciento doscientos "
    "trescientos cuatrocientos quinientos seiscientos setecientos ochocientos novecientos mil millón millones"
).split()
_NUMBER_WORD_RE = re.compile(r"(?<!\w)(?:" + "|".join(_NUMBER_WORDS) + r")(?!\w)", re.I)


class ClauseTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z_]+$")
    title_es: str
    title_en: str
    basis: Literal["ley", "acuerdo_partes"]
    scope: Literal["federal", "estatal", "cualquiera"] = "cualquiera"
    categories: list[Category] = []
    requirement_ids: list[str] = []
    template_es: str
    required_fields: list[str] = []
    requires_party: Literal["fiador"] | None = None
    omit_if_zero: Literal["deposit_mxn"] | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.basis == "acuerdo_partes" and (self.categories or self.requirement_ids):
            raise ValueError(f"{self.key}: una cláusula acuerdo_partes no lleva fundamento")
        if self.basis == "ley" and not (self.categories or self.requirement_ids):
            raise ValueError(f"{self.key}: una cláusula ley necesita categories o requirement_ids")
        text = self.template_es + self.title_es + self.title_en
        stripped = re.sub(r"\$\{?\w+\}?", "", text)
        if re.search(r"\d", stripped) or re.search(r"\bart[íi]?c?u?l?o?\.", text, re.I):
            raise ValueError(f"{self.key}: las plantillas no pueden contener números ni artículos legales")
        # A legal cap or article number can also be written in words ("dos meses", "diez por ciento",
        # "artículo dos mil cuatrocientos..."). Reject spelled-out numbers, "por ciento" and the word
        # "artículo"/"artículos": every legal fact must live in a verified quote in the Annex, never
        # in a template.
        if _NUMBER_WORD_RE.search(stripped) or re.search(r"\bart[íi]culos?\b", text, re.I) \
                or re.search(r"\bpor\s+ciento\b", text, re.I):
            raise ValueError(f"{self.key}: las plantillas no pueden contener hechos legales en letra "
                             "(números, porcentajes o artículos escritos con palabras)")
        ids = Template(self.template_es).get_identifiers()
        if not set(ids) <= TEMPLATE_VARS:
            raise ValueError(f"{self.key}: variables desconocidas {sorted(set(ids) - TEMPLATE_VARS)}")
        if not set(self.required_fields) <= FIELDS:
            raise ValueError(f"{self.key}: required_fields desconocidos {sorted(set(self.required_fields) - FIELDS)}")
        return self


def load_clauses(path: Path) -> list[ClauseTemplate]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    clauses = [ClauseTemplate(**c) for c in data]
    keys = [c.key for c in clauses]
    if len(keys) != len(set(keys)):
        raise ValueError("claves de cláusula duplicadas")
    return clauses


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

_U = ["", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece",
      "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiún", "veintidós",
      "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_T = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_H = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
      "ochocientos", "novecientos"]


def _below_1000(n: int) -> str:
    if n == 100:
        return "cien"
    h, r = divmod(n, 100)
    parts = [_H[h]] if h else []
    if r < 30:
        parts.append(_U[r])
    else:
        t, u = divmod(r, 10)
        parts.append(_T[t] + (f" y {_U[u]}" if u else ""))
    return " ".join(p for p in parts if p)


def number_to_words(n: int) -> str:
    """Spanish cardinal with apocope ("veintiún", "un millón"), as used before "pesos"."""
    if n == 0:
        return "cero"
    if not 0 < n < 1_000_000_000:
        raise ValueError("fuera de rango")
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append("un millón" if millions == 1 else f"{_below_1000(millions)} millones")
    if thousands:
        parts.append("mil" if thousands == 1 else f"{_below_1000(thousands)} mil")
    if units:
        parts.append(_below_1000(units))
    return " ".join(parts)


def money(x: Decimal) -> str:
    return f"${x.quantize(Decimal('0.01'), ROUND_HALF_UP):,.2f} MXN"


def money_words(x: Decimal) -> str:
    q = x.quantize(Decimal("0.01"), ROUND_HALF_UP)
    pesos, cents = int(q), int((q - int(q)) * 100)
    w = number_to_words(pesos)
    de = " de" if pesos >= 1_000_000 and pesos % 1_000_000 == 0 else ""
    return f"{w}{de} pesos {cents:02d}/100 M.N.".upper()


def date_es(d: date) -> str:
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def canonicalize(text: str) -> str:
    """NFC, LF line ends, no trailing spaces, at most 2 consecutive blank lines, one final LF."""
    t = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in t.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        blank = blank + 1 if ln == "" else 0
        if blank <= 2:
            out.append(ln)
    return "\n".join(out).strip("\n") + "\n"


def contract_hash(text: str) -> str:
    return hashlib.sha256(canonicalize(text).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Clause planning
# --------------------------------------------------------------------------- #


@dataclass
class Plan:
    coverage: str
    included: list[tuple[ClauseTemplate, list[VerifiedRequirement]]] = field(default_factory=list)
    omitted: list[dict] = field(default_factory=list)

    def required_fields(self) -> dict[str, list[str]]:
        """field -> requirement ids that make it legally required ([] = required by the template only)."""
        out: dict[str, list[str]] = {}
        for c, reqs in self.included:
            for f in c.required_fields:
                out.setdefault(f, [])
                out[f] += [v.req.id for v in reqs if v.req.id not in out[f]]
        return out


def _effective(c: ClauseTemplate, abbr: str | None, coverage: str,
               verified: dict[str, VerifiedRequirement]) -> list[VerifiedRequirement]:
    juris = {"federal": {"FED"}, "estatal": {abbr} if coverage == "estatal_verificada" else set(),
             "cualquiera": {"FED", abbr} if coverage == "estatal_verificada" else {"FED"}}[c.scope]
    out = [v for v in verified.values()
           if v.req.jurisdiction in juris and v.req.applies_to_contract and v.req.kind in LAW_KINDS
           and (v.req.category in c.categories or v.req.id in c.requirement_ids)]
    return sorted(out, key=lambda v: (v.req.jurisdiction == "FED", v.req.id))


def plan_clauses(clauses: list[ClauseTemplate], abbr: str | None, coverage: str,
                 verified: dict[str, VerifiedRequirement], *, has_fiador: bool, deposit_zero: bool) -> Plan:
    plan = Plan(coverage)
    for c in clauses:
        title = {"es": c.title_es, "en": c.title_en}
        if c.requires_party == "fiador" and not has_fiador:
            plan.omitted.append({"key": c.key, "title": title, "reason": "sin_fiador"})
            continue
        if c.omit_if_zero == "deposit_mxn" and deposit_zero:
            plan.omitted.append({"key": c.key, "title": title, "reason": "sin_deposito_pactado"})
            continue
        if c.basis == "acuerdo_partes":
            plan.included.append((c, []))
            continue
        if c.scope == "estatal" and coverage != "estatal_verificada":
            plan.omitted.append({"key": c.key, "title": title, "reason": "entidad_solo_federal"})
            continue
        reqs = _effective(c, abbr, coverage, verified)
        if not reqs:
            plan.omitted.append({"key": c.key, "title": title, "reason": "sin_requisito_verificado"})
            continue
        plan.included.append((c, reqs))
    return plan


# --------------------------------------------------------------------------- #
# Validation against data and verified checks
# --------------------------------------------------------------------------- #


def _get(obj, dotted: str):
    for part in dotted.split("."):
        obj = getattr(obj, part, None) if obj is not None else None
    return obj


def missing_fields(req: ContractCreate, plan: Plan) -> list[dict]:
    return [{"field": f, "requirement_ids": ids} for f, ids in plan.required_fields().items()
            if _get(req, f) in (None, "")]


_OPS = {"le": lambda a, b: a <= b, "lt": lambda a, b: a < b, "ge": lambda a, b: a >= b, "gt": lambda a, b: a > b,
        "eq": lambda a, b: a == b}


def check_violations(req: ContractCreate, plan: Plan) -> list[dict]:
    """Bounds from the ``checks`` of verified requirements used by the included clauses."""
    values = {"deposit_months": req.deposit_mxn / req.monthly_rent_mxn, "term_months": Decimal(req.term_months),
              "payment_day": Decimal(req.payment_day), "monthly_rent_mxn": req.monthly_rent_mxn,
              "deposit_mxn": req.deposit_mxn}
    out, seen = [], set()
    for _, reqs in plan.included:
        for v in reqs:
            for c in v.req.checks:
                k = (v.req.id, c.field, c.op, c.value)
                if k in seen or _OPS[c.op](values[c.field], c.value):
                    continue
                seen.add(k)
                out.append({"field": c.field, "op": c.op, "value": str(c.value), "requirement_id": v.req.id,
                            "citation": v.req.citation, "quote": v.quote_verified})
    return out


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def _vars(req: ContractCreate, estado: str, municipio: str) -> dict[str, str]:
    i = req.inmueble
    dom = f"{i.calle} {i.num_ext}" + (f" Int. {i.num_int}" if i.num_int else "") + \
        f", Col. {i.colonia}, C.P. {i.cp}, {municipio}, {estado}"
    return {"arrendador_nombre": req.arrendador.full_name, "arrendatario_nombre": req.arrendatario.full_name,
            "fiador_nombre": req.fiador.full_name if req.fiador else "", "domicilio": dom, "municipio": municipio,
            "estado": estado, "renta": money(req.monthly_rent_mxn), "renta_letra": money_words(req.monthly_rent_mxn),
            "deposito": money(req.deposit_mxn), "deposito_letra": money_words(req.deposit_mxn),
            "fecha_inicio": date_es(req.start_date), "plazo_meses": str(req.term_months),
            "dia_pago": str(req.payment_day)}


def build_contract(req: ContractCreate, plan: Plan, *, estado: str, municipio: str, now: datetime,
                   contract_id: str, supersedes: str | None = None) -> dict:
    """Pure: same input + same clock + same id => same text and sha256."""
    v = _vars(req, estado, municipio)
    clauses, used = [], {}
    for n, (c, reqs) in enumerate(plan.included, start=1):
        clauses.append({"n": n, "ordinal": ORDINALS[n - 1] if n <= len(ORDINALS) else str(n), "key": c.key,
                        "title": c.title_es, "title_en": c.title_en, "basis": c.basis,
                        "text": Template(c.template_es).substitute(v).strip(),
                        "requirement_ids": [x.req.id for x in reqs]})
        for x in reqs:
            used.setdefault(x.req.id, x)
    lines = ["CONTRATO DE ARRENDAMIENTO DE CASA HABITACIÓN", "",
             f"Folio: {contract_id}", f"Plantilla: {TEMPLATE_VERSION}",
             f"Fecha de generación (UTC): {now.date().isoformat()}",
             f"Ubicación del inmueble: {municipio}, {estado}", "", DISCLAIMER_LINE, ""]
    if plan.coverage == "solo_federal":
        lines += ["AVISO: " + SOLO_FEDERAL_NOTICE["es"], ""]
    lines += ["CLÁUSULAS", ""]
    for c in clauses:
        basis = ("Fundamento: " + ", ".join(c["requirement_ids"]) + " (ver Anexo).") if c["requirement_ids"] \
            else PACT_LABEL
        lines += [f"{c['ordinal']}. {c['title'].upper()}", c["text"], basis, ""]
    lines += ["ANEXO. FUNDAMENTO LEGAL", ""]
    if not used:
        lines += ["Ninguna cláusula de este contrato cita fundamento legal verificado.", ""]
    for rid, x in used.items():
        d = public_doc(x.doc)
        lines += [f"[{rid}] {x.req.citation}", f"“{x.quote_verified}”",
                  f"Fuente: {d['title']} ({d['publisher']}). {d['url']} Consultado: {d['retrieved_at'][:10]}."
                  + (f" Última reforma: {d['last_reform']}." if d["last_reform"] else ""), ""]
    lines += ["FIRMAS", SIGNATURE_LINE, "", f"ARRENDADOR: {req.arrendador.full_name}",
              f"ARRENDATARIO: {req.arrendatario.full_name}"]
    if req.fiador:
        lines.append(f"FIADOR: {req.fiador.full_name}")
    text = canonicalize("\n".join(lines))
    from .requirements import item  # local: avoid a cycle at import time

    return {"contract_id": contract_id, "template_version": TEMPLATE_VERSION,
            "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "cve_ent": req.cve_ent, "cve_mun": req.cve_mun, "estado": estado, "municipio": municipio,
            "listing_id": req.listing_id, "coverage": plan.coverage,
            "notice": SOLO_FEDERAL_NOTICE["es"] if plan.coverage == "solo_federal" else None,
            "text": text, "text_lang": "es", "sha256": contract_hash(text), "clauses": clauses,
            "omitted_clauses": plan.omitted,
            "legal_basis": [item(x, "es") for x in used.values()],
            "required_fields": plan.required_fields(),
            "required_roles": ["arrendador", "arrendatario"] + (["fiador"] if req.fiador else []),
            "supersedes": supersedes}
