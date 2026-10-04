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
