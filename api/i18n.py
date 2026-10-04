"""Deterministic English / Spanish labels and texts for the API (no LLM).

* ``type_label``: change-test type in plain words.
* ``change_title`` / ``change_notes``: Spanish title and notes of a change test built from the
  same structured data as the English notes (``out/changes_full.json``): same numbers, long-form
  dates ("1 de enero de 2026"), glossary terms (data/glossary_es.yaml) and "usted".
* ``missing_label``: readable name of a missing fact.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

TYPE_LABEL = {
    "as_of": ("Change by date", "Cambio por fecha"),
    "boundary": ("City boundary", "Límite de ciudad"),
    "pending": ("Pending bill", "Proyecto de ley pendiente"),
    "negative": ("Did not become law", "No se convirtió en ley"),
    "new_document": ("New document (hour 16)", "Documento nuevo (hora 16)"),
}
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
RESULT_ES = {"applies": "aplica", "unknown": "desconocido", "superseded": "reemplazada",
             "not_yet_effective": "aún no vigente", "pending": "pendiente", "omitted": "no aplica",
             "not_in_stack": "fuera de la jurisdicción"}
CATEGORY_ES = {"rent_increase_limits": "control de rentas", "just_cause_eviction": "desalojo con causa justa",
               "security_deposits": "depósitos de garantía", "application_screening_fees": "cuotas de solicitud",
               "screening_restrictions": "evaluación de inquilinos",
               "algorithmic_rent_setting": "fijación de renta con algoritmos"}
STATE_ES = {"CA": "California", "NJ": "Nueva Jersey", "MA": "Massachusetts"}

MISSING_LABEL = {
    "year_built": ("year built", "año de construcción"),
    "units": ("number of units", "número de unidades"),
    "owner_type": ("type of owner", "tipo de propietario"),
    "owner_occupied": ("whether an owner lives on the property", "si un propietario vive en la propiedad"),
    "certificate": ("certificate of occupancy date", "fecha del certificado de ocupación"),
    "use.affordable": ("affordability restriction", "restricción de asequibilidad"),
    "use.section8": ("Section 8 / HUD subsidy", "subsidio de Sección 8 / HUD"),
    "use.coop": ("cooperative ownership", "propiedad en cooperativa"),
    "use.elderly": ("housing for the elderly", "vivienda para personas mayores"),
    "use.condo": ("condominium ownership", "propiedad en condominio"),
}


def type_label(kind: str | None, lang: str) -> str | None:
    pair = TYPE_LABEL.get(kind or "")
    return pair[lang == "es"] if pair else None


def long_date(d: str | date | None, lang: str) -> str:
    """'2026-01-01' -> 'January 1, 2026' / '1 de enero de 2026'; partial 'YYYY-MM' -> month and year."""
    if d is None:
        return "fecha no indicada" if lang == "es" else "date not stated"
    s = d.isoformat() if isinstance(d, date) else str(d)
    parts = [int(x) for x in s.split("-")]
    if lang == "es":
        if len(parts) == 2:
            return f"{MONTHS_ES[parts[1] - 1]} de {parts[0]}"
        return f"{parts[2]} de {MONTHS_ES[parts[1] - 1]} de {parts[0]}"
    dt = date(parts[0], parts[1], parts[2] if len(parts) > 2 else 1)
    return dt.strftime("%B %Y") if len(parts) == 2 else f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def missing_label(m: str, lang: str) -> str:
    """Readable name of a missing fact; free-text facts from the compiler are kept as written."""
    key = "certificate" if m.startswith("certificate of occupancy") else m
    pair = MISSING_LABEL.get(key)
    if pair:
        return pair[lang == "es"]
    return m if lang == "en" else f"dato no disponible (en inglés): {m}"


def _cities_es(counter: Counter) -> str:
    return ", ".join(f"{c} {n}" for c, n in sorted(counter.items())) or "ninguna"


def rule_label_es(rule: dict) -> str:
    cat = CATEGORY_ES.get(rule["category"], rule["category"])
    jur = rule["jurisdiction"]
    jur = STATE_ES.get(jur, jur)
    return f"{rule['citation']} ({cat}, {jur})" if rule.get("citation") else f"{cat} ({jur})"


def change_title(test: dict, rules: list[dict], lang: str) -> str:
    if lang == "en":
        return test.get("title") or test.get("test_id", "")
    kind = test.get("type")
    labels = "; ".join(rule_label_es(r) for r in rules)
    if kind == "as_of":
        return f"Entrada en vigor: {labels}"
    if kind == "boundary":
        return f"Límite de ciudad: {labels}"
    if kind == "pending":
        return f"Proyectos de ley pendientes: {labels}"
    if kind == "negative":
        return f"No se convirtió en ley: {labels}"
    if kind == "new_document":
        return f"Documento nuevo ({test.get('original_file')}): {labels}"
    return f"{TYPE_LABEL.get(kind, ('', 'Cambio'))[1]}: {labels}"


STATUS_ES = {"in_force": "vigente", "not_yet_effective": "aún no vigente", "pending": "pendiente",
             "failed": "no vigente"}


def change_notes_es(test: dict, entry: dict, rules: list[dict], addresses: dict, city_of: dict[str, str]) -> str:
    """Spanish notes from the same data as the English ones (resolver/changes.notes)."""
    kind = test.get("type")
    ids = ", ".join(r["team_rule_id"] for r in rules)
    affected, flagged = entry["affected_address_ids"], entry["conflict_flag_address_ids"]
    where = _cities_es(Counter(city_of.get(a, "?") for a in affected))
    if kind == "as_of":
        first = rules[0]["team_rule_id"]
        trans = Counter((addresses[a][first]["before"], addresses[a][first]["after"]) for a in affected
                        if a in addresses and first in addresses[a])
        tr = "; ".join(f"{RESULT_ES.get(b, b)} → {RESULT_ES.get(a, a)}: {n}" for (b, a), n in trans.items())
        s = (f"{ids} cambia entre el {long_date(test['as_of_before'], 'es')} y el "
             f"{long_date(test['as_of_after'], 'es')} (entra en vigor el {long_date(rules[0].get('effective_date'), 'es')}) "
             f"en {len(affected)} direcciones ({where}); {tr}.")
        if flagged:
            s += (f" {len(flagged)} direcciones tienen una alerta de conflicto: posible preempción de las ordenanzas "
                  "locales sobre algoritmos, marcada para revisión humana.")
        return s
    on = long_date(test.get("as_of"), "es")
    if kind == "boundary":
        return (f"{ids} aplican solo dentro de los límites de su propia ciudad al {on} ({where}); en ninguna otra. "
                "El texto de las ordenanzas locales no está en el corpus; su alcance proviene del documento de los "
                f"organizadores (reglas atestiguadas en el manifiesto). Las {len(flagged)} tienen alerta de conflicto: "
                "la Ley FAIR de Nueva Jersey podría desplazarlas cuando entre en vigor.")
    if kind == "pending":
        return (f"{ids} son proyectos de ley pendientes, no leyes, al {on}; si se aprobaran cubrirían "
                f"{len(affected)} direcciones de Massachusetts ({where}). El texto de los proyectos de ley no está en "
                "el corpus: su alcance se indica a nivel estatal según las páginas de estado de los proyectos.")
    if kind == "negative":
        rule = rules[0]
        status = "fallida" if rule.get("status") == "failed" else rule.get("status")
        return (f"No hay ningún tope de renta vigente en Massachusetts al {on}: el conjunto de direcciones afectadas "
                f"está vacío ({len(affected)}). La pregunta de boleta sobre control de rentas ({rule['team_rule_id']}, "
                f"IP 25-21) consta como {status} (anulada el {long_date('2026-06-23', 'es')}); la ley M.G.L. c. 40P "
                "prohíbe el control de rentas local y no es un tope.")
    if kind == "new_document":
        parts = [f"Regla nueva {r['team_rule_id']} ({STATE_ES.get(r['jurisdiction'], r['jurisdiction'])}, "
                 f"{CATEGORY_ES.get(r['category'], r['category'])}) del documento {test.get('doc_id')}: "
                 f"{STATUS_ES.get(r.get('status'), r.get('status'))} al {long_date(test.get('as_of_before'), 'es')}, "
                 f"entra en vigor el {long_date(r.get('effective_date'), 'es')}" for r in rules]
        return ("; ".join(parts) + f". A partir del {long_date(test.get('as_of_after'), 'es')} cubre "
                f"{len(affected)} direcciones ({where}).")
    return f"{TYPE_LABEL.get(kind, ('', 'Cambio'))[1]}: {len(affected)} direcciones afectadas ({where})."
