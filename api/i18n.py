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


# --------------------------------------------------------------------------- #
# /explain and /timeline labels (deterministic; Spanish uses "usted" and the glossary terms)
# --------------------------------------------------------------------------- #

FACT_LABEL = {
    "units": ("number of units", "número de unidades"),
    "year_built": ("year built", "año de construcción"),
    "co_date": ("Certificate of Occupancy date", "fecha del Certificado de Ocupación"),
    "building_age": ("building age (years)", "antigüedad del edificio (años)"),
    "use_class": ("type of building", "tipo de edificio"),
    "owner_type": ("type of owner", "tipo de propietario"),
    "owner_occupied": ("whether an owner lives on the property", "si un propietario vive en la propiedad"),
    "use.affordable": ("an affordability restriction", "una restricción de asequibilidad"),
    "use.section8": ("a Section 8 / HUD subsidy", "un subsidio de Sección 8 / HUD"),
    "use.coop": ("cooperative ownership", "propiedad en cooperativa"),
    "use.elderly": ("housing for the elderly", "vivienda para personas mayores"),
    "use.condo": ("condominium ownership", "propiedad en condominio"),
    "use.single_family": ("single-family use", "uso unifamiliar"),
    "use.tic": ("tenancy-in-common ownership", "propiedad en común (TIC)"),
    "use.mixed_use": ("mixed (commercial and residential) use", "uso mixto (comercial y residencial)"),
    "use.luxury": ("luxury housing", "vivienda de lujo"),
}
OP_LABEL = {"<=": ("is at most", "es como máximo"), "<": ("is less than", "es menor que"),
            ">=": ("is at least", "es al menos"), ">": ("is more than", "es mayor que"),
            "==": ("is", "es"), "!=": ("is not", "no es"), "in": ("is one of", "es uno de")}
USE_CLASS_ES = {"apartment_building": "edificio de apartamentos", "single_family": "casa unifamiliar",
                "condo": "condominio", "mobilehome": "casa móvil", "dormitory": "dormitorio",
                "mixed_use": "uso mixto", "duplex": "dúplex", "hotel": "hotel"}
OUTCOME = {"T": "yes", "F": "no", "U": "unknown"}


def _l(pair: tuple[str, str], lang: str) -> str:
    return pair[lang == "es"]


def fact_label(fact: str | None, lang: str) -> str:
    if fact is None:
        return "dato no disponible" if lang == "es" else "fact not in the data"
    return _l(FACT_LABEL.get(fact, (fact, fact)), lang)


def _value(fact: str, v, lang: str) -> str:
    if isinstance(v, list):
        return ", ".join(_value(fact, x, lang) for x in v)
    if fact == "co_date" and isinstance(v, str):
        return long_date(v, lang)
    if fact == "use_class" and lang == "es":
        return USE_CLASS_ES.get(v, str(v).replace("_", " "))
    return str(v).replace("_", " ") if isinstance(v, str) else str(v)


def verbalize(p: dict, lang: str) -> str:
    """A compiled predicate in plain words ("number of units is at least 2 and ...")."""
    es = lang == "es"
    if "and" in p or "or" in p:
        parts = []
        for x in p.get("and") or p["or"]:
            s = verbalize(x, lang)
            if s not in parts:
                parts.append(s)
        if len(parts) == 1:
            return parts[0]
        word = (" y " if es else " and ") if "and" in p else (" o " if es else " or ")
        return word.join(f"({s})" if (" y " in s or " o " in s or " and " in s or " or " in s) else s for s in parts)
    if "not" in p:
        return f"no ({verbalize(p['not'], lang)})" if es else f"not ({verbalize(p['not'], lang)})"
    if "const" in p:
        return ("siempre" if p["const"] else "nunca") if es else ("always" if p["const"] else "never")
    if "missing" in p:
        return (f"requiere un dato que no tenemos: {p['missing']}" if es
                else f"requires a fact not in the data: {p['missing']}")
    fact, op, v = p["fact"], p["op"], p["value"]
    if fact.startswith("use.") and op in ("==", "!=") and isinstance(v, bool):
        has = (v is True) == (op == "==")
        if es:
            return f"el edificio {'tiene' if has else 'no tiene'} {fact_label(fact, lang)}"
        return f"the building {'has' if has else 'does not have'} {fact_label(fact, lang)}"
    if fact == "owner_occupied" and isinstance(v, bool):
        has = (v is True) == (op == "==")
        if es:
            return "un propietario vive en la propiedad" if has else "ningún propietario vive en la propiedad"
        return "an owner lives on the property" if has else "no owner lives on the property"
    return f"{fact_label(fact, lang)} {_l(OP_LABEL[op], lang)} {_value(fact, v, lang)}"


def value_text(fact: str, v, lang: str) -> str | None:
    """The value the evaluator used, readable (intervals as ranges)."""
    if v is None:
        return None
    if fact == "units" and isinstance(v, list):
        lo, hi = v
        if hi is None:
            return f"{lo} o más" if lang == "es" else f"{lo} or more"
        return str(lo) if lo == hi else f"{lo}–{hi}"
    if fact == "building_age" and isinstance(v, list):
        lo, hi = v
        return str(lo) if lo == hi else (f"entre {lo} y {hi}" if lang == "es" else f"{lo} to {hi}")
    if fact == "co_date" and isinstance(v, str) and ".." in v:
        a, b = v.split("..")
        return (f"entre el {long_date(a, 'es')} y el {long_date(b, 'es')}" if lang == "es"
                else f"between {long_date(a, 'en')} and {long_date(b, 'en')}")
    if isinstance(v, bool):
        return ("sí" if v else "no") if lang == "es" else ("yes" if v else "no")
    return _value(fact, v, lang)


CERTAINTY_LABEL = {
    "exact": ("exact (assessor record)", "exacto (registro del tasador)"),
    "parsed": ("read from the assessor description", "leído de la descripción del tasador"),
    "range": ("range from the use code", "rango según el código de uso"),
    "proxy": ("approximate (year built used as proxy)", "aproximado (se usa el año de construcción)"),
    "inferred": ("inferred from the use code", "inferido del código de uso"),
    "unknown": ("not in the data", "no está en los datos"),
}

EXPLAIN = {
    # step notes
    "cond_yes": ("The building meets this condition.", "El edificio cumple esta condición."),
    "cond_no": ("The building does not meet this condition, so the rule does not cover it.",
                "El edificio no cumple esta condición, así que la regla no lo cubre."),
    "cond_unknown": ("Cannot be decided with the available data.", "No se puede decidir con los datos disponibles."),
    "exem_yes": ("This exemption applies, so the building is exempt.", "Esta exención aplica, así que el edificio está exento."),
    "exem_no": ("This exemption does not apply.", "Esta exención no aplica."),
    "exem_unknown": ("Cannot be decided with the available data.", "No se puede decidir con los datos disponibles."),
    "presumed": ("Presumed absent: the assessor data shows no evidence of it (special status presumption).",
                 "Se presume que no existe: los datos del tasador no muestran evidencia (presunción de estatus especial)."),
    "unit_or_tenancy": ("Depends on the unit or the tenancy, not on the building: shown as a caveat; it does not "
                        "change the result.",
                        "Depende de la unidad o del contrato de arrendamiento, no del edificio: se muestra como "
                        "advertencia y no cambia el resultado."),
    "other_law_yields": ("Refers to {law}; {rid} covers this building, so this rule yields to it.",
                         "Se refiere a {law}; {rid} cubre este edificio, así que esta regla cede ante ella."),
    "other_law_maybe": ("Refers to {law}; whether it covers this building is unknown ({rids}).",
                        "Se refiere a {law}; no se sabe si cubre este edificio ({rids})."),
    "other_law_none": ("Refers to {law}, which does not cover this building.",
                       "Se refiere a {law}, que no cubre este edificio."),
    "other_law_unresolved": ("The law it refers to could not be identified among this address's rules; not applied.",
                             "No se pudo identificar la ley a la que se refiere entre las reglas de esta dirección; "
                             "no se aplica."),
    "dependency_yes": ("Defined by {law}: {rid} applies to this building.",
                       "Definida por {law}: {rid} aplica a este edificio."),
    "dependency_unknown": ("Defined by {law}: whether it covers this building is unknown.",
                           "Definida por {law}: no se sabe si cubre este edificio."),
    "dependency_no": ("Defined by {law}, which does not apply here.", "Definida por {law}, que no aplica aquí."),
    "review": ("Not machine-checkable; listed for human review and not counted in the result.",
               "No se puede verificar automáticamente; queda para revisión humana y no cuenta en el resultado."),
    "human_review": ("Added by human review {hr}.", "Agregada por la revisión humana {hr}."),
    # precedence
    "basis_overrides": ("{rid} yields to {gov} (Module A precedence: \"{text}\").",
                        "{rid} cede ante {gov} (precedencia del Módulo A: \"{text}\")."),
    "basis_other_law": ("{rid} has an exemption for housing covered by another law, and {gov} covers this building.",
                        "{rid} tiene una exención para viviendas cubiertas por otra ley, y {gov} cubre este edificio."),
    "basis_same_law": ("{rid} is part of the same law and section as {via}, which yields to {gov}; the same "
                       "precedence carries over.",
                       "{rid} es parte de la misma ley y sección que {via}, que cede ante {gov}; se aplica la misma "
                       "precedencia."),
    "also_overrides": ("Module A precedence also says it yields to {gov}.",
                       "La precedencia del Módulo A también indica que cede ante {gov}."),
    "not_superseded": ("No other rule governs instead of this one at this address.",
                       "Ninguna otra regla rige en lugar de esta en esta dirección."),
    "preemption": ("Possible preemption conflict with {other}; both rules are kept and flagged for human review.",
                   "Posible conflicto de preempción con {other}; se mantienen ambas reglas y se marcan para revisión "
                   "humana."),
    # status
    "stage": ("Legislative stage: {stage}.", "Etapa legislativa: {stage}."),
    "eff_literal": ("Effective date stated in the text: \"{quote}\"", "Fecha de vigencia indicada en el texto: \"{quote}\""),
    "eff_derived": ("Effective date computed from a formula in the text: \"{quote}\"",
                    "Fecha de vigencia calculada con una fórmula del texto: \"{quote}\""),
    "eff_calendar": ("No effective date in the text; calendar rule {source}: January 1 after enactment.",
                     "El texto no indica fecha de vigencia; regla de calendario {source}: 1 de enero después de la "
                     "promulgación."),
    "eff_attested": ("Date from the organizers' manifest ({basis}); the text is not in the corpus.",
                     "Fecha del manifiesto de los organizadores ({basis}); el texto no está en el corpus."),
    "enacted": ("Enacted on {date}.", "Promulgada el {date}."),
    "sunset": ("Ends on {date}.", "Termina el {date}."),
    "no_dates": ("No effective date: an enacted rule without one is in force.",
                 "Sin fecha de vigencia: una regla promulgada sin ella está vigente."),
    "status_at": ("Status on {as_of}: {status}.", "Estado al {as_of}: {status}."),
    # confidence
    "conf_rule": ("Extraction confidence of the rule (validated quote and citation).",
                  "Confianza de la extracción de la regla (cita textual y referencia validadas)."),
    "conf_rule_attested": ("Manifest-attested rule: text not in the corpus.",
                           "Regla atestiguada en el manifiesto: el texto no está en el corpus."),
    "units_range": ("The unit count is a range from the use code, not an exact count.",
                    "El número de unidades es un rango según el código de uso, no un conteo exacto."),
    "dataset_fallback": ("City from the dataset, not confirmed by the geocoder.",
                         "Ciudad tomada de los datos, no confirmada por el geocodificador."),
    "co_approx": ("Year built used as a proxy for the Certificate of Occupancy date.",
                  "Se usa el año de construcción en lugar de la fecha del Certificado de Ocupación."),
    "special_status_presumption": ("The result rests on the special status presumption.",
                                   "El resultado depende de la presunción de estatus especial."),
    "no_factor": ("No reduction: every fact used is exact.", "Sin reducción: todos los datos usados son exactos."),
    "geo_census": ("Census geocoder: {quality}.", "Geocodificador del Censo: {quality}."),
    "geo_fallback": ("The geocoder found no match; city taken from the dataset (×0.85).",
                     "El geocodificador no encontró coincidencia; ciudad tomada de los datos (×0,85)."),
    "juris_ok": ("{level} rule of {jur}; this address is in {jur} ({source}).",
                 "Regla {level} de {jur}; esta dirección está en {jur} ({source})."),
    "juris_no": ("{level} rule of {jur}; this address is not in {jur}, so the rule does not reach it.",
                 "Regla {level} de {jur}; esta dirección no está en {jur}, así que la regla no la alcanza."),
}
LEVEL_LABEL = {"state": ("State", "estatal"), "city": ("City", "municipal")}
STAGE_LABEL = {"enacted": ("enacted", "promulgada"), "bill_pending": ("pending bill, not law", "proyecto de ley pendiente, no es ley"),
               "bill_failed": ("failed bill", "proyecto de ley fallido"), "administrative": ("administrative", "administrativa"),
               "unknown": ("unknown", "desconocida")}
SOURCE_LABEL = {"census": ("Census geocoder", "geocodificador del Censo"),
                "dataset_fallback": ("dataset city, geocoder fallback", "ciudad de los datos, sin geocodificador")}
MATCH_LABEL = {"exact": ("exact match", "coincidencia exacta"), "non_exact": ("non-exact match", "coincidencia no exacta"),
               "no_match": ("no match", "sin coincidencia")}


LAW_ES = {"la_rso": "la Ordenanza de Estabilización de Arrendamientos de Los Ángeles (RSO)",
          "la_jco": "la Ordenanza de Causa Justa de Los Ángeles (JCO)",
          "berkeley_rent_ordinance": "la Ordenanza de Arrendamiento de Berkeley",
          "local_rent_control": "el control de rentas local", "local_just_cause": "una ordenanza local de causa justa"}


def law_label(law: dict, lang: str) -> str:
    return LAW_ES.get(law.get("id"), law["label"]) if lang == "es" else law["label"]


def t(key: str, lang: str, **kw) -> str:
    s = _l(EXPLAIN[key], lang).format(**kw)
    return s.replace(" a el ", " al ").replace(" de el ", " del ") if lang == "es" else s


def result_label(result: str | None, lang: str) -> str:
    en = {"applies": "applies", "unknown": "unknown", "superseded": "superseded", "not_yet_effective": "not yet in force",
          "pending": "pending bill", "omitted": "does not apply", "not_in_stack": "outside the jurisdiction"}
    r = result or "omitted"
    return RESULT_ES.get(r, r) if lang == "es" else en.get(r, r)


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
