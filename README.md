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
│   ├── validate.py            # quoted_span must occur in raw_text; JSON Schema check
│   ├── normalize.py           # citations, dedup, stable IDs, conflict flags
│   ├── status.py              # derive status from stage + dates for --as-of
│   ├── export.py              # RuleInternal -> RuleOut -> out/rules.json
│   ├── audit.py               # append-only out/audit.jsonl
│   └── models.py              # pydantic models (RuleInternal, RuleOut, ...)
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

The API key is read **only** from `ANTHROPIC_API_KEY`; it is never written to config
objects, cache entries, or the audit log.

---

## Commands

```bash
# Offline sanity checks — no API calls
python -m extractor.cli smoke-check

# Extract a single document and print its rules (debugging)
python -m extractor.cli extract-doc "participant-final-no-hour16 3/corpus/text/D022.txt"

# Extract all loadable documents (results cached in .cache/)
python -m extractor.cli extract-all

# Compute status for a query date and write schema-valid out/rules.json
python -m extractor.cli export --as-of 2026-10-01
```

---

## Pipeline

```
corpus.py    manifest + text/*.txt -> Document (header split; link-only/failed rows skipped)
clean.py     drop nav/boilerplate *whole lines only*; keep clean->raw offset map
extract.py   clean_text -> LLM (llm.py: structured output, retries, cache) -> RuleInternal[]
validate.py  quoted_span must occur in raw_text; JSON Schema check
normalize.py citations, dedup, stable IDs, conflict flags
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

`.cache/` is keyed by `sha256(document text)` + `PROMPT_VERSION` + model + effort.
Bump `PROMPT_VERSION` in `config.py` whenever the prompt changes — a bump invalidates
cached extractions.

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
