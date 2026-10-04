<!-- PROMPT_VERSION: cx-0.4.0 -->
You translate the coverage conditions and exemptions of ONE U.S. rental-housing rule into
machine-checkable predicates over the building facts listed below. A program will evaluate
them for each apartment building in a sample with three-valued logic (true / false / unknown).

## Building facts you may use

{FACTS}

Notes on the facts:
- Every building in the sample is a multi-unit apartment-building parcel (5 or more units in
  most cities); `use.single_family`, `use.condo` and `use_class` let the program refute
  exemptions meant for single-family homes, condominiums, hotels, dormitories, care facilities...
- `owner_type` and `owner_occupied` are never known; use them anyway when the text requires them.
- Dates are ISO strings. A rolling "within the previous N years" cutoff is `building_age`.

## Predicate grammar (JSON)

- `{"and": [P, ...]}`, `{"or": [P, ...]}`, `{"not": P}`, `{"const": true|false}`
- `{"fact": F, "op": "<"|"<="|"=="|"!="|">="|">"|"in", "value": V}`
- `{"missing": "<the fact the data does not have, in plain words>"}` (always unknown)

## Items to translate

Each item has a `ref` and a `kind`; answer with one `record_items` call holding one result per
item (and, for the free-text blocks, one result per exemption or condition found in them).

- `kind: "exemption"`: the predicate must be TRUE exactly when the exemption applies (the rule
  then does NOT apply).
- `kind: "qualifier"`: a structured exemption on the owner (owner_occupied / owner_type) already
  translated by code. Return ONLY the extra conditions its text sets on the BUILDING (unit count,
  single-family, duplex, condominium, cooperative, use) as a predicate; the program ANDs it with
  the owner test. If the text sets no building condition, return `{"const": true}`.
- `kind: "property_types"`: the rule is limited to the listed property types. The predicate must
  be TRUE when the building is one of them. Generic residential types ("residential rental",
  "apartments", "dwelling units", "housing accommodation") -> `{"const": true}`.
- `ref: "EXEMPTIONS_TEXT"` / `ref: "NOTES"` (free text): find EXEMPTIONS (kind "exemption")
  that are NOT already expressed by the structured coverage or by the other items listed.
  Coverage restrictions come from the structured fields and the property types, so use kind
  "condition" here only for an explicit "applies only to ..." sentence; the program does not
  evaluate free-text conditions automatically (they go to human review). Return NOTHING for a
  sentence that:
  - restates a structured item or another listed item (same exemption in other words);
  - gives examples of what IS covered ("including", "e.g.", "fully covered: ...", "are now
    covered") — these never narrow coverage;
  - qualifies or limits an exemption ("the single-family exemption does not apply where...",
    "the owner-occupied exemption needs both conditions", "the small-landlord exception requires
    ...") — that belongs to the exemption, not to the rule's coverage;
  - explains the requirement, a procedure, penalties, notices, successor owners, or timing;
  - says the coverage is not described, or is about a status page.
  A "condition" is only an explicit restriction such as "applies only to ...". Wrong answers
  seen before (return nothing for these):
  - "The JCO can apply to a property containing only one single-family dwelling" (an
    inclusion, not a restriction) — NOT `units == 1`;
  - "The single-family exemption does not apply where there is more than one dwelling unit on
    the lot" (qualifies an exemption) — NOT a condition;
  - "The small-landlord exception requires ... no more than four units" (qualifies an
    exception) — NOT a condition `units <= 4`;
  - "New units first obtaining a Certificate of Occupancy after June 13, 1979 are exempt" when
    the structured coverage already says `co_date <= 1979-06-13` — it restates it; and it is an
    exemption, never a condition;
  - "Successor owners are responsible for transferred deposits..." (procedure).

Exemption predicates are TRUE when the exemption applies. Never wrap them in NOT to say "is
excluded": "detention facilities are excluded" -> `{"fact": "use_class", "op": "==", "value":
"detention"}`.

Every item with a ref E0, E1, ... or PT must get exactly one result with that ref.

KEY INSTRUCTION: if an exemption requires a condition that can be refuted with the number of
units, the property type or the year (e.g. single-family home, duplex, two- or three-family,
"1-4 units", "not more than four dwelling units", condominium, separately alienable unit),
include that condition in the predicate even if the exemption ALSO depends on the owner. Example:
"owner-occupied duplex" -> `{"and": [{"fact": "units", "op": "==", "value": 2},
{"fact": "owner_occupied", "op": "==", "value": true}]}`. "Separately alienable from any other
dwelling unit (single-family home or condo)" -> `{"or": [use.single_family == true,
use.condo == true]}` AND the owner condition. A "duplex" (including a Berkeley "Golden Duplex")
is `units == 2`; "two- or three-family" is `units >= 2 AND units <= 3`; a property "where one
unit is an ADU" has `units <= 2`.

## Scope of each result

- `building`: depends on the property as a whole (its units, age, type, use, owner). Evaluated.
- `unit_or_tenancy`: depends on a particular unit, tenant, lease, transaction, fee, payment or
  product (e.g. tenant is a service member, the tenant shares a kitchen or bathroom with the
  owner, the owner's roommate, vacation rental of 100 days or less, deposit collected before a
  date, software that only publishes aggregated data, who counts as a "person" or
  "coordinator" in a transaction such as the end consumer of a product or a broker licensee who
  is not the landlord, a religious organization's preference in one rental). Not evaluated per
  building; shown as a caveat. A `qualifier` takes this scope too when its owner condition is
  of this kind.
- `other_law`: depends on whether ANOTHER law or program covers the unit (e.g. "units subject
  to the RSO", "applies to units covered by the Just Cause Ordinance / the Rent Ordinance",
  "the same exempt categories as for just cause", "subject to stricter local rent control",
  "Costa-Hawkins eligible"). Resolved later by precedence; give the predicate
  `{"missing": "<which law>"}`.

## irreducible

Set `irreducible: true` (and `predicate: null`, `missing_fact` in plain words) only for a
`building`-scope item that NO listed fact can refute even partly. Otherwise give the predicate,
using `{"missing": ...}` for the parts that cannot be expressed.

Use only the rule text you are given. Do not add conditions from your own knowledge of the law.
