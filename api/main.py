"""Rental Housing Law Navigator API (FastAPI). Read-only; no LLM call in any route.

Run locally:  uvicorn api.main:app --reload
Data loaded at startup: out/rules.json, out/rules_attested.json, out/rules_normalized.json (via
results.Engine), data/building_facts.json, data/jurisdictions.json, data/compiled_exemptions.json,
data/plain_language.json, out/changes.json, out/changes_full.json, out/conflicts.json.
(`python -m extractor.cli reproduce && python -m resolver.cli changes` produce the out/ files
without an API key.)
"""

from __future__ import annotations

import functools
import json
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from extractor import config
from resolver.results import CATEGORY_LABEL, Engine, rule_status

from . import i18n
from .mx import MxBodyLimit
from .mx import router as mx_router

API_VERSION = "1.0.0"
AS_OF_MIN, AS_OF_MAX = date(2020, 1, 1), date(2030, 12, 31)
AUDIO_DIR = config.DATA_DIR / "audio"
DISCLAIMER = {
    "en": "Not legal advice. This prototype summarizes public housing law for information only; "
          "check the cited source and consult a qualified professional before acting.",
    "es": "No es asesoría legal. Este prototipo resume leyes públicas de vivienda solo con fines informativos; "
          "revise la fuente citada y consulte a un profesional calificado antes de actuar.",
}
CATEGORY_ES = {"RENT": "RENTA", "JUST CAUSE": "CAUSA JUSTA", "DEPOSIT": "DEPÓSITO",
               "SCREENING FEE": "CUOTA DE EVALUACIÓN", "SCREENING": "EVALUACIÓN", "ALGORITHMIC": "ALGORITMOS"}
#: Lovable preview/production domains + local development; ALLOWED_ORIGINS adds exact origins.
ORIGIN_REGEX = r"https://([a-z0-9-]+\.)*(lovable\.app|lovable\.dev|lovableproject\.com)|http://(localhost|127\.0\.0\.1)(:\d+)?"


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class Store:
    """Everything the routes read, loaded once."""

    def __init__(self):
        self.rules = _load(config.RULES_PATH).get("rules", [])
        self.attested = _load(config.ATTESTED_PATH).get("rules", [])
        self.facts = _load(config.DATA_DIR / "building_facts.json")["facts"]
        self.juris = _load(config.DATA_DIR / "jurisdictions.json")["stacks"]
        self.compiled = _load(config.DATA_DIR / "compiled_exemptions.json")
        self.plain = _load(config.DATA_DIR / "plain_language.json")
        self.changes = _load(config.OUT_DIR / "changes.json")
        self.changes_full = _load(config.OUT_DIR / "changes_full.json")
        self.conflicts = _load(config.CONFLICTS_PATH).get("conflicts", [])
        self.manifest = _load(config.SNAPSHOTS_DIR / "a-0.4.0" / "MANIFEST.json")
        self.open_questions = yaml.safe_load((config.DATA_DIR / "open_questions.yaml").read_text(encoding="utf-8"))["questions"]
        self.review = yaml.safe_load((config.DATA_DIR / "human_review.yaml").read_text(encoding="utf-8"))["reviews"]
        self.by_id = {r["team_rule_id"]: r for r in self.rules + self.attested}
        internal = _load(config.NORMALIZED_PATH).get("rules", [])
        self.retrieved = {r["team_rule_id"]: r["retrieved_at"][:10] for r in internal
                          if r.get("team_rule_id") and r["disposition"] == "accepted"}
        self.audio = _load(AUDIO_DIR / "manifest.json").get("items", {})


def audio_url(rid: str, lang: str) -> str | None:
    """/audio/<lang>/<rule>.mp3?v=<text hash> (path on this API), or null if the file does not exist.
    The version query changes with the spoken text, so the long cache headers stay safe."""
    item = store().audio.get(f"{lang}/{rid}")
    if not item or not (AUDIO_DIR / item["file"]).exists():
        return None
    return f"/audio/{item['file']}?v={item['text_sha256'][:8]}"


class AudioFiles(StaticFiles):
    """data/audio served as audio/mpeg with long cache headers."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            if path.endswith(".mp3"):
                response.headers["Content-Type"] = "audio/mpeg"
        return response


@functools.lru_cache(maxsize=1)
def store() -> Store:
    return Store()


@functools.lru_cache(maxsize=16)
def engine(as_of: date) -> Engine:
    return Engine(as_of)


def parse_as_of(as_of: str | None) -> date:
    if as_of is None:
        return config.DEFAULT_AS_OF
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise HTTPException(422, f"as_of must be YYYY-MM-DD, got {as_of!r}")
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        raise HTTPException(422, f"as_of is not a valid date: {as_of!r}") from None
    if not AS_OF_MIN <= d <= AS_OF_MAX:
        raise HTTPException(422, f"as_of must be between {AS_OF_MIN} and {AS_OF_MAX}")
    return d


def lang_of(lang: str) -> str:
    if lang not in ("en", "es"):
        raise HTTPException(422, "lang must be 'en' or 'es'")
    return lang


@asynccontextmanager
async def _lifespan(_app):
    store()  # load everything once
    engine(config.DEFAULT_AS_OF)
    yield


app = FastAPI(title="Rental Housing Law Navigator API", version=API_VERSION, lifespan=_lifespan,
              description="Address-level answers from public housing law, with citations. Not legal advice.")
app.add_middleware(MxBodyLimit)  # 413 for POST /mx/* bodies > 256 KB (added first: CORS stays outermost)
# POST/OPTIONS for the Renta MX forms (/mx/*); the US routes are all GET and unchanged.
app.add_middleware(CORSMiddleware, allow_origin_regex=ORIGIN_REGEX,
                   allow_origins=[o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o],
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])
app.mount("/audio", AudioFiles(directory=AUDIO_DIR, check_dir=False), name="audio")
app.include_router(mx_router)  # Renta MX (/mx/*): data loaded lazily, 503 if missing; US routes unaffected


# --------------------------------------------------------------------------- #
# Builders (shared with api/export_static.py)
# --------------------------------------------------------------------------- #


def status_line(status: str, effective: str | None, lang: str, result: str | None = None,
                superseded_by: str | None = None) -> str:
    """Status at as_of, prepended to plain_language (computed per request; the stored summary is undated)."""
    es = lang == "es"
    if result == "superseded" and superseded_by:
        return f"Aplica, pero rige {superseded_by}" if es else f"Covered, but {superseded_by} governs instead"
    if status == "not_yet_effective":
        when = effective or ("fecha por confirmar" if es else "date to be confirmed")
        return f"Aún no vigente — entra en vigor el {when}" if es else f"Not in force yet — takes effect {when}"
    if status == "pending":
        return "Proyecto de ley pendiente — no es ley" if es else "Pending bill — not law"
    if status == "failed":
        return "No vigente (fallida o derogada)" if es else "Not in force (failed or repealed)"
    if effective:
        return f"Vigente desde el {effective}" if es else f"In force since {effective}"
    return "Vigente" if es else "In force"


def plain_with_status(rid: str, lang: str, line: str) -> dict | None:
    p = (store().plain.get("rules", {}).get(rid) or {}).get(lang)
    return {"status_line": line, **p} if p else None


def building_facts(aid: str) -> dict:
    f = store().facts[aid]
    flags = {k: v for k, v in f["use_flags"].items() if v["value"] is not None}
    return {"units": f["units"], "year_built": f["year_built"], "co_year_approx": f["co_year_approx"],
            "use_flags": flags, "use_class": f["use_class"], "owner_type": f["owner_type"],
            "owner_occupied": f["owner_occupied"]}


def address_info(aid: str) -> dict:
    s, f = store(), store().facts[aid]
    stack = s.juris[aid]
    return {"address_id": aid, "street": stack["input"]["street"], "postal_city": stack["input"]["city"],
            "state": f["state"], "city": stack["city"] or f["dataset_city"], "dataset_city": f["dataset_city"]}


def jurisdiction_stack(aid: str) -> dict:
    j = store().juris[aid]
    return {k: j.get(k) for k in ("state", "county", "city", "place", "county_subdivision", "match_quality",
                                  "source", "certainty", "matched_address", "coordinates", "levels")}


def lookup_payload(aid: str, as_of: date, lang: str) -> dict:
    s = store()
    if aid not in s.facts:
        raise HTTPException(404, f"unknown address_id {aid!r}")
    plain = s.plain.get("rules", {})
    lk = engine(as_of).lookup(aid, plain=plain)
    groups: dict[str, list] = {}
    for r in lk["results"]:
        rule = s.by_id.get(r["team_rule_id"]) or next(x for x in engine(as_of).rules
                                                     if x["team_rule_id"] == r["team_rule_id"])
        label = CATEGORY_LABEL[r["category"]]
        notes = [n for n in [rule.get("conflict_note"), *r["conflict_notes"]] if n]
        groups.setdefault(CATEGORY_ES[label] if lang == "es" else label, []).append({
            "team_rule_id": r["team_rule_id"], "title": rule["title"], "category": r["category"],
            "level": r["level"], "result": r["result"],
            "explanation": r["explanation_es"] if lang == "es" else r["explanation"],
            "plain_language": plain_with_status(r["team_rule_id"], lang, status_line(
                r["status"], r["effective_date"], lang, r["result"], r["superseded_by"])),
            "citation": rule.get("citation"), "source_url": rule.get("source_url") or
            ", ".join(x["url"] for x in rule.get("sources", [])),
            "retrieved_at": s.retrieved.get(r["team_rule_id"]), "quoted_span": rule.get("quoted_span"),
            "effective_date": r["effective_date"], "status": r["status"], "confidence": r["confidence"],
            "conflict_flag": r["conflict_flag"], "conflict_note": "; ".join(notes) or None,
            "needs_review": r["needs_review"], "missing_facts": r["missing_facts"],
            "missing_facts_label": [i18n.missing_label(m, lang) for m in r["missing_facts"]],
            "presumptions": r["presumptions"], "superseded_by": r["superseded_by"], "attested": r["attested"],
            "audio_url": audio_url(r["team_rule_id"], lang),
        })
    return {"address": address_info(aid), "building_facts": building_facts(aid),
            "jurisdiction_stack": jurisdiction_stack(aid), "as_of": as_of.isoformat(), "lang": lang,
            "disclaimer": DISCLAIMER[lang], "category_order": [CATEGORY_ES[c] if lang == "es" else c
                                                              for c in CATEGORY_LABEL.values()],
            "results": groups,
            "counts": dict(Counter(x["result"] for g in groups.values() for x in g))}


def rules_payload(as_of: date, lang: str, jurisdiction: str | None = None, category: str | None = None) -> dict:
    s, eng = store(), engine(as_of)
    out = []
    for r in s.rules + s.attested:
        if jurisdiction and r["jurisdiction"] != jurisdiction or category and r["category"] != category:
            continue
        status, eff = rule_status(r, eng.internal, as_of)
        out.append({"team_rule_id": r["team_rule_id"], "jurisdiction": r["jurisdiction"], "level": r["level"],
                    "category": r["category"], "title": r["title"], "status": status,
                    "effective_date": eff.isoformat() if eff else None, "citation": r.get("citation"),
                    "source_url": r.get("source_url"), "retrieved_at": s.retrieved.get(r["team_rule_id"]),
                    "quoted_span": r.get("quoted_span"), "key_value": r.get("key_value"),
                    "confidence": r.get("confidence"), "conflict_flag": r.get("conflict_flag", False),
                    "conflict_note": r.get("conflict_note"), "attested": r.get("evidence_type") == "manifest_only",
                    "plain_language": plain_with_status(r["team_rule_id"], lang, status_line(
                        status, eff.isoformat() if eff else None, lang)),
                    "audio_url": audio_url(r["team_rule_id"], lang)})
    return {"as_of": as_of.isoformat(), "disclaimer": DISCLAIMER[lang], "count": len(out), "rules": out}


def change_texts(tid: str, lang: str) -> dict:
    """type, type_label, title and notes of a change test in the requested language."""
    s = store()
    entry, full = s.changes[tid], s.changes_full.get(tid, {})
    test = full.get("test") or {"test_id": tid, "type": None, "title": tid}
    rules = [s.by_id[r] for r in full.get("our_rule_ids") or [] if r in s.by_id]
    if lang == "es":
        city_of = {a: f["dataset_city"] for a, f in s.facts.items()}
        notes = i18n.change_notes_es(test, entry, rules, full.get("addresses", {}), city_of)
    else:
        notes = entry["notes"]
    return {"type": test.get("type"), "type_label": i18n.type_label(test.get("type"), lang),
            "title": i18n.change_title(test, rules, lang), "notes": notes}


def changes_payload(lang: str) -> dict:
    s = store()
    texts = {tid: change_texts(tid, lang) for tid in s.changes}
    summary = {tid: {"affected": len(e["affected_address_ids"]), "conflict_flagged": len(e["conflict_flag_address_ids"]),
                     **texts[tid]} for tid, e in s.changes.items()}
    changes = {tid: {**e, "notes": texts[tid]["notes"]} for tid, e in s.changes.items()}
    return {"disclaimer": DISCLAIMER[lang], "lang": lang, "changes": changes, "summary": summary}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/health")
def health(lang: str = "en") -> dict:
    s = store()
    return {"status": "ok", "version": API_VERSION, "rules": len(s.rules), "attested_rules": len(s.attested),
            "addresses": len(s.facts), "default_as_of": config.DEFAULT_AS_OF.isoformat(),
            "disclaimer": DISCLAIMER[lang_of(lang)]}


@app.get("/addresses")
def addresses(city: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=500),
              lang: str = "en") -> dict:
    s = store()
    out = []
    for aid in sorted(s.facts):
        info = address_info(aid)
        if city and city.lower() not in (info["city"].lower(), info["dataset_city"].lower(),
                                         info["dataset_city"].split(",")[0].lower()):
            continue
        if q and not any(q.lower() in str(v).lower() for v in (aid, info["street"], info["postal_city"], info["city"])):
            continue
        out.append(info)
    return {"disclaimer": DISCLAIMER[lang_of(lang)], "count": len(out), "addresses": out[:limit]}


@app.get("/lookup/{address_id}")
def lookup(address_id: str, as_of: str | None = None, lang: str = "en") -> dict:
    return lookup_payload(address_id, parse_as_of(as_of), lang_of(lang))


def explain_payload(aid: str, rid: str, as_of: date, lang: str) -> dict:
    from . import explain

    if aid not in store().facts:
        raise HTTPException(404, f"unknown address_id {aid!r}")
    if rid not in {r["team_rule_id"] for r in engine(config.DEFAULT_AS_OF).rules}:
        raise HTTPException(404, f"unknown team_rule_id {rid!r}")
    return explain.build(aid, rid, as_of, lang)


def timeline_payload(aid: str, frm: date, to: date, lang: str) -> dict:
    from . import timeline

    if aid not in store().facts:
        raise HTTPException(404, f"unknown address_id {aid!r}")
    if frm > to:
        raise HTTPException(422, "from must be on or before to")
    return timeline.build(aid, frm, to, lang)


@app.get("/explain/{address_id}/{team_rule_id}")
def explain_route(address_id: str, team_rule_id: str, as_of: str | None = None, lang: str = "en") -> dict:
    return explain_payload(address_id, team_rule_id, parse_as_of(as_of), lang_of(lang))


@app.get("/timeline/{address_id}")
def timeline_route(address_id: str, from_: str | None = Query(None, alias="from"), to: str | None = None,
                   lang: str = "en") -> dict:
    from .timeline import DEFAULT_FROM, DEFAULT_TO

    frm = parse_as_of(from_) if from_ else DEFAULT_FROM
    end = parse_as_of(to) if to else DEFAULT_TO
    return timeline_payload(address_id, frm, end, lang_of(lang))


@app.get("/changes")
def changes(lang: str = "en") -> dict:
    return changes_payload(lang_of(lang))


@app.get("/changes/{test_id}")
def change_detail(test_id: str, lang: str = "en") -> dict:
    s = store()
    if test_id not in s.changes:
        raise HTTPException(404, f"unknown test_id {test_id!r}; known: {sorted(s.changes)}")
    lang = lang_of(lang)
    full = s.changes_full.get(test_id, {})
    return {"disclaimer": DISCLAIMER[lang], "lang": lang, "test_id": test_id, "test": full.get("test"),
            "our_rule_ids": full.get("our_rule_ids"), **s.changes[test_id], **change_texts(test_id, lang),
            "addresses": full.get("addresses", {})}


@app.get("/rules")
def rules(jurisdiction: str | None = None, category: str | None = None, as_of: str | None = None,
          lang: str = "en") -> dict:
    return rules_payload(parse_as_of(as_of), lang_of(lang), jurisdiction, category)


@app.get("/conflicts")
def conflicts(lang: str = "en") -> dict:
    s, eng = store(), engine(config.DEFAULT_AS_OF)
    flagged = [{"team_rule_id": r["team_rule_id"], "jurisdiction": r["jurisdiction"], "conflict_note": r.get("conflict_note")}
               for r in s.rules + s.attested if r.get("conflict_flag")]
    pairs = [sorted(p) for p in eng.pairs]
    return {"disclaimer": DISCLAIMER[lang_of(lang)], "module_a_conflicts": s.conflicts, "flagged_rules": flagged,
            "preemption_pairs": sorted(pairs), "open_questions": s.open_questions, "human_review": s.review}


@app.get("/audit")
def audit(lang: str = "en") -> dict:
    s = store()
    m = s.manifest
    return {"disclaimer": DISCLAIMER[lang_of(lang)],
            "extraction": {"snapshot": m.get("snapshot"), "prompt_version": m.get("prompt_version"),
                           "model": m.get("model"), "effort": m.get("effort"), "created_at": m.get("created_at"),
                           "cost_usd": m.get("cost_usd"), "documents": len(m.get("documents", {})),
                           "candidates": (m.get("counts") or {}).get("candidates")},
            "rules": {"exported": len(s.rules), "manifest_attested": len(s.attested),
                      "by_status": dict(Counter(r["status"] for r in s.rules))},
            "coverage_compiler": {"model": s.compiled.get("model"), "prompt_version": s.compiled.get("prompt_version"),
                                  "human_review_applied": s.compiled.get("human_review_applied")},
            "plain_language": {"model": s.plain.get("model"), "prompt_version": s.plain.get("prompt_version"),
                               "methods": dict(Counter(v["method"] for v in s.plain.get("rules", {}).values()))},
            "geocoder": _load(config.DATA_DIR / "jurisdictions.json").get("geocoder"),
            "addresses": len(s.facts), "default_as_of": config.DEFAULT_AS_OF.isoformat(),
            "human_review_entries": [r["id"] for r in s.review]}
