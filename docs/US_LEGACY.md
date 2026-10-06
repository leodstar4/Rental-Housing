# US legacy (frozen)

The original Rental Housing Law Navigator (US state/city housing law) is **frozen**. Renta MX is
the active product; the US pipeline and routes stay in the repo, reproducible, but are no longer
part of the deploy build and are **tolerant of a missing `out/`**.

> ⚖️ Information prototype. **Not legal advice.**

## What is frozen

| Area | Paths | Status |
|---|---|---|
| Module A — extraction | `extractor/` | frozen; snapshot `snapshots/a-0.4.0/` is immutable |
| Module B/C — resolver | `resolver/` | frozen |
| US API routes | `api/main.py` (`/lookup`, `/explain`, `/timeline`, `/changes`, `/changes/{id}`, `/rules`, `/conflicts`), `api/explain.py`, `api/timeline.py`, `api/export_static.py` | frozen; still mounted |
| Frozen snapshot | `snapshots/a-0.4.0/` | immutable (raw model output, prompt, ids, cost) |
| Versioned US data | `data/building_facts.json`, `data/jurisdictions.json`, `data/compiled_exemptions.json`, `data/plain_language.json`, `data/*.yaml` | versioned, unchanged |
| Audio | `data/audio/` (US rule MP3s) | frozen |

Renta MX (`mx/`, `api/mx.py`, `corpus_mx/`, `data/mx/`, the `/mx/*` routes) and the frontend are
**not** frozen.

## Behavior when `out/` is absent (e.g. on Render)

The Render build no longer runs `python -m extractor.cli reproduce` or
`python -m resolver.cli changes`, so the US `out/` artifacts (`out/rules.json`,
`out/rules_normalized.json`, `out/changes.json`, …) are not generated during deploy. The API is
tolerant of this:

- The service **starts normally**; the versioned `data/` files load as usual.
- `GET /health` returns **200** with `"us_data": false` (and `true` when the US `out/` files are
  present). `GET /mx/health` always answers.
- The US routes return **503** with a clear detail
  (`"US (legacy) data is not available on this instance; regenerate it with …"`).
- `GET /addresses` and `GET /audit` keep working from the versioned data/snapshot.

Readiness is decided by `api.main.US_DATA_FILES` (currently `out/rules.json` and
`out/rules_normalized.json`).

## Regenerate `out/` locally

To serve the US routes locally (no API key needed — everything replays from the frozen
snapshot):

```sh
python -m extractor.cli reproduce      # Module A from snapshots/a-0.4.0 -> out/rules.json (~5 s)
python -m resolver.cli lookup          # Module B -> out/lookups.json + out/lookups_full.json
python -m resolver.cli changes         # Module C -> out/changes.json + T1–T5 dashboard
```

Then `uvicorn api.main:app --reload` serves the US routes too (`/health` reports
`"us_data": true`). Optional self-checks:

```sh
python -m extractor.cli smoke-check
python -m pytest -q
```

To host the US answers on Render as well, add those commands back to `buildCommand` in
`render.yaml` (they add ~10 s and no API calls), or serve the static backup
(`python -m api.export_static` → `static/`).
