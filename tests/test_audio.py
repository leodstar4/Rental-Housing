"""api/audio.py: speakable text, plan and budget guard. No ElevenLabs call (synthesize is patched)."""

from __future__ import annotations

import pytest

from api import audio


@pytest.mark.parametrize("lang,src,want", [
    ("en", "no more than $50 to apply", "no more than 50 dollars to apply"),
    ("es", "más de $1,500 al mes", "más de 1500 dólares al mes"),
    ("en", "a fee of $68.96", "a fee of 68 dollars and 96 cents"),
    ("es", "una cuota de $68.96", "una cuota de 68 dólares con 96 centavos"),
    ("en", "5% plus CPI, max 10%", "5 percent plus Consumer Price Index, max 10 percent"),
    ("es", "un 8.9% según el IPC", "un 8 punto 9 por ciento según el índice de precios al consumidor"),
    ("en", "Cal. Civ. Code § 1947.12", "Cal. Civ. Code section 1947.12"),
    ("es", "artículo § 8.72", "artículo sección 8.72"),
    ("en", "households (80% AMI or below)", "households (80 percent of the Area Median Income or below)"),
    ("es", "hogares (80% AMI o menos)", "hogares (80 por ciento del ingreso medio del área o menos)"),
    ("en", "the Housing Department (LAHD). Ask LAHD", "the Housing Department. Ask Los Angeles Housing Department"),
    ("en", "units under the RSO in Hoboken, NJ", "units under the Rent Stabilization Ordinance in Hoboken, New Jersey"),
])
def test_speakable(lang, src, want):
    assert audio.speakable(src, lang) == want


def test_script_joins_sections_without_status():
    e = {"en": {"what_it_means": "A", "who_it_covers": "B", "what_you_can_do": "C"},
         "es": {"what_it_means": "A", "who_it_covers": "B", "what_you_can_do": "C"}}
    assert audio.script(e, "en") == "A. Who it covers: B. What you can do: C."
    assert audio.script(e, "es") == "A. A quién cubre: B. Lo que usted puede hacer: C."


def test_plan_covers_every_rule_and_language():
    cfg = {"api_key": "", "voice_id": "v", "model_id": audio.DEFAULT_MODEL, "output_format": audio.OUTPUT_FORMAT,
           "budget": audio.DEFAULT_BUDGET}
    items = audio.plan(cfg)
    assert len(items) == 2 * len(audio.rule_ids()) and {x["lang"] for x in items} == {"en", "es"}
    for x in items:
        assert not any(s in x["text"] for s in ("§", "%", "$", "Vigente", "In force since")), x["team_rule_id"]
    assert sum(x["characters"] for x in items) <= audio.DEFAULT_BUDGET


def test_generate_aborts_before_any_call_over_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(audio, "MANIFEST_PATH", tmp_path / "manifest.json")
    calls = []
    monkeypatch.setattr(audio, "synthesize", lambda *a, **k: calls.append(a) or b"ID3")
    cfg = {"api_key": "k", "voice_id": "v", "model_id": audio.DEFAULT_MODEL, "output_format": audio.OUTPUT_FORMAT,
           "budget": 100}
    with pytest.raises(SystemExit, match="ABORT before any call"):
        audio.generate(cfg, log=lambda *_: None)
    assert calls == []


def test_api_serves_audio_and_audio_url(tmp_path, monkeypatch):
    """audio_url only when the file exists; /audio/... is audio/mpeg with long cache headers."""
    import json

    from fastapi.testclient import TestClient

    from api import main

    (tmp_path / "es").mkdir()
    (tmp_path / "es" / "SF-RENT-01.mp3").write_bytes(b"ID3fake-mp3")
    (tmp_path / "manifest.json").write_text(json.dumps({"items": {"es/SF-RENT-01": {
        "file": "es/SF-RENT-01.mp3", "text_sha256": "abcdef1234"}, "en/SF-RENT-01": {
        "file": "en/SF-RENT-01.mp3", "text_sha256": "0000"}}}), encoding="utf-8")
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path)
    main.store.cache_clear()
    try:
        app_mount = next(r for r in main.app.routes if getattr(r, "name", "") == "audio")
        monkeypatch.setattr(app_mount.app, "directory", tmp_path)
        monkeypatch.setattr(app_mount.app, "all_directories", [tmp_path])
        with TestClient(main.app) as c:
            es = c.get("/lookup/A0016", params={"lang": "es"}).json()
            urls = {x["team_rule_id"]: x["audio_url"] for g in es["results"].values() for x in g}
            assert urls["SF-RENT-01"] == "/audio/es/SF-RENT-01.mp3?v=abcdef12"
            assert all(u is None for r, u in urls.items() if r != "SF-RENT-01")
            en = c.get("/lookup/A0016").json()  # manifest entry but no file -> null
            assert all(x["audio_url"] is None for g in en["results"].values() for x in g)
            rules = {r["team_rule_id"]: r["audio_url"] for r in c.get("/rules", params={"lang": "es"}).json()["rules"]}
            assert rules["SF-RENT-01"] == urls["SF-RENT-01"]
            r = c.get(urls["SF-RENT-01"])
            assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
            assert "max-age=31536000" in r.headers["cache-control"] and r.content == b"ID3fake-mp3"
            assert c.get("/audio/es/NOPE.mp3").status_code == 404
    finally:
        main.store.cache_clear()


def test_generate_caches_by_text_voice_model(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(audio, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(audio, "rule_ids", lambda: ["CA-RENT-01"])
    calls = []
    monkeypatch.setattr(audio, "synthesize", lambda text, lang, cfg: calls.append(lang) or b"ID3fake")
    cfg = {"api_key": "k", "voice_id": "v", "model_id": audio.DEFAULT_MODEL, "output_format": audio.OUTPUT_FORMAT,
           "budget": 10_000}
    r = audio.generate(cfg, log=lambda *_: None)
    assert r["generated"] == 2 and (tmp_path / "es" / "CA-RENT-01.mp3").exists()
    assert audio.generate(cfg, log=lambda *_: None)["generated"] == 0  # cached
    assert audio.generate({**cfg, "voice_id": "other"}, log=lambda *_: None)["generated"] == 2  # new voice
    assert len(calls) == 4
    m = audio.load_manifest()
    assert m["items"]["en/CA-RENT-01"]["voice_id"] == "other" and m["spent_characters"] == 2 * r["characters"]
