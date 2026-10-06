"""mx.verify on FIXTURE data (tests/fixtures/mx): quote cascade, hashes, id and kind rules. Offline."""

from __future__ import annotations

import json

import pytest
import yaml
from mx_support import mx_env  # noqa: F401  (pytest fixture)

from extractor import config
from extractor.validate import match_span
from mx import verify


def _drop_bad_zone_stats(env):
    """The zones fixture deliberately carries two unsourced stats (API tests); remove them here."""
    p = env.data / "zones.json"
    z = json.loads(p.read_text(encoding="utf-8"))
    stats = z["states"][0]["municipios"][0]["stats"]
    stats.pop("sin_fuente")
    stats.pop("fuente_desconocida")
    p.write_text(json.dumps(z, ensure_ascii=False), encoding="utf-8")


def _edit_req(env, file, rid, **changes):
    p = env.data / "requirements" / file
    items = yaml.safe_load(p.read_text(encoding="utf-8"))
    for it in items:
        if it["id"] == rid:
            it.update(changes)
    p.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _results(env):
    r = verify.verify_all(env.data, env.corpus)
    return r, {x.id: x for x in r.results}


def test_fixture_verifies_with_each_match_type(mx_env):
    _drop_bad_zone_stats(mx_env)
    report, res = _results(mx_env)
    assert report.ok, report.as_json()
    assert {k: v.match_type for k, v in res.items()} == {
        "MX-FED-FIRMA-01": "exact", "MX-FED-DATOS-01": "exact", "MX-FED-COMILLAS-01": "normalized",
        "MX-FED-GUION-01": "normalized_mx", "MX-CDMX-DEPOSITO-01": "exact", "MX-CDMX-FORMA-01": "exact"}
    # served quote = literal source fragment (curly quotes kept, whitespace collapsed)
    assert "“comillas curvas”" in res["MX-FED-COMILLAS-01"].quote_verified
    assert "arren- damiento" in res["MX-FED-GUION-01"].quote_verified


def test_cascade_matches_extractor_match_span(mx_env):
    raw = (mx_env.corpus / "fed" / "fed_fixture.txt").read_text(encoding="utf-8")
    idx = verify.DocIndex(raw)
    for q in ("Las partes de un contrato de prueba podrán expresar",
              'Disposición ficticia con "comillas curvas" y un salto de línea en medio'):
        m, mine = match_span(raw, q, allow_fuzzy=False), idx.match(q)
        assert (m.match_type, m.raw_start, m.raw_end) == mine
    assert match_span(raw, "el arrendamiento de prueba se rige", allow_fuzzy=False) is None
    assert idx.match("el arrendamiento de prueba se rige")[0] == "normalized_mx"


def test_changed_word_fails_and_main_exits_1(mx_env):
    _drop_bad_zone_stats(mx_env)
    _edit_req(mx_env, "FED.yaml", "MX-FED-FIRMA-01",
              quote="Las partes de un contrato de prueba deberán expresar su consentimiento por medios electrónicos")
    _, res = _results(mx_env)
    assert res["MX-FED-FIRMA-01"].status == "failed"
    assert verify.main([]) == 1
    out = json.loads((config.OUT_DIR / "mx_validation.json").read_text(encoding="utf-8"))
    assert out["ok"] is False and out["counts"]["failed"] == 1


def test_main_exit_0_when_all_verify(mx_env):
    _drop_bad_zone_stats(mx_env)
    assert verify.main([]) == 0


def test_short_quote_fails(mx_env):
    _edit_req(mx_env, "FED.yaml", "MX-FED-FIRMA-01", quote="Las partes")
    _, res = _results(mx_env)
    assert any("longitud" in e for e in res["MX-FED-FIRMA-01"].errors)


def test_altered_text_invalidates_every_quote_of_the_doc(mx_env):
    p = mx_env.corpus / "fed" / "fed_fixture.txt"
    p.write_bytes(p.read_bytes() + b"\nTexto agregado.\n")
    report, res = _results(mx_env)
    assert report.sources.docs["D-MX-FED-01"].status == "hash_mismatch"
    assert all(res[r].status == "failed" for r in res if r.startswith("MX-FED"))
    assert res["MX-CDMX-DEPOSITO-01"].status == "verified"


def test_practica_cannot_feed_the_contract(mx_env):
    _edit_req(mx_env, "FED.yaml", "MX-FED-DATOS-01", kind="practica")
    _, res = _results(mx_env)
    assert any("practica" in e for e in res["MX-FED-DATOS-01"].errors)


def test_id_prefix_and_cross_jurisdiction_rules(mx_env):
    _edit_req(mx_env, "FED.yaml", "MX-FED-FIRMA-01", jurisdiction="CDMX")
    _edit_req(mx_env, "CDMX.yaml", "MX-CDMX-FORMA-01", doc_id="D-MX-FED-01")
    _, res = _results(mx_env)
    assert any("no coinciden" in e for e in res["MX-FED-FIRMA-01"].errors)
    assert any("no puede citar" in e for e in res["MX-CDMX-FORMA-01"].errors)


def test_check_value_must_appear_in_quote(mx_env):
    _edit_req(mx_env, "CDMX.yaml", "MX-CDMX-DEPOSITO-01",
              checks=[{"field": "deposit_months", "op": "le", "value": 3}])
    _, res = _results(mx_env)
    assert any("no aparece" in e for e in res["MX-CDMX-DEPOSITO-01"].errors)


def test_unknown_field_and_unknown_doc_fail(mx_env):
    _edit_req(mx_env, "FED.yaml", "MX-FED-FIRMA-01", inventado="x")
    _edit_req(mx_env, "FED.yaml", "MX-FED-DATOS-01", doc_id="D-MX-FED-77")
    _, res = _results(mx_env)
    assert res["MX-FED-FIRMA-01"].status == res["MX-FED-DATOS-01"].status == "failed"


def test_zone_stat_without_known_source_is_an_error(mx_env):
    report, _ = _results(mx_env)
    assert not report.ok and any("sin_fuente" in e for e in report.errors)


@pytest.mark.parametrize("value,quote,ok", [("2", "no podrá exceder de 2 meses", True),
                                            ("1", "no podrá exceder de un mes", True),
                                            ("3", "no podrá exceder de 2 meses", False),
                                            ("2", "no podrá exceder de 12 meses", False)])
def test_value_in_quote(value, quote, ok):
    from decimal import Decimal

    assert verify._value_in_quote(Decimal(value), quote) is ok
