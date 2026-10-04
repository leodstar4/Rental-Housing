# Rental Housing Law Navigator — Module A (Extraction)

Extracts structured, citation-backed **rule records** from a corpus of U.S. rental-housing
legal documents (statutes, ordinances, bills, agency bulletins). It reads the starter-pack
corpus and produces `out/rules.json` (`{"rules": [...]}`), validated against
`schema/rule_record.schema.json`.

Every rule carries a `quoted_span` that is **verified to exist verbatim** in the source
text, so each extracted claim is traceable back to the exact words of the law.

> ⚖️ **Not legal advice.** This is an information-extraction tool, not a source of legal counsel.

---

## What it does

Given raw legal text, the pipeline identifies rules across six categories:

- `rent_increase_limits`
- `just_cause_eviction`
- `security_deposits`
- `application_screening_fees`
- `screening_restrictions`
- `algorithmic_rent_setting`

For each rule it captures the jurisdiction, requirement, coverage conditions (year built,
unit counts, owner/property exemptions, etc.), the law's lifecycle stage and dates, conflict
flags, and full provenance (citation, source document, source URL, and a verbatim quote).

A rule's **status** (`in_force`, `not_yet_effective`, `pending`, `failed`) is *derived* from
its legislative stage and dates relative to a query date (`--as-of`) — it is never extracted
directly from the text.

---

## Project layout

```
.
├── extractor/                 # the pipeline (one module per stage)
│   ├── cli.py                 # python -m extractor.cli <command>
│   ├── config.py              # paths + runtime settings (env/.env overridable)
│   ├── corpus.py              # manifest + text/*.txt -> Document
│   ├── clean.py               # drop nav/boilerplate (whole lines only); keep offset map
│   ├── extract.py             # clean_text -> LLM -> RuleInternal[]
│   ├── llm.py                 # structured output, retries, on-disk cache
│   ├── validate.py            # quote cascade, date checks, dispositions, confidence
│   ├── dates.py               # date formats + date-kind classification
│   ├── normalize.py           # citations, citation resolution, defaults, merge, admin links, IDs, precedence
│   ├── conflicts.py           # conflicts between documents -> out/conflicts.json
│   ├── status.py              # derive status from stage + dates for --as-of
│   ├── export.py              # RuleInternal -> RuleOut -> out/rules.json
│   ├── snapshot.py            # freeze / load snapshots (reproduction without API)
│   ├── incremental.py         # extract-doc: one new document on top of a snapshot
│   ├── smoke.py               # smoke-check dashboard
│   ├── audit.py               # append-only out/audit.jsonl
│   └── models.py              # pydantic models (RuleInternal, RuleOut, ...)
├── resolver/                  # Module B (python -m resolver.cli <command>)
│   ├── addresses.py           # sample_addresses.csv -> Address (all strings) + dataset city
│   ├── facts.py               # building facts: units range, year built, use flags
│   └── geocode.py             # Census Geocoder -> jurisdiction stack
├── data/
│   ├── citation_aliases.yaml       # law alias table (see "Citation aliases")
│   ├── jurisdiction_defaults.yaml  # calendar defaults (see "Status")
│   ├── review_flags.yaml           # known open questions flagged for review (guide §9)
│   ├── test_rule_map.yaml          # dev/change_tests.json ids -> our ids
│   ├── use_code_map.yaml           # use codes -> unit ranges and use flags
│   ├── building_facts.json         # Module B output (versioned)
│   ├── jurisdictions.json          # Module B output (versioned)
│   └── geocode_raw/                # raw Census responses (versioned; demo works offline)
├── prompts/                   # extract_system.md (PROMPT_VERSION), quote_retry.md
├── snapshots/a-0.4.0/         # frozen official extraction (see "Reproducing from the snapshot")
├── corpus/new/                # documents added with extract-doc (created on demand)
├── tests/                     # offline pytest suite, fixtures, expected_citations.yaml
├── participant-final-no-hour16 3/   # starter pack (corpus, schema, templates)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup (Python 3.11+)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then set ANTHROPIC_API_KEY
```

The starter pack is expected at `./participant-final-no-hour16 3/` (override with the
`STARTER_DIR` environment variable).

### Configuration

Settings live in `extractor/config.py` and are overridable via environment variables / `.env`:

| Variable             | Default                          | Purpose                                  |
| -------------------- | -------------------------------- | ---------------------------------------- |
| `ANTHROPIC_API_KEY`  | *(required for extraction)*      | API key — read only, never logged/cached |
| `EXTRACT_MODEL`      | `claude-opus-5-5`                | Model used for extraction                |
| `EXTRACT_EFFORT`     | `high`                           | Reasoning effort for extraction calls    |
| `AS_OF`              | `2026-10-01`                     | Default query date for status            |
| `STARTER_DIR`        | `participant-final-no-hour16 3`  | Location of the starter pack             |
| `OUT_DIR`            | `out/`                           | Output directory                         |
| `CACHE_DIR`          | `.cache/`                        | On-disk extraction cache                 |
| `QUOTE_RETRY_EFFORT` | `medium`                         | Effort for the single quote-retry call   |
| `DATE_CLASSIFIER_MODEL` | `claude-haiku-4-5`            | Small model for ambiguous date kinds     |

The API key is read **only** from `ANTHROPIC_API_KEY`; it is never written to config
objects, cache entries, or the audit log.

---

## Commands

```bash
# Reproduce out/rules.json from the frozen snapshot — no API key needed (~5 s)
python -m extractor.cli reproduce                      # = extract-all --from-snapshot + normalize + export

# Dashboard: pipeline invariants, expected citations, T1/T3/T4/T5 — no API calls
python -m extractor.cli smoke-check

# Incremental mode (hour 16): add ONE new document (.txt/.pdf/.html) on top of the snapshot
python -m extractor.cli extract-doc path/to/new_ordinance.pdf --jurisdiction "Cambridge, MA"

# Full re-extraction (needs ANTHROPIC_API_KEY; results cached in .cache/), then freeze it
python -m extractor.cli extract-all
python -m extractor.cli normalize
python -m extractor.cli export --as-of 2026-10-01
python -m extractor.cli snapshot --name a-0.5.0
```

## Reproducing from the snapshot (no API key)

The official extraction is frozen in **`snapshots/a-0.4.0/`** (versioned in git):

| File | Content |
|---|---|
| `MANIFEST.json` | prompt version + sha256 + fingerprint, model (`claude-opus-5-5`), effort (`high`), creation date, cost, token counts, per-document text sha256 |
| `extract_system.md` | the frozen extraction prompt |
| `llm/<doc_id>.json` | raw model output per document (`record_rules` tool input + usage) |
| `aux_cache/` | quote-retry and date-kind answers used by validation |
| `extracted/<doc_id>.json` | validated rules per document |
| `ids.json` | uid → `team_rule_id` of the official run (keeps ids stable) |
| `rules.json`, `conflicts.json` | official export (as of 2026-10-01) |

`python -m extractor.cli reproduce` (or `extract-all --from-snapshot snapshots/a-0.4.0`
followed by `normalize --ids-from snapshots/a-0.4.0/ids.json`, `export` and `attest`) serves
every document from `llm/`, re-runs validation, normalization, conflicts and status locally,
and writes `out/rules.json` and `out/rules_attested.json`. The output is deterministic; it
differs from the frozen `snapshots/a-0.4.0/rules.json` only by the documented Module B
adjustments (see "Module B adjustments to the rules"), which
`tests/test_snapshot_incremental.py` checks record by record. In snapshot mode the API client
is disabled (`config.OFFLINE`); a document missing from the snapshot is an error, never a
silent API call.

## Incremental mode — `extract-doc`

```bash
python -m extractor.cli extract-doc tests/fixtures/fake_cambridge_ordinance.txt --jurisdiction "Cambridge, MA"
```

1. **ingest** — `.txt`, `.pdf` (pypdf) or `.html` → text, saved to `corpus/new/<doc_id>.txt`
   (corpus format, SOURCE/RETRIEVED header) with `<doc_id>.meta.json` (sha256 of the
   original file, retrieval date, jurisdiction hint).
2. **extract** — only this document, with the frozen prompt (aborts if
   `prompts/extract_system.md` differs from the snapshot's).
3. **validate → normalize → conflicts → status/export** — on snapshot rules + the new
   ones; the new rules merge with same-law rules, and existing `team_rule_id`s never change
   (new rules get the next free number in their cell).

It prints a video-friendly summary (new/modified rules, status as of 2026-10-01,
effective date and whether it was derived, new conflicts, seconds per stage) and writes
`out/increment_<doc_id>.json` for Module C. Rehearsal with the fictitious Cambridge
ordinance (`tests/fixtures/`): CAM-ALG-01, city, `algorithmic_rent_setting`,
`not_yet_effective`, effective 2027-03-13 derived from "180 days after its adoption"
(adopted 2026-09-14), exemption `units < 6`; ~17 s, of which ~16 s is the LLM call.
To undo an incremental run: delete `corpus/new/<doc_id>.*` and run `reproduce`.

## Smoke check

`python -m extractor.cli smoke-check` reads the current `out/` artifacts (run `reproduce`
first) and prints a dashboard (also saved to `out/smoke_check.json`):

* **Pipeline**: corpus loads and cleaning keeps raw lines verbatim; `rules.json` is
  schema-valid; every exported rule has a citation and a verified quote.
* **Expected citations** (`tests/expected_citations.yaml`, measurement only — never read
  by extraction): found / found as held / absent because the source is link-only (pattern
  absent from every loadable text and the jurisdiction has link-only sources) / absent
  without explanation (text present but not extracted).
* **Behaviour**: T1 (AB 325 not yet effective 2025-12-31, in force 2026-01-02), T3 (FAIR Act
  not yet effective 2026-10-01, in force 2027-07-02), T4 (S.2983 and H.5222 pending), T5 (no
  MA, Boston or Cambridge rent **cap** in force: a rule fails only if it has a `key_value` and
  is not a prohibition/preemption of local rent control — M.G.L. c. 40P is still reported, with
  the note "c. 40P bars local rent control → no local cap").

## Cost of Module A

| Run | USD |
|---|---:|
| Prompt iterations on 4 documents (a-0.2.0, a-0.3.0, schema probes) | ≈ 0.62 |
| Full corpus a-0.3.0 (54 documents) | 3.63 |
| Full corpus a-0.4.0 — **official snapshot** (`MANIFEST.json`: extraction 3.86 + date classifier 0.01) | 3.87 |
| Incremental rehearsal (1 document) | 0.07 |
| **Total Module A** | **≈ 8.2** |

Reproducing from the snapshot, normalization, export and smoke-check cost nothing.

---

## Pipeline

```
corpus.py    manifest + text/*.txt -> Document (header split; link-only/failed rows skipped)
clean.py     drop nav/boilerplate *whole lines only*; keep clean->raw offset map
extract.py   clean_text -> LLM (llm.py: structured output, retries, cache) -> RuleInternal[]
validate.py  quoted_span must occur in raw_text; dates verified by value and classified by kind
normalize.py citation aliases, citation resolution, calendar defaults, merge, admin links, IDs, precedence
conflicts.py conflicts between documents (dates, values, preemption, values marked pending)
status.py    status computed from stage + dates for --as-of (never extracted)
export.py    RuleInternal -> RuleOut -> out/rules.json (jsonschema-validated)
audit.py     out/audit.jsonl, append-only
```

### Cleaning guarantees

- Only **whole lines** are removed; every kept line is byte-identical to the raw line.
- Header/footer cuts are **refused** if they would drop a line that looks like legal text
  (`shall`, `unlawful`, `§`, `(a)`, `SEC. n`); refusals are reported.
- The page title line is **always kept** (it is often the only citation context, e.g.
  `General Law - Part II, Title I, Chapter 186, Section 11`).
- Quotes are verified against `raw_text`, **not** `clean_text`.

### Caching

`.cache/` is keyed by `sha256(document text)` + `PROMPT_VERSION` + a hash of the prompt and
tool schema + model + effort. `PROMPT_VERSION` is declared on the first line of
`prompts/extract_system.md`; bump it whenever the prompt changes. Quote retries and date-kind
classifications are cached too, so re-validating from cache costs nothing.

---

## Data model

- **`RuleInternal`** — the rich internal record: structured dates, coverage, provenance,
  and quote offsets. Everything downstream reads this.
- **`RuleOut`** — mirrors `schema/rule_record.schema.json` exactly (no extra keys);
  produced only by `export.to_rule_out` and re-validated with `jsonschema` on export.

See `extractor/models.py` for the full schema.

---

## License / disclaimer

This project was built for the MIT Rental Housing Law Navigator challenge. It is provided
for research and informational purposes only and does **not** constitute legal advice.

## Validation (`validate.py`)

Every candidate's `quoted_span` is checked against the source document's **raw** text:

| Step | `match_type` | How |
|---|---|---|
| a | `exact` | literal substring |
| b | `normalized` | whitespace/line breaks, curly quotes, dashes, NBSP folded; span replaced by the literal raw fragment |
| c | `fuzzy` | rapidfuzz `partial_ratio` ≥ 95 (spans ≥ 20 chars); span replaced by the aligned raw fragment |
| d | `retry` | ONE LLM call (`prompts/quote_retry.md`) asks for a literal quote; a–c re-run |
| e | — | `rejected` / `citation_unverified` → `out/rejected.json` + audit; never exported |

Date quotes (`effective_dates`, `enacted_date`, `sunset_date`) run a–c. An unverified
date is dropped (not the rule). A non-derived date's **value** must appear in its quote in
any common format ("October 6, 2025", "Oct. 6, 2025", "10/06/2025", "3/01/26", "6-24-2023").
A `derived` date also needs a verified `enacted_date` (its base).

Each date gets a **kind** (`dates.py`): `effective` (general entry into force), `operative`
(calculation/base date, e.g. "rent increases occurring on or after March 15, 2019"),
`amendment` (effective date of an amendment, e.g. a statute history note "(Amended by
Stats. …) Effective January 1, 2026."), or `enacted`. Rules on the wording decide first;
only ambiguous dates go to a small, configurable model (`DATE_CLASSIFIER_MODEL`, cached).
Date conflicts and status only use `effective` dates.

Dispositions: `accepted` (exported) · `held` (kept internally for conflicts and
interactions, not exported: `no_citation`, `administrative_unlinked`) · `rejected`
(`citation_unverified`, `schema_invalid`) · `merged` (folded into another rule:
`duplicate_merged`, `administrative_linked`).

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

## Normalization (`normalize.py`, no LLM)

1. **Citations** are put in schema style (`Cal. Civ. Code § 1950.6`, `§ ` with a space,
   `LAMC 165.03` → `L.A. Mun. Code § 165.03`) and law names are mapped through
   `data/citation_aliases.yaml`. A **state bill** citation (`MA H.3744`, `CA AB 325`) is always
   state jurisdiction/level, even when the bill concerns one city (a home-rule petition for
   Boston is still MA law); the correction is noted in `validation_errors`.
2. **Missing citations**: a `held`/`no_citation` rule takes the citation of an accepted rule
   of the *same law and jurisdiction*. If the held rule names its law (aliases), only those
   names and its title are matched; otherwise its text must name exactly one law ("applies
   to RSO and JCO units" stays held). The citation is **law-level** when the alias table
   knows the law (SF "Rent Ordinance" matched via § 37.10C → `S.F. Admin. Code ch. 37`), not
   the source's section. `citation_resolved_from = <team_rule_id>`, confidence × 0.9.
3. **Calendar defaults** from `data/jurisdiction_defaults.yaml` (see Status).
4. **Merge**: same jurisdiction, category and base citation (without subsection) → one
   rule, unless coverage thresholds, key value or effective dates differ. `requirement`
   summarizes the members; every literal quote is kept in `evidence`. The same law seen at
   different **stages** (e.g. a bill page saying pending and the adopted text) merges too:
   the most advanced verified stage wins (enacted > administrative > failed > pending >
   unknown) and every document's claim is kept in `stage_history`.
5. **Administrative figures** (annual allowable increases, relocation amounts) are folded
   into the enacted rule of the same jurisdiction and category, preferring the same law, as
   `key_value_details`. It stays `held` / `administrative_unlinked` when it names a law
   (citation, or an alias such as "Resident Protections Ordinance") that has no enacted rule
   here, when there is no enacted rule to attach to, or when it names no law and several
   candidate rules exist without a clear title match (similarity ≥ 60 and 10 points above the
   runner-up). On export, `key_value` shows the legal value plus every figure in force on
   `--as-of`.
6. **IDs**: `{JUR}-{CAT}-{NN}`, or `{JUR}-{CAT}-{P|F|H}{N}` for a pending bill, failed bill or
   held (internal) rule, e.g. `CA-RENT-01`, `CA-ALG-01`, `MA-ALG-P1` (the style of
   `dev/change_tests.json`). Deterministic across runs; snapshot ids in the older style
   (`ALGO`, `P01`) are upgraded when loaded (`upgrade_legacy_id`).
7. **Precedence**: a state rule whose interaction says it yields to stricter local law (e.g.
   Civ. Code § 1947.12 vs local rent control) or preempts it gets the local `team_rule_id`s in
   `overrides`, and each local rule gets the state id; the direction is written in `interaction`.

### Citation aliases (`data/citation_aliases.yaml`)

Each entry maps the names a jurisdiction's documents use for one law to a canonical,
law-level citation: `canonical`, `names` (exact names/abbreviations), `section_pattern` (regex
on section citations, e.g. `^S\.F\. Admin\. Code § 37\.` → `S.F. Admin. Code ch. 37`) and
`source` (the user decision or corpus document that justifies it). Entries are
jurisdiction-scoped ("Rent Ordinance" means different laws in SF and Berkeley). The
`formatting` list holds the generic style rewrites. Only add entries backed by the corpus or
an explicit decision.

## Conflicts (`conflicts.py`)

Flags both rules (`conflict_flag`, `conflict_note`) and writes `out/conflicts.json`:

| Type | When |
|---|---|
| `effective_date` | same jurisdiction, category and law; different documents; different effective dates for the same provision |
| `key_value` | same jurisdiction, category and law; different documents; same coverage; different figures |
| `preemption` | a state rule says it preempts/prohibits local rules → every local rule of that category in the state (held ones too) |
| `value_pending` | the text marks a date or figure as pending, not published or "to be determined" |

`preemption_no_local_rule` records (informational, nothing flagged) list state preemption
clauses with no local rule of that category in the corpus.

## Status (`status.py`)

| Stage | Status on `--as-of` |
|---|---|
| `bill_pending` | `pending` |
| `bill_failed` | `failed` |
| `enacted` / `administrative` / `unknown` | `pending` if enacted after as_of; `failed` if its sunset date ≤ as_of (exported with `conflict_note` "expired on <sunset_date>"); `not_yet_effective` if every effective date > as_of; else `in_force` |

**Calendar defaults** (`data/jurisdiction_defaults.yaml`): only California is configured. A
CA statute that is enacted, has a verified `enacted_date` and no effective date in its text
gets January 1 of the following year (Cal. Const. art. IV, § 8(c)), unless the text contains
urgency-statute language. The date is stored as derived with `rule_applied:
CA-const-art-IV-8c`. NJ and MA have no defaults by design.

Outputs: `out/extracted/<doc_id>.json` (per document, validated), `out/rules_internal.json`
(accepted + held, pre-normalization), `out/rejected.json`, `out/validation_report.json`
(per document and global counts), `out/rules_normalized.json` (every rule after
normalization, all dispositions), `out/conflicts.json`, `out/rules.json` (export),
`out/audit.jsonl` (append-only).

## Preguntas abiertas no resolubles con el corpus

Questions the participant guide raises whose answer depends on sources that are **not in
the supplied text** (manifest rows with `capture = link-only` or `check-terms`). The system
never fills them from outside knowledge; it records what the corpus supports and leaves the
gap visible.

| Question | What the corpus has | Missing source (no text) | How the system handles it |
|---|---|---|---|
| **Berkeley ch. 13.63 — two published effective dates** (March 1, 2026 per the ordinance; January 2026 per an Aug 2026 law-firm alert) | D001: Ordinance No. 7,992-N.S. amending ch. 13.63, recorded only as "passed to print" on November 18, 2025 (first reading). No effective date, no adoption/second-reading record. No other Berkeley document mentions 13.63. | D002 (Morgan Lewis alert, link-only) | The rule is extracted with stage `bill_pending` → status `pending`, no effective date. With one date-less source, no date conflict can be raised; `data/review_flags.yaml` sets `conflict_flag` on BRK-ALG-P1 with the §9 note. |
| **Los Angeles RSO new formula — two effective dates** (2026-02-02 per LAHD; 2026-01-24 per a landlord association) | D041 and D042 (LAHD) both state February 2, 2026. | The landlord-association statement is not in the corpus; D044 (AAGLA, link-only) is about deposit interest; LAMC text D038 is check-terms. | RSO rules carry the single verified date 2026-02-02; no conflict is flagged because only one source is readable. |
| **Hoboken and Jersey City algorithmic rent-setting ordinances** (T2 boundary, T3 preemption by the NJ FAIR Act) | D036 (Jersey City landlord/tenant page) has no algorithm content. | Hoboken code D032–D034 (ecode360, check-terms); Jersey City D035 (news) and D037 (Morgan Lewis), link-only; D060 (Day Pitney on the FAIR Act), link-only. | No local NJ `algorithmic_rent_setting` rule exists. The FAIR Act's "municipalities are prohibited from enacting ordinances…" clause is recorded in `out/conflicts.json` as `preemption_no_local_rule` (informational) instead of a conflict pair. Module B adds manifest-attested records HOB-ALG-A1 and JC-ALG-A1 (`out/rules_attested.json`, see "Responsible design"), flagged as possibly preempted by NJ-ALG-01. |
| **Massachusetts bills S.2983 and H.5222** (T4: who would be affected) | D045, D046, D047: bill status/history pages (titles, committee actions, dates). D011: H.3744 status page. | The bill texts themselves (no bill-text document in the manifest); D059 (WBUR on the struck ballot question), link-only. | Bills are recorded with stage `bill_pending` (status `pending`), `key_value` null and coverage "not described"; their scope can only be stated at jurisdiction level (MA statewide). H.3744 is `failed`. No MA or Boston/Cambridge rent cap exists (T5 empty), consistent with M.G.L. c. 40P. The struck ballot question itself (T5's MA-RENT-P1) is the manifest-attested MA-RENT-A1, status `failed`; it is not our MA-RENT-F1 (H.3744). |

## Module B adjustments to the rules

Applied by `normalize.py` on every run (no API calls), on top of the frozen a-0.4.0 extraction:

| Change | What | Rules affected |
|---|---|---|
| Id style | `ALGO` → `ALG`; `P01`/`F01`/`H01` → `P1`/`F1`/`H1` | every algorithmic, pending, failed and held id |
| Certificate of occupancy (step 4b) | `year_built_max` → `certificate_of_occupancy_on_or_before` when the coverage text, notes or quote mention a certificate of occupancy, or state the cutoff as a full date other than Dec 31 (a year cannot express it) | LA-JUST-03, LA-RENT-01..04: 1978 → 1978-10-01 ("first built on or before October 1, 1978"; guide §4.1 treats it as the certificate date) |
| Review flags (step 8, `data/review_flags.yaml`) | `conflict_flag` + note for open questions of guide §9 | BRK-ALG-P1 (Berkeley ch. 13.63 effective date) |

`data/test_rule_map.yaml` maps every rule id of `dev/change_tests.json` to ours; `smoke-check`
verifies each mapped id exists.

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
* They are written **only** to `out/rules_attested.json`, never to `rules.json` (they cannot
  meet the schema's quoted-span requirement), and Module B/C use them **only** for affected
  address sets and conflict flags — never to state a requirement, a figure or a date.

**Human review.** Every manual correction to the compiled coverage is an entry of
`data/human_review.yaml`, and nothing else in the code or data changes a rule by hand. Each entry
has an id (HR-NNN), the rule, the action (`set_scope`, `add_item`, or `merge_rule`, applied in
Module A's normalize step so the merged rule leaves `rules.json`), a `quoted_span`, the reason,
the reviewer (a role, not a name) and the date. Entries whose quoted span is not found verbatim
in the rule's text are refused (compiler) or not applied (normalize); applied ids are recorded
(`human_review_applied` in `data/compiled_exemptions.json`, `human review merges` in the normalize
report), and each corrected item carries a "human review HR-NNN" note. Current entries: HR-001
(MA-RENT-01 exemptions → other_law), HR-002 (CA-DEP-06 limited to ≤ 4 units), HR-003
(CA-JUST-01, an exemption extracted as a standalone rule, folded into CA-JUST-02), HR-004
(CA-JUST-03 demolition condition as unit_or_tenancy, stated in its explanation). When a rule
changes only by gaining items (e.g. a merge), the compiler reuses the reviewed answers for the
unchanged items and asks the model only about the new ones.
`tests/test_human_review.py` runs the hour-16 flow (extract-doc of a new ordinance → compile →
coverage) with an empty register to show a new document never needs an entry.

**Building facts are never guessed.** Owner type and owner occupancy are always unknown;
`year_built` stands in for the certificate-of-occupancy date only as a flagged approximation;
unit counts inferred from use codes are ranges, and every inference names its basis in
`data/use_code_map.yaml`.

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
  elderly, mixed_use, luxury), `owner_type` / `owner_occupied` (unknown).

**Jurisdictions** (`resolver/geocode.py`): one Census batch request (`Public_AR_Current` /
`Current_Current`; NJ rows sent without ZIP because the sample's NJ ZIPs are mostly mailing
ZIPs of other cities or states), then one `geographies/coordinates` lookup per matched point
for the incorporated place (the batch output has none), 4 at a time with retries. The stack
holds state, county (informational), city = incorporated place in rules.json format
("Jersey City city" → "Jersey City, NJ"), `match_quality` (exact / non_exact / no_match) and
`source` (census / dataset_fallback, certainty low). The geocoder's place wins over the
dataset city; every disagreement is listed in `discrepancies`.

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
transaction), `other_law` (depends on another law's coverage; deferred to precedence, B3),
`duplicate` (free text restating a structured exemption), or `review` (free-text coverage
conditions and exemptions that restate the rule's own scope — the small model read inclusive
examples and exemption qualifiers as restrictions, so these are shown for review, never
evaluated). Deterministic scope hints (`SCOPE_HINTS`) correct the model on recurring cases. The
raw answers are versioned in `data/compiled_exemptions.json`; reproducing reassembles them with
no API call (cost of a full compile ≈ $0.42).

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
affordability restriction, HUD subsidy (Section 8/202/811…), nonprofit cooperative, government or
university owner, institutional or care use, single-sex designation, condo / co-op / fee-simple
conversion — are marked `special_status` at compile time (regex `SPECIAL_STATUS` OR a one-call
LLM classification stored in `special_status_llm`). At evaluation their unknown status leaves
are presumed false unless a use flag in the data shows the status (Boston A/125 → section8,
A/118 → elderly, NJ "CO-OP" / "AFFORDABL"), and the result carries "presumed: no evidence of
<status> in assessor data". Generic owner type (natural person vs entity), owner occupancy,
cutoff-year and missing units / year built are never presumed. Manual corrections live only
in the human review register (see Responsible design → Human review).

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
only unknown, both are reported with "may yield to". Rules defined only as "for units covered by
<law>" (LA-RENT-05, LA-JUST-04/05) follow that law's coverage-defining rules. Preemption the
other way (FAIR Act vs Hoboken/Jersey City bans, NJ-RENT-03 vs JC-RENT-01) is never superseded:
both carry `conflict_flag` and a review note. `conflict_flag` means a legal conflict only (the
rule's own Module A flag, or a preemption conflict at the address); a combined confidence (rule ×
coverage × geocoding, fallback ×0.85) below 0.5 sets `needs_review` in `lookups_full.json`
instead. When a rule prevails over R it also prevails over the other in-force rules with R's
base citation and category (e.g. every Cal. Civ. Code § 1946.2 rule under SF's just cause).
Explanations are deterministic: requirement, why (facts used, governing rule, effective date,
"pending bill, not law", or the missing fact), presumptions/notes, then source, retrieval date,
as-of date and "Not legal advice." `lookups.json` holds only rules.json ids (validated);
manifest-attested rules appear only in `lookups_full.json`.

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

`--new-doc` runs extract-doc (Module A), compiles the new rules in memory (the versioned compile
snapshot is not written), and reports each new rule's affected addresses at the default query
date and the day after its effective date as entry `T6`. Rehearsal with
`tests/fixtures/fake_cambridge_ordinance.txt`: CAM-ALG-01 not_yet_effective on 2026-10-01, applies
from 2027-03-14 at 45 Cambridge addresses (the 5 with fewer than 6 units are not covered), none
elsewhere; ≈ 30 s (extract-doc ≈ 17 s, compile ≈ 11 s). To undo: delete
`corpus/new/<doc_id>.*`, then `python -m extractor.cli reproduce` and `python -m resolver.cli changes`.

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
  Spanish explanations use the validated Spanish summary as their first sentence and fixed
  templates for the rest.

### Deploy on Render

1. Push the repository to GitHub, then in Render: **New → Blueprint** and pick the repo
   (`render.yaml`). No `ANTHROPIC_API_KEY` is needed: the build runs
   `python -m extractor.cli reproduce` and `python -m resolver.cli changes` from the versioned
   snapshot, then starts `uvicorn api.main:app`.
2. Set `ALLOWED_ORIGINS` if the front end is served from a non-Lovable domain.
3. Free instances sleep: point the front end at `static/` (export it and host it with the
   front end, e.g. as public assets) when `/health` does not answer.

## Tests

```bash
python -m pytest -q        # offline; the API client is never built, no Census calls
```
