# Rental Housing Law Navigator — Module A (Rule Extraction)

Module A of the MIT AI Hackathon challenge *Rental Housing Law Navigator* (RealPage
discussion draft, October 2026). It reads the starter-pack corpus of real U.S. rental-housing
law (California, New Jersey, Massachusetts and ten of their cities) and turns it into
structured, citation-backed **rule records**: `out/rules.json` (`{"rules": [...]}`), valid
against the official `schema/rule_record.schema.json`.

Every exported rule carries a `quoted_span` that is **verified to exist in the source text**,
a citation, the source URL and retrieval date, and a **status as of a query date** that is
computed — never guessed — from the law's legislative stage and dates.

> ⚖️ **Not legal advice.** This is an information-extraction prototype, not legal counsel or a
> compliance certification. Summaries of law here are for building a prototype.

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
17. [Known limitations and design decisions](#known-limitations-and-design-decisions)
18. [Prompt history](#prompt-history)
19. [Cost of Module A](#cost-of-module-a)
20. [Tests](#tests)
21. [Versioning and release](#versioning-and-release)

---

## Results at a glance

Official run: snapshot **`a-0.4.0`** (prompt `a-0.4.0`, `claude-opus-5-5`, effort `high`),
query date **2026-10-01**.

| | |
|---|---|
| Documents with text in the corpus | 54 of 87 (the rest are link-only / check-terms / failed capture) |
| Candidate rules extracted | 103 |
| Quotes verified | 103/103 (86 exact, 16 normalized, 1 fuzzy, 0 needed an LLM retry); 0 rejected |
| Rules exported to `rules.json` | **66** (schema-valid) |
| Held internally (not exported) | 12 (7 `no_citation`, 5 `administrative_unlinked`) |
| Folded into other rules | 25 (10 duplicates, 15 administrative figures) |
| Status on 2026-10-01 | 58 `in_force` · 4 `pending` · 3 `failed` · 1 `not_yet_effective` |
| Conflicts between documents | 2 flagged pairs + 2 informational records |
| Smoke check | **all checks pass** (pipeline 3/3, behaviour T1/T3/T4/T5 8/8; 20 of 23 expected citations found, 3 absent because their source is link-only) |

Exported rules by jurisdiction × category:

| Jurisdiction | rent_increase | just_cause | deposits | app_fees | screening | algorithmic | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| CA | 1 | 3 | 6 | 2 | 2 | 1 | 15 |
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
| **Total** | 16 | 17 | 11 | 7 | 8 | 7 | **66** |

Empty cells are explained by the corpus, not by the pipeline: Hoboken and Newark have no
supplied text (their codes are `check-terms` on ecode360), Boston and Cambridge cannot have a
rent cap (M.G.L. c. 40P), and several city ordinances are link-only (see
[Preguntas abiertas](#preguntas-abiertas-no-resolubles-con-el-corpus)).

Change-test checks on the exported rules:

| Test | Rule | Expected | Result |
|---|---|---|---|
| T1 — CA AB 325 | `CA-ALGO-01` (Cal. Bus. & Prof. Code § 16729) | `not_yet_effective` 2025-12-31, `in_force` 2026-01-02 | ✅ (effective 2026-01-01 derived from the CA calendar default) |
| T3 — NJ FAIR Act | `NJ-ALGO-01` (P.L.2026, c.43) | `not_yet_effective` 2026-10-01, `in_force` 2027-07-02 | ✅ (2027-07-01 derived from "first day of the twelfth month next following enactment", approved 2026-07-20) |
| T4 — MA S.2983 / H.5222 | `MA-ALGO-P02`, `MA-ALGO-P01` | `pending` | ✅ |
| T5 — MA rent-control ballot question | — | no rent cap in force in MA / Boston / Cambridge | ✅ (M.G.L. c. 40P is reported: it bars local rent control → no local cap) |

---

## Quick start

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Rebuild out/rules.json from the frozen snapshot — no API key needed, ~5 s
python -m extractor.cli reproduce

# Dashboard of checks (pipeline, expected citations, T1/T3/T4/T5)
python -m extractor.cli smoke-check
```

An API key is only needed to extract **new** text (full re-extraction or `extract-doc`):

```bash
cp .env.example .env                   # then set ANTHROPIC_API_KEY
```

The starter pack is expected at `./participant-final-no-hour16 3/` (override with
`STARTER_DIR`).

### Configuration

Settings live in `extractor/config.py`, overridable via environment variables or `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(only for new extraction)* | API key — read only from the environment, never logged or cached |
| `EXTRACT_MODEL` | `claude-opus-5-5` | Extraction model |
| `EXTRACT_EFFORT` | `high` | Effort for extraction calls (Opus 5.5 defaults to `medium`, so it is set explicitly) |
| `EXTRACT_MAX_TOKENS` | `32000` | Max output per extraction call (streamed) |
| `EXTRACT_CONCURRENCY` | `4` | Documents extracted in parallel |
| `LLM_MAX_RETRIES` | `4` | SDK retries with exponential backoff (408/409/429/5xx) |
| `QUOTE_RETRY_EFFORT` | `medium` | Effort for the single quote-retry call in validation |
| `DATE_CLASSIFIER_MODEL` | `claude-haiku-4-5` | Small model for ambiguous date kinds |
| `AS_OF` | `2026-10-01` | Default query date |
| `STARTER_DIR` | `participant-final-no-hour16 3` | Starter pack location |
| `OUT_DIR` / `CACHE_DIR` | `out/` / `.cache/` | Outputs / on-disk LLM cache (both git-ignored) |

Dependencies (pinned in `requirements.txt`): `anthropic`, `pydantic`, `typer`,
`jsonschema`, `python-dotenv`, `rapidfuzz`, `pyyaml`, `pypdf`, `pytest`.

---

## Commands

```bash
# Reproduce from the frozen snapshot (offline): extract-all --from-snapshot + normalize + export
python -m extractor.cli reproduce [--snapshot snapshots/a-0.4.0] [--as-of 2026-10-01]

# Offline dashboard: pipeline invariants, expected citations, T1/T3/T4/T5
python -m extractor.cli smoke-check

# Incremental mode (hour 16): add ONE new document (.txt/.pdf/.html) on top of the snapshot
python -m extractor.cli extract-doc path/to/ordinance.pdf --jurisdiction "Cambridge, MA"

# Export for another query date (status and effective dates are recomputed, no LLM)
python -m extractor.cli export --as-of 2027-07-02

# Full re-extraction with the API (cached in .cache/), then freeze it as a new snapshot
python -m extractor.cli extract-all [--only D022 --only D069] [--no-cache]
python -m extractor.cli normalize [--ids-from snapshots/a-0.4.0/ids.json]
python -m extractor.cli export --as-of 2026-10-01
python -m extractor.cli snapshot --name a-0.5.0
```

---

## Project layout

```
.
├── extractor/                     # the pipeline, one module per stage
│   ├── cli.py                     # python -m extractor.cli <command>
│   ├── config.py                  # paths + settings (env/.env); PROMPT_VERSION read from the prompt file
│   ├── corpus.py                  # manifest + text/*.txt -> Document (header split, cleaning)
│   ├── clean.py                   # boilerplate removal (whole lines only) + clean->raw offset map
│   ├── llm.py                     # Anthropic client, record_rules tool, retries, cache, snapshot lookup
│   ├── extract.py                 # Document -> LLM -> RuleInternal[] (+ validation)
│   ├── validate.py                # quote cascade, date checks, dispositions, final confidence
│   ├── dates.py                   # date formats + date-kind classification
│   ├── normalize.py               # citations, citation resolution, defaults, merge, admin links, IDs, precedence
│   ├── conflicts.py               # conflicts between documents -> out/conflicts.json
│   ├── status.py                  # status as of a date
│   ├── export.py                  # RuleInternal -> RuleOut -> out/rules.json (jsonschema-validated)
│   ├── snapshot.py                # freeze / activate snapshots (reproduction without API)
│   ├── incremental.py             # extract-doc: one new document on top of a snapshot
│   ├── smoke.py                   # smoke-check dashboard
│   ├── audit.py                   # append-only out/audit.jsonl
│   └── models.py                  # pydantic models (RuleCandidate, RuleInternal, RuleOut, ...)
├── prompts/
│   ├── extract_system.md          # extraction prompt; first line declares PROMPT_VERSION
│   └── quote_retry.md             # prompt for the single quote-retry call
├── data/
│   ├── citation_aliases.yaml      # law alias table + citation formatting rules
│   └── jurisdiction_defaults.yaml # calendar defaults (CA only)
├── snapshots/a-0.4.0/             # frozen official extraction (versioned in git)
├── corpus/new/                    # documents added with extract-doc (created on demand)
├── tests/                         # offline pytest suite
│   ├── expected_citations.yaml    # measurement-only list for smoke-check
│   └── fixtures/                  # fictitious Cambridge ordinance + its frozen LLM answer
├── participant-final-no-hour16 3/ # starter pack: corpus, schema, sample addresses, change tests, brief
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
              merge), administrative figures, stable team_rule_ids, precedence
conflicts.py  conflicts between documents
status.py     status as of --as-of (never extracted)
export.py     accepted rules -> RuleOut -> out/rules.json (validated with jsonschema)
audit.py      every step appends to out/audit.jsonl
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
| `merged` | `duplicate_merged`, `administrative_linked` | no — folded into another rule |

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
5. **Administrative figures** (annual allowable increases, relocation amounts, deposit
   interest) are folded into the enacted rule of the same jurisdiction and category,
   preferring the same law, as `key_value_details` (value, period, source, quote). A figure
   stays `held` / `administrative_unlinked` when it names a law with no enacted rule here,
   when there is no enacted rule to attach to, or when it names no law and several candidate
   rules exist without a clear title match (similarity ≥ 60 and 10 points above the
   runner-up). On export, `key_value` shows the legal value plus every figure in force on the
   query date, e.g. `SF-RENT-01`: "current (2026-03-01 to 2027-02-28; D080): 1.6%".
6. **IDs** — `{JUR}-{CAT}-{NN}` with `P` for pending bills, `F` for failed bills and `H` for
   held rules (internal), e.g. `CA-RENT-01`, `MA-ALGO-P01`, `MA-RENT-F01`. Codes: CA, NJ, MA,
   BRK, LA, SD, SF, SNA, HOB, JC, NWK, BOS, CAM × RENT, JUST, DEP, FEE, SCRN, ALGO.
   Deterministic; with a snapshot's `ids.json` (incremental runs, `reproduce`) published ids
   never change and new rules take the next free number in their cell.
7. **Precedence** — a state rule whose interaction says it yields to stricter local law
   (Civ. Code § 1947.12 and § 1946.2 vs local rent control / just cause) or preempts it gets
   the local `team_rule_id`s in `overrides`, each local rule gets the state id, and the
   direction is written in `interaction`. 23 exported rules carry `overrides`.

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

Current conflicts (snapshot a-0.4.0):

| Type | Rules | Detail |
|---|---|---|
| `key_value` | `CA-FEE-01` ↔ `CA-FEE-02` | Cal. Civ. Code § 1950.6: statute (D026) "$30 per applicant, CPI-adjusted annually" vs Berkeley Rent Board page (D005) "$68.96 (2026 maximum)" — **the CA screening-fee cap has no single official 2026 figure** |
| `preemption` | `NJ-RENT-03` ↔ `JC-RENT-01` | NJ Newly Constructed Multiple Dwellings Law (30-year exemption) overrides the Jersey City rent control ordinance |
| `preemption_no_local_rule` | `MA-RENT-01` | M.G.L. c. 40P bars local rent control; no local MA rent rule exists |
| `preemption_no_local_rule` | `NJ-ALGO-01` | FAIR Act prohibits conflicting municipal ordinances; no local NJ algorithmic rule is in the corpus |

Other notes on exported rules: `LA-RENT-04` "expired on 2024-01-31" (RSO COVID freeze);
`LA-RENT-05` "stage unclear" (the model could not tell the stage; confidence capped at 0.5).

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
| `rules.json`, `conflicts.json` | official export (as of 2026-10-01) |

`python -m extractor.cli reproduce` serves every document from `llm/`, re-runs validation,
normalization, conflicts and status locally, and writes `out/rules.json` and
`out/conflicts.json` — **byte-identical** to the snapshot's (verified with no API key and an
empty `.cache/`, ~5 s). In snapshot mode the API client is disabled (`config.OFFLINE`): a
document missing from the snapshot is an error, never a silent API call. All artifacts are
written with LF line endings on every platform, and `.gitattributes` keeps git from
converting them, so hashes and byte-identity hold on Windows, macOS and Linux.

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
   `team_rule_id`s never change.

It prints a video-friendly summary — new/modified rules, status as of 2026-10-01, effective
date and whether it was derived, new conflicts, seconds per stage — and writes
`out/increment_<doc_id>.json` (consumed by Module C).

**Rehearsal** with a fictitious Cambridge ordinance (`tests/fixtures/fake_cambridge_ordinance.txt`:
Ordinance No. 2026-17, ch. 8.72, adopted 2026-09-14, "effective 180 days after adoption",
exemption for buildings with fewer than six units):

```
[NEW] CAM-ALGO-01 · Cambridge, MA · city · algorithmic_rent_setting
  citation       : Cambridge Mun. Code § 8.72.030
  STATUS         : not_yet_effective
  effective_date : 2027-03-13   (DERIVED: one hundred eighty (180) days after its adoption)
  exemption      : units < 6
TIME: ingest 0.03 · extract (LLM) 16.18 · validate 0.00 · normalize 0.40 · conflicts 0.07 · export 0.15 · TOTAL 16.8 s
```

All 66 existing rules kept their ids and content. Cost ≈ $0.07. The rehearsal was undone
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
gap visible.

| Question | What the corpus has | Missing source (no text) | How the system handles it |
|---|---|---|---|
| **Berkeley ch. 13.63 — two published effective dates** (March 1, 2026 per the ordinance; January 2026 per an Aug 2026 law-firm alert) | D001: Ordinance No. 7,992-N.S. amending ch. 13.63, recorded only as "passed to print" on November 18, 2025 (first reading). No effective date, no adoption or second-reading record. No other Berkeley document mentions 13.63. | D002 (Morgan Lewis alert, link-only) | `BRK-ALGO-P01`, stage `bill_pending` → status `pending`, no effective date. With one date-less source, no date conflict can be raised. |
| **San Diego §§ 98.1101–98.1104** (algorithmic ban) | D076: the *proposed* ordinance package (O-2025-107); ordinance number, date of final passage and adoption certificate are blank. | D074 (codified text, check-terms) | `SD-ALGO-P01`, `pending`. |
| **Los Angeles RSO new formula — two effective dates** (2026-02-02 per LAHD; 2026-01-24 per a landlord association) | D041 and D042 (LAHD) both state February 2, 2026. | The landlord-association statement is not in the corpus; D044 (AAGLA, link-only) is about deposit interest; the LAMC text D038 is check-terms. | RSO rules carry the single verified date 2026-02-02; no conflict is flagged because only one source is readable. |
| **Hoboken and Jersey City algorithmic rent-setting ordinances** (T2 boundary, T3 preemption by the NJ FAIR Act) | D036 (Jersey City landlord/tenant page) has no algorithm content. | Hoboken code D032–D034 (ecode360, check-terms); Jersey City D035 (news) and D037 (Morgan Lewis), link-only; D060 (Day Pitney on the FAIR Act), link-only. | No local NJ `algorithmic_rent_setting` rule exists. The FAIR Act's "municipalities are prohibited from enacting ordinances…" clause is recorded in `out/conflicts.json` as `preemption_no_local_rule` (informational) instead of a conflict pair. |
| **San Francisco annual allowable increase (Rent Ordinance § 37.3)** | D079 says some units "are exempt from the rent increase limitations of the Ordinance" (certificate of occupancy after 1979-06-13, Costa-Hawkins); D080/D083 give the Rent Board's 1.6% / 1.4% figures. | The text of § 37.3 itself is not in the corpus. | `SF-RENT-01` (`S.F. Admin. Code ch. 37`, coverage `certificate_of_occupancy_on_or_before 1979-06-13`, `key_value` null) with the Rent Board figures attached; the 60%-of-CPI formula is not stated. |
| **Massachusetts bills S.2983 and H.5222** (T4: who would be affected) | D045, D046, D047: bill status/history pages (titles, committee actions, dates). D011: H.3744 status page. | The bill texts themselves (no bill-text document in the manifest); D059 (WBUR on the struck ballot question), link-only. | Bills are recorded with stage `bill_pending` (status `pending`), `key_value` null and coverage "not described"; their scope can only be stated at jurisdiction level (MA statewide). H.3744 is `failed`. No MA or Boston/Cambridge rent cap exists (T5), consistent with M.G.L. c. 40P. |

---

## Known limitations and design decisions

* **Corpus-bound by design.** Rules, dates, citations and aliases come only from the
  supplied text or explicit team decisions. A law whose text is link-only is absent (see the
  table above), even when its content is publicly known.
* **Category judgments vary between runs.** Re-extraction with the same prompt can move a
  borderline provision in or out of a category (e.g. M.G.L. c. 186 § 11, a 14-day notice to
  quit for nonpayment, was a `just_cause_eviction` rule in a-0.3.0 and is not in a-0.4.0).
  The snapshot freezes one run so results are reproducible.
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
* **The brief PDF in the starter pack** (`…v5-participant-no-scoring-no-hour16.pdf`) does not
  contain the citation examples used by `expected_citations.yaml`; the list was supplied by
  the team and is used for measurement only.

---

## Prompt history

| Version | Change | Effect on the 4-document test set (D081, D069, D022, D016) |
|---|---|---|
| a-0.2.0 | first prompt; one rule per distinct requirement | 14 rules; D016 (CRD FAQ) produced deposit rules from discrimination examples; quotes sometimes started mid-sentence |
| a-0.3.0 | granularity per law; strict category definitions; `is_secondary_source` only for another jurisdiction; relative dates derived (`derived`); quotes start at a sentence with the operative verb; typed exemptions; `citation_aliases` | 5 rules; FAIR Act effective date 2027-07-01 derived; AB 325 1 rule (§ 16729) |
| a-0.4.0 | record a law whose coverage/exemptions are described even without the limit's value (`key_value` null) | full corpus: 62 → 66 exported rules; `SF-RENT-01` (Rent Ordinance coverage, CO ≤ 1979-06-13) now exists |

Validation, normalization, conflicts and status evolved alongside (date verification by
value, date kinds, stage merge, administrative linking, stable ids); they never call the
extraction model.

---

## Cost of Module A

| Run | USD |
|---|---:|
| Prompt iterations on 4 documents (a-0.2.0, a-0.3.0, strict-schema probes) | ≈ 0.62 |
| Full corpus a-0.3.0 (54 documents) | 3.63 |
| Full corpus a-0.4.0 — **official snapshot** (`MANIFEST.json`: extraction 3.86 + date classifier 0.01) | 3.87 |
| Incremental rehearsal (1 document) | 0.07 |
| **Total Module A** | **≈ 8.2** |

Pricing used: Claude Opus 5.5 $4 / $20 per million input/output tokens (cache write 1.25×
input, cache read $0.20); Claude Haiku 4.5 $1 / $5. Reproducing from the snapshot,
normalization, export and smoke-check cost nothing.

---

## Tests

```bash
python -m pytest -q        # 54 tests, offline; the API client is never built
```

Covers: quote cascade (curly quotes, line breaks, fuzzy, paraphrase → retry or rejected,
invented quote → rejected), date value formats and kinds, dispositions and confidence,
citation formatting and aliases, merge and stage merge, administrative linking and
ambiguity, citation resolution, stable ids, CA calendar default and T1/T3, conflicts
(key value, preemption, pending values, no false positives), extraction with a mocked
client (retries, cache, audit), byte-identical reproduction from the snapshot, offline mode,
ingest of .html/.txt, and the incremental Cambridge rehearsal from its frozen LLM answer.

---

## Versioning and release

* Branch **`module-a`**, tag **`module-a-v1`** (snapshot a-0.4.0, smoke check all green).
* `snapshots/` is versioned; `out/`, `.cache/` and `.env` are git-ignored.
* `.gitattributes` marks the starter-pack corpus, `snapshots/`, `tests/fixtures/` and
  `prompts/*.md` as `-text` (no line-ending conversion): `text_sha256`, `prompt_sha256` and
  byte-identical reproduction depend on them.
* To change the extraction: edit `prompts/extract_system.md`, bump `PROMPT_VERSION` on its
  first line, run `extract-all`, `normalize`, `export`, and freeze with `snapshot --name …`
  (snapshots are immutable).

---

*Built for the MIT Rental Housing Law Navigator challenge. Research and informational use
only — **not legal advice**.*
