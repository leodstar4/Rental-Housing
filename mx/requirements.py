"""Requirements view for an entity: FED + state, verified only, grouped by category."""

from __future__ import annotations

from .models import CATEGORIES
from .sources import public_doc
from .verify import VerifiedRequirement

LAW_KINDS = ("ley", "reglamento", "norma")
SOLO_FEDERAL_NOTICE = {
    "es": "No contamos con el código civil verificado de esta entidad. El arrendamiento se rige por la legislación "
          "civil local; este documento puede no cumplirla. Revíselo con un profesional.",
    "en": "We do not have a verified civil code for this state. Residential leases are governed by local civil law; "
          "this document may not comply with it. Have it reviewed by a professional.",
}
SUMMARY_CAVEAT = {"es": "Resumen no oficial; la cita literal es la fuente.",
                  "en": "Unofficial summary; the literal quote is the source."}


def coverage(abbr: str | None, verified: dict[str, VerifiedRequirement]) -> str:
    """estatal_verificada iff the entity has >= 1 verified legal (non-practice) requirement."""
    if abbr and any(v.req.jurisdiction == abbr and v.req.kind in LAW_KINDS for v in verified.values()):
        return "estatal_verificada"
    return "solo_federal"


def item(v: VerifiedRequirement, lang: str) -> dict:
    r, d = v.req, public_doc(v.doc)
    return {"id": r.id, "level": "federal" if r.jurisdiction == "FED" else "estatal", "jurisdiction": r.jurisdiction,
            "category": r.category, "kind": r.kind, "is_law": r.kind in LAW_KINDS,
            "title": r.title_es if lang == "es" else r.title_en,
            "summary": r.summary_es if lang == "es" else r.summary_en,
            "summary_caveat": SUMMARY_CAVEAT[lang], "citation": r.citation, "quote": v.quote_verified,
            "quote_lang": "es", "match_type": v.match_type, "applies_to_contract": r.applies_to_contract,
            "checks": [c.model_dump(mode="json") for c in r.checks], "reviewed_by": r.reviewed_by,
            "doc_id": d["doc_id"], "doc_title": d["title"], "publisher": d["publisher"], "url": d["url"],
            "retrieved_at": d["retrieved_at"], "last_reform": d["last_reform"]}


def for_entity(abbr: str | None, verified: dict[str, VerifiedRequirement]) -> list[VerifiedRequirement]:
    """Verified FED requirements + those of the entity (state first)."""
    own = [v for v in verified.values() if abbr and v.req.jurisdiction == abbr]
    fed = [v for v in verified.values() if v.req.jurisdiction == "FED"]
    return own + fed


def view(abbr: str | None, verified: dict[str, VerifiedRequirement], lang: str) -> dict:
    cov = coverage(abbr, verified)
    items = [item(v, lang) for v in for_entity(abbr, verified)]
    cats = {c: [x for x in items if x["category"] == c] for c in CATEGORIES}
    return {"legal_coverage": cov, "notice": SOLO_FEDERAL_NOTICE[lang] if cov == "solo_federal" else None,
            "count": len(items),
            "counts": {"estatal": sum(x["level"] == "estatal" for x in items),
                       "federal": sum(x["level"] == "federal" for x in items),
                       "practica": sum(x["kind"] == "practica" for x in items)},
            "category_counts": {c: len(v) for c, v in cats.items() if v},
            "categories": {c: v for c, v in cats.items() if v}}
