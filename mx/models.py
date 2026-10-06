"""Pydantic models for Renta MX (docs/MX_ARCHITECTURE.md §3)."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, model_validator

CATEGORIES = ("contrato_forma", "deposito", "incremento_renta", "duracion", "obligaciones_arrendador",
              "obligaciones_arrendatario", "garantias_fiador", "terminacion", "registro", "firma_electronica",
              "datos_personales", "fiscal", "habitabilidad", "otro")
Category = Literal["contrato_forma", "deposito", "incremento_renta", "duracion", "obligaciones_arrendador",
                   "obligaciones_arrendatario", "garantias_fiador", "terminacion", "registro", "firma_electronica",
                   "datos_personales", "fiscal", "habitabilidad", "otro"]
Kind = Literal["ley", "reglamento", "norma", "practica"]
Role = Literal["arrendador", "arrendatario", "fiador"]

DOC_ID_RE = re.compile(r"^D-MX-(FED|INEGI|[A-Z]{2,4})-\d{2}$")
REQ_ID_RE = re.compile(r"^MX-(FED|[A-Z]{2,4})-[A-Z][A-Z_-]*-\d{2}$")
# ASCII C0 controls + DEL, plus Unicode line/paragraph separators and C1 controls that
# str.splitlines() and text renderers treat as line breaks (U+0085 NEL, U+2028 LS, U+2029 PS).
# Without these a party name could inject a visible fake clause into the signed contract text.
_UNICODE_BREAKS = "\x85\u2028\u2029"
_CONTROL = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")
_CONTROL_BUT_NL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f\x85\u2028\u2029]")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


def _one_line(v: str) -> str:
    """Single-line free text: no CR/LF or control characters (no clause injection)."""
    if _CONTROL.search(v):
        raise ValueError("no se permiten saltos de línea ni caracteres de control")
    return v


def _multi_line(v: str) -> str:
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    if _CONTROL_BUT_NL.search(v):
        raise ValueError("no se permiten caracteres de control")
    return v


def _email(v: str) -> str:
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("correo electrónico inválido")
    return v


def Line(max_len: int, min_len: int = 1):  # noqa: N802 - type factory
    return Annotated[str, Field(min_length=min_len, max_length=max_len), AfterValidator(_one_line)]


Email = Annotated[str, Field(max_length=254), AfterValidator(_email)]
Money = Annotated[Decimal, Field(gt=0, le=10_000_000, decimal_places=2)]
MoneyOrZero = Annotated[Decimal, Field(ge=0, le=10_000_000, decimal_places=2)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Sources and requirements (data files written by the research agents)
# --------------------------------------------------------------------------- #


class DerivedFile(BaseModel):
    model_config = ConfigDict(extra="allow")
    file_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceDoc(BaseModel):
    """Manifest entry. Extra metadata fields written by the research agents are kept, not rejected."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)
    doc_id: str
    title: str
    publisher: str
    jurisdiction: str
    url: HttpUrl
    retrieved_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    file_path: str
    text_path: str | None = None     # None for data files (INEGI): they cannot back a quote
    file_in_repo: bool = True        # False: large raw file not versioned (hash checked only if present)
    derived_files: list[DerivedFile] = []
    last_reform: str | None = None   # as printed by the publisher (e.g. "DOF 14-11-2025"); never guessed
    text_extractor: str | None = None


class Check(_Strict):
    """Optional machine-readable bound; ``value`` must appear literally in the quote (mx.verify)."""

    field: Literal["deposit_months", "term_months", "payment_day", "monthly_rent_mxn", "deposit_mxn"]
    op: Literal["le", "lt", "ge", "gt", "eq"]
    value: Decimal


class Requirement(_Strict):
    id: str
    jurisdiction: str
    category: Category
    kind: Kind
    title_es: str
    title_en: str
    summary_es: str
    summary_en: str
    doc_id: str
    citation: str
    quote: str
    applies_to_contract: bool
    reviewed_by: str | None = None
    checks: list[Check] = []


# --------------------------------------------------------------------------- #
# Listings
# --------------------------------------------------------------------------- #


class ListingCreate(_Strict):
    cve_ent: str = Field(pattern=r"^\d{2}$")
    cve_mun: str = Field(pattern=r"^\d{3}$")
    cp: str = Field(pattern=r"^\d{5}$")
    colonia: Line(120)
    title: Line(120)
    description: Annotated[str, Field(max_length=2000), AfterValidator(_multi_line)] = ""
    monthly_rent_mxn: Money
    deposit_mxn: MoneyOrZero | None = None
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: Decimal = Field(ge=0, le=20, multiple_of=Decimal("0.5"))
    area_m2: Decimal | None = Field(None, gt=0, le=100_000, decimal_places=2)
    furnished: bool = False
    pets_allowed: bool | None = None
    available_from: date
    contact_name: Line(120)
    contact_email: Email
    truthfulness_consent: Literal[True]
    privacy_consent: Literal[True]


class ListingPublic(BaseModel):
    """What GET returns: never the contact e-mail nor the consents."""

    id: str
    created_at: datetime
    cve_ent: str
    cve_mun: str
    cp: str
    colonia: str
    title: str
    description: str
    monthly_rent_mxn: Decimal
    deposit_mxn: Decimal | None
    bedrooms: int
    bathrooms: Decimal
    area_m2: Decimal | None
    furnished: bool
    pets_allowed: bool | None
    available_from: date
    contact_name: str
    published_by: Literal["usuario"] = "usuario"
    verified_owner: Literal[False] = False


# --------------------------------------------------------------------------- #
# Contracts and signatures
# --------------------------------------------------------------------------- #


class Party(_Strict):
    full_name: Line(120, 3)
    email: Email
    rol: Role | None = None


class Inmueble(_Strict):
    calle: Line(120)
    num_ext: Line(20)
    num_int: Line(20) | None = None
    colonia: Line(120)
    cp: str = Field(pattern=r"^\d{5}$")


class ContractCreate(_Strict):
    listing_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    cve_ent: str = Field(pattern=r"^\d{2}$")
    cve_mun: str = Field(pattern=r"^\d{3}$")
    inmueble: Inmueble
    arrendador: Party
    arrendatario: Party
    fiador: Party | None = None
    monthly_rent_mxn: Money
    deposit_mxn: MoneyOrZero = Decimal("0")
    start_date: date
    term_months: int = Field(ge=1, le=120)
    payment_day: int = Field(ge=1, le=28)
    lang: Literal["es", "en"] = "es"
    acknowledge_solo_federal: bool = False


class SignRequest(_Strict):
    role: Role
    full_name: Line(120, 3)
    email: Email
    signature_png_base64: str | None = Field(None, max_length=200_000)
    typed_signature: Line(120) | None = None
    method: Literal["trazo", "tecleada"] | None = None   # "tecleada" when the UI rasterized a typed name to PNG
    consent: Literal[True]
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    token: str = Field(min_length=10, max_length=100)

    @model_validator(mode="after")
    def _one_signature(self):
        if (self.signature_png_base64 is None) == (self.typed_signature is None):
            raise ValueError("envíe exactamente uno: signature_png_base64 o typed_signature")
        return self
