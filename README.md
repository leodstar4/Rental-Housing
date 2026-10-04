# Rental Housing Law Navigator

MIT AI Hackathon challenge *Rental Housing Law Navigator* (RealPage discussion draft, October
2026). The system reads the starter-pack corpus of real U.S. rental-housing law (California, New
Jersey, Massachusetts and ten of their cities) and answers, for each of 500 sample apartment
addresses, **which rules apply on a query date, with citations**, and how the supplied change
cases affect the answer.

* **Module A — rule extraction** (`extractor/`): structured, citation-backed rule records,
  `out/rules.json`, valid against `schema/rule_record.schema.json`. Every rule carries a
  `quoted_span` verified in the source text and a status computed — never guessed — from its
  legislative stage and dates.
* **Module B — address lookup** (`resolver/`): building facts, jurisdiction stacks (Census
  Geocoder), three-valued coverage, precedence → `out/lookups.json` for all 500 addresses.
* **Module C — change tracking** (`resolver/changes.py`): `out/changes.json` for tests T1–T5,
  plus the hour-16 flow (T6) for a new document.
* **API** (`api/`): read-only FastAPI service with plain-language summaries in English and
  Spanish, a static backup and a Render blueprint (contract in `docs/API.md`).

> ⚖️ **Not legal advice.** This is an information prototype, not legal counsel or a compliance
> certification. Summaries of law here are for building a prototype.

---

## Contents

1. [Results at a glance](#results-at-a-glance)
2. [Quick start](#quick-start)
3. [Commands](#commands)
4. [Project layout](#project-layout)
5. [How the pipeline works](#how-the-pipeline-works)
6. [Extraction (LLM)](#extraction-llm)
7. [Validation](#validation-validatepy)
8. [Normalization](#normalization-normalizepy-no-llm)
9. [Conflicts](#conflicts-conflictspy)
10. [Status and calendar defaults](#status-statuspy)
11. [Export](#export-exportpy)
12. [Reproducing from the snapshot](#reproducing-from-the-snapshot-no-api-key)
13. [Incremental mode — `extract-doc`](#incremental-mode--extract-doc)
14. [Smoke check](#smoke-check)
15. [Outputs and audit log](#outputs-and-audit-log)
16. [Preguntas abiertas no resolubles con el corpus](#preguntas-abiertas-no-resolubles-con-el-corpus)
17. [Module B — adjustments to the rules](#module-b--adjustments-to-the-rules)
18. [Module B — building facts and jurisdictions](#module-b--building-facts-and-jurisdictions)
19. [Module B — coverage (three-valued)](#module-b--coverage-three-valued)
20. [Module B — lookups](#module-b--lookups-results-per-address)
21. [Module C — change tracking](#module-c--change-tracking) · [Hour 16 runbook](#hour-16-runbook)
22. [API and plain language](#api-fastapi-and-plain-language)
23. [Responsible design](#responsible-design)
24. [Known limitations and design decisions](#known-limitations-and-design-decisions)
25. [Prompt history](#prompt-history)
26. [Cost](#cost)
27. [Tests](#tests)
28. [Versioning and release](#versioning-and-release)

---

## Results at a glance

Extraction: frozen snapshot **`a-0.4.0`** (prompt `a-0.4.0`, `claude-opus-5-5`, effort `high`),
query date **2026-10-01**. Figures below are the current export (the snapshot plus the Module B
adjustments to the rules, which make no API call).

| | |
|---|---|
| Documents with text in the corpus | 54 of 87 (the rest are link-only / check-terms / failed capture) |
| Candidate rules extracted | 103 |
| Quotes verified | 103/103 (86 exact, 16 normalized, 1 fuzzy, 0 needed an LLM retry); 0 rejected |
| Rules exported to `rules.json` | **65** (schema-valid) |
| Held internally (not exported) | 12 (7 `no_citation`, 5 `administrative_unlinked`) |
| Folded into other rules | 26 (10 duplicates, 15 administrative figures, 1 human review merge) |
| Status on 2026-10-01 | 57 `in_force` · 4 `pending` · 3 `failed` · 1 `not_yet_effective` |
| Manifest-attested rules (no corpus text, `out/rules_attested.json`) | 3 (Hoboken and Jersey City algorithmic bans, MA rent-control ballot question) |
| Conflicts between documents | 2 flagged pairs + 2 informational records |
| Smoke check | **all checks pass** (pipeline 3/3, behaviour T1/T3/T4/T5 7/7, change-test rule map 7/7; 20 of 23 expected citations found, 3 absent because their source is link-only) |
| Change tests (Module C dashboard) | **14/14 pass** (T1 250 CA · T2 40 / 50 / 0 · T3 140 NJ, 90 flagged · T4 110 pending · T5 empty) |
| Address lookups | 500 addresses; results `applies` / `unknown` / `superseded` / `not_yet_effective` / `pending` with explanation and citation |

Exported rules by jurisdiction × category:

| Jurisdiction | rent_increase | just_cause | deposits | app_fees | screening | algorithmic | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| CA | 1 | 2 | 6 | 2 | 2 | 1 | 14 |
| NJ | 3 | 2 | 3 | 1 | 2 | 1 | 12 |
| MA | 2 | 1 | 1 | 2 | 1 | 2 | 9 |
| Berkeley, CA | 2 | 1 | 1 | 2 | 1 | 1 | 8 |
| Los Angeles, CA | 5 | 6 | · | · | · | · | 11 |
| San Diego, CA | · | 1 | · | · | · | 1 | 2 |
| San Francisco, CA | 1 | 1 | · | · | 1 | 1 | 4 |
| Santa Ana, CA | 1 | 2 | · | · | · | · | 3 |
| Hoboken, NJ | · | · | · | · | · | · | 0 |
| Jersey City, NJ | 1 | · | · | · | · | · | 1 |
| Newark, NJ | · | · | · | · | · | · | 0 |
| Boston, MA | · | · | · | · | · | · | 0 |
| Cambridge, MA | · | · | · | · | 1 | · | 1 |
| **Total** | 16 | 16 | 11 | 7 | 8 | 7 | **65** |

Empty cells are explained by the corpus, not by the pipeline: Hoboken and Newark have no
supplied text (their codes are `check-terms` on ecode360), Boston and Cambridge cannot have a
rent cap (M.G.L. c. 40P), and several city ordinances are link-only (see
[Preguntas abiertas](#preguntas-abiertas-no-resolubles-con-el-corpus)).

Change-test checks on the exported rules:

| Test | Rule | Expected | Result |
|---|---|---|---|
| T1 — CA AB 325 | `CA-ALG-01` (Cal. Bus. & Prof. Code § 16729) | `not_yet_effective` 2025-12-31, `in_force` 2026-01-02 | ✅ (effective 2026-01-01 derived from the CA calendar default) |
| T2 — Hoboken / Jersey City bans | `HOB-ALG-A1`, `JC-ALG-A1` (manifest-attested) | each only inside its own city, none in Newark | ✅ |
| T3 — NJ FAIR Act | `NJ-ALG-01` (P.L.2026, c.43) | `not_yet_effective` 2026-10-01, `in_force` 2027-07-02, conflict at Hoboken / Jersey City | ✅ (2027-07-01 derived from "first day of the twelfth month next following enactment", approved 2026-07-20) |
| T4 — MA S.2983 / H.5222 | `MA-ALG-P2`, `MA-ALG-P1` | `pending` | ✅ |
| T5 — MA rent-control ballot question | `MA-RENT-A1` (attested, `failed`) | no rent cap in force in MA / Boston / Cambridge | ✅ (M.G.L. c. 40P is reported: it bars local rent control → no local cap) |

---

## Quick start

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Rebuild out/ from the frozen snapshot — no API key needed, ~5 s
python -m extractor.cli reproduce

# Dashboard of checks (pipeline, expected citations, T1/T3/T4/T5, change-test rule map)
python -m extractor.cli smoke-check

# Module B + C from the versioned data (no API key)
python -m resolver.cli lookup          # out/lookups.json + out/lookups_full.json
python -m resolver.cli changes         # out/changes.json + T1-T5 dashboard

# API
uvicorn api.main:app --reload          # http://localhost:8000/docs
```

An API key is only needed to extract **new** text (full re-extraction or `extract-doc`) or to
recompile coverage / plain language for changed rules:

```bash
cp .env.example .env                   # then set ANTHROPIC_API_KEY
```

The starter pack is expected at `./participant-final-no-hour16 3/` (override with
`STARTER_DIR`).

### Configuration

Settings live in `extractor/config.py` (and the module named), overridable via environment
variables or `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(only for new model output)* | API key — read only from the environment, never logged or cached |
| `EXTRACT_MODEL` | `claude-opus-5-5` | Extraction model |
| `EXTRACT_EFFORT` | `high` | Effort for extraction calls (Opus 5.5 defaults to `medium`, so it is set explicitly) |
| `EXTRACT_MAX_TOKENS` | `32000` | Max output per extraction call (streamed) |
| `EXTRACT_CONCURRENCY` | `4` | Documents extracted in parallel |
| `LLM_MAX_RETRIES` | `4` | SDK retries with exponential backoff (408/409/429/5xx) |
| `QUOTE_RETRY_EFFORT` | `medium` | Effort for the single quote-retry call in validation |
| `DATE_CLASSIFIER_MODEL` | `claude-haiku-4-5` | Small model for ambiguous date kinds |
| `COMPILE_MODEL` | `claude-haiku-4-5` | Coverage/exemption compiler (`resolver/compile_exemptions.py`) |
| `PLAIN_MODEL` | `claude-haiku-4-5` | Plain-language summaries (`api/plain_language.py`) |
| `PRESUME_SPECIAL_STATUS` | `true` | Presume special-status exemptions absent unless the data shows them (`resolver/coverage.py`) |
| `ALLOWED_ORIGINS` | *(empty)* | Extra exact CORS origins for the API (Lovable domains are allowed by default) |
| `AS_OF` | `2026-10-01` | Default query date |
| `STARTER_DIR` | `participant-final-no-hour16 3` | Starter pack location |
| `OUT_DIR` / `CACHE_DIR` | `out/` / `.cache/` | Outputs / on-disk LLM cache (both git-ignored) |

Dependencies (pinned in `requirements.txt`): `anthropic`, `pydantic`, `typer`,
`jsonschema`, `python-dotenv`, `rapidfuzz`, `pyyaml`, `pypdf`, `pytest`, `fastapi`, `uvicorn`,
`httpx`.

---

## Commands

```bash
# --- Module A -------------------------------------------------------------------------------
# Reproduce from the frozen snapshot (offline): extract-all --from-snapshot + normalize + export + attest
python -m extractor.cli reproduce [--snapshot snapshots/a-0.4.0] [--as-of 2026-10-01]

# Offline dashboard: pipeline invariants, expected citations, T1/T3/T4/T5, change-test rule map
python -m extractor.cli smoke-check

# Incremental mode (hour 16): add ONE new document (.txt/.pdf/.html) on top of the snapshot
python -m extractor.cli extract-doc path/to/ordinance.pdf --jurisdiction "Cambridge, MA"

# Export for another query date (status and effective dates are recomputed, no LLM)
python -m extractor.cli export --as-of 2027-07-02

# Manifest-attested rules (no corpus text) -> out/rules_attested.json
python -m extractor.cli attest

# Full re-extraction with the API (cached in .cache/), then freeze it as a new snapshot
python -m extractor.cli extract-all [--only D022 --only D069] [--no-cache]
python -m extractor.cli normalize [--ids-from snapshots/a-0.4.0/ids.json]
python -m extractor.cli export --as-of 2026-10-01
python -m extractor.cli snapshot --name a-0.5.0

# --- Module B / C ---------------------------------------------------------------------------
python -m resolver.cli facts                      # data/building_facts.json
python -m resolver.cli geocode [--refresh]        # data/jurisdictions.json (reuses data/geocode_raw/)
python -m resolver.cli compile [--refresh]        # data/compiled_exemptions.json + review table
python -m resolver.cli coverage --as-of 2026-10-01
python -m resolver.cli lookup --as-of 2026-10-01 [--address A0016]
python -m resolver.cli changes                    # T1-T5
python -m resolver.cli changes --new-doc path/to/ordinance.txt --jurisdiction "Cambridge, MA"   # T6 (kept)
python scripts/hour16.py path/to/ordinance.pdf --jurisdiction "Cambridge, MA" [--dry-run]     # full hour-16 runbook

# --- API ------------------------------------------------------------------------------------
python -m api.plain_language [--only RULE_ID]     # data/plain_language.json
uvicorn api.main:app --reload
python -m api.export_static                       # static/ backup
```

---

## Project layout

```
.
├── extractor/                     # Module A: the pipeline, one module per stage
│   ├── cli.py                     # python -m extractor.cli <command>
│   ├── config.py                  # paths + settings (env/.env); PROMPT_VERSION read from the prompt file
│   ├── corpus.py                  # manifest + text/*.txt -> Document (header split, cleaning)
│   ├── clean.py                   # boilerplate removal (whole lines only) + clean->raw offset map
│   ├── llm.py                     # Anthropic client, record_rules tool, retries, cache, snapshot lookup
│   ├── extract.py                 # Document -> LLM -> RuleInternal[] (+ validation)
│   ├── validate.py                # quote cascade, date checks, dispositions, final confidence
│   ├── dates.py                   # date formats + date-kind classification
│   ├── normalize.py               # citations, citation resolution, defaults, merge, CO cutoffs, admin links,
│   │                              #   IDs, human review merges, precedence, review flags
│   ├── conflicts.py               # conflicts between documents -> out/conflicts.json
│   ├── status.py                  # status as of a date
│   ├── export.py                  # RuleInternal -> RuleOut -> out/rules.json (jsonschema-validated)
│   ├── attested.py                # manifest-attested rules -> out/rules_attested.json
│   ├── snapshot.py                # freeze / activate snapshots (reproduction without API)
│   ├── incremental.py             # extract-doc: one new document on top of a snapshot
│   ├── smoke.py                   # smoke-check dashboard
│   ├── audit.py                   # append-only out/audit.jsonl
│   └── models.py                  # pydantic models (RuleCandidate, RuleInternal, RuleOut, ...)
├── resolver/                      # Module B and C (python -m resolver.cli <command>)
│   ├── addresses.py               # sample_addresses.csv -> Address (all strings) + dataset city
│   ├── facts.py                   # building facts: units range, year built, use flags
│   ├── geocode.py                 # Census Geocoder -> jurisdiction stack
│   ├── predicates.py              # predicate grammar over building facts
│   ├── compile_exemptions.py      # coverage + exemptions -> predicates (code + small LLM)
│   ├── coverage.py                # Kleene three-valued coverage evaluator
│   ├── results.py                 # status + coverage + precedence -> lookups, explanations
│   ├── changes.py                 # Module C: change tests T1-T6
│   └── cli.py
├── api/                           # FastAPI service, plain language, static export
│   ├── main.py · plain_language.py · export_static.py
├── prompts/
│   ├── extract_system.md          # extraction prompt; first line declares PROMPT_VERSION
│   ├── quote_retry.md             # prompt for the single quote-retry call
│   └── compile_exemptions.md      # coverage compiler prompt (cx-0.4.0)
├── data/
│   ├── citation_aliases.yaml      # law alias table + citation formatting rules
│   ├── jurisdiction_defaults.yaml # calendar defaults (CA only)
│   ├── review_flags.yaml          # known open questions flagged for review (guide §9)
│   ├── human_review.yaml          # register of every manual correction (Responsible design)
│   ├── test_rule_map.yaml         # dev/change_tests.json ids -> our ids
│   ├── use_code_map.yaml          # use codes -> unit ranges and use flags
│   ├── other_law_map.yaml         # laws referred to by other rules (RSO, JCO, local rent control…)
│   ├── open_questions.yaml        # guide §9 questions served by GET /conflicts
│   ├── glossary_es.yaml           # fixed English -> Spanish legal terms
│   ├── building_facts.json · jurisdictions.json · geocode_raw/    # Module B data (versioned)
│   ├── compiled_exemptions.json · compiled_exemptions_review.md   # compiled coverage + review table
│   └── plain_language.json        # tenant summaries EN/ES
├── scripts/hour16.py · hour16.ps1 # hour-16 runbook (one command, --dry-run to rehearse)
├── docs/API.md                    # API contract with real responses
├── snapshots/a-0.4.0/             # frozen official extraction (versioned in git)
├── corpus/new/                    # documents added with extract-doc (created on demand)
├── tests/                         # offline pytest suite (+ fixtures, expected_citations.yaml)
├── participant-final-no-hour16 3/ # starter pack: corpus, schema, sample addresses, change tests, brief
├── render.yaml                    # Render blueprint for the API
├── .gitattributes                 # byte-exact files (no EOL conversion), see "Versioning"
├── requirements.txt
└── .env.example
```

---

## How the pipeline works

```
corpus.py     manifest + text/Dxxx.txt -> Document (SOURCE/RETRIEVED header split; link-only rows skipped)
clean.py      drop navigation/boilerplate WHOLE LINES only; keep a clean->raw offset map
extract.py    clean_text + manifest metadata -> LLM (record_rules tool) -> candidate rules
validate.py   quotes verified against raw_text; dates verified by value and classified by kind;
              dispositions; final confidence
normalize.py  citation style + aliases, citation resolution, calendar defaults, merge (incl. stage
              merge), certificate-of-occupancy cutoffs, administrative figures, stable team_rule_ids,
              human review merges, precedence, review flags
conflicts.py  conflicts between documents
status.py     status as of --as-of (never extracted)
export.py     accepted rules -> RuleOut -> out/rules.json (validated with jsonschema)
attested.py   laws named by the starter pack without text -> out/rules_attested.json
audit.py      every step appends to out/audit.jsonl
   ↓
resolver/     facts + geocode -> compile coverage -> Kleene coverage -> results (lookups) -> changes
api/          read-only HTTP API over the outputs
```

### Corpus loading (`corpus.py`)

* Loads `corpus_manifest.csv`; only rows with `status == ok` and a text file are loadable
  (54 documents). `links_only.csv` is never loaded as content; D056 (403 capture failure) is
  skipped.
* Each `text/Dxxx.txt` starts with `SOURCE:` / `RETRIEVED:` lines; `raw_text` is the body
  after that header, byte for byte (read with `newline=""`). The header URL must match the
  manifest URL.
* `text_sha256` is computed over `raw_text` (the manifest's `sha256` hashes the original
  HTML/PDF capture, not the text file) and keys the cache and the snapshot.

### Cleaning guarantees (`clean.py`)

* Only **whole lines** are removed; every kept line is byte-identical to the raw line, and a
  segment map converts clean offsets back to raw offsets.
* Site profiles (leginfo, malegislature, boston.gov, LAHD, sf.gov, CRD, Berkeley Rent Board,
  …) cut headers, footers and tab strips. A cut is **refused** if it would drop a line that
  looks like legal text (`shall`, `unlawful`, `may not`, `§`, `(a)`, `SEC. n`); refusals are
  reported.
* The page title line is **always kept** — it is often the only citation context (e.g.
  `General Law - Part II, Title I, Chapter 186, Section 11`).
* Quotes are verified against `raw_text`, **not** `clean_text`.

---

## Extraction (LLM)

One call per document: the cleaned text plus manifest metadata (`doc_id`, URL, retrieval
date, jurisdictions, source type), system prompt `prompts/extract_system.md`.

* **Tool `record_rules`** — its `input_schema` is generated from the pydantic model
  `RecordRulesInput` (`RuleCandidate`) and sent with `strict: true`, so the API guarantees
  schema-valid arguments. Claude Opus 5.5 rejects *forced* tool use (`tool_choice` `any` /
  `tool` → 400), so the request uses `tool_choice: auto` + an instruction to call the tool
  exactly once; if the model answers without exactly one valid call, the request is retried
  (up to 3 attempts, 2 s / 4 s backoff).
* **Typed exemptions vs grammar limit** — a fully typed union for `exemption_conditions`
  (boolean for `owner_occupied`, integer for `units`/`year_built`, ISO date for `co_date`)
  exceeds the API's compiled-grammar limit for strict tools. The strict schema therefore
  uses a flat `value: boolean | integer | string | list[string] | null` (so a JSON boolean is
  still a real boolean), and pydantic enforces the per-field type afterwards; an exemption
  whose value has the wrong type is moved to `coverage.notes` as `UNVERIFIABLE exemption …`
  instead of rejecting the whole rule.
* **What the model must NOT produce**: `status` (computed later), `team_rule_id`, and
  provenance (`source_doc_id`, `source_url`, `retrieved_at`), which are filled from the
  document. The prompt forbids completing dates, amounts or citations from outside knowledge.
* **Prompt rules** (a-0.4.0): one rule per (enacting jurisdiction × category × law), split only
  when coverage, key value or effective date differ; strict category definitions (general
  anti-discrimination rules are not recorded); quotes must start at a sentence or enumerated
  subsection and contain the operative verb; `is_secondary_source` only when a different
  jurisdiction enacts the rule; relative effective dates are computed when the same document
  gives the enactment date (`derived: true`); no general calendar rules in extraction;
  `citation_aliases` lists other ways the text names the law; a law whose coverage or
  exemptions are described without the limit's value is still recorded with `key_value`
  null.
* **Request settings**: streaming with `max_tokens` 32000, `output_config.effort = high`,
  adaptive thinking (always on for Opus 5.5), prompt caching on the system block (tools +
  system ≈ 6k tokens are written once per run and read by every other document; the first
  document runs alone to warm the cache, then 4 run in parallel). **No refusal fallback**
  (reproducibility): a refusal is audited and the document yields no rules.
* **Cache**: `.cache/<key>.json`, key = sha256(text_sha256 | `PROMPT_VERSION` | hash of prompt +
  tool schema | model | effort). Re-running with unchanged inputs makes zero API calls.
  Quote retries and date-kind answers are cached too.

---

## Validation (`validate.py`)

Every candidate's `quoted_span` is checked against the source document's **raw** text:

| Step | `match_type` | How |
|---|---|---|
| a | `exact` | literal substring |
| b | `normalized` | whitespace/line breaks, curly quotes, dashes, NBSP folded (`clean.locate_quote`); the span is replaced by the literal raw fragment |
| c | `fuzzy` | rapidfuzz `partial_ratio` ≥ 95 (spans ≥ 20 chars); replaced by the aligned raw fragment, widened to word boundaries |
| d | `retry` | ONE LLM call (`prompts/quote_retry.md`) asks for a literal supporting quote; a–c re-run on it |
| e | — | `rejected` / `citation_unverified` → `out/rejected.json` + audit; never exported |

**Dates** (`effective_dates`, `enacted_date`, `sunset_date`) run a–c. An unverified date is
dropped, not the rule. A non-derived date's **value** must appear in its quote in a common
format ("October 6, 2025", "Oct. 6, 2025", "10/06/2025", "3/01/26", "6-24-2023"). A `derived`
date (computed from a relative formula) also needs a verified `enacted_date` — its base.

**Date kinds** (`dates.py`): each verified effective-date claim is classified as

| Kind | Meaning | Example |
|---|---|---|
| `effective` | general entry into force | "This section shall become operative on April 1, 2024." |
| `operative` | calculation or base date | "rent increases occurring on or after March 15, 2019" |
| `amendment` | effective date of an amendment | statute/ordinance history notes: "(Amended by Stats. 2025, Ch. 203 …) Effective January 1, 2026.", "(Amended 2-27-2024 by O-21769 N.S.; effective 3-28-2024.)" |
| `enacted` | signing / adoption | "approved July 20, 2026" |

Wording rules decide first; only ambiguous dates go to the small model
(`DATE_CLASSIFIER_MODEL`, cached). **Date conflicts and status use only `effective` dates**
(this removed the false conflicts that statute history notes used to create).

**Dispositions** (after validation and normalization):

| Disposition | Reasons | Exported? |
|---|---|---|
| `accepted` | — | yes |
| `held` | `no_citation`, `administrative_unlinked` | no — kept for conflicts and interactions |
| `rejected` | `citation_unverified`, `schema_invalid` | no — `out/rejected.json` |
| `merged` | `duplicate_merged`, `administrative_linked`, `human_review:HR-NNN` | no — folded into another rule |

### Final confidence

```
confidence = model confidence
           × match factor      exact 1.0 · normalized 0.97 · fuzzy 0.85 · retry 0.8
           × 0.8               if is_secondary_source
           × 0.9               if stage = enacted and no verified (or derived) date of kind effective
           × 0.85              if >1 distinct verified dates of kind effective (also conflict_flag = true)
           × 0.9               if the citation was resolved from another rule (normalize.py)
capped at 0.5                  if stage = unknown (also conflict_flag = true, note "stage unclear")
```

---

## Normalization (`normalize.py`, no LLM)

Steps, in order:

1. **Citations** — schema style (`Cal. Civ. Code § 1950.6`, `§ ` with a space,
   `LAMC 165.03` → `L.A. Mun. Code § 165.03`, `P.L. 2025, c.405` → `P.L.2025, c.405`) and law
   names mapped through `data/citation_aliases.yaml`. A **state bill** citation (`MA H.3744`,
   `CA AB 325`) is always state jurisdiction/level, even when the bill concerns one city (a
   home-rule petition for Boston is still MA law); the correction is noted in
   `validation_errors`.
2. **Missing citations** — a `held`/`no_citation` rule takes the citation of an accepted rule
   of the *same law and jurisdiction*. If the held rule names its law (aliases), only those
   names and its title are matched; otherwise its text must name exactly one law ("applies
   to RSO and JCO units" names two). The resolved citation is **law-level** when the alias
   table knows the law (SF "Rent Ordinance" matched through § 37.10C → `S.F. Admin. Code
   ch. 37`). `citation_resolved_from = <team_rule_id>`, confidence × 0.9.
3. **Calendar defaults** from `data/jurisdiction_defaults.yaml` (see [Status](#status-statuspy)).
4. **Merge** — same jurisdiction, category and base citation (subsections stripped:
   `§ 16729(a)` → `§ 16729`, `§ 151.09.G` → `§ 151.09`) → one rule, unless coverage thresholds,
   key value or effective dates differ. `requirement` summarizes the members; every literal
   quote is kept in `evidence`. The same law at **different stages** (a bill page saying
   pending and the adopted text) also merges: the most advanced verified stage wins
   (enacted > administrative > failed > pending > unknown) and every document's claim is kept
   in `stage_history`.
   **4b. Certificate-of-occupancy cutoffs** — a `year_built_max` becomes
   `certificate_of_occupancy_on_or_before` when the coverage text, notes or quote mention a
   certificate of occupancy, or state the cutoff as a full date other than Dec 31 (a year
   cannot express it): L.A. RSO "first built on or before October 1, 1978" → 1978-10-01
   (guide §4.1), so a building of 1978 is unknown, not covered.
5. **Administrative figures** (annual allowable increases, relocation amounts, deposit
   interest) are folded into the enacted rule of the same jurisdiction and category,
   preferring the same law, as `key_value_details` (value, period, source, quote). A figure
   stays `held` / `administrative_unlinked` when it names a law with no enacted rule here,
   when there is no enacted rule to attach to, or when it names no law and several candidate
   rules exist without a clear title match (similarity ≥ 60 and 10 points above the
   runner-up). On export, `key_value` shows the legal value plus every figure in force on the
   query date, e.g. `SF-RENT-01`: "current (2026-03-01 to 2027-02-28; D080): 1.6%".
6. **IDs** — `{JUR}-{CAT}-{NN}`, or `{JUR}-{CAT}-{P|F|H}{N}` for pending bills, failed bills and
   held rules (internal) — the id style of `dev/change_tests.json`: e.g. `CA-RENT-01`,
   `CA-ALG-01`, `MA-ALG-P1`, `MA-RENT-F1`. Codes: CA, NJ, MA, BRK, LA, SD, SF, SNA, HOB, JC, NWK,
   BOS, CAM × RENT, JUST, DEP, FEE, SCRN, ALG. Deterministic; with a snapshot's `ids.json`
   (incremental runs, `reproduce`) published ids never change and new rules take the next free
   number in their cell; snapshot ids in the older style (`ALGO`, `P01`) are upgraded when loaded
   (`upgrade_legacy_id`).
   **6b. Human review merges** — `merge_rule` entries of `data/human_review.yaml` fold a rule
   extracted as a standalone rule into another as an exemption (HR-003: CA-JUST-01 into
   CA-JUST-02); the merged rule leaves `rules.json`.
7. **Precedence** — a state rule whose interaction says it yields to stricter local law
   (Civ. Code § 1947.12 and § 1946.2 vs local rent control / just cause) or preempts it gets
   the local `team_rule_id`s in `overrides`, each local rule gets the state id, and the
   direction is written in `interaction`. 23 exported rules carry `overrides`.
8. **Review flags** — `data/review_flags.yaml` sets `conflict_flag` and a note on rules tied
   to an open question of guide §9 (BRK-ALG-P1: Berkeley ch. 13.63 effective date).

### Citation aliases (`data/citation_aliases.yaml`)

Each entry maps the names one jurisdiction's documents use for a law to a canonical,
law-level citation: `canonical`, `names` (exact names/abbreviations), `section_pattern`
(regex on section citations, e.g. `^S\.F\. Admin\. Code § 37\.` → `S.F. Admin. Code ch. 37`)
and `source` (the decision or corpus document that justifies it). Entries are
jurisdiction-scoped ("Rent Ordinance" is a different law in SF and in Berkeley).

| Law | Canonical | Source |
|---|---|---|
| SF Rent Ordinance | `S.F. Admin. Code ch. 37` | team decision; D079/D081/D082/D083 |
| LA Rent Stabilization Ordinance (RSO) | `L.A. Mun. Code ch. XV` | team decision; D043 cites LAMC 151.xx |
| Berkeley Rent Ordinance | `Berkeley Mun. Code ch. 13.76` | D008 (BMC 13.76.110A) |
| Jersey City Rent Control Ordinance | `Jersey City Mun. Code ch. 260` | D036 |
| NJ Law Against Discrimination | `N.J.S.A. 10:5-12` | D067 |
| Santa Ana Rent Stabilization and Just Cause Eviction Ordinance | (ordinance name; no code section in corpus) | D084 |

The `formatting` list holds generic style rewrites. Only entries backed by the corpus or an
explicit team decision are allowed — never memory.

---

## Conflicts (`conflicts.py`)

Flags both rules (`conflict_flag`, `conflict_note`) and writes `out/conflicts.json`:

| Type | When |
|---|---|
| `effective_date` | same jurisdiction, category and law; different documents; different effective dates for the same provision (title similarity ≥ 70 or equal key value) |
| `key_value` | same jurisdiction, category and law; different documents; same coverage thresholds; different figures for the same provision (title match, or figures of the same unit — $, %, months, days — unless their effective dates tell them apart) |
| `preemption` | a state rule says it preempts / prohibits local rules → every local rule of that category in the state (held ones too); negations ("does not preempt") are excluded |
| `value_pending` | the text marks a date or figure as pending, not yet published or "to be determined" |
| `preemption_no_local_rule` | informational: a state preemption clause with no local rule of that category in the corpus (nothing flagged) |

Current conflicts:

| Type | Rules | Detail |
|---|---|---|
| `key_value` | `CA-FEE-01` ↔ `CA-FEE-02` | Cal. Civ. Code § 1950.6: statute (D026) "$30 per applicant, CPI-adjusted annually" vs Berkeley Rent Board page (D005) "$68.96 (2026 maximum)" — **the CA screening-fee cap has no single official 2026 figure** |
| `preemption` | `NJ-RENT-03` ↔ `JC-RENT-01` | NJ Newly Constructed Multiple Dwellings Law (30-year exemption) overrides the Jersey City rent control ordinance |
| `preemption_no_local_rule` | `MA-RENT-01` | M.G.L. c. 40P bars local rent control; no local MA rent rule exists |
| `preemption_no_local_rule` | `NJ-ALG-01` | FAIR Act prohibits conflicting municipal ordinances; no local NJ algorithmic rule is in the corpus (Module B adds the attested Hoboken / Jersey City bans and flags the conflict at those addresses) |

Other notes on exported rules: `LA-RENT-04` "expired on 2024-01-31" (RSO COVID freeze);
`LA-RENT-05` "stage unclear" (the model could not tell the stage; confidence capped at 0.5);
`BRK-ALG-P1` flagged by `data/review_flags.yaml`.

---

## Status (`status.py`)

| Stage | Status on `--as-of` |
|---|---|
| `bill_pending` | `pending` |
| `bill_failed` | `failed` |
| `enacted` / `administrative` / `unknown` | `pending` if enacted after as_of; `failed` if its sunset date ≤ as_of (exported with `conflict_note` "expired on <sunset_date>"); `not_yet_effective` if every effective date > as_of; otherwise `in_force` |

Only dates of kind `effective` count (verified quotes, dates derived from a formula in the
text, and calendar defaults). If effective dates straddle the query date the rule is
`in_force` and the conflict is flagged. `effective_date` in the export is the date that
decides the status (earliest future date if not yet effective, else the latest past one).

**Calendar defaults** (`data/jurisdiction_defaults.yaml`) — only California is configured: a
CA statute that is enacted, has a verified `enacted_date` and no effective date in its text
gets January 1 of the following year (Cal. Const. art. IV, § 8(c)(2), the fall signing
period), unless the text contains urgency-statute language. The date is stored as derived
with `kind_source: default` and `rule_applied: CA-const-art-IV-8c`. NJ and MA have no
defaults by design (their acts state their own effective dates). Applied once in the corpus:
AB 325 (approved 2025-10-06) → 2026-01-01.

---

## Export (`export.py`)

`python -m extractor.cli export --as-of YYYY-MM-DD` writes `out/rules.json` with **accepted
rules only**, sorted by `team_rule_id`, each record mapped to `RuleOut` (exactly the official
schema, no extra keys) and validated with `jsonschema` (Draft 2020-12). If any record is
invalid nothing is written. `coverage_conditions` is an object with the non-null coverage
tests, exemption conditions, notes and summary text. Status, `effective_date` and the
"current" administrative figure in `key_value` are recomputed for each `--as-of`, without
the LLM.

---

## Reproducing from the snapshot (no API key)

The official extraction is frozen in **`snapshots/a-0.4.0/`** (versioned in git):

| File | Content |
|---|---|
| `MANIFEST.json` | prompt version + sha256 + fingerprint, model, effort, date, cost (extraction $3.86 + date classifier $0.01 = **$3.87**), token counts, per-document `text_sha256` |
| `extract_system.md` | the frozen extraction prompt |
| `llm/<doc_id>.json` | raw model output per document (`record_rules` tool input + usage) |
| `aux_cache/` | quote-retry and date-kind answers used by validation |
| `extracted/<doc_id>.json` | validated rules per document |
| `ids.json` | uid → `team_rule_id` of the official run |
| `rules.json`, `conflicts.json` | official export of the Module A run (as of 2026-10-01) |

`python -m extractor.cli reproduce` serves every document from `llm/`, re-runs validation,
normalization, conflicts and status locally, and writes `out/rules.json`,
`out/conflicts.json` and `out/rules_attested.json` (no API key, empty `.cache/`, ~5 s). The
output is deterministic; it differs from the frozen `snapshots/a-0.4.0/rules.json` only by the
documented [Module B adjustments](#module-b--adjustments-to-the-rules), which
`tests/test_snapshot_incremental.py` checks record by record. In snapshot mode the API client is
disabled (`config.OFFLINE`): a document missing from the snapshot is an error, never a silent
API call. All artifacts are written with LF line endings on every platform, and
`.gitattributes` keeps git from converting them, so hashes hold on Windows, macOS and Linux.

---

## Incremental mode — `extract-doc`

For the hour-16 scenario: add one new document without re-extracting the corpus.

```bash
python -m extractor.cli extract-doc tests/fixtures/fake_cambridge_ordinance.txt --jurisdiction "Cambridge, MA"
```

1. **ingest** — `.txt`, `.pdf` (pypdf) or `.html` → text, saved to `corpus/new/<doc_id>.txt`
   in corpus format (SOURCE/RETRIEVED header) with `<doc_id>.meta.json` (sha256 of the
   original file, retrieval date, jurisdiction hint).
2. **extract** — only this document, with the **frozen prompt** (aborts if
   `prompts/extract_system.md` differs from the snapshot's).
3. **validate → normalize → conflicts → status/export** — on the snapshot's rules + the new
   ones; new rules merge with same-law rules (including stage merge), existing
   `team_rule_id`s never change. Changes are reported against the snapshot normalized with the
   current code, so only the new document's effect shows up.

It prints a video-friendly summary — new/modified rules, status as of 2026-10-01, effective
date and whether it was derived, new conflicts, seconds per stage — and writes
`out/increment_<doc_id>.json`. Module C's `changes --new-doc` builds on it (T6).

**Rehearsal** with a fictitious Cambridge ordinance (`tests/fixtures/fake_cambridge_ordinance.txt`:
Ordinance No. 2026-17, ch. 8.72, adopted 2026-09-14, "effective 180 days after adoption",
exemption for buildings with fewer than six units):

```
[NEW] CAM-ALG-01 · Cambridge, MA · city · algorithmic_rent_setting
  citation       : Cambridge Mun. Code § 8.72.030
  STATUS         : not_yet_effective
  effective_date : 2027-03-13   (DERIVED: one hundred eighty (180) days after its adoption)
  exemption      : units < 6
TIME: ingest 0.03 · extract (LLM) 16.18 · validate 0.00 · normalize 0.40 · conflicts 0.07 · export 0.15 · TOTAL 16.8 s
```

All existing rules kept their ids and content. Cost ≈ $0.07. The rehearsal was undone
afterwards; its frozen LLM answer is in `tests/fixtures/` for an offline test. To undo any
incremental run: delete `corpus/new/<doc_id>.*` and run `reproduce`.

---

## Smoke check

`python -m extractor.cli smoke-check` reads the current `out/` artifacts (run `reproduce`
first), prints a dashboard and saves it to `out/smoke_check.json`. No API calls.

* **Pipeline**: the corpus loads and cleaning keeps raw lines verbatim; `rules.json` is
  schema-valid; every exported rule has a citation and a verified quote.
* **Expected citations** (`tests/expected_citations.yaml`, **measurement only — never read
  by extraction**; list supplied by the team from the brief's category table): each is
  *found*, *found as held*, *absent: source link-only* (pattern absent from every loadable
  text and the jurisdiction has link-only/check-terms sources) or *absent without
  explanation* (text present but not extracted). Current: 20 found; Santa Ana NS-3090,
  Jersey City § 218-12 and Hoboken ch. 158 absent because their sources are link-only.
* **Behaviour**: T1 (AB 325 not yet effective on 2025-12-31, in force on 2026-01-02), T3 (FAIR
  Act not yet effective on 2026-10-01, in force on 2027-07-02), T4 (S.2983 and H.5222
  pending), T5 (no rent **cap** in force in MA, Boston or Cambridge: a rule fails only if it
  has a `key_value` and is not a prohibition/preemption of local rent control — M.G.L. c. 40P
  is still reported, with the note "c. 40P bars local rent control → no local cap").
* **Test rule map**: every rule id of `dev/change_tests.json` maps (`data/test_rule_map.yaml`)
  to an exported rule or a manifest-attested one.

---

## Outputs and audit log

| File | Content |
|---|---|
| `out/extracted/<doc_id>.json` | validated rules per document + validation counts + LLM usage |
| `out/rules_internal.json` | accepted + held rules before normalization |
| `out/rejected.json` | rejected rules with reason |
| `out/validation_report.json` | per-document and global validation counts |
| `out/rules_normalized.json` | every rule after normalization, all dispositions, evidence, stage history |
| `out/conflicts.json` | conflicts between documents |
| `out/rules.json` | **submission file** — accepted rules, schema-valid |
| `out/rules_attested.json` | manifest-attested rules (never in rules.json) |
| `out/coverage.json` | three-valued coverage per (address, rule) |
| `out/lookups.json` | **submission file** — results for all 500 addresses (template format) |
| `out/lookups_full.json` | lookups + reasons, presumptions, needs_review, attested rules, stack |
| `out/changes.json` | **submission file** — change tests T1–T5 (T6 after an hour-16 run) |
| `out/changes_full.json` | before/after per address for each test |
| `out/increment_<doc_id>.json` | summary of an incremental run |
| `out/smoke_check.json` | smoke-check results |
| `out/audit.jsonl` | append-only log |

`out/audit.jsonl` is never rewritten. Each line has a UTC timestamp and a run id. Events:
`run_start`, `doc_loaded` (cleaning cuts and warnings), `llm_call` (model, prompt version,
cache hit, usage), `llm_error`, `quote_retry`, `date_kind_llm`, `rule_rejected`, `rule_held`,
`validated`, `run_end`, `normalize`, `conflict_flagged`, `export`, `increment`. Secrets and
full document text are never logged.

---

## Preguntas abiertas no resolubles con el corpus

Questions the participant guide raises whose answer depends on sources that are **not in
the supplied text** (manifest rows with `capture = link-only` or `check-terms`). The system
never fills them from outside knowledge; it records what the corpus supports and leaves the
gap visible. (Also served by `GET /conflicts` from `data/open_questions.yaml`.)

| Question | What the corpus has | Missing source (no text) | How the system handles it |
|---|---|---|---|
| **Berkeley ch. 13.63 — two published effective dates** (March 1, 2026 per the ordinance; January 2026 per an Aug 2026 law-firm alert) | D001: Ordinance No. 7,992-N.S. amending ch. 13.63, recorded only as "passed to print" on November 18, 2025 (first reading). No effective date, no adoption or second-reading record. No other Berkeley document mentions 13.63. | D002 (Morgan Lewis alert, link-only) | `BRK-ALG-P1`, stage `bill_pending` → status `pending`, no effective date. With one date-less source, no date conflict can be raised; `data/review_flags.yaml` sets `conflict_flag` with the §9 note. |
| **San Diego §§ 98.1101–98.1104** (algorithmic ban) | D076: the *proposed* ordinance package (O-2025-107); ordinance number, date of final passage and adoption certificate are blank. | D074 (codified text, check-terms) | `SD-ALG-P1`, `pending`. |
| **Los Angeles RSO new formula — two effective dates** (2026-02-02 per LAHD; 2026-01-24 per a landlord association) | D041 and D042 (LAHD) both state February 2, 2026. | The landlord-association statement is not in the corpus; D044 (AAGLA, link-only) is about deposit interest; the LAMC text D038 is check-terms. | RSO rules carry the single verified date 2026-02-02; no conflict is flagged because only one source is readable. |
| **Hoboken and Jersey City algorithmic rent-setting ordinances** (T2 boundary, T3 preemption by the NJ FAIR Act) | D036 (Jersey City landlord/tenant page) has no algorithm content. | Hoboken code D032–D034 (ecode360, check-terms); Jersey City D035 (news) and D037 (Morgan Lewis), link-only; D060 (Day Pitney on the FAIR Act), link-only. | No local NJ `algorithmic_rent_setting` rule in `rules.json`. The FAIR Act's "municipalities are prohibited from enacting ordinances…" clause is recorded in `out/conflicts.json` as `preemption_no_local_rule`. Module B adds manifest-attested `HOB-ALG-A1` and `JC-ALG-A1` (`out/rules_attested.json`, see [Responsible design](#responsible-design)), flagged as possibly preempted by `NJ-ALG-01`. |
| **San Francisco annual allowable increase (Rent Ordinance § 37.3)** | D079 says some units "are exempt from the rent increase limitations of the Ordinance" (certificate of occupancy after 1979-06-13, Costa-Hawkins); D080/D083 give the Rent Board's 1.6% / 1.4% figures. | The text of § 37.3 itself is not in the corpus. | `SF-RENT-01` (`S.F. Admin. Code ch. 37`, coverage `certificate_of_occupancy_on_or_before 1979-06-13`, `key_value` null) with the Rent Board figures attached; the 60%-of-CPI formula is not stated. |
| **Massachusetts bills S.2983 and H.5222** (T4: who would be affected) | D045, D046, D047: bill status/history pages (titles, committee actions, dates). D011: H.3744 status page. | The bill texts themselves (no bill-text document in the manifest); D059 (WBUR on the struck ballot question), link-only. | Bills are recorded with stage `bill_pending` (status `pending`), `key_value` null and coverage "not described"; their scope can only be stated at jurisdiction level (MA statewide). H.3744 is `failed` (`MA-RENT-F1`, `MA-JUST-F1`). No MA or Boston/Cambridge rent cap exists (T5), consistent with M.G.L. c. 40P. The struck ballot question itself (T5's MA-RENT-P1) is the manifest-attested `MA-RENT-A1`, status `failed`; it is not `MA-RENT-F1` (H.3744). |

---

## Module B — adjustments to the rules

Applied by `normalize.py` and `attested.py` on every run (no API calls), on top of the frozen
a-0.4.0 extraction:

| Change | What | Rules affected |
|---|---|---|
| Id style | `ALGO` → `ALG`; `P01`/`F01`/`H01` → `P1`/`F1`/`H1` | every algorithmic, pending, failed and held id |
| Certificate of occupancy (step 4b) | `year_built_max` → `certificate_of_occupancy_on_or_before` | LA-JUST-03, LA-RENT-01..04: 1978 → 1978-10-01 |
| Human review merge (step 6b) | HR-003: exemption extracted as a standalone rule folded into its law's rule | CA-JUST-01 → CA-JUST-02 |
| Review flags (step 8) | `conflict_flag` + note for open questions of guide §9 | BRK-ALG-P1 |
| Manifest-attested rules | laws named by the starter pack without corpus text → `out/rules_attested.json` | HOB-ALG-A1, JC-ALG-A1, MA-RENT-A1 |

`data/test_rule_map.yaml` maps every rule id of `dev/change_tests.json` to ours (MA-ALG-P1/P2
cross because the test does not say which bill is P1); `smoke-check` verifies each mapped id.

## Module B — building facts and jurisdictions

```bash
python -m resolver.cli facts      # -> data/building_facts.json (+ table and warnings)
python -m resolver.cli geocode    # -> data/jurisdictions.json; reuses data/geocode_raw/ (--refresh to query again)
```

**Facts** (`resolver/facts.py`), per address, each with source and certainty:

* `units`: `range` [min, max] (max null = open-ended), certainty `exact` (units column),
  `parsed` (count in a NJ MOD-IV description: `3S-F-D-6U-NH` → 6; buildings separated by `/`
  summed; `1OU` read as 10; `NUG` is a garage, not units), `range` (from the use code, e.g.
  Boston `A/112` → 7–30, NJ class `4C` → 5+) or `unknown`. A column that contradicts the code is
  kept with a warning (SF TIC A0398); a column equal to the description's commercial count is
  replaced by the description (Hoboken A0227: `13B-93U-2C-G` → 93, not 2).
* `year_built`, `co_year_approx` (approximate), `use_flags` (section8, coop, affordable, tic,
  elderly, mixed_use, luxury, single_family, condo — true / false / unknown, from
  `data/use_code_map.yaml`), `use_class` (apartment_building), `owner_type` / `owner_occupied`
  (always unknown).

**Jurisdictions** (`resolver/geocode.py`): one Census batch request (`Public_AR_Current` /
`Current_Current`; NJ rows sent without ZIP because the sample's NJ ZIPs are mostly mailing
ZIPs of other cities or states), a second batch for unmatched streets with zero-padded
ordinals removed ("05TH AV" → "5TH AV"), then one `geographies/coordinates` lookup per matched
point for the incorporated place (the batch output has none), 4 at a time with retries. The
stack holds state, county (informational), city = incorporated place in rules.json format
("Jersey City city" → "Jersey City, NJ"), `match_quality` (exact / non_exact / no_match) and
`source` (census / dataset_fallback, certainty low). The geocoder's place wins over the
dataset city; every disagreement is listed in `discrepancies` (none in the sample; 15 no-match
addresses use the dataset city).

## Module B — coverage (three-valued)

```bash
python -m resolver.cli compile    # -> data/compiled_exemptions.json + data/compiled_exemptions_review.md
python -m resolver.cli coverage --as-of 2026-10-01   # -> out/coverage.json + summary
```

**Compiling** (`resolver/compile_exemptions.py`, once per rule): coverage scalars and
structured exemptions are translated by code into predicates over the building facts
(`resolver/predicates.py`: units, year_built, co_date, building_age, use flags, use_class,
owner_type, owner_occupied, `missing` leaves). Free text — `field: other` exemptions, the
`exemptions` text, coverage notes, property types, and the building conditions inside
owner-occupied / owner-type exemptions ("owner-occupied two- or three-family dwellings") — goes
to a small model (`COMPILE_MODEL`, default `claude-haiku-4-5`, prompt
`prompts/compile_exemptions.md`) through tool use; answers are validated (grammar, one result
per item, no negated or always-true exemption) and retried with the rejection reason. Every
item gets a scope: `building` (evaluated), `unit_or_tenancy` (caveat: tenant, unit, product or
transaction), `other_law` (depends on another law's coverage; resolved by precedence),
`duplicate` (free text restating a structured exemption), or `review` (free-text coverage
conditions and exemptions that restate the rule's own scope — the small model read inclusive
examples and exemption qualifiers as restrictions, so these are shown for review, never
evaluated). Deterministic scope hints (`SCOPE_HINTS`) correct the model on recurring cases. The
raw answers are versioned in `data/compiled_exemptions.json`; reproducing reassembles them with
no API call, and a rule that only gains items reuses the reviewed answers for the unchanged ones.

**Evaluating** (`resolver/coverage.py`): Kleene T/F/U. Rules match by jurisdiction stack (state
rule → same state, city rule → same city). Units are intervals; the certificate-of-occupancy
date is the interval of the building's year (a cutoff inside it → unknown); the rolling
building-age cutoff likewise; owner facts are always U unless another term decides.
`coverage` = not_covered (a condition is F) / exempt (an exemption is T) / covered / unknown,
with `reasons` (condition, value used, fact source, result), `missing_facts`, caveats, deferred
other-law items and `confidence_coverage` (×0.9 unit range or fallback city, ×0.8
certificate-date proxy, ×0.9 special-status presumption).

**Special-status presumption** (team decision B2, `PRESUME_SPECIAL_STATUS=true` by default):
exemptions and conditions that need a recorded or documented status — deed or regulatory
affordability restriction, HUD subsidy (Section 8/202/811…), nonprofit cooperative, government,
housing-authority or university owner, institutional or care use, single-sex designation, condo /
co-op / fee-simple conversion — are marked `special_status` at compile time (regex
`SPECIAL_STATUS` OR a one-call LLM classification stored in `special_status_llm`). At evaluation
their unknown status leaves are presumed false unless a use flag in the data shows the status
(Boston A/125 → section8, A/118 → elderly, NJ "CO-OP" / "AFFORDABL"), and the result carries
"presumed: no evidence of <status> in assessor data". Generic owner type (natural person vs
entity), owner occupancy, cutoff-year and missing units / year built are never presumed.

## Module B — lookups (results per address)

```bash
python -m resolver.cli lookup --as-of 2026-10-01                    # all 500 -> out/lookups.json + out/lookups_full.json
python -m resolver.cli lookup --as-of 2026-10-01 --address A0016    # readable summary by category (demo)
```

`resolver/results.py` combines the rule's status at the query date (Module A `status.py`) with
its coverage: failed or not_covered/exempt → omitted (reason kept in `lookups_full.json`);
pending → `pending`; not yet effective → `not_yet_effective`; in force → `applies` / `unknown`.
Precedence: a rule that yields to a covered, in-force rule of the address (Module A
"[Yields to]" / "[Takes precedence over]", or a B2 `other_law` exemption resolved through
`data/other_law_map.yaml`) becomes `superseded`, naming the rule that governs; if that rule is
only unknown, both are reported with "may yield to". When a rule prevails over R it also
prevails over the other in-force rules with R's base citation and category. Rules defined only
as "for units covered by <law>" (LA-RENT-05, LA-JUST-04/05) follow that law's coverage-defining
rules. Preemption the other way (FAIR Act vs Hoboken/Jersey City bans, NJ-RENT-03 vs JC-RENT-01)
is never superseded: both carry `conflict_flag` and a review note. `conflict_flag` means a legal
conflict only (the rule's own Module A flag, or a preemption conflict at the address); a
combined confidence (rule × coverage × geocoding, fallback ×0.85) below 0.5 sets `needs_review`
in `lookups_full.json` instead. Explanations are deterministic (English, plus Spanish for the
API): requirement, why (facts used, governing rule, effective date, "pending bill, not law", or
the missing fact), presumptions/notes, then source, retrieval date, as-of date and "Not legal
advice." `lookups.json` holds only rules.json ids (validated); manifest-attested rules appear only
in `lookups_full.json`.

Brief example (SF, 1926, 21 units — A0016): SF-RENT-01 applies, CA-RENT-01 superseded; SF-JUST-01
applies, CA-JUST-02 superseded; CA deposit rules apply (CA-DEP-06, the small-landlord rule, does
not cover 21 units); CA-FEE applies; SF-ALG-01 and CA-ALG-01 apply.

## Module C — change tracking

```bash
python -m resolver.cli changes        # T1-T5 -> out/changes.json + out/changes_full.json + dashboard (~3 s)
python -m resolver.cli changes --new-doc path/to/ordinance.txt --jurisdiction "Cambridge, MA"   # hour 16 -> T6
```

`resolver/changes.py` reuses `results.py` lookups at any dates (`diff(address, rules, before,
after)`, attested rules included) and maps the change tests through `data/test_rule_map.yaml`.
Affected = the rule's result changes between the two dates (as_of: T1, T3); is applies / unknown
/ not_yet_effective (boundary: T2, with the attested Hoboken and Jersey City bans); is pending
(T4); or an in-force rent cap exists (negative: T5, empty — c. 40P is a ban, not a cap).
`conflict_flag_address_ids` are affected addresses whose test-rule result carries
`conflict_flag`. The dashboard checks the expected counts (T1 250 CA, T2 40 / 50 / 0, T3 140 NJ
with 90 flagged, T4 110 pending, T5 empty and IP 25-21 failed).

`--new-doc` runs extract-doc (Module A) and **keeps** the result: the increment is stored in
`corpus/new/` (original file byte for byte, its text, `meta.json` with sha256 / retrieval date /
new rule ids, and the validated rules in `<doc_id>.extracted.json`), its coverage is compiled
into `data/compiled_exemptions.json`, and the change tests are rewritten with a `T6` entry (each
new rule's result at the default query date and the day after its effective date). `reproduce`
and `changes` replay kept increments with no API call, so the Render build shows T6 too. To
undo: delete `corpus/new/<doc_id>.*`, then run `python -m extractor.cli reproduce`,
`python -m resolver.cli compile` and `python -m resolver.cli changes`.

## Hour 16 runbook

One command, end to end (needs `ANTHROPIC_API_KEY` in `.env`):

```bash
python scripts/hour16.py path/to/new_document.pdf --jurisdiction "Cambridge, MA" --dry-run   # rehearse in a temp copy
python scripts/hour16.py path/to/new_document.pdf --jurisdiction "Cambridge, MA"             # real run: keep, commit, push
.\scripts\hour16.ps1 path\to\new_document.pdf -Jurisdiction "Cambridge, MA" [-DryRun] [-NoGit]  # Windows wrapper
```

Accepts `.txt`, `.pdf`, `.html` and `.docx`. Each step prints what it did and its time:

| Step | What |
|---|---|
| a | copy the file unchanged to `corpus/new/` (sha256, retrieval date) and its text in corpus format |
| b | extraction (Opus, frozen prompt) + validation + normalization; increment kept; coverage compiled; change tests with T6 |
| c | summary: new rules, jurisdiction, category, effective date (derived or stated), status on 2026-10-01, affected addresses by city, exemptions applied, new conflicts |
| d | checks: affected addresses inside the rule's jurisdiction · `effective_date` set · literal quote verified · smoke-check and the T1–T5 dashboard green |
| e | regenerate `out/lookups.json`, `out/changes.json`, plain language (new rules only) and `static/`; check that the API shows T6 (`/changes`, `/changes/T6` en/es) and that `/lookup` of an affected address after the effective date shows the new rule as `applies` |
| f | `out/hour16_report.md` (source, timings, cost, results, checks); copied to `docs/hour16_report.md` on a real run |
| g | real run only: `git add` the kept artifacts, commit "T6: hour-16 ordinance", push → Render redeploys |

**What to review before publishing:** every check in step d is green (a red line is reported,
never fixed by hand — fix it through the human review register if needed); the new rule's
jurisdiction, category and effective date match the document; the affected count by city makes
sense for its coverage (e.g. the unit threshold); and after the push, `GET /changes?lang=es` on
the deployed service lists the new entry.

Rehearsals (`--dry-run`, fictitious Cambridge ordinance, `tests/fixtures/`): `.txt` 16.6 s wall
clock (extraction from cache); `.pdf` 42.6 s (Opus extraction 20.6 s, $0.08; compiler $0.005).
Both: CAM-ALG-01, `not_yet_effective` on 2026-10-01, effective 2027-03-13 (derived from "180
days after its adoption"), `applies` from 2027-03-14 at 45 Cambridge addresses (the 5 with fewer
than 6 units are not covered), none elsewhere; all checks pass.

## API (FastAPI) and plain language

```bash
python -m api.plain_language          # tenant summaries EN/ES -> data/plain_language.json (reuses unchanged entries)
uvicorn api.main:app --reload         # http://localhost:8000/docs
python -m api.export_static           # static/ backup: one JSON per address and language (+ index, rules, changes)
```

* **Plain language** (`api/plain_language.py`): per rule, `what_it_means`, `who_it_covers`,
  `what_you_can_do` in English and Spanish, written by `PLAIN_MODEL` (default
  claude-haiku-4-5) from the rule's requirement, key_value, coverage text, exemptions and
  effective date only. Validator: every number, amount, percentage, month and date must appear
  in those fields, and nothing may suggest avoiding the rule; one regeneration with the reason,
  then a deterministic template (also used for attested rules). Spanish always uses "usted"
  and the fixed legal terms of `data/glossary_es.yaml` (Certificado de Ocupación, Ordenanza de
  Arrendamiento, depósito de garantía…); both are validated, and summaries written before
  these rules were revised in Spanish only (`es_version`). Versioned, so the API never calls a
  model. The API prepends `status_line`, computed at the requested `as_of` ("In force since …",
  "Not in force yet — takes effect …", "Pending bill — not law", "Covered, but X governs
  instead"; Spanish equivalents).
* **Routes** (`api/main.py`, contract and real examples in `docs/API.md`): `/health`,
  `/addresses`, `/lookup/{address_id}?as_of=&lang=`, `/changes`, `/changes/{test_id}`,
  `/rules`, `/conflicts`, `/audit`. Every response has a disclaimer in the requested language;
  `as_of` is validated (YYYY-MM-DD, 2020–2030); CORS allows Lovable domains and localhost.
  `/changes` and `/changes/{test_id}` take `lang` too: `type_label`, `title` and `notes` in
  Spanish come from deterministic templates in `api/i18n.py` (same numbers, long-form dates,
  glossary, "usted"); `/lookup` results add `missing_facts_label` (readable names of the
  missing facts in the requested language).
* **Static backup** (`api/export_static.py`): `static/` with the same JSON as the routes for
  `as_of=2026-10-01` — 1,011 files, ≈ 29 MB (≈ 7 MB gzipped), git-ignored, rebuilt in ~3 s.

### Deploy on Render

1. In Render: **New → Blueprint** and pick the repository (`render.yaml`). No
   `ANTHROPIC_API_KEY` is needed: the build runs `python -m extractor.cli reproduce` and
   `python -m resolver.cli changes` from the versioned snapshot, then starts
   `uvicorn api.main:app`.
2. Set `ALLOWED_ORIGINS` if the front end is served from a non-Lovable domain.
3. Free instances sleep: point the front end at `static/` (export it and host it with the
   front end, e.g. as public assets) when `/health` does not answer.

---

## Responsible design

**Manifest-attested rules (`out/rules_attested.json`).** Three laws named by the starter pack
have no text in the corpus: the Hoboken and Jersey City algorithmic rent-setting ordinances
(T2, T3) and the struck Massachusetts rent-control ballot question (T5). The corpus was searched
for "Hoboken", "Jersey City", "218-12" and "158" near algorithm/software/rent-setting wording;
the only hit is the FAIR Act's findings (D069: Hoboken studio rents up 61 percent), which
describes no local ordinance, so there was nothing to re-extract. Instead of inventing text,
`extractor/attested.py` builds one record per such law from `data/test_rule_map.yaml`, the
manifest's link-only rows and `dev/change_tests.json`:

* `evidence_type: "manifest_only"`, `confidence: 0.3`; `quoted_span`, requirement and coverage
  null. Citation and effective date only where the organizers' challenge brief (p.3) gives them:
  Jersey City Code § 218-12, 2025-06; Hoboken Code ch. 158 Art. II, 2025-07 (`status_basis`:
  "Challenge brief p.3 (organizer-provided); text not in corpus"). `sources` lists the
  link-only documents (topical URL, or every link-only row of the jurisdiction when no URL names
  the topic, as for Hoboken's ecode360 pages).
* They are written **only** to `out/rules_attested.json`, never to `rules.json` or
  `lookups.json` (they cannot meet the schema's quoted-span requirement), and are used **only**
  for affected address sets, conflict flags and the interface — never to state a requirement, a
  figure or a date.

**Human review.** Every manual correction is an entry of `data/human_review.yaml`, and nothing
else in the code or data changes a rule by hand. Each entry has an id (HR-NNN), the rule, the
action (`set_scope`, `add_item`, or `merge_rule`, applied in Module A's normalize step so the
merged rule leaves `rules.json`), a `quoted_span`, the reason, the reviewer (a role, not a name)
and the date. Entries whose quoted span is not found verbatim in the rule's text are refused
(compiler) or not applied (normalize); applied ids are recorded (`human_review_applied` in
`data/compiled_exemptions.json`, `human review merges` in the normalize report), and each
corrected item carries a "human review HR-NNN" note. Current entries: HR-001 (MA-RENT-01
exemptions → other_law), HR-002 (CA-DEP-06 limited to ≤ 4 units), HR-003 (CA-JUST-01, an
exemption extracted as a standalone rule, folded into CA-JUST-02), HR-004 (CA-JUST-03
demolition condition as unit_or_tenancy, stated in its explanation).
`tests/test_human_review.py` runs the hour-16 flow (extract-doc of a new ordinance → compile →
coverage) with an empty register to show a new document never needs an entry.

**Unknown instead of guessing.** Owner type and owner occupancy are always unknown; `year_built`
stands in for the certificate-of-occupancy date only as a flagged approximation (a cutoff inside
the building's year is unknown); unit counts inferred from use codes are ranges, and every
inference names its basis in `data/use_code_map.yaml`. The only presumption — special statuses
absent unless the data shows them — is configurable, stated in every result it affects and
lowers its confidence.

**Every answer is traceable and not legal advice.** Each result carries citation, source URL,
retrieval date, the literal quote and the as-of date; enacted, pending, not-yet-effective and
failed law are kept apart; conflicts are flagged for human review, never resolved silently; the
audit log and the versioned snapshots let another person reproduce every output.

---

## Known limitations and design decisions

* **Corpus-bound by design.** Rules, dates, citations and aliases come only from the
  supplied text or explicit team decisions. A law whose text is link-only is absent from
  `rules.json` (see the table above), even when its content is publicly known.
* **Category judgments vary between runs.** Re-extraction with the same prompt can move a
  borderline provision in or out of a category (e.g. M.G.L. c. 186 § 11, a 14-day notice to
  quit for nonpayment, was a `just_cause_eviction` rule in a-0.3.0 and is not in a-0.4.0).
  The snapshot freezes one run so results are reproducible; the same holds for the small model
  that compiles coverage, whose reviewed answers are frozen in `data/compiled_exemptions.json`.
* **Granularity is per law.** One rule per (jurisdiction × category × law); provisions of the
  same law with the same coverage, value and dates merge — e.g. `CA-DEP-03` and `CA-DEP-04`
  each absorb another § 1950.5 provision (photographs, deductions) with compatible coverage
  and dates. Every source quote is kept in `evidence`.
* **Administrative figures need a legal anchor.** Rent Board / LAHD figures are shown only
  inside an enacted rule of the same law; figures naming a law with no enacted rule (SF
  deposit interest, Civ. Code § 1947.9 temporary displacement, some Ellis Act amounts, the LA
  RPO chart) stay held.
* **Status mapping.** An enacted rule past its sunset is exported as `failed` with "expired on
  <date>"; a rule with no verified effective date is `in_force`.
* **Calendar defaults only for California** (Cal. Const. art. IV, § 8(c)); not applied to NJ
  or MA.
* **Stage merge.** Implemented and tested, but not triggered by the current corpus (no law
  appears at two stages in readable text).
* **Free-text coverage conditions are not evaluated** (scope `review`): the small model read
  inclusive examples and exemption qualifiers as restrictions; restrictions come from the
  structured fields, the property types and the human review register.
* **The brief PDF in the starter pack** (`…v5-participant-no-scoring-no-hour16.pdf`) does not
  contain the citation examples used by `expected_citations.yaml` nor the attested effective
  dates; both were supplied by the team (measurement only, and attested rules only).

---

## Prompt history

| Version | Change | Effect on the 4-document test set (D081, D069, D022, D016) |
|---|---|---|
| a-0.2.0 | first prompt; one rule per distinct requirement | 14 rules; D016 (CRD FAQ) produced deposit rules from discrimination examples; quotes sometimes started mid-sentence |
| a-0.3.0 | granularity per law; strict category definitions; `is_secondary_source` only for another jurisdiction; relative dates derived (`derived`); quotes start at a sentence with the operative verb; typed exemptions; `citation_aliases` | 5 rules; FAIR Act effective date 2027-07-01 derived; AB 325 1 rule (§ 16729) |
| a-0.4.0 | record a law whose coverage/exemptions are described even without the limit's value (`key_value` null) | full corpus: 62 → 66 exported rules; `SF-RENT-01` (Rent Ordinance coverage, CO ≤ 1979-06-13) now exists |

Validation, normalization, conflicts and status evolved alongside (date verification by
value, date kinds, stage merge, administrative linking, stable ids); they never call the
extraction model. Module B prompts: `prompts/compile_exemptions.md` cx-0.1.0 → cx-0.4.0
(counter-examples for inclusive sentences and negated exemptions; free-text conditions moved to
review); plain language pl-0.1.0 → pl-0.2.0 (Spanish glossary and "usted").

---

## Cost

| Run | USD |
|---|---:|
| Module A — prompt iterations on 4 documents (a-0.2.0, a-0.3.0, strict-schema probes) | ≈ 0.62 |
| Module A — full corpus a-0.3.0 (54 documents) | 3.63 |
| Module A — full corpus a-0.4.0, **official snapshot** (`MANIFEST.json`: extraction 3.86 + date classifier 0.01) | 3.87 |
| Module A — incremental rehearsal (1 document) | 0.07 |
| Module B — coverage compiler, four full compiles while iterating the prompt (Haiku 4.5) + partial recompiles | ≈ 1.7 |
| Module C — T6 rehearsal (extract-doc + compile) | ≈ 0.08 |
| API — plain-language summaries and Spanish revision (Haiku 4.5) | not metered (small) |
| **Total measured** | **≈ 10** |

Pricing used: Claude Opus 5.5 $4 / $20 per million input/output tokens (cache write 1.25×
input, cache read $0.20); Claude Haiku 4.5 $1 / $5. Reproducing from the snapshot,
normalization, export, smoke-check, lookups, change tests and every API route cost nothing.

---

## Tests

```bash
python -m pytest -q        # 179 tests, offline; the API client is never built, no Census calls
```

Covers, for Module A: quote cascade (curly quotes, line breaks, fuzzy, paraphrase → retry or
rejected, invented quote → rejected), date value formats and kinds, dispositions and
confidence, citation formatting and aliases, merge and stage merge, administrative linking and
ambiguity, citation resolution, stable and legacy ids, certificate-of-occupancy conversion, CA
calendar default and T1/T3, conflicts (key value, preemption, pending values, no false
positives), extraction with a mocked client (retries, cache, audit), reproduction from the
snapshot (differs only by the documented Module B adjustments), offline mode, ingest of
.html/.txt, and the incremental Cambridge rehearsal from its frozen LLM answer. For Module B/C
and the API: building facts and geocoding (offline), compiler safeguards, Kleene coverage (guide
cases: SF/LA certificate cutoffs, AB 1482 rolling 15 years, owner exemptions refuted by unit
counts, Hoboken parsed units, Boston units unknown), presumption scope, human review register,
the brief's SF example, T1–T5, the change dashboard, one test per API route, the plain-language
validator, Spanish glossary and "usted".

---

## Versioning and release

* Branch **`module-a`**, tag **`module-a-v1`** (snapshot a-0.4.0, Module A only); branch
  **`module-b`** (Modules B and C); **`main`** with tag **`modules-abc-v1`** (merge of Modules
  A, B and C) and the API on top.
* `snapshots/` and the Module B data in `data/` are versioned; `out/`, `static/`, `.cache/` and
  `.env` are git-ignored.
* `.gitattributes` marks the starter-pack corpus, `snapshots/`, `tests/fixtures/`,
  `prompts/*.md`, `data/geocode_raw/` and `data/*.json` as `-text` (no line-ending conversion):
  `text_sha256`, `prompt_sha256` and reproduction depend on them.
* To change the extraction: edit `prompts/extract_system.md`, bump `PROMPT_VERSION` on its
  first line, run `extract-all`, `normalize`, `export`, and freeze with `snapshot --name …`
  (snapshots are immutable).

---

*Built for the MIT Rental Housing Law Navigator challenge. Research and informational use
only — **not legal advice**.*
