"""Spoken versions of the plain-language summaries (ElevenLabs text-to-speech).

    python -m api.audio --dry-run     default: build and measure the texts, NO API call
    python -m api.audio --generate    call ElevenLabs for what is not cached (within the budget)

One MP3 per rule and language (every rule in out/rules.json + the manifest-attested rules, en and
es) at data/audio/<lang>/<team_rule_id>.mp3, plus data/audio/manifest.json (text hash, voice,
model, output format, characters per file, characters spent).

Text read aloud: what_it_means + who_it_covers + what_you_can_do from data/plain_language.json
joined with "Who it covers:" / "A quién cubre:" and "What you can do:" / "Lo que usted puede
hacer:" (no status line: the audio stays valid when the date changes). ``speakable`` normalizes it
for the voice: § -> section / sección, % -> percent / por ciento, $50 -> 50 dollars / 50 dólares,
acronyms expanded (RSO, CPI / IPC, AMI, NJ...).

ElevenLabs API (docs: POST /v1/text-to-speech/{voice_id}, header xi-api-key, body text +
model_id, query output_format): default model ``eleven_multilingual_v2`` (the API default,
English + Spanish; ``language_code`` is not supported for multilingual_v2 models, so it is sent only
for other models), output ``mp3_22050_32`` (the lightest MP3: 22.05 kHz, 32 kbps, mono voice).
Env: ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL (optional), AUDIO_CHAR_BUDGET
(default 115000).

Cache: a file is regenerated only if sha256(text | voice | model | format) changed or the MP3 is
missing. --generate aborts BEFORE any call if characters already spent + characters to generate
would exceed AUDIO_CHAR_BUDGET.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from extractor import config  # loads .env

AUDIO_DIR: Path = config.DATA_DIR / "audio"
MANIFEST_PATH: Path = AUDIO_DIR / "manifest.json"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_22050_32"
NO_LANGUAGE_CODE = {"eleven_multilingual_v2"}  # docs: language_code not supported for multilingual_v2
DEFAULT_BUDGET = 115_000
LANGS = ("en", "es")
JOIN = {"en": ("Who it covers:", "What you can do:"), "es": ("A quién cubre:", "Lo que usted puede hacer:")}

ACRONYMS = {
    "en": {"RSO": "Rent Stabilization Ordinance", "JCO": "Just Cause Ordinance", "CPI": "Consumer Price Index",
           "AMI": "Area Median Income", "LAHD": "Los Angeles Housing Department",
           "VASH": "Veterans Affairs Supportive Housing", "HUD": "H U D", "LLC": "limited liability company",
           "NJ": "New Jersey", "MA": "Massachusetts", "CA": "California", "TIC": "tenancy in common",
           "REIT": "real estate investment trust", "M.G.L.": "Massachusetts General Laws"},
    "es": {"RSO": "Ordenanza de Estabilización de Arrendamientos", "JCO": "Ordenanza de Causa Justa",
           "IPC": "índice de precios al consumidor", "CPI": "índice de precios al consumidor",
           "AMI": "ingreso medio del área", "LAHD": "Departamento de Vivienda de Los Ángeles",
           "VASH": "vivienda de apoyo para veteranos", "HUD": "H U D", "LLC": "compañía de responsabilidad limitada",
           "NJ": "Nueva Jersey", "MA": "Massachusetts", "CA": "California", "TIC": "propiedad en común",
           "REIT": "fideicomiso de inversión inmobiliaria", "M.G.L.": "Leyes Generales de Massachusetts"},
}


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #


def _sentence(s: str) -> str:
    s = s.strip()
    return s if not s or s[-1] in ".!?" else s + "."


def _money(m: re.Match, lang: str) -> str:
    whole, cents = m.group(1).replace(",", ""), m.group(2)
    if lang == "es":
        return f"{whole} dólares" + (f" con {int(cents)} centavos" if cents and int(cents) else "")
    return f"{whole} dollars" + (f" and {int(cents)} cents" if cents and int(cents) else "")


def _percent(m: re.Match, lang: str) -> str:
    n = m.group(1).replace(",", "") if lang == "en" else m.group(1)
    if lang == "es":
        n = re.sub(r"^(\d+)[.,](\d+)$", r"\1 punto \2", n)
        return f"{n} por ciento"
    return f"{n} percent"


def speakable(text: str, lang: str) -> str:
    """Normalize a summary so a voice reads it well."""
    acr = ACRONYMS[lang]
    alt = "|".join(re.escape(k) for k in sorted(acr, key=len, reverse=True))
    s = re.sub(r"\s*\((" + alt + r")\)", "", text)  # "... Department (LAHD)": the name is already spoken
    s = re.sub(r"(\d+(?:[.,]\d+)?)\s?% AMI\b", r"\1% of the AMI" if lang == "en" else r"\1% del AMI", s)
    s = re.sub(r"\$(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?", lambda m: _money(m, lang), s)
    s = re.sub(r"(\d+(?:[.,]\d+)?)\s?%", lambda m: _percent(m, lang), s)
    s = s.replace("§§", " secciones " if lang == "es" else " sections ").replace(
        "§", " sección " if lang == "es" else " section ")
    s = re.sub(r"(?<![\w.])(" + alt + r")(?![\w])", lambda m: acr[m.group(1)], s)
    s = s.replace("—", ", ").replace("–", " a " if lang == "es" else " to ").replace("…", ".")
    s = re.sub(r"(\d),(\d{3})\b", r"\1\2", s)  # 1,500 -> 1500 (no pause in the number)
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def script(entry: dict, lang: str) -> str:
    """The exact text read aloud for one rule in one language (no status line)."""
    p = entry[lang]
    who, can = JOIN[lang]
    raw = " ".join([_sentence(p["what_it_means"]), who, _sentence(p["who_it_covers"]), can,
                    _sentence(p["what_you_can_do"])])
    return speakable(raw, lang)


def rule_ids() -> list[str]:
    ids = [r["team_rule_id"] for r in json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]]
    if config.ATTESTED_PATH.exists():
        ids += [r["team_rule_id"] for r in json.loads(config.ATTESTED_PATH.read_text(encoding="utf-8"))["rules"]]
    return ids


# --------------------------------------------------------------------------- #
# Plan / cache
# --------------------------------------------------------------------------- #


def settings() -> dict:
    return {"api_key": os.getenv("ELEVENLABS_API_KEY", "").strip(), "voice_id": os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
            "model_id": os.getenv("ELEVENLABS_MODEL", "").strip() or DEFAULT_MODEL, "output_format": OUTPUT_FORMAT,
            "budget": int(os.getenv("AUDIO_CHAR_BUDGET", DEFAULT_BUDGET))}


def cache_key(text: str, voice_id: str, model_id: str, output_format: str) -> str:
    return hashlib.sha256("|".join([text, voice_id, model_id, output_format]).encode("utf-8")).hexdigest()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"output_format": OUTPUT_FORMAT, "spent_characters": 0, "items": {}}


def plan(cfg: dict) -> list[dict]:
    plain = json.loads((config.DATA_DIR / "plain_language.json").read_text(encoding="utf-8"))["rules"]
    items = load_manifest()["items"]
    out = []
    for rid in rule_ids():
        for lang in LANGS:
            text = script(plain[rid], lang)
            key = cache_key(text, cfg["voice_id"], cfg["model_id"], cfg["output_format"])
            path = AUDIO_DIR / lang / f"{rid}.mp3"
            cached = items.get(f"{lang}/{rid}", {}).get("cache_key") == key and path.exists()
            out.append({"team_rule_id": rid, "lang": lang, "text": text, "characters": len(text), "cache_key": key,
                        "path": path, "cached": cached})
    return out


# --------------------------------------------------------------------------- #
# Generation (--generate only)
# --------------------------------------------------------------------------- #


def synthesize(text: str, lang: str, cfg: dict, retries: int = 4) -> bytes:
    body = {"text": text, "model_id": cfg["model_id"]}
    if cfg["model_id"] not in NO_LANGUAGE_CODE:
        body["language_code"] = lang
    req = urllib.request.Request(API_URL.format(voice_id=cfg["voice_id"]) + f"?output_format={cfg['output_format']}",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": cfg["api_key"], "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(f"ElevenLabs HTTP {e.code}: {detail}") from None
    raise RuntimeError("unreachable")


def generate(cfg: dict, log=print) -> dict:
    if not cfg["api_key"] or not cfg["voice_id"]:
        raise SystemExit("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID must be set in .env")
    todo = [x for x in plan(cfg) if not x["cached"]]
    manifest = load_manifest()
    need = sum(x["characters"] for x in todo)
    if manifest["spent_characters"] + need > cfg["budget"]:
        raise SystemExit(f"ABORT before any call: spent {manifest['spent_characters']} + needed {need} > "
                         f"AUDIO_CHAR_BUDGET {cfg['budget']}")
    for i, x in enumerate(todo, 1):
        audio = synthesize(x["text"], x["lang"], cfg)
        x["path"].parent.mkdir(parents=True, exist_ok=True)
        x["path"].write_bytes(audio)
        manifest["spent_characters"] += x["characters"]
        manifest["items"][f"{x['lang']}/{x['team_rule_id']}"] = {
            "file": x["path"].relative_to(AUDIO_DIR).as_posix(), "cache_key": x["cache_key"],
            "text_sha256": hashlib.sha256(x["text"].encode("utf-8")).hexdigest(), "voice_id": cfg["voice_id"],
            "model_id": cfg["model_id"], "output_format": cfg["output_format"], "characters": x["characters"],
            "bytes": len(audio), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        manifest["output_format"] = cfg["output_format"]
        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        log(f"[{i}/{len(todo)}] {x['lang']}/{x['team_rule_id']}: {x['characters']} chars, {len(audio)} bytes")
    return {"generated": len(todo), "characters": need, "spent_total": manifest["spent_characters"]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def dry_run(cfg: dict) -> dict:
    items = plan(cfg)
    by_lang = {l: sum(x["characters"] for x in items if x["lang"] == l) for l in LANGS}
    todo = [x for x in items if not x["cached"]]
    spent = load_manifest()["spent_characters"]
    need = sum(x["characters"] for x in todo)
    return {"files": len(items), "rules": len(items) // len(LANGS), "total": sum(by_lang.values()), "by_lang": by_lang,
            "avg_per_rule": {l: round(by_lang[l] / (len(items) // len(LANGS))) for l in LANGS},
            "cached": len(items) - len(todo), "to_generate": len(todo), "characters_to_generate": need,
            "spent": spent, "within_budget": spent + need <= cfg["budget"],
            "longest": sorted(items, key=lambda x: -x["characters"])[:3], "items": items}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: no API call")
    mode.add_argument("--generate", action="store_true", help="call ElevenLabs for files not cached")
    ap.add_argument("--show", nargs="*", default=[], metavar="LANG/RULE", help="print the exact text, e.g. es/SF-RENT-01")
    args = ap.parse_args(argv)
    cfg = settings()
    key = cfg["api_key"]
    print(f"ELEVENLABS_API_KEY: {'set' if key else 'MISSING'}"
          + (f" ({len(key)} chars, prefix {key[:3]}…, not printed)" if key else ""))
    print(f"ELEVENLABS_VOICE_ID: {cfg['voice_id'] or 'MISSING'} ({len(cfg['voice_id'])} chars)")
    print(f"model: {cfg['model_id']} · output_format: {cfg['output_format']} · AUDIO_CHAR_BUDGET: {cfg['budget']}")
    if args.generate:
        print(generate(cfg))
        return
    r = dry_run(cfg)
    print(f"\nDRY RUN (no API call): {r['files']} files = {r['rules']} rules × {len(LANGS)} languages")
    print(f"characters: total {r['total']} · en {r['by_lang']['en']} · es {r['by_lang']['es']} · "
          f"average per rule en {r['avg_per_rule']['en']} / es {r['avg_per_rule']['es']}")
    print(f"cache: {r['cached']} cached · {r['to_generate']} to generate ({r['characters_to_generate']} chars) · "
          f"spent so far {r['spent']} · budget {cfg['budget']} → {'OK' if r['within_budget'] else 'WOULD ABORT'}")
    print("\nlongest texts:")
    for x in r["longest"]:
        print(f"  {x['lang']}/{x['team_rule_id']}: {x['characters']} chars")
    for want in args.show:
        lang, rid = want.split("/", 1)
        x = next(i for i in r["items"] if i["lang"] == lang and i["team_rule_id"] == rid)
        print(f"\n--- {lang}/{rid} ({x['characters']} chars) ---\n{x['text']}")


if __name__ == "__main__":
    main()
