"""GET /explain/{address_id}/{team_rule_id}: why /lookup gave this answer (deterministic, no LLM).

Built from the same ``Engine.lookup`` call as /lookup (``trace=True`` only adds the decision
trace), so the result is identical for the same date by construction. Labels come from
``api/i18n.py`` (Spanish with "usted" and the glossary terms); source texts, citations and
quotes stay as in the source.
"""

from __future__ import annotations

from datetime import date

from extractor import config
from resolver.coverage import PRESUME_SPECIAL_STATUS, jurisdiction_match
from resolver.results import REVIEW_BELOW, is_law, law_named, rule_status

from . import i18n

_DEFAULTS = None


def _calendar_sources() -> dict[str, str]:
    global _DEFAULTS
    if _DEFAULTS is None:
        import yaml
        data = yaml.safe_load((config.DATA_DIR / "jurisdiction_defaults.yaml").read_text(encoding="utf-8"))
        _DEFAULTS = {d["id"]: d.get("source") or d["id"] for d in data.get("defaults", [])}
    return _DEFAULTS


def _certainty(fact: str, facts: dict) -> str:
    if fact == "units":
        return facts["units"]["certainty"] if facts["units"]["range"] else "unknown"
    if fact == "year_built":
        return facts["year_built"]["certainty"] if facts["year_built"]["value"] else "unknown"
    if fact in ("co_date", "building_age"):
        return "proxy" if facts["year_built"]["value"] else "unknown"
    if fact.startswith("use."):
        flag = facts["use_flags"].get(fact[4:]) or {}
        return "inferred" if flag.get("value") is not None else "unknown"
    if fact == "use_class":
        return facts["use_class"].get("certainty") or "inferred"
    return "unknown"


def _step(item: dict, reason: dict | None, facts: dict, lang: str, kind: str) -> dict:
    """One condition / exemption with the facts the evaluator used."""
    fused = list(reason["value_used"]) if reason else []
    step = {
        "condition": i18n.verbalize(item["predicate"], lang),
        "source_text": item["text"],
        "fact_used": [i18n.fact_label(f, lang) for f in fused],
        "value": {i18n.fact_label(f, lang): i18n.value_text(f, reason["value_used"][f], lang) for f in fused},
        "fact_source": {i18n.fact_label(f, lang): reason["fact_source"][f] for f in fused},
        "certainty": {i18n.fact_label(f, lang): i18n._l(i18n.CERTAINTY_LABEL[_certainty(f, facts)], lang)
                      for f in fused},
        "outcome": i18n.OUTCOME[reason["result"]] if reason else "unknown",
        "note": "",
    }
    if reason:
        step["note"] = i18n.t(f"{'cond' if kind == 'condition' else 'exem'}_{step['outcome']}", lang)
        if reason.get("presumed"):
            step["note"] = i18n.t("presumed", lang)
    if item.get("origin") == "human_review":
        step["note"] = f"{step['note']} {i18n.t('human_review', lang, hr=item['source'].split(':')[-1])}".strip()
    return step


def _other_law_note(item: dict, rule: dict, res: dict | None, by_result: dict, lang: str) -> tuple[str, str]:
    laws = law_named(item["text"], rule)
    if not laws:
        return "unknown", i18n.t("other_law_unresolved", lang)
    label = " / ".join(i18n.law_label(l, lang) for l in laws)
    ts = [x for x in by_result.values() if x["team_rule_id"] != rule["team_rule_id"]
          and any(is_law(x["_rule"], l, l.get("category") or rule["category"]) for l in laws)]
    gov = [x["team_rule_id"] for x in ts if x["result"] == "applies"]
    if res and res["result"] == "superseded" and res["superseded_by"] in gov:
        return "yes", i18n.t("other_law_yields", lang, law=label, rid=res["superseded_by"])
    if gov:
        return "yes", i18n.t("other_law_yields", lang, law=label, rid=gov[0])
    maybe = [x["team_rule_id"] for x in ts if x["result"] == "unknown"] + (res or {}).get("may_yield_to", [])
    if maybe:
        return "unknown", i18n.t("other_law_maybe", lang, law=label, rids=", ".join(dict.fromkeys(maybe)))
    return "no", i18n.t("other_law_none", lang, law=label)


def _status_steps(rule: dict, eng, as_of: date, status: str, lang: str) -> list[dict]:
    rid, steps = rule["team_rule_id"], []
    if rule.get("evidence_type") == "manifest_only":
        steps.append({"step": "effective_date", "date": rule.get("effective_date"), "origin": "attested",
                      "note": i18n.t("eff_attested", lang, basis=rule.get("status_basis") or "manifest")})
    else:
        r = eng.internal[rid]
        stage = r.stage.value
        steps.append({"step": "stage", "value": stage,
                      "note": i18n.t("stage", lang, stage=i18n._l(i18n.STAGE_LABEL.get(stage, (stage, stage)), lang))})
        if r.enacted_date and r.enacted_date.value:
            steps.append({"step": "enacted", "date": r.enacted_date.value.isoformat(),
                          "quote": r.enacted_date.quoted_span,
                          "note": i18n.t("enacted", lang, date=i18n.long_date(r.enacted_date.value, lang))})
        effs = sorted((d for d in r.effective_dates if d.kind == "effective" and d.value), key=lambda d: d.value)
        for d in effs:
            origin = date_origin(d)
            if origin == "calendar_default":
                src = _calendar_sources().get(d.rule_applied, d.rule_applied)
                note = i18n.t("eff_calendar", lang, source=src)
            else:
                note = i18n.t("eff_literal" if origin == "literal" else "eff_derived", lang, quote=d.quoted_span or d.raw)
            steps.append({"step": "effective_date", "date": d.value.isoformat(), "origin": origin,
                          "quote": d.quoted_span, "raw": d.raw, "rule_applied": d.rule_applied,
                          "calendar_source": _calendar_sources().get(d.rule_applied) if d.rule_applied else None,
                          "verified": d.verified, "source_doc_id": d.source_doc_id, "note": note})
        if not effs and stage not in ("bill_pending", "bill_failed"):
            steps.append({"step": "effective_date", "date": None, "origin": None, "note": i18n.t("no_dates", lang)})
        if r.sunset_date and r.sunset_date.value:
            steps.append({"step": "sunset", "date": r.sunset_date.value.isoformat(), "quote": r.sunset_date.quoted_span,
                          "note": i18n.t("sunset", lang, date=i18n.long_date(r.sunset_date.value, lang))})
    label = i18n.STATUS_ES.get(status, status) if lang == "es" else status.replace("_", " ")
    steps.append({"step": "status", "value": status,
                  "note": i18n.t("status_at", lang, as_of=i18n.long_date(as_of, lang), status=label)})
    return steps


def date_origin(claim) -> str:
    """literal (quoted in the text) | derived (formula in the text) | calendar_default (jurisdiction rule)."""
    if claim.rule_applied or claim.kind_source == "default":
        return "calendar_default"
    return "derived" if claim.derived else "literal"


def build(aid: str, rid: str, as_of: date, lang: str) -> dict:
    from . import main as M

    s, eng = M.store(), M.engine(as_of)
    rules = {r["team_rule_id"]: r for r in eng.rules}
    rule, facts, stack = rules[rid], eng.facts[aid], eng.stacks[aid]
    lk = eng.lookup(aid, plain=s.plain.get("rules", {}), trace=True)
    by_result = {r["team_rule_id"]: {**r, "_rule": rules[r["team_rule_id"]]} for r in lk["results"]}
    omitted = {o["team_rule_id"]: o for o in lk["omitted"]}
    res, om = by_result.get(rid), omitted.get(rid)
    in_stack = jurisdiction_match(rule, stack)
    result = res["result"] if res else ("omitted" if om else "not_in_stack")
    status, eff = rule_status(rule, eng.internal, as_of)
    detail = (res or om or {}).get("trace", {}).get("coverage_detail")
    compiled = eng.compiled[rid]
    level = i18n._l(i18n.LEVEL_LABEL[rule["level"]], lang)
    src = i18n._l(i18n.SOURCE_LABEL.get(stack.get("source"), (stack.get("source"), stack.get("source"))), lang)

    jurisdiction = {
        "rule_jurisdiction": rule["jurisdiction"], "rule_level": rule["level"],
        "address_state": stack.get("state"), "address_city": stack.get("city"),
        "source": stack.get("source"), "match_quality": stack.get("match_quality"),
        "certainty": stack.get("certainty"), "matched_address": stack.get("matched_address"),
        "in_stack": in_stack,
        "note": i18n.t("juris_ok" if in_stack else "juris_no", lang, level=level, jur=rule["jurisdiction"], source=src),
    }

    # coverage and exemption steps: building items in evaluation order, then the others
    reasons = list((detail or {}).get("reasons", []))
    cond_r = [x for x in reasons if x["kind"] == "condition"]
    exem_r = [x for x in reasons if x["kind"] == "exemption"]
    coverage_steps, exemption_steps = [], []
    for kind, items, rs, out in (("condition", compiled["conditions"], cond_r, coverage_steps),
                                 ("exemption", compiled["exemptions"], exem_r, exemption_steps)):
        b = iter(rs)
        for it in items:
            if it["scope"] == "duplicate":
                continue
            if it["scope"] == "building":
                step = _step(it, next(b, None) if detail else None, facts, lang, kind)
                cls = "special_status" if it.get("special_status") else "building"
            else:
                step = _step(it, None, facts, lang, kind)
                cls = it["scope"]
                if it["scope"] == "unit_or_tenancy":
                    step["note"] = i18n.t("unit_or_tenancy", lang)
                elif it["scope"] == "other_law" and kind == "exemption":
                    step["outcome"], step["note"] = _other_law_note(it, rule, res, by_result, lang)
                elif it["scope"] == "other_law" or (it["scope"] == "review" and kind == "condition" and eng.deps[rid]):
                    laws = eng.deps[rid] or law_named(it["text"], rule)
                    label = " / ".join(i18n.law_label(l, lang) for l in laws) or it["text"]
                    via = (res or {}).get("trace", {}).get("dependency_via")
                    if via:
                        step["outcome"], step["note"] = "yes", i18n.t("dependency_yes", lang, law=label, rid=via[1])
                    elif res:
                        step["outcome"], step["note"] = "unknown", i18n.t("dependency_unknown", lang, law=label)
                    else:
                        step["outcome"], step["note"] = "no", i18n.t("dependency_no", lang, law=label)
                else:
                    step["note"] = i18n.t("review", lang)
            if kind == "exemption":
                step["class"] = cls
                if cls == "special_status":
                    step["special_status_presumption"] = PRESUME_SPECIAL_STATUS
            out.append(step)

    # precedence
    tr = (res or {}).get("trace", {})
    basis_raw = tr.get("precedence_basis")
    prec = {"superseded": result == "superseded", "governed_by": None, "governing_title": None, "basis": None,
            "same_law_as": None, "interaction": rule.get("interaction"), "may_yield_to": (res or {}).get("may_yield_to", []),
            "conflict_flag": bool(res and res["conflict_flag"]), "conflict_note": None, "note": i18n.t("not_superseded", lang)}
    if result == "superseded":
        gov = res["superseded_by"]
        basis = basis_raw.split(":")[0] if basis_raw else "overrides"
        prec.update(governed_by=gov, governing_title=rules[gov]["title"], basis=basis)
        if basis == "same_law":
            via = basis_raw.split(":", 1)[1]
            prec["same_law_as"] = via
            prec["note"] = i18n.t("basis_same_law", lang, rid=rid, via=via, gov=gov)
        elif basis == "other_law":
            prec["note"] = i18n.t("basis_other_law", lang, rid=rid, gov=gov)
            if gov in eng.yields.get(rid, ()):
                prec["note"] += " " + i18n.t("also_overrides", lang, gov=gov)
        else:
            prec["note"] = i18n.t("basis_overrides", lang, rid=rid, gov=gov,
                                  text=(rule.get("interaction") or rules[gov].get("interaction") or "").strip()[:300])
    if res:
        notes = [n for n in [rule.get("conflict_note"), *(res["conflict_notes"] if lang == "en" else [])] if n]
        prec["conflict_note"] = "; ".join(notes) or None
        others = sorted({o for p in eng.pairs if rid in p for o in p if o != rid and o in by_result})
        if others:
            prec["preemption"] = [i18n.t("preemption", lang, other=o) for o in others]

    # confidence: rule x coverage x geocoding (same product as /lookup)
    attested = rule.get("evidence_type") == "manifest_only"
    rconf = rule.get("confidence") or 1.0
    cconf = (detail or {}).get("confidence_coverage", 1.0)
    factors = (detail or {}).get("confidence_factors", [])
    geo = (res or om or {}).get("trace", {}).get("geocode_factor", 0.85 if stack.get("source") == "dataset_fallback" else 1.0)
    quality = i18n._l(i18n.MATCH_LABEL.get(stack.get("match_quality"), (stack.get("match_quality"),) * 2), lang)
    combined = round(rconf * cconf * geo, 3)
    confidence = {
        "rule": {"value": rconf, "reason": i18n.t("conf_rule_attested" if attested else "conf_rule", lang)},
        "coverage": {"value": cconf, "factors": [{"factor": f["factor"], "reason": i18n.t(f["reason"], lang)}
                                                 for f in factors] or [{"factor": 1.0, "reason": i18n.t("no_factor", lang)}]},
        "geocoding": {"value": geo, "reason": i18n.t("geo_fallback", lang) if geo < 1
                      else i18n.t("geo_census", lang, quality=quality)},
        "combined": combined, "needs_review": combined < REVIEW_BELOW,
    }

    # provenance
    reviews = [r for r in s.review if r["rule_id"] == rid or r.get("into") == rid]
    if attested:
        provenance = {"doc_id": None, "source_url": ", ".join(x["url"] for x in rule.get("sources", [])),
                      "retrieved_at": None, "quoted_span": None, "citation": rule.get("citation"),
                      "status_basis": rule.get("status_basis"), "prompt_version": None, "model": None,
                      "snapshot": None, "evidence": "manifest_only"}
    else:
        r = eng.internal[rid]
        snap = s.manifest.get("snapshot") if r.source_doc_id in s.manifest.get("documents", {}) else "corpus/new (incremental)"
        provenance = {"doc_id": r.source_doc_id, "source_url": r.source_url, "retrieved_at": r.retrieved_at,
                      "quoted_span": rule.get("quoted_span"), "citation": rule.get("citation"),
                      "prompt_version": r.prompt_version, "model": r.model, "snapshot": snap,
                      "supporting_quotes": [{"doc_id": e.source_doc_id, "role": e.role, "quoted_span": e.quoted_span}
                                            for e in r.evidence if e.role != "primary"]}
    provenance["coverage_compiler"] = {"model": s.compiled.get("model"), "prompt_version": s.compiled.get("prompt_version")}
    provenance["human_review"] = [{k: r.get(k) for k in ("id", "rule_id", "action", "into", "quoted_span", "reason",
                                                         "reviewer", "date") if r.get(k) is not None} for r in reviews]

    summary = _summary(rid, result, res, om, detail, coverage_steps, exemption_steps, eff, as_of, combined, lang)
    return {
        "address": M.address_info(aid), "team_rule_id": rid, "title": rule["title"], "category": rule["category"],
        "as_of": as_of.isoformat(), "lang": lang, "disclaimer": M.DISCLAIMER[lang],
        "result": result, "status": status, "effective_date": eff.isoformat() if eff else None,
        "coverage": (detail or {}).get("coverage"), "confidence": res["confidence"] if res else combined,
        "conflict_flag": bool(res and res["conflict_flag"]), "superseded_by": (res or {}).get("superseded_by"),
        "omitted_reason": om["reason"] if om else None,
        "status_line": M.status_line(status, eff.isoformat() if eff else None, lang, result,
                                     (res or {}).get("superseded_by")),
        "summary": summary, "jurisdiction": jurisdiction, "coverage_steps": coverage_steps,
        "exemption_steps": exemption_steps, "precedence": prec,
        "status_steps": _status_steps(rule, eng, as_of, status, lang),
        "confidence_breakdown": confidence, "provenance": provenance,
    }


def _summary(rid, result, res, om, detail, cov, exem, eff, as_of, conf, lang) -> str:
    es = lang == "es"
    on = i18n.long_date(as_of, lang)
    if result == "applies":
        s = (f"{rid} aplica a esta dirección al {on}: el edificio cumple las condiciones de cobertura y no aplica "
             "ninguna exención." if es else
             f"{rid} applies at this address on {on}: the building meets its coverage conditions and no exemption applies.")
    elif result == "superseded":
        g = res["superseded_by"]
        s = (f"{rid} cubre este edificio al {on}, pero rige {g} en su lugar." if es else
             f"{rid} covers this building on {on}, but {g} governs instead.")
    elif result == "not_yet_effective":
        when = i18n.long_date(eff, lang) if eff else ("fecha por confirmar" if es else "a date to be confirmed")
        s = (f"{rid} está aprobada pero aún no vigente al {on}: entra en vigor el {when}." if es else
             f"{rid} is enacted but not yet in force on {on}: it takes effect {when}.")
    elif result == "pending":
        s = (f"{rid} es un proyecto de ley pendiente, no es ley, al {on}." if es else
             f"{rid} is a pending bill, not law, on {on}.")
    elif result == "unknown":
        miss = ", ".join(i18n.missing_label(m, lang) for m in res["missing_facts"]) or (
            "datos que no tenemos" if es else "facts not in the data")
        s = (f"No se puede saber si {rid} aplica a esta dirección al {on}: depende de {miss}." if es else
             f"Whether {rid} applies at this address on {on} cannot be known: it depends on {miss}.")
    elif result == "not_in_stack":
        s = (f"{rid} no aplica: esta dirección está fuera de su jurisdicción." if es else
             f"{rid} does not apply: this address is outside its jurisdiction.")
    else:
        reason = (om or {}).get("reason") or ""
        if "not_covered" in reason:
            c = next((x["condition"] for x in cov if x["outcome"] == "no"), "")
            s = (f"{rid} no cubre este edificio al {on}: no se cumple la condición «{c}»." if es else
                 f"{rid} does not cover this building on {on}: the condition \"{c}\" is not met.")
        elif "exempt" in reason:
            c = next((x["condition"] for x in exem if x["outcome"] == "yes"), "")
            s = (f"{rid} no aplica al {on}: el edificio está exento («{c}»)." if es else
                 f"{rid} does not apply on {on}: the building is exempt (\"{c}\").")
        elif "failed" in reason:
            s = (f"{rid} no está vigente al {on} (fallida o derogada)." if es else
                 f"{rid} is not in force on {on} (failed or repealed).")
        else:
            s = (f"{rid} no aplica aquí al {on}: {reason}." if es else f"{rid} does not apply here on {on}: {reason}.")
    if result in ("applies", "superseded", "unknown", "not_yet_effective", "pending"):
        s += (f" Confianza: {conf} (regla × cobertura × geocodificación)." if es else
              f" Confidence: {conf} (rule × coverage × geocoding).")
    return s
