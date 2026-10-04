# Rental Housing Law Navigator — Method note

*7th Global AI Hackathon · Hack-Nation × RealPage · Challenge 02: Rental Housing Law Navigator · Not legal advice.*

**Problem.** Whether a rental rule applies to an apartment depends on layered state and city
law, coverage tests, exemptions, effective dates and the address's legal city, which is not
always its mailing city. We read a fixed corpus of real law (3 states, 10 cities, 6 categories)
and answer, for 500 sample addresses and any query date, which rules apply and why. Every
answer has a citation and a literal quote.

**Approach.** *Module A, extraction:* Claude Opus 5.5 reads each of the 54 documents with text
once and answers through a strict tool schema. It never writes status, ids or provenance. Code
then verifies every quote against the raw source (exact, normalized, fuzzy, at most one
retry), checks and types the dates, merges provisions of the same law, applies calendar
defaults (Cal. Const. art. IV § 8(c)), and computes status for any date from the legislative
stage. The result is 65 schema-valid rules. *Module B, lookup:* building facts (units as
intervals, year built, use flags, each with its basis) and the Census Geocoder give each
address its jurisdiction stack. Coverage and exemptions are compiled once into predicates
(code, plus Claude Haiku 4.5 for free text) and evaluated in three-valued Kleene logic, so a
missing fact yields *unknown*, not a guess. State rules that yield to local law become
superseded. Preemption conflicts are flagged, never resolved silently. *Module C, change
tracking:* the same as-of engine runs at two dates and diffs the results for the five supplied
cases. At hour 16, one command adds a new document as test T6.

**Data and models.** We used only the starter pack (87 corpus entries: 54 readable, 23
link-only, 9 check-terms, 1 failed capture; a public assessor sample with no owner names) and
the public Census Geocoder. Opus 5.5 extracts; Haiku 4.5 types ambiguous dates, compiles
coverage and writes the English and Spanish summaries. ElevenLabs reads the summaries in an AI
voice (82,935 characters). The official extraction cost $3.87 and is frozen in a snapshot from
which every output, the API and the tests reproduce offline without an API key. About $10 was
measured across all runs.

**Verification.** All 103 candidate quotes were verified in the raw text (86 exact,
16 normalized, 1 fuzzy); an unverifiable quote is never exported. 211 offline tests cover the
quote cascade, dates, coverage logic, every API route and the hour-16 flow. The scoring script
and answer key were not in our starter pack. Instead, a smoke check (pipeline invariants;
20 of 23 expected citations found, the other 3 link-only; behaviour on the change cases) and a
T1–T5 dashboard (14/14) run on every build. Results: T1 250 California addresses from
2026-01-01. T2 40 Hoboken, 50 Jersey City, 0 Newark. T3 140 New Jersey addresses, 90 flagged.
T4 110 pending in Massachusetts. T5 empty. The T6 rehearsal took 38.7 s with live extraction:
a rule effective 2027-03-13 at 45 Cambridge addresses, all checks green.

**Responsible AI.** Every answer shows its citation, source, retrieval date, quote and as-of
date, and says "Not legal advice". Enacted, not-yet-effective, pending and failed law are kept
apart. Missing facts give *unknown* and name the fact needed. Legal conflicts (845 results)
and low-confidence answers (743 below 0.5) are flagged for human review. Manual corrections
exist only as dated entries in a human-review register with a verbatim quote. An append-only
audit log records every run. Three laws without corpus text are attested records, used only
for address sets and conflict flags. The summary validator rejects figures that are not in the
rule and any hint of evasion. Nothing is scraped.

**Limitations.** The system is bound to the corpus, so link-only laws are absent. Berkeley
ch. 13.63 and San Diego's ordinance are pending as far as the corpus shows. The California
screening-fee cap has two figures ($30 CPI-adjusted vs $68.96) and is flagged. Year built
stands in for the certificate-of-occupancy date only as an interval. 212 addresses lack a year
built, 32 lack units, and owner facts are always unknown. Repeated LLM runs can classify
borderline provisions differently; the frozen snapshot fixes one reviewed run.

**Scalability.** A new jurisdiction needs its documents, one command per document, and its
addresses' facts and geocoding. The engine, the API and the interface do not change.
Local differences live in configuration (citation aliases, calendar defaults, use codes).
Extraction cost about $0.07 per document; a new document took 38.7 s end to end.
