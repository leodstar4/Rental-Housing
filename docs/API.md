# Rental Housing Law Navigator — API contract (v1.0.0)

Read-only JSON API over the Module A/B/C outputs. **No LLM call happens in any route**: rule
extraction, coverage compilation and plain-language summaries are precomputed and versioned.
Every response carries `disclaimer` ("Not legal advice …" / "No es asesoría legal …").

* Base URL (Render): `https://<service>.onrender.com` · local: `http://localhost:8000`
  (`uvicorn api.main:app --reload`). Interactive docs at `/docs` (OpenAPI at `/openapi.json`).
* Static backup (backend asleep): `static/` from `python -m api.export_static` — same JSON as
  the routes for `as_of=2026-10-01`: `static/lookup/<address_id>.<lang>.json`,
  `static/timeline/<address_id>.<lang>.json` (default `from`/`to`),
  `static/rules.<lang>.json`, `static/changes.json`, `static/changes/<test_id>.json`,
  `static/conflicts.json`, `static/audit.json`, and `static/index.json` (address list + file map).
* CORS: any `https://*.lovable.app`, `*.lovable.dev`, `*.lovableproject.com`, and localhost;
  more exact origins via the `ALLOWED_ORIGINS` env var. Methods: GET.
* Errors: `422` (bad `as_of` — must be `YYYY-MM-DD` between 2020-01-01 and 2030-12-31 — or bad
  `lang`), `404` (unknown address, rule or test). Body: `{"detail": "<message>"}`.

## Common parameters

| Param | Values | Default |
|---|---|---|
| `as_of` | `YYYY-MM-DD` (2020-01-01 … 2030-12-31) | `2026-10-01` |
| `lang` | `en` \| `es` | `en` |

## Routes

### `GET /health`
`{status, version, rules, attested_rules, addresses, default_as_of, disclaimer}`

### `GET /addresses?city=&q=&limit=50`
Search for autocomplete. `city` matches the legal city ("Hoboken" or "Hoboken, NJ"); `q`
matches address id, street, postal city or city (case-insensitive).

```json
{
  "disclaimer": "Not legal advice. This prototype summarizes public housing law for information only; check the cited source and consult a qualified professional before acting.",
  "count": 1,
  "addresses": [
    {
      "address_id": "A0019",
      "street": "3820 HAINES ST",
      "postal_city": "San Diego",
      "state": "CA",
      "city": "San Diego, CA",
      "dataset_city": "San Diego, CA"
    }
  ]
}
```

### `GET /lookup/{address_id}?as_of=&lang=`
The answer for one address. Top level:

| Field | Meaning |
|---|---|
| `address` | id, street, postal_city, state, legal `city`, `dataset_city` |
| `building_facts` | `units` (`range` [min, max], max null = open; `certainty` exact \| parsed \| range \| unknown; `source`), `year_built`, `co_year_approx` (year built as certificate-of-occupancy proxy), `use_flags` (only known values), `use_class`, `owner_type` / `owner_occupied` (always unknown) |
| `jurisdiction_stack` | `state`, `county` (informational), `city` (incorporated place), `place`, `match_quality` (exact \| non_exact \| no_match), `source` (census \| dataset_fallback), `certainty`, `matched_address`, `coordinates`, `levels` |
| `as_of`, `lang`, `disclaimer` | |
| `category_order` | display order of the groups (labels in the requested language) |
| `results` | `{<category label>: [result, …]}` |
| `counts` | results per value of `result` |

Each **result**:

| Field | Meaning |
|---|---|
| `team_rule_id`, `title`, `category`, `level` | rule identity (`level`: state \| city) |
| `result` | `applies` · `unknown` (depends on a fact not in the data, see `missing_facts`) · `superseded` (covered, but `superseded_by` governs) · `not_yet_effective` (see `effective_date`) · `pending` (bill, not law) |
| `explanation` | deterministic text in the requested language: what the rule requires, why this result, notes, source, as-of date, "Not legal advice" |
| `plain_language` | `{what_it_means, who_it_covers, what_you_can_do}` for tenants (validated: no figures beyond the rule's own fields; never how to avoid a rule) |
| `citation`, `source_url`, `retrieved_at`, `quoted_span` | provenance; `quoted_span` is the literal text of the source (null for attested rules) |
| `effective_date`, `status` | status of the rule at `as_of` |
| `confidence` | rule confidence × coverage confidence × geocoding certainty |
| `conflict_flag`, `conflict_note` | a **legal** conflict for human review (Module A flag or a preemption conflict at this address) |
| `needs_review` | combined confidence < 0.5 (show a "needs review" badge; not a conflict) |
| `missing_facts`, `presumptions` | why `unknown` (internal names); special-status presumptions applied ("presumed: no evidence of … in assessor data") |
| `missing_facts_label` | the same missing facts as readable names in the requested language ("year built" / "año de construcción", "number of units" / "número de unidades", "type of owner" / "tipo de propietario", "certificate of occupancy date" / "fecha del certificado de ocupación") |
| `superseded_by` | rule that governs instead (when `result` = superseded) |
| `attested` | true for laws named by the organizers but without text in the corpus (Hoboken / Jersey City algorithmic bans): show them with a "text not in corpus" badge |
| `audio_url` | spoken plain-language summary in the requested language, a path on this API (`/audio/<lang>/<team_rule_id>.mp3?v=<text hash>`; prefix the API base URL), or null if there is no audio file (e.g. a rule added at hour 16 without an ElevenLabs key) |

Rules omitted from `results`: failed rules, and rules that do not cover the building
(`not_covered` / `exempt`).

**Example — `GET /lookup/A0016?as_of=2026-10-01&lang=en` (real response):**

```json
{
  "address": {
    "address_id": "A0016",
    "street": "3515 FILLMORE ST",
    "postal_city": "San Francisco",
    "state": "CA",
    "city": "San Francisco, CA",
    "dataset_city": "San Francisco, CA"
  },
  "building_facts": {
    "units": {
      "range": [
        21,
        21
      ],
      "certainty": "exact",
      "source": "units column"
    },
    "year_built": {
      "value": 1926,
      "certainty": "exact",
      "source": "year_built column"
    },
    "co_year_approx": {
      "value": 1926,
      "certainty": "approximate",
      "basis": "year_built as a proxy; the certificate-of-occupancy date is not in the data (guide §4.1): a cutoff falling inside this year is unknown"
    },
    "use_flags": {
      "tic": {
        "value": false,
        "source": "use_code",
        "basis": "SF codes separate TIC buildings (TIC) and flat-and-store buildings (FS5)"
      },
      "mixed_use": {
        "value": false,
        "source": "use_code",
        "basis": "SF codes separate TIC buildings (TIC) and flat-and-store buildings (FS5)"
      },
      "single_family": {
        "value": false,
        "source": "use_code",
        "basis": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "condo": {
        "value": false,
        "source": "use_code",
        "basis": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      }
    },
    "use_class": {
      "value": "apartment_building",
      "certainty": "inferred",
      "basis": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
    },
    "owner_type": {
      "value": null,
      "certainty": "unknown",
      "basis": "the sample has no owner data (owner names deliberately excluded, guide §4.1)"
    },
    "owner_occupied": {
      "value": null,
      "certainty": "unknown",
      "basis": "the sample has no owner data (owner names deliberately excluded, guide §4.1)"
    }
  },
  "jurisdiction_stack": {
    "state": "CA",
    "county": {
      "name": "San Francisco County",
      "fips": "06075",
      "informational": true
    },
    "city": "San Francisco, CA",
    "place": {
      "name": "San Francisco city",
      "geoid": "0667000"
    },
    "county_subdivision": {
      "name": "Richmond-Presidio-Marina CCD",
      "geoid": "0607592605"
    },
    "match_quality": "exact",
    "source": "census",
    "certainty": "high",
    "matched_address": "3515 FILLMORE ST, SAN FRANCISCO, CA, 94123",
    "coordinates": {
      "lon": -122.436684852142,
      "lat": 37.801874337429
    },
    "levels": [
      {
        "level": "state",
        "jurisdiction": "CA"
      },
      {
        "level": "city",
        "jurisdiction": "San Francisco, CA"
      }
    ]
  },
  "as_of": "2026-10-01",
  "lang": "en",
  "disclaimer": "Not legal advice. This prototype summarizes public housing law for information only; check the cited source and consult a qualified professional before acting.",
  "category_order": [
    "RENT",
    "JUST CAUSE",
    "DEPOSIT",
    "SCREENING FEE",
    "SCREENING",
    "ALGORITHMIC"
  ],
  "results": {
    "RENT": [
      {
        "team_rule_id": "SF-RENT-01",
        "title": "Rent Ordinance rent increase limitations – exempt tenancies",
        "category": "rent_increase_limits",
        "level": "city",
        "result": "applies",
        "explanation": "The Rent Ordinance imposes rent increase limitations, but certain tenancies are exempt from them, including newly constructed units that first obtained a Certificate of Occupancy after June 13, 1979,… Applies here (built 1926). Source: S.F. Admin. Code ch. 37 (https://sf.gov/information/overview-just-cause-evictions, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "San Francisco's Rent Ordinance limits how much landlords can raise rent on covered units. Some units are exempt from this rule, including new buildings, certain tenancies under Costa-Hawkins, and units regulated by other government agencies.",
          "who_it_covers": "Rental units in San Francisco that are covered by the Rent Ordinance, except for exempt units like those first obtaining a Certificate of Occupancy after June 13, 1979.",
          "what_you_can_do": "Ask your landlord in writing what rent increase, if any, applies to your unit, and whether your unit is exempt from the Rent Ordinance."
        },
        "citation": "S.F. Admin. Code ch. 37",
        "source_url": "https://sf.gov/information/overview-just-cause-evictions",
        "retrieved_at": "2026-10-01",
        "quoted_span": "Some tenancies that are exempt from the rent increase limitations of the Ordinance are still subject to the eviction provisions of the Ordinance, and tenants in these categories can only be evicted for one of the “just cause” reasons listed in the Ordinance.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.421,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": true,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/SF-RENT-01.mp3?v=7fafa433"
      },
      {
        "team_rule_id": "CA-RENT-01",
        "title": "Statewide rent cap (Tenant Protection Act rent increase limits)",
        "category": "rent_increase_limits",
        "level": "state",
        "result": "superseded",
        "explanation": "Owners of covered residential property may not raise rent over any 12-month period by more than 5% plus the percentage change in cost of living, or 10%, whichever is lower, measured from the lowest rent charged in the… Covered here (built 1926; 21 units), but SF-RENT-01 (Rent Ordinance rent increase limitations – exempt tenancies) governs instead. Notes: Presumed no evidence of an affordability restriction in assessor data. Source: Cal. Civ. Code § 1947.12 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1947.12, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "Covered, but SF-RENT-01 governs instead",
          "what_it_means": "Your landlord cannot raise your rent more than 5% plus the cost of living increase, or 10%, whichever is lower, in any 12-month period. When you first move in, your landlord can set any starting rent. Rent can only go up in up to two steps in a 12-month period if you stay.",
          "who_it_covers": "Tenants in residential units (apartments, houses, mobilehomes) in California, except for certain new buildings, subsidized housing, school dorms, and some single-family homes.",
          "what_you_can_do": "Keep track of what rent you paid in the prior 12 months and ask your landlord in writing to show how they calculated any rent increase to make sure it follows the 5% plus cost of living limit."
        },
        "citation": "Cal. Civ. Code § 1947.12",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1947.12",
        "retrieved_at": "2026-10-01",
        "quoted_span": "Subject to subdivision (b), an owner of residential real property shall not, over the course of any 12-month period, increase the gross rental rate for a dwelling or a unit more than 5 percent plus the percentage change in the cost of living, or 10 percent, whichever is lower, of the lowest gross rental rate charged for that dwelling or unit at any time during the 12 months prior to the effective date of the increase.",
        "effective_date": "2024-04-01",
        "status": "in_force",
        "confidence": 0.648,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [
          "presumed: no evidence of an affordability restriction in assessor data"
        ],
        "superseded_by": "SF-RENT-01",
        "attested": false,
        "audio_url": "/audio/en/CA-RENT-01.mp3?v=2e8a5449"
      }
    ],
    "JUST CAUSE": [
      {
        "team_rule_id": "SF-JUST-01",
        "title": "Rent Ordinance just cause eviction requirement (17 just causes)",
        "category": "just_cause_eviction",
        "level": "city",
        "result": "applies",
        "explanation": "A landlord may evict a tenant from a unit covered by the Rent Ordinance only for one of 17 listed just cause reasons, and that reason must be the dominant motive; mere lease expiration or change in ownership is not… Applies here (all covered rentals in San Francisco, CA). Source: S.F. Admin. Code § 37.9 (https://sf.gov/information/overview-just-cause-evictions, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "A landlord can only evict a tenant from a rental unit covered by the San Francisco Rent Ordinance if they have one of 17 specific just cause reasons. The landlord must prove this reason is the main reason for eviction. Simply ending a lease or selling the building is not enough reason to evict. Landlords also need just cause to remove housing services like parking, storage, or laundry.",
          "who_it_covers": "Rental units covered by the San Francisco Rent Ordinance, including some units exempt from rent increase limits.",
          "what_you_can_do": "Ask your landlord in writing to explain the just cause reason for any eviction or removal of housing services. Keep copies of all notices and documents from your landlord."
        },
        "citation": "S.F. Admin. Code § 37.9",
        "source_url": "https://sf.gov/information/overview-just-cause-evictions",
        "retrieved_at": "2026-10-01",
        "quoted_span": "In order to evict a tenant from a rental unit covered by the Rent Ordinance, a landlord must have a \"just cause\" reason that is the dominant motive for pursuing the eviction.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.765,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/SF-JUST-01.mp3?v=77d8cb84"
      },
      {
        "team_rule_id": "CA-JUST-02",
        "title": "Tenant Protection Act just cause requirement for terminating tenancies",
        "category": "just_cause_eviction",
        "level": "state",
        "result": "superseded",
        "explanation": "Once a tenant has lawfully lived in a residential unit for 12 months (or 24 months for at least one tenant if adult tenants were added), the owner may end the tenancy only for an at-fault or no-fault just cause listed… Covered here (built 1926; 21 units), but SF-JUST-01 (Rent Ordinance just cause eviction requirement (17 just causes)) governs instead. Notes: Presumed no evidence of an affordability restriction in assessor data. Source: Cal. Civ. Code § 1946.2 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946.2, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "Covered, but SF-JUST-01 governs instead",
          "what_it_means": "After you have lived in your rental home for 12 months, your landlord can only end your tenancy for a valid reason. The landlord must tell you the reason in writing. If the reason is not your fault, the landlord must pay you one month's rent or let you skip your final month's rent.",
          "who_it_covers": "Tenants who have lived continuously and lawfully in residential units (including mobilehomes) for 12 months or longer.",
          "what_you_can_do": "Keep records of when you moved in and ask your landlord for the reason in writing if they try to end your tenancy."
        },
        "citation": "Cal. Civ. Code § 1946.2",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946.2",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(a) Notwithstanding any other law, after a tenant has continuously and lawfully occupied a residential real property for 12 months, the owner of the residential real property shall not terminate a tenancy without just cause, which shall be stated in the written notice to terminate tenancy.",
        "effective_date": "2024-04-01",
        "status": "in_force",
        "confidence": 0.629,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [
          "presumed: no evidence of an affordability restriction in assessor data"
        ],
        "superseded_by": "SF-JUST-01",
        "attested": false,
        "audio_url": "/audio/en/CA-JUST-02.mp3?v=da31426d"
      },
      {
        "team_rule_id": "CA-JUST-03",
        "title": "Housing Crisis Act relocation for lower-income households displaced by demolition",
        "category": "just_cause_eviction",
        "level": "state",
        "result": "applies",
        "explanation": "Under the state Housing Crisis Act, lower-income households (80% AMI or below) displaced by demolition for new construction must receive relocation benefits matching what public entities must pay under Gov. Code § 7260… Applies here (all covered rentals in CA). Applies only if the unit is demolished for new housing development. Source: Cal. Gov. Code § 66300.6 (https://housing.lacity.gov/wp-content/uploads/2026/08/Relocation-Assistance-Bulletins-A-and-B-Combined.pdf, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "If your home is demolished so a new building can be built, your landlord must pay relocation benefits. These benefits must match what the state requires for public agencies to pay.",
          "who_it_covers": "Lower-income households (80% AMI or below) whose rental units are demolished for new construction.",
          "what_you_can_do": "Ask your landlord in writing what relocation benefits they will provide if your unit is demolished."
        },
        "citation": "Cal. Gov. Code § 66300.6",
        "source_url": "https://housing.lacity.gov/wp-content/uploads/2026/08/Relocation-Assistance-Bulletins-A-and-B-Combined.pdf",
        "retrieved_at": "2026-10-01",
        "quoted_span": "3. Pay relocation assistance to tenants in compliance with the State law’s Housing Crisis Act",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.36,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": true,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-JUST-03.mp3?v=7b137446"
      }
    ],
    "DEPOSIT": [
      {
        "team_rule_id": "CA-DEP-01",
        "title": "AB 12 security deposit cap of one month's rent",
        "category": "security_deposits",
        "level": "state",
        "result": "applies",
        "explanation": "Starting July 1, 2024, most landlords may charge a security deposit of no more than one month's rent for both furnished and unfurnished units. Applies here (21 units). Source: CA AB 12 (https://rentboard.berkeleyca.gov/rights-responsibilities/security-deposits, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force since 2024-07-01",
          "what_it_means": "Starting July 1, 2024, most landlords can charge a security deposit of no more than one month's rent. Your last month's rent counts toward the deposit, but your first month's rent does not.",
          "who_it_covers": "Furnished and unfurnished rental units in California. Small landlords with only two rental properties and no more than four units total may charge up to two months' rent instead.",
          "what_you_can_do": "Ask your landlord in writing how much the security deposit is and get a clear explanation of what it covers."
        },
        "citation": "CA AB 12",
        "source_url": "https://rentboard.berkeleyca.gov/rights-responsibilities/security-deposits",
        "retrieved_at": "2026-10-01",
        "quoted_span": "Starting July 1, 2024, many landlords may only charge one month's rent for unfurnished and furnished units",
        "effective_date": "2024-07-01",
        "status": "in_force",
        "confidence": 0.66,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-DEP-01.mp3?v=8047814b"
      },
      {
        "team_rule_id": "CA-DEP-03",
        "title": "General security deposit cap of one month's rent",
        "category": "security_deposits",
        "level": "state",
        "result": "applies",
        "explanation": "A landlord may not demand or receive security, however labeled, greater than one month's rent, in addition to first month's rent. Applies here (all covered rentals in CA). Source: Cal. Civ. Code § 1950.5 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.5, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force since 2024-07-01",
          "what_it_means": "Your landlord can only keep one month's rent as a security deposit. Your landlord must photograph your rental unit right when you move in, starting July 1, 2025.",
          "who_it_covers": "Tenants in residential rental homes and apartments in California.",
          "what_you_can_do": "Ask your landlord in writing how much security deposit they are charging and get a receipt for what you pay."
        },
        "citation": "Cal. Civ. Code § 1950.5",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.5",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(c) (1) Except as provided in paragraph (2), (3), or (5), a landlord shall not demand or receive security, however denominated, in an amount or value in excess of an amount equal to one month’s rent, in addition to any rent for the first month paid on or before initial occupancy.",
        "effective_date": "2024-07-01",
        "status": "in_force",
        "confidence": 0.873,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-DEP-03.mp3?v=68adf0c2"
      },
      {
        "team_rule_id": "CA-DEP-04",
        "title": "Higher security charged to service members: disclosure and return",
        "category": "security_deposits",
        "level": "state",
        "result": "applies",
        "explanation": "If a landlord charges a service member a higher-than-standard security because of credit or housing history, the landlord must give a written statement of the amount and the reason. Applies here (all covered rentals in CA). Source: Cal. Civ. Code § 1950.5 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.5, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force since 2025-04-01",
          "what_it_means": "If a landlord charges a service member extra money for a security deposit because of credit or housing history, the landlord must give a written statement explaining the amount and reason. The extra amount must be returned after no more than six months if the tenant is not behind on rent. The landlord must photograph the unit before and after any repairs or cleanings that will be deducted from the deposit.",
          "who_it_covers": "Service members who rent residential property they will live in.",
          "what_you_can_do": "Ask your landlord for a written statement if they charge an extra security deposit, and keep a record of when the extra amount should be returned."
        },
        "citation": "Cal. Civ. Code § 1950.5",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.5",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(4) On or after April 1, 2025, if a landlord or its agent charges a service member who rents residential property in which the service member will reside a higher than standard or advertised security pursuant to paragraph (1) due to the credit history, credit score, housing history, or other factor related to the tenant, the landlord shall provide the tenant with a written statement, on or before the date the lease is signed, of the amount of the higher security and an explanation why the higher security amount is being charged.",
        "effective_date": "2025-04-01",
        "status": "in_force",
        "confidence": 0.825,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-DEP-04.mp3?v=2a169a41"
      },
      {
        "team_rule_id": "CA-DEP-05",
        "title": "Return of security deposit, itemized statement and permitted deductions",
        "category": "security_deposits",
        "level": "state",
        "result": "applies",
        "explanation": "Within 21 calendar days after the tenant moves out, the landlord must return the remaining security with an itemized statement. Applies here (all covered rentals in CA). Source: Cal. Civ. Code § 1950.5 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.5, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "Your landlord must return your security deposit within 21 calendar days after you move out. The landlord must send you an itemized statement showing what money was kept and why. If you paid the deposit electronically, the return must also be electronic. If deductions are more than $125, the landlord must include supporting documents and photos.",
          "who_it_covers": "Tenants who paid a security deposit for a residential rental property where they live.",
          "what_you_can_do": "Keep records of your move-out date and the condition of your rental. If you do not receive your deposit within 21 days with an itemized statement, contact your local housing authority or tenant rights organization."
        },
        "citation": "Cal. Civ. Code § 1950.5",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.5",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(h) (1) No later than 21 calendar days after the tenant has vacated the premises, but not earlier than the time that either the landlord or the tenant provides a notice to terminate the tenancy under Section 1946 or 1946.1, Section 1161 of the Code of Civil Procedure, or not earlier than 60 calendar days prior to\nthe expiration of a fixed-term lease, the landlord shall furnish the tenant, a copy of an itemized statement indicating the basis for, and the amount of, any security received and the disposition of the security, and shall return any remaining portion of the security to the tenant as follows:",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.698,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-DEP-05.mp3?v=ddd31165"
      }
    ],
    "SCREENING FEE": [
      {
        "team_rule_id": "CA-FEE-01",
        "title": "Application screening fee cap and conditions",
        "category": "application_screening_fees",
        "level": "state",
        "result": "applies",
        "explanation": "Landlords may charge an application screening fee of no more than their actual out-of-pocket costs, capped at $30 per applicant (adjustable annually by CPI since January 1, 1998). Applies here (all covered rentals in CA). Source: Cal. Civ. Code § 1950.6 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.6, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "Landlords can charge you a fee to screen your rental application, but only up to $30 per person (this amount changes each year). They must give you an itemized receipt, refund any money they don't use, and show you a copy of your credit report within seven days.",
          "who_it_covers": "Renters, guarantors, and cosigners who apply to rent residential property in California.",
          "what_you_can_do": "Ask your landlord for an itemized receipt of any application fee and request a copy of your credit report within seven days of applying."
        },
        "citation": "Cal. Civ. Code § 1950.6",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1950.6",
        "retrieved_at": "2026-10-01",
        "quoted_span": "In no case shall the amount of the application screening fee charged by the landlord or their agent be greater than thirty dollars ($30) per applicant.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.837,
        "conflict_flag": true,
        "conflict_note": "key_value conflict with CA-FEE-02: D026: '$30 per applicant, CPI-adjusted annually' vs D005: '$68.96 (2026 maximum)'",
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-FEE-01.mp3?v=a19de4f5"
      },
      {
        "team_rule_id": "CA-FEE-02",
        "title": "State limits on tenant screening fees (Civil Code 1950.6)",
        "category": "application_screening_fees",
        "level": "state",
        "result": "applies",
        "explanation": "Landlords may charge a capped screening fee only to get information such as a credit report. Applies here (all covered rentals in CA). Source: Cal. Civ. Code § 1950.6 (https://rentboard.berkeleyca.gov/laws-regulations/city-berkeley-ordinances-affecting-rental-properties/tenant-screening-and, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "Landlords can charge a screening fee up to $68.96 (2026 maximum) to get information like a credit report. They must give you a copy of the report, a receipt showing what they charged for, and refund any money they did not use. Landlords must accept a reusable screening report if you provide one.",
          "who_it_covers": "People who apply to rent a home and are charged a screening fee by a landlord.",
          "what_you_can_do": "Ask your landlord in writing for a copy of your credit report, an itemized receipt, and a refund of any unused fee money. If you have a screening report from another application, offer it to the landlord."
        },
        "citation": "Cal. Civ. Code § 1950.6",
        "source_url": "https://rentboard.berkeleyca.gov/laws-regulations/city-berkeley-ordinances-affecting-rental-properties/tenant-screening-and",
        "retrieved_at": "2026-10-01",
        "quoted_span": "The landlord cannot charge a prospective tenant a screening fee if no rental unit is actually available. The landlord must also return a screening fee to any applicant not selected, or have a policy under which they: (1) review applications in the order received and the first qualified applicant gets the unit, and (2) do not charge a screening fee to any applicant not considered.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.524,
        "conflict_flag": true,
        "conflict_note": "key_value conflict with CA-FEE-01: D026: '$30 per applicant, CPI-adjusted annually' vs D005: '$68.96 (2026 maximum)'",
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-FEE-02.mp3?v=f158b939"
      }
    ],
    "SCREENING": [
      {
        "team_rule_id": "CA-SCRN-01",
        "title": "Source of income discrimination and credit history alternatives for subsidized applicants",
        "category": "screening_restrictions",
        "level": "state",
        "result": "applies",
        "explanation": "Housing owners may not discriminate against applicants or tenants because of source of income, including housing vouchers such as Section 8 and VASH. Applies here (all covered rentals in CA). Source: Cal. Gov. Code § 12955 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=GOV&sectionNum=12955, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "Landlords cannot refuse to rent to you because you use a housing voucher like Section 8 or VASH. If you get government help to pay rent, landlords cannot require an income level that ignores what you pay yourself, and they must consider other proof of ability to pay, not just credit history.",
          "who_it_covers": "All housing owners in California.",
          "what_you_can_do": "If a landlord refuses to rent to you because of your income source or voucher, or treats you unfairly about credit history when you have government rent help, contact your local housing department or fair housing agency."
        },
        "citation": "Cal. Gov. Code § 12955",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=GOV&sectionNum=12955",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(a) For the owner of any housing accommodation to discriminate against or harass any person because of the race, color, religion, sex, gender, gender identity, gender expression, sexual orientation, marital status, national origin, ancestry, familial status, source of income, disability, veteran or military status, or genetic information of that person.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.698,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-SCRN-01.mp3?v=c960874b"
      },
      {
        "team_rule_id": "CA-SCRN-02",
        "title": "FEHA source-of-income protections in tenant selection",
        "category": "screening_restrictions",
        "level": "state",
        "result": "applies",
        "explanation": "Housing providers may not refuse to rent, or apply different terms, based on how a tenant will pay rent (source of income). Applies here (21 units). Source: California Fair Employment and Housing Act (https://calcivilrights.ca.gov/housing/, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force",
          "what_it_means": "Landlords cannot say no to tenants or charge different prices based on how they pay rent, including Section 8 vouchers. Landlords cannot refuse to rent to people just because they were arrested, have sealed records, or have a criminal history. If a landlord denies someone because of a conviction, the offense must be directly related to being a safe tenant.",
          "who_it_covers": "Landlords, property managers, and screening companies in California that handle most rental housing.",
          "what_you_can_do": "If a landlord rejects you because of your income source, past arrests, sealed records, or conviction, contact your local housing department or civil rights agency to file a complaint."
        },
        "citation": "California Fair Employment and Housing Act",
        "source_url": "https://calcivilrights.ca.gov/housing/",
        "retrieved_at": "2026-10-01",
        "quoted_span": "California law protects tenants from discrimination based on how a tenant will be paying rent (“source of income”).",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.54,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-SCRN-02.mp3?v=1dbaa2c0"
      }
    ],
    "ALGORITHMIC": [
      {
        "team_rule_id": "SF-ALG-01",
        "title": "Prohibition on algorithmic devices to set rents or manage occupancy",
        "category": "algorithmic_rent_setting",
        "level": "city",
        "result": "applies",
        "explanation": "Selling or using algorithmic devices (such as software that analyzes nonpublic competitor rental data to recommend rents for vacant units) to set rents or manage occupancy levels for residential units in San Francisco… Applies here (all covered rentals in San Francisco, CA). Source: S.F. Admin. Code § 37.10C (https://www.sf.gov/news/new-law-prohibits-algorithmic-devices-used-set-rents-san-francisco, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force since 2024-10-14",
          "what_it_means": "San Francisco forbids landlords and property managers from using algorithmic software or devices to set rents or control how many tenants live in residential units. This ban applies to tools that analyze competitor rental data to recommend prices.",
          "who_it_covers": "Residential rental units in San Francisco.",
          "what_you_can_do": "If you believe your landlord is using algorithmic pricing to set your rent, you can contact the San Francisco City Attorney's office or consult a local housing advocate for guidance."
        },
        "citation": "S.F. Admin. Code § 37.10C",
        "source_url": "https://www.sf.gov/news/new-law-prohibits-algorithmic-devices-used-set-rents-san-francisco",
        "retrieved_at": "2026-10-01",
        "quoted_span": "The law prohibits the sale or use of algorithmic devices to set rents or manage occupancy levels for residential units in San Francisco.",
        "effective_date": "2024-10-14",
        "status": "in_force",
        "confidence": 0.85,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/SF-ALG-01.mp3?v=50b0cce1"
      },
      {
        "team_rule_id": "CA-ALG-01",
        "title": "Cartwright Act: prohibition on use or distribution of common pricing algorithms (AB 325)",
        "category": "algorithmic_rent_setting",
        "level": "state",
        "result": "applies",
        "explanation": "It is unlawful to use or distribute a common pricing algorithm as part of a contract, trust combination, or conspiracy to restrain trade. Applies here (all covered rentals in CA). Source: Cal. Bus. & Prof. Code § 16729 (https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260AB325, retrieved 2026-10-01). As of 2026-10-01. Not legal advice.",
        "plain_language": {
          "status_line": "In force since 2026-01-01",
          "what_it_means": "Starting January 1, 2026, it will be illegal to use or share a pricing algorithm to fix prices or force others to use recommended prices in California. This applies to businesses and organizations, not individual consumers.",
          "who_it_covers": "The rule does not specifically cover rental housing. It applies to any business or organization in California that uses pricing algorithms for products or services.",
          "what_you_can_do": "If you think a landlord is using an illegal pricing algorithm to set your rent unfairly, contact your local housing authority or rent board for guidance."
        },
        "citation": "Cal. Bus. & Prof. Code § 16729",
        "source_url": "https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260AB325",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(a) It shall be unlawful for a person to use or distribute a common pricing algorithm as part of a contract, combination in the form of a trust, or conspiracy to restrain trade or commerce in violation of this chapter.",
        "effective_date": "2026-01-01",
        "status": "in_force",
        "confidence": 0.655,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/en/CA-ALG-01.mp3?v=543afc42"
      }
    ]
  },
  "counts": {
    "applies": 13,
    "superseded": 2
  }
}
```

**Example — `GET /lookup/A0016?as_of=2026-10-01&lang=es` (real response, excerpt):**

```json
{
  "address": {
    "address_id": "A0016",
    "street": "3515 FILLMORE ST",
    "postal_city": "San Francisco",
    "state": "CA",
    "city": "San Francisco, CA",
    "dataset_city": "San Francisco, CA"
  },
  "building_facts": {
    "units": {
      "range": [
        21,
        21
      ],
      "certainty": "exact",
      "source": "units column"
    },
    "year_built": {
      "value": 1926,
      "certainty": "exact",
      "source": "year_built column"
    },
    "co_year_approx": {
      "value": 1926,
      "certainty": "approximate",
      "basis": "year_built as a proxy; the certificate-of-occupancy date is not in the data (guide §4.1): a cutoff falling inside this year is unknown"
    },
    "use_flags": {
      "tic": {
        "value": false,
        "source": "use_code",
        "basis": "SF codes separate TIC buildings (TIC) and flat-and-store buildings (FS5)"
      },
      "mixed_use": {
        "value": false,
        "source": "use_code",
        "basis": "SF codes separate TIC buildings (TIC) and flat-and-store buildings (FS5)"
      },
      "single_family": {
        "value": false,
        "source": "use_code",
        "basis": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "condo": {
        "value": false,
        "source": "use_code",
        "basis": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      }
    },
    "use_class": {
      "value": "apartment_building",
      "certainty": "inferred",
      "basis": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
    },
    "owner_type": {
      "value": null,
      "certainty": "unknown",
      "basis": "the sample has no owner data (owner names deliberately excluded, guide §4.1)"
    },
    "owner_occupied": {
      "value": null,
      "certainty": "unknown",
      "basis": "the sample has no owner data (owner names deliberately excluded, guide §4.1)"
    }
  },
  "jurisdiction_stack": {
    "state": "CA",
    "county": {
      "name": "San Francisco County",
      "fips": "06075",
      "informational": true
    },
    "city": "San Francisco, CA",
    "place": {
      "name": "San Francisco city",
      "geoid": "0667000"
    },
    "county_subdivision": {
      "name": "Richmond-Presidio-Marina CCD",
      "geoid": "0607592605"
    },
    "match_quality": "exact",
    "source": "census",
    "certainty": "high",
    "matched_address": "3515 FILLMORE ST, SAN FRANCISCO, CA, 94123",
    "coordinates": {
      "lon": -122.436684852142,
      "lat": 37.801874337429
    },
    "levels": [
      {
        "level": "state",
        "jurisdiction": "CA"
      },
      {
        "level": "city",
        "jurisdiction": "San Francisco, CA"
      }
    ]
  },
  "as_of": "2026-10-01",
  "lang": "es",
  "disclaimer": "No es asesoría legal. Este prototipo resume leyes públicas de vivienda solo con fines informativos; revise la fuente citada y consulte a un profesional calificado antes de actuar.",
  "category_order": [
    "RENTA",
    "CAUSA JUSTA",
    "DEPÓSITO",
    "CUOTA DE EVALUACIÓN",
    "EVALUACIÓN",
    "ALGORITMOS"
  ],
  "results": {
    "RENTA": [
      {
        "team_rule_id": "SF-RENT-01",
        "title": "Rent Ordinance rent increase limitations – exempt tenancies",
        "category": "rent_increase_limits",
        "level": "city",
        "result": "applies",
        "explanation": "La Ordenanza de Arrendamiento de San Francisco limita cuánto pueden aumentar el alquiler los propietarios en unidades cubiertas. Algunas unidades están exentas de esta regla, incluyendo edificios nuevos, ciertos arrendamientos bajo Costa-Hawkins, y unidades reguladas por otras agencias del gobierno. Aplica aquí (construido en 1926). Fuente: S.F. Admin. Code ch. 37 (https://sf.gov/information/overview-just-cause-evictions, consultado el 2026-10-01). Vigente al 2026-10-01. No es asesoría legal.",
        "plain_language": {
          "status_line": "Vigente",
          "what_it_means": "La Ordenanza de Arrendamiento de San Francisco limita cuánto pueden aumentar el alquiler los propietarios en unidades cubiertas. Algunas unidades están exentas de esta regla, incluyendo edificios nuevos, ciertos arrendamientos bajo Costa-Hawkins, y unidades reguladas por otras agencias del gobierno.",
          "who_it_covers": "Unidades de alquiler en San Francisco que están cubiertas por la Ordenanza de Arrendamiento, excepto unidades exentas como aquellas que obtuvieron por primera vez un Certificado de Ocupación después del 13 de junio de 1979.",
          "what_you_can_do": "Pregúntele a su propietario por escrito qué aumento de alquiler, si alguno, se aplica a su unidad, y si su unidad está exenta de la Ordenanza de Arrendamiento."
        },
        "citation": "S.F. Admin. Code ch. 37",
        "source_url": "https://sf.gov/information/overview-just-cause-evictions",
        "retrieved_at": "2026-10-01",
        "quoted_span": "Some tenancies that are exempt from the rent increase limitations of the Ordinance are still subject to the eviction provisions of the Ordinance, and tenants in these categories can only be evicted for one of the “just cause” reasons listed in the Ordinance.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.421,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": true,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/es/SF-RENT-01.mp3?v=fc276d7d"
      },
      {
        "team_rule_id": "CA-RENT-01",
        "title": "Statewide rent cap (Tenant Protection Act rent increase limits)",
        "category": "rent_increase_limits",
        "level": "state",
        "result": "superseded",
        "explanation": "Su arrendador no puede subir la renta más del 5% más el aumento del costo de vida, o 10%, lo que sea menor, en cualquier período de 12 meses. Cuando usted se muda por primera vez, su arrendador puede fijar cualquier renta inicial. La renta solo puede subir en hasta dos pasos en un período de 12 meses si usted se queda. Cubre este edificio (construido en 1926; 21 unidades), pero rige SF-RENT-01 (Rent Ordinance rent increase limitations – exempt tenancies). Notas: se presume que no hay evidencia de un estatus especial (1) en los datos del tasador. Fuente: Cal. Civ. Code § 1947.12 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1947.12, consultado el 2026-10-01). Vigente al 2026-10-01. No es asesoría legal.",
        "plain_language": {
          "status_line": "Aplica, pero rige SF-RENT-01",
          "what_it_means": "Su arrendador no puede subir la renta más del 5% más el aumento del costo de vida, o 10%, lo que sea menor, en cualquier período de 12 meses. Cuando usted se muda por primera vez, su arrendador puede fijar cualquier renta inicial. La renta solo puede subir en hasta dos pasos en un período de 12 meses si usted se queda.",
          "who_it_covers": "Inquilinos en unidades residenciales (apartamentos, casas, casas móviles) en California, excepto ciertos edificios nuevos, viviendas subsidiadas, dormitorios escolares y algunas casas unifamiliares.",
          "what_you_can_do": "Mantenga un registro de lo que pagó de renta en los 12 meses anteriores y pídale a su arrendador por escrito que le muestre cómo calculó cualquier aumento de renta para asegurarse de que sigue el límite del 5% más el costo de vida."
        },
        "citation": "Cal. Civ. Code § 1947.12",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1947.12",
        "retrieved_at": "2026-10-01",
        "quoted_span": "Subject to subdivision (b), an owner of residential real property shall not, over the course of any 12-month period, increase the gross rental rate for a dwelling or a unit more than 5 percent plus the percentage change in the cost of living, or 10 percent, whichever is lower, of the lowest gross rental rate charged for that dwelling or unit at any time during the 12 months prior to the effective date of the increase.",
        "effective_date": "2024-04-01",
        "status": "in_force",
        "confidence": 0.648,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [
          "presumed: no evidence of an affordability restriction in assessor data"
        ],
        "superseded_by": "SF-RENT-01",
        "attested": false,
        "audio_url": "/audio/es/CA-RENT-01.mp3?v=454e2203"
      }
    ],
    "CAUSA JUSTA": [
      {
        "team_rule_id": "SF-JUST-01",
        "title": "Rent Ordinance just cause eviction requirement (17 just causes)",
        "category": "just_cause_eviction",
        "level": "city",
        "result": "applies",
        "explanation": "Un arrendador solo puede desalojar a un inquilino de una unidad de alquiler cubierta por la Ordenanza de Arrendamiento de San Francisco si tiene una de 17 razones de causa justa específicas. El arrendador debe probar que esta razón es la razón principal para el desalojo. Simplemente terminar un contrato de arrendamiento o vender el edificio no es razón suficiente para desalojar. Los arrendadores también necesitan causa justa para remover servicios de vivienda como estacionamiento, almacenamiento o lavandería. Aplica aquí (todas las viviendas de alquiler cubiertas en San Francisco, CA). Fuente: S.F. Admin. Code § 37.9 (https://sf.gov/information/overview-just-cause-evictions, consultado el 2026-10-01). Vigente al 2026-10-01. No es asesoría legal.",
        "plain_language": {
          "status_line": "Vigente",
          "what_it_means": "Un arrendador solo puede desalojar a un inquilino de una unidad de alquiler cubierta por la Ordenanza de Arrendamiento de San Francisco si tiene una de 17 razones de causa justa específicas. El arrendador debe probar que esta razón es la razón principal para el desalojo. Simplemente terminar un contrato de arrendamiento o vender el edificio no es razón suficiente para desalojar. Los arrendadores también necesitan causa justa para remover servicios de vivienda como estacionamiento, almacenamiento o lavandería.",
          "who_it_covers": "Unidades de alquiler cubiertas por la Ordenanza de Arrendamiento de San Francisco, incluyendo algunas unidades exentas de los límites de aumento de alquiler.",
          "what_you_can_do": "Pida a su arrendador por escrito que explique la razón de causa justa para cualquier desalojo o retiro de servicios de vivienda. Guarde copias de todos los avisos y documentos de su arrendador."
        },
        "citation": "S.F. Admin. Code § 37.9",
        "source_url": "https://sf.gov/information/overview-just-cause-evictions",
        "retrieved_at": "2026-10-01",
        "quoted_span": "In order to evict a tenant from a rental unit covered by the Rent Ordinance, a landlord must have a \"just cause\" reason that is the dominant motive for pursuing the eviction.",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.765,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/es/SF-JUST-01.mp3?v=ecf6da81"
      },
      {
        "team_rule_id": "CA-JUST-02",
        "title": "Tenant Protection Act just cause requirement for terminating tenancies",
        "category": "just_cause_eviction",
        "level": "state",
        "result": "superseded",
        "explanation": "Después de haber vivido en su hogar de alquiler durante 12 meses, su arrendador solo puede terminar su contrato de arrendamiento por una razón válida. El arrendador debe decirle la razón por escrito. Si la razón no es su culpa, el arrendador debe pagarle un mes de alquiler o permitirle saltarse su último mes de alquiler. Cubre este edificio (construido en 1926; 21 unidades), pero rige SF-JUST-01 (Rent Ordinance just cause eviction requirement (17 just causes)). Notas: se presume que no hay evidencia de un estatus especial (1) en los datos del tasador. Fuente: Cal. Civ. Code § 1946.2 (https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946.2, consultado el 2026-10-01). Vigente al 2026-10-01. No es asesoría legal.",
        "plain_language": {
          "status_line": "Aplica, pero rige SF-JUST-01",
          "what_it_means": "Después de haber vivido en su hogar de alquiler durante 12 meses, su arrendador solo puede terminar su contrato de arrendamiento por una razón válida. El arrendador debe decirle la razón por escrito. Si la razón no es su culpa, el arrendador debe pagarle un mes de alquiler o permitirle saltarse su último mes de alquiler.",
          "who_it_covers": "Inquilinos que han vivido continua y legalmente en unidades residenciales (incluidas casas móviles) durante 12 meses o más.",
          "what_you_can_do": "Guarde registros de cuándo se mudó y solicítele a su arrendador que le proporcione la razón por escrito si intenta terminar su arrendamiento."
        },
        "citation": "Cal. Civ. Code § 1946.2",
        "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946.2",
        "retrieved_at": "2026-10-01",
        "quoted_span": "(a) Notwithstanding any other law, after a tenant has continuously and lawfully occupied a residential real property for 12 months, the owner of the residential real property shall not terminate a tenancy without just cause, which shall be stated in the written notice to terminate tenancy.",
        "effective_date": "2024-04-01",
        "status": "in_force",
        "confidence": 0.629,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": false,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [
          "presumed: no evidence of an affordability restriction in assessor data"
        ],
        "superseded_by": "SF-JUST-01",
        "attested": false,
        "audio_url": "/audio/es/CA-JUST-02.mp3?v=6de7c4b7"
      },
      {
        "team_rule_id": "CA-JUST-03",
        "title": "Housing Crisis Act relocation for lower-income households displaced by demolition",
        "category": "just_cause_eviction",
        "level": "state",
        "result": "applies",
        "explanation": "Si su unidad de alquiler es demolida para construir un edificio nuevo, el arrendador debe pagar asistencia de reubicación. Esta asistencia debe corresponder a lo que el estado requiere que paguen las agencias públicas. Aplica aquí (todas las viviendas de alquiler cubiertas en CA). Aplica solo si la unidad se demuele para un nuevo desarrollo de vivienda. Fuente: Cal. Gov. Code § 66300.6 (https://housing.lacity.gov/wp-content/uploads/2026/08/Relocation-Assistance-Bulletins-A-and-B-Combined.pdf, consultado el 2026-10-01). Vigente al 2026-10-01. No es asesoría legal.",
        "plain_language": {
          "status_line": "Vigente",
          "what_it_means": "Si su unidad de alquiler es demolida para construir un edificio nuevo, el arrendador debe pagar asistencia de reubicación. Esta asistencia debe corresponder a lo que el estado requiere que paguen las agencias públicas.",
          "who_it_covers": "Hogares de ingresos bajos (80% AMI o menos) cuyas unidades de alquiler son demolidas para nueva construcción.",
          "what_you_can_do": "Pregunte a su arrendador por escrito qué asistencia de reubicación le proporcionará si su unidad es demolida."
        },
        "citation": "Cal. Gov. Code § 66300.6",
        "source_url": "https://housing.lacity.gov/wp-content/uploads/2026/08/Relocation-Assistance-Bulletins-A-and-B-Combined.pdf",
        "retrieved_at": "2026-10-01",
        "quoted_span": "3. Pay relocation assistance to tenants in compliance with the State law’s Housing Crisis Act",
        "effective_date": null,
        "status": "in_force",
        "confidence": 0.36,
        "conflict_flag": false,
        "conflict_note": null,
        "needs_review": true,
        "missing_facts": [],
        "missing_facts_label": [],
        "presumptions": [],
        "superseded_by": null,
        "attested": false,
        "audio_url": "/audio/es/CA-JUST-03.mp3?v=3e3077fe"
      }
    ]
  },
  "counts": {
    "applies": 13,
    "superseded": 2
  },
  "_note": "Excerpt: RENTA and CAUSA JUSTA only. Full response: static/lookup/A0016.es.json."
}
```

### `GET /rules?jurisdiction=&category=&as_of=&lang=`
Every rule (and attested rule) with its status at `as_of`, citation, source, quote, key value,
confidence, conflict flag/note and plain language. `jurisdiction`: `CA` | `NJ` | `MA` or
`"City, ST"`; `category`: rent_increase_limits | just_cause_eviction | security_deposits |
application_screening_fees | screening_restrictions | algorithmic_rent_setting.

`/rules` entries also carry `audio_url` (same format as in `/lookup`).

### `GET /audio/{lang}/{team_rule_id}.mp3`
The spoken plain-language summary (what it means, who it covers, what you can do; no status
line, so it does not change with `as_of`). `Content-Type: audio/mpeg`, `Cache-Control: public,
max-age=31536000, immutable` (the `?v=` in `audio_url` changes when the text changes). MP3 mono,
22.05 kHz, 32 kbps, from ElevenLabs `eleven_multilingual_v2`, generated once by
`python -m api.audio --generate` (cached by text, voice and model; `data/audio/manifest.json`
records text hash, voice, model and characters). `404` if there is no file.
**AI disclosure:** the voice is AI-generated (ElevenLabs); label the player "AI-generated voice"
in any interface. Information only — not legal advice.

### `GET /changes?lang=` and `GET /changes/{test_id}?lang=`
`/changes`: `changes` (per test `affected_address_ids`, `conflict_flag_address_ids`, `notes` —
notes in the requested language) and `summary` (counts, `type`, `type_label`, `title`, `notes`).
`/changes/T1` … `T5` (and `T6` after an hour-16 run): the test definition, our rule ids,
`type_label`, `title`, `notes` and the before/after result per address.

`type_label`: as_of → "Change by date" / "Cambio por fecha"; boundary → "City boundary" /
"Límite de ciudad"; pending → "Pending bill" / "Proyecto de ley pendiente"; negative → "Did not
become law" / "No se convirtió en ley". Spanish titles and notes are deterministic templates
(no model) with the same numbers, long-form dates ("1 de enero de 2026"), the glossary terms
and "usted". (The submission file `out/changes.json` keeps the English notes.)

```json
{
  "disclaimer": "Not legal advice. This prototype summarizes public housing law for information only; check the cited source and consult a qualified professional before acting.",
  "summary": {
    "T1": {
      "affected": 250,
      "conflict_flagged": 0,
      "type": "as_of",
      "type_label": "Change by date",
      "title": "California AB 325 / SB 763 takes effect",
      "notes": "CA-ALG-01 changes between 2025-12-31 and 2026-01-02 (effective 2026-01-01) at 250 addresses (Berkeley, CA 40, Los Angeles, CA 80, San Diego, CA 50, San Francisco, CA 80); not_yet_effective -> applies: 250."
    },
    "T2": {
      "affected": 90,
      "conflict_flagged": 90,
      "type": "boundary",
      "type_label": "City boundary",
      "title": "Hoboken vs Jersey City local algorithmic bans",
      "notes": "HOB-ALG-A1, JC-ALG-A1 apply only inside their own city limits as of 2026-10-01 (Hoboken, NJ 40, Jersey City, NJ 50); none elsewhere. Local ordinance text not in corpus; scope from organizer brief (manifest-attested rules). All 90 carry a conflict flag: the NJ FAIR Act may preempt them once effective."
    },
    "T3": {
      "affected": 140,
      "conflict_flagged": 90,
      "type": "as_of",
      "type_label": "Change by date",
      "title": "NJ FAIR Act: enacted, not yet effective; possible preemption",
      "notes": "NJ-ALG-01 changes between 2026-10-01 and 2027-07-02 (effective 2027-07-01) at 140 addresses (Hoboken, NJ 40, Jersey City, NJ 50, Newark, NJ 50); not_yet_effective -> applies: 140. 90 addresses carry a conflict flag: possible preemption of the local algorithmic ordinances, flagged for human review."
    },
    "T4": {
      "affected": 110,
      "conflict_flagged": 0,
      "type": "pending",
      "type_label": "Pending bill",
      "title": "Massachusetts pending bills S.2983 and H.5222",
      "notes": "MA-ALG-P2, MA-ALG-P1 are pending bills, not law, as of 2026-10-01; if enacted they would cover 110 Massachusetts addresses (Boston, MA 60, Cambridge, MA 50). Bill text not in corpus: scope stated statewide from the bill status pages."
    },
    "T5": {
      "affected": 0,
      "conflict_flagged": 0,
      "type": "negative",
      "type_label": "Did not become law",
      "title": "Massachusetts rent-control ballot question struck",
      "notes": "No rent cap in force in Massachusetts as of 2026-10-01: affected set is empty (0). The rent-control ballot question (MA-RENT-A1, IP 25-21) is recorded as failed (struck 2026-06-23); M.G.L. c. 40P bars local rent control and is not a cap."
    }
  },
  "changes": {
    "T5": {
      "affected_address_ids": [],
      "conflict_flag_address_ids": [],
      "notes": "No rent cap in force in Massachusetts as of 2026-10-01: affected set is empty (0). The rent-control ballot question (MA-RENT-A1, IP 25-21) is recorded as failed (struck 2026-06-23); M.G.L. c. 40P bars local rent control and is not a cap."
    },
    "T1": {
      "affected_address_ids": [
        "A0001",
        "A0004",
        "A0005",
        "A0007",
        "A0014",
        "…"
      ],
      "conflict_flag_address_ids": [],
      "notes": "CA-ALG-01 changes between 2025-12-31 and 2026-01-02 (effective 2026-01-01) at 250 addresses (Berkeley, CA 40, Los Angeles, CA 80, San Diego, CA 50, San Francisco, CA 80); not_yet_effective -> applies: 250."
    }
  }
}
```

Spanish summary (`GET /changes?lang=es`, real response, `summary` only):

```json
{
  "T1": {
    "affected": 250,
    "conflict_flagged": 0,
    "type": "as_of",
    "type_label": "Cambio por fecha",
    "title": "Entrada en vigor: Cal. Bus. & Prof. Code § 16729 (fijación de renta con algoritmos, California)",
    "notes": "CA-ALG-01 cambia entre el 31 de diciembre de 2025 y el 2 de enero de 2026 (entra en vigor el 1 de enero de 2026) en 250 direcciones (Berkeley, CA 40, Los Angeles, CA 80, San Diego, CA 50, San Francisco, CA 80); aún no vigente → aplica: 250."
  },
  "T2": {
    "affected": 90,
    "conflict_flagged": 90,
    "type": "boundary",
    "type_label": "Límite de ciudad",
    "title": "Límite de ciudad: Hoboken Code ch. 158, Art. II (fijación de renta con algoritmos, Hoboken, NJ); Jersey City Code § 218-12 (fijación de renta con algoritmos, Jersey City, NJ)",
    "notes": "HOB-ALG-A1, JC-ALG-A1 aplican solo dentro de los límites de su propia ciudad al 1 de octubre de 2026 (Hoboken, NJ 40, Jersey City, NJ 50); en ninguna otra. El texto de las ordenanzas locales no está en el corpus; su alcance proviene del documento de los organizadores (reglas atestiguadas en el manifiesto). Las 90 tienen alerta de conflicto: la Ley FAIR de Nueva Jersey podría desplazarlas cuando entre en vigor."
  },
  "T3": {
    "affected": 140,
    "conflict_flagged": 90,
    "type": "as_of",
    "type_label": "Cambio por fecha",
    "title": "Entrada en vigor: P.L.2026, c.43 (fijación de renta con algoritmos, Nueva Jersey)",
    "notes": "NJ-ALG-01 cambia entre el 1 de octubre de 2026 y el 2 de julio de 2027 (entra en vigor el 1 de julio de 2027) en 140 direcciones (Hoboken, NJ 40, Jersey City, NJ 50, Newark, NJ 50); aún no vigente → aplica: 140. 90 direcciones tienen una alerta de conflicto: posible preempción de las ordenanzas locales sobre algoritmos, marcada para revisión humana."
  },
  "T4": {
    "affected": 110,
    "conflict_flagged": 0,
    "type": "pending",
    "type_label": "Proyecto de ley pendiente",
    "title": "Proyectos de ley pendientes: MA S.2983 (fijación de renta con algoritmos, Massachusetts); MA H.5222 (fijación de renta con algoritmos, Massachusetts)",
    "notes": "MA-ALG-P2, MA-ALG-P1 son proyectos de ley pendientes, no leyes, al 1 de octubre de 2026; si se aprobaran cubrirían 110 direcciones de Massachusetts (Boston, MA 60, Cambridge, MA 50). El texto de los proyectos de ley no está en el corpus: su alcance se indica a nivel estatal según las páginas de estado de los proyectos."
  },
  "T5": {
    "affected": 0,
    "conflict_flagged": 0,
    "type": "negative",
    "type_label": "No se convirtió en ley",
    "title": "No se convirtió en ley: control de rentas (Massachusetts)",
    "notes": "No hay ningún tope de renta vigente en Massachusetts al 1 de octubre de 2026: el conjunto de direcciones afectadas está vacío (0). La pregunta de boleta sobre control de rentas (MA-RENT-A1, IP 25-21) consta como fallida (anulada el 23 de junio de 2026); la ley M.G.L. c. 40P prohíbe el control de rentas local y no es un tope."
  }
}
```

### `GET /explain/{address_id}/{team_rule_id}?as_of=&lang=`
"Why this answer?" — loaded on demand so `/lookup` stays small. A deterministic trace (no
model) built from **the same lookup** as `/lookup`, so `result`, `status`, `effective_date`,
`confidence`, `conflict_flag` and `superseded_by` are always identical to `/lookup` on the same
date (tested for every rule of several addresses and dates). Labels in the requested language
(Spanish with "usted" and the glossary terms); source texts, citations and quotes stay as written.
`404` for an unknown address or rule; a rule outside the address's jurisdiction returns
`result: "not_in_stack"`.

| Field | Meaning |
|---|---|
| `result`, `status`, `effective_date`, `coverage`, `confidence`, `conflict_flag`, `superseded_by`, `omitted_reason`, `status_line` | the answer being explained (`result` also `omitted` — not covered / exempt / failed — or `not_in_stack`) |
| `summary` | 1–2 plain sentences |
| `jurisdiction` | rule level and jurisdiction vs the address's geocoded state/city: `source` (census \| dataset_fallback), `match_quality`, `certainty`, `in_stack`, `note` |
| `coverage_steps` | each coverage condition: `{condition (readable), source_text, fact_used, value, fact_source, certainty, outcome: yes \| no \| unknown, note}` |
| `exemption_steps` | same shape plus `class`: `special_status` (presumed absent unless a use flag shows it), `building`, `unit_or_tenancy` (a caveat that does not change the result), `other_law` (resolved against the address's other rules), `review` (not machine-checkable, not counted); `note` says why it was resolved that way |
| `precedence` | `superseded`, `governed_by`, `governing_title`, `basis` (`overrides` = Module A "[Yields to]" / "[Takes precedence over]"; `other_law` = an exemption for housing covered by another law; `same_law` = carried over from `same_law_as`, a rule of the same law and section), `interaction`, `may_yield_to`, `conflict_flag`, `conflict_note`, `preemption` (notes), `note` |
| `status_steps` | legislative `stage`, `enacted`, each `effective_date` with its `origin` — `literal` (with `quote`) \| `derived` (formula in the text, with `quote`) \| `calendar_default` (`calendar_source`, e.g. Cal. Const. art. IV, § 8(c)) \| `attested` — `sunset`, and the resulting `status` |
| `confidence_breakdown` | `rule`, `coverage` (with each reducing `factor` and its reason), `geocoding`, `combined` (= `confidence`), `needs_review` |
| `provenance` | `doc_id`, `source_url`, `retrieved_at`, `quoted_span`, `citation`, extraction `prompt_version`, `model`, `snapshot`, `supporting_quotes`, `coverage_compiler`, and the `human_review` register entries that affect the rule |

**Example — `GET /explain/A0016/CA-RENT-01?lang=en` (real response):**

```json
{
  "address": {
    "address_id": "A0016",
    "street": "3515 FILLMORE ST",
    "postal_city": "San Francisco",
    "state": "CA",
    "city": "San Francisco, CA",
    "dataset_city": "San Francisco, CA"
  },
  "team_rule_id": "CA-RENT-01",
  "title": "Statewide rent cap (Tenant Protection Act rent increase limits)",
  "category": "rent_increase_limits",
  "as_of": "2026-10-01",
  "lang": "en",
  "disclaimer": "Not legal advice. This prototype summarizes public housing law for information only; check the cited source and consult a qualified professional before acting.",
  "result": "superseded",
  "status": "in_force",
  "effective_date": "2024-04-01",
  "coverage": "covered",
  "confidence": 0.648,
  "conflict_flag": false,
  "superseded_by": "SF-RENT-01",
  "omitted_reason": null,
  "status_line": "Covered, but SF-RENT-01 governs instead",
  "summary": "CA-RENT-01 covers this building on October 1, 2026, but SF-RENT-01 governs instead. Confidence: 0.648 (rule × coverage × geocoding).",
  "jurisdiction": {
    "rule_jurisdiction": "CA",
    "rule_level": "state",
    "address_state": "CA",
    "address_city": "San Francisco, CA",
    "source": "census",
    "match_quality": "exact",
    "certainty": "high",
    "matched_address": "3515 FILLMORE ST, SAN FRANCISCO, CA, 94123",
    "in_stack": true,
    "note": "State rule of CA; this address is in CA (Census geocoder)."
  },
  "coverage_steps": [
    {
      "condition": "building age (years) is at least 15",
      "source_text": "building_age_min_years = 15",
      "fact_used": [
        "building age (years)"
      ],
      "value": {
        "building age (years)": "99 to 100"
      },
      "fact_source": {
        "building age (years)": "year_built 1926 as certificate-of-occupancy proxy, as of 2026-10-01"
      },
      "certainty": {
        "building age (years)": "approximate (year built used as proxy)"
      },
      "outcome": "yes",
      "note": "The building meets this condition."
    },
    {
      "condition": "always",
      "source_text": "residential real property",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "yes",
      "note": "The building meets this condition."
    }
  ],
  "exemption_steps": [
    {
      "condition": "the building has an affordability restriction",
      "source_text": "Housing deed- or regulatory-restricted as affordable housing for very low, low, or moderate income persons, or subject to an affordable housing subsidy agreement",
      "fact_used": [
        "an affordability restriction"
      ],
      "value": {
        "an affordability restriction": null
      },
      "fact_source": {
        "an affordability restriction": "the use code does not say"
      },
      "certainty": {
        "an affordability restriction": "not in the data"
      },
      "outcome": "no",
      "note": "Presumed absent: the assessor data shows no evidence of it (special status presumption).",
      "class": "special_status",
      "special_status_presumption": true
    },
    {
      "condition": "type of building is dormitory",
      "source_text": "Dormitories owned and operated by an institution of higher education or a K-12 school",
      "fact_used": [
        "type of building"
      ],
      "value": {
        "type of building": "apartment building"
      },
      "fact_source": {
        "type of building": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "certainty": {
        "type of building": "inferred from the use code"
      },
      "outcome": "no",
      "note": "This exemption does not apply.",
      "class": "building"
    },
    {
      "condition": "requires a fact not in the data: subject to stricter local rent control",
      "source_text": "Housing subject to local rent or price control under Chapter 2.7 that restricts annual increases to less than subdivision (a)",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "yes",
      "note": "Refers to local rent control; SF-RENT-01 covers this building, so this rule yields to it.",
      "class": "other_law"
    },
    {
      "condition": "building age (years) is less than 15 and not (type of building is mobilehome)",
      "source_text": "Housing issued a certificate of occupancy within the previous 15 years, unless it is a mobilehome",
      "fact_used": [
        "building age (years)",
        "type of building"
      ],
      "value": {
        "building age (years)": "99 to 100",
        "type of building": "apartment building"
      },
      "fact_source": {
        "building age (years)": "year_built 1926 as certificate-of-occupancy proxy, as of 2026-10-01",
        "type of building": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "certainty": {
        "building age (years)": "approximate (year built used as proxy)",
        "type of building": "inferred from the use code"
      },
      "outcome": "no",
      "note": "This exemption does not apply.",
      "class": "building"
    },
    {
      "condition": "type of owner is one of individual or entity other than REIT, corporation, LLC with corporate member, or mobilehome park management (separately alienable unit, with notice)",
      "source_text": "Residential property alienable separate from any other dwelling unit (including mobilehome) where owner is not a REIT, corporation, LLC with a corporate member, or mobilehome park management, and tenants received the required written exemption notice",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "unknown",
      "note": "Depends on the unit or the tenancy, not on the building: shown as a caveat; it does not change the result.",
      "class": "unit_or_tenancy"
    },
    {
      "condition": "an owner lives on the property and number of units is 2",
      "source_text": "Two-unit property in a single structure where the owner occupied one unit as principal residence at the beginning of the tenancy and continues in occupancy, and neither unit is an ADU or JADU",
      "fact_used": [
        "whether an owner lives on the property",
        "number of units"
      ],
      "value": {
        "whether an owner lives on the property": null,
        "number of units": "21"
      },
      "fact_source": {
        "whether an owner lives on the property": "no owner data in the sample",
        "number of units": "units column"
      },
      "certainty": {
        "whether an owner lives on the property": "not in the data",
        "number of units": "exact (assessor record)"
      },
      "outcome": "no",
      "note": "This exemption does not apply.",
      "class": "building"
    },
    {
      "condition": "type of building is mobilehome",
      "source_text": "Homeowner of a mobilehome, as defined in Section 798.9",
      "fact_used": [
        "type of building"
      ],
      "value": {
        "type of building": "apartment building"
      },
      "fact_source": {
        "type of building": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "certainty": {
        "type of building": "inferred from the use code"
      },
      "outcome": "no",
      "note": "This exemption does not apply.",
      "class": "building"
    },
    {
      "condition": "building age (years) is less than 15",
      "source_text": "Units constructed within the last 15 years (rolling)",
      "fact_used": [
        "building age (years)"
      ],
      "value": {
        "building age (years)": "99 to 100"
      },
      "fact_source": {
        "building age (years)": "year_built 1926 as certificate-of-occupancy proxy, as of 2026-10-01"
      },
      "certainty": {
        "building age (years)": "approximate (year built used as proxy)"
      },
      "outcome": "no",
      "note": "This exemption does not apply.",
      "class": "building"
    },
    {
      "condition": "the building has an affordability restriction",
      "source_text": "Units restricted by deed, regulatory restriction or recorded document limiting affordability to low or moderate-income households",
      "fact_used": [
        "an affordability restriction"
      ],
      "value": {
        "an affordability restriction": null
      },
      "fact_source": {
        "an affordability restriction": "the use code does not say"
      },
      "certainty": {
        "an affordability restriction": "not in the data"
      },
      "outcome": "no",
      "note": "Presumed absent: the assessor data shows no evidence of it (special status presumption).",
      "class": "special_status",
      "special_status_presumption": true
    },
    {
      "condition": "type of owner is one of not real estate trust, not corporation, not LLC with corporate member and (the building has single-family use or the building has condominium ownership)",
      "source_text": "Single-family homes and condominiums not owned by a real estate trust, corporation, or LLC with at least one corporate member, where the landlord gave written notice of exemption",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "unknown",
      "note": "Depends on the unit or the tenancy, not on the building: shown as a caveat; it does not change the result.",
      "class": "unit_or_tenancy"
    },
    {
      "condition": "requires a fact not in the data: subject to Los Angeles RSO",
      "source_text": "Units already subject to the City's RSO",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "no",
      "note": "Refers to the Los Angeles Rent Stabilization Ordinance (RSO), which does not cover this building.",
      "class": "other_law"
    }
  ],
  "precedence": {
    "superseded": true,
    "governed_by": "SF-RENT-01",
    "governing_title": "Rent Ordinance rent increase limitations – exempt tenancies",
    "basis": "other_law",
    "same_law_as": null,
    "interaction": "Does not apply to housing under local rent control (consistent with Civ. Code Ch. 2.7, § 1954.50 et seq.) that restricts annual increases to less than this section's cap. It does not expand or limit local governments' authority to regulate rents under Chapter 2.7. Waivers are void. Does not apply to units subject to the Los Angeles RSO; the JCO does not regulate rent increases. [Yields to: BRK-RENT-01, BRK-RENT-02, LA-RENT-01, LA-RENT-02, LA-RENT-03, LA-RENT-04, SF-RENT-01, SNA-RENT-01]",
    "may_yield_to": [],
    "conflict_flag": false,
    "conflict_note": null,
    "note": "CA-RENT-01 has an exemption for housing covered by another law, and SF-RENT-01 covers this building. Module A precedence also says it yields to SF-RENT-01."
  },
  "status_steps": [
    {
      "step": "stage",
      "value": "enacted",
      "note": "Legislative stage: enacted."
    },
    {
      "step": "effective_date",
      "date": "2024-04-01",
      "origin": "literal",
      "quote": "This section shall become operative on April 1, 2024.",
      "raw": "operative on April 1, 2024",
      "rule_applied": null,
      "calendar_source": null,
      "verified": true,
      "source_doc_id": "D024",
      "note": "Effective date stated in the text: \"This section shall become operative on April 1, 2024.\""
    },
    {
      "step": "status",
      "value": "in_force",
      "note": "Status on October 1, 2026: in force."
    }
  ],
  "confidence_breakdown": {
    "rule": {
      "value": 0.9,
      "reason": "Extraction confidence of the rule (validated quote and citation)."
    },
    "coverage": {
      "value": 0.72,
      "factors": [
        {
          "factor": 0.8,
          "reason": "Year built used as a proxy for the Certificate of Occupancy date."
        },
        {
          "factor": 0.9,
          "reason": "The result rests on the special status presumption."
        }
      ]
    },
    "geocoding": {
      "value": 1.0,
      "reason": "Census geocoder: exact match."
    },
    "combined": 0.648,
    "needs_review": false
  },
  "provenance": {
    "doc_id": "D024",
    "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1947.12",
    "retrieved_at": "2026-10-01T22:35:00+00:00",
    "quoted_span": "Subject to subdivision (b), an owner of residential real property shall not, over the course of any 12-month period, increase the gross rental rate for a dwelling or a unit more than 5 percent plus the percentage change in the cost of living, or 10 percent, whichever is lower, of the lowest gross rental rate charged for that dwelling or unit at any time during the 12 months prior to the effective date of the increase.",
    "citation": "Cal. Civ. Code § 1947.12",
    "prompt_version": "a-0.4.0",
    "model": "claude-opus-5-5",
    "snapshot": "a-0.4.0",
    "supporting_quotes": [
      {
        "doc_id": "D040",
        "role": "merged",
        "quoted_span": "A\nnnual rent increases are limited to no more than 5% plus the percentage change in the cost of living for the region in which the property is located, or 10% whichever is lower)"
      },
      {
        "doc_id": "D040",
        "role": "administrative",
        "quoted_span": "Effective August 1, 2024 to July 31, 2025, the maximum allowable increase is\n8.9%"
      },
      {
        "doc_id": "D040",
        "role": "administrative",
        "quoted_span": "Previously, from August 1, 2023 to July 31, 2024 the maximum annual increase for units subject to AB 1482 was 8.8%"
      }
    ],
    "coverage_compiler": {
      "model": "claude-haiku-4-5",
      "prompt_version": "cx-0.4.0"
    },
    "human_review": []
  }
}
```

**Example — `GET /explain/A0016/CA-RENT-01?lang=es` (real response):**

```json
{
  "address": {
    "address_id": "A0016",
    "street": "3515 FILLMORE ST",
    "postal_city": "San Francisco",
    "state": "CA",
    "city": "San Francisco, CA",
    "dataset_city": "San Francisco, CA"
  },
  "team_rule_id": "CA-RENT-01",
  "title": "Statewide rent cap (Tenant Protection Act rent increase limits)",
  "category": "rent_increase_limits",
  "as_of": "2026-10-01",
  "lang": "es",
  "disclaimer": "No es asesoría legal. Este prototipo resume leyes públicas de vivienda solo con fines informativos; revise la fuente citada y consulte a un profesional calificado antes de actuar.",
  "result": "superseded",
  "status": "in_force",
  "effective_date": "2024-04-01",
  "coverage": "covered",
  "confidence": 0.648,
  "conflict_flag": false,
  "superseded_by": "SF-RENT-01",
  "omitted_reason": null,
  "status_line": "Aplica, pero rige SF-RENT-01",
  "summary": "CA-RENT-01 cubre este edificio al 1 de octubre de 2026, pero rige SF-RENT-01 en su lugar. Confianza: 0.648 (regla × cobertura × geocodificación).",
  "jurisdiction": {
    "rule_jurisdiction": "CA",
    "rule_level": "state",
    "address_state": "CA",
    "address_city": "San Francisco, CA",
    "source": "census",
    "match_quality": "exact",
    "certainty": "high",
    "matched_address": "3515 FILLMORE ST, SAN FRANCISCO, CA, 94123",
    "in_stack": true,
    "note": "Regla estatal de CA; esta dirección está en CA (geocodificador del Censo)."
  },
  "coverage_steps": [
    {
      "condition": "antigüedad del edificio (años) es al menos 15",
      "source_text": "building_age_min_years = 15",
      "fact_used": [
        "antigüedad del edificio (años)"
      ],
      "value": {
        "antigüedad del edificio (años)": "entre 99 y 100"
      },
      "fact_source": {
        "antigüedad del edificio (años)": "year_built 1926 as certificate-of-occupancy proxy, as of 2026-10-01"
      },
      "certainty": {
        "antigüedad del edificio (años)": "aproximado (se usa el año de construcción)"
      },
      "outcome": "yes",
      "note": "El edificio cumple esta condición."
    },
    {
      "condition": "siempre",
      "source_text": "residential real property",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "yes",
      "note": "El edificio cumple esta condición."
    }
  ],
  "exemption_steps": [
    {
      "condition": "el edificio tiene una restricción de asequibilidad",
      "source_text": "Housing deed- or regulatory-restricted as affordable housing for very low, low, or moderate income persons, or subject to an affordable housing subsidy agreement",
      "fact_used": [
        "una restricción de asequibilidad"
      ],
      "value": {
        "una restricción de asequibilidad": null
      },
      "fact_source": {
        "una restricción de asequibilidad": "the use code does not say"
      },
      "certainty": {
        "una restricción de asequibilidad": "no está en los datos"
      },
      "outcome": "no",
      "note": "Se presume que no existe: los datos del tasador no muestran evidencia (presunción de estatus especial).",
      "class": "special_status",
      "special_status_presumption": true
    },
    {
      "condition": "tipo de edificio es dormitorio",
      "source_text": "Dormitories owned and operated by an institution of higher education or a K-12 school",
      "fact_used": [
        "tipo de edificio"
      ],
      "value": {
        "tipo de edificio": "edificio de apartamentos"
      },
      "fact_source": {
        "tipo de edificio": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "certainty": {
        "tipo de edificio": "inferido del código de uso"
      },
      "outcome": "no",
      "note": "Esta exención no aplica.",
      "class": "building"
    },
    {
      "condition": "requiere un dato que no tenemos: subject to stricter local rent control",
      "source_text": "Housing subject to local rent or price control under Chapter 2.7 that restricts annual increases to less than subdivision (a)",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "yes",
      "note": "Se refiere al control de rentas local; SF-RENT-01 cubre este edificio, así que esta regla cede ante ella.",
      "class": "other_law"
    },
    {
      "condition": "antigüedad del edificio (años) es menor que 15 y no (tipo de edificio es casa móvil)",
      "source_text": "Housing issued a certificate of occupancy within the previous 15 years, unless it is a mobilehome",
      "fact_used": [
        "antigüedad del edificio (años)",
        "tipo de edificio"
      ],
      "value": {
        "antigüedad del edificio (años)": "entre 99 y 100",
        "tipo de edificio": "edificio de apartamentos"
      },
      "fact_source": {
        "antigüedad del edificio (años)": "year_built 1926 as certificate-of-occupancy proxy, as of 2026-10-01",
        "tipo de edificio": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "certainty": {
        "antigüedad del edificio (años)": "aproximado (se usa el año de construcción)",
        "tipo de edificio": "inferido del código de uso"
      },
      "outcome": "no",
      "note": "Esta exención no aplica.",
      "class": "building"
    },
    {
      "condition": "tipo de propietario es uno de individual or entity other than REIT, corporation, LLC with corporate member, or mobilehome park management (separately alienable unit, with notice)",
      "source_text": "Residential property alienable separate from any other dwelling unit (including mobilehome) where owner is not a REIT, corporation, LLC with a corporate member, or mobilehome park management, and tenants received the required written exemption notice",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "unknown",
      "note": "Depende de la unidad o del contrato de arrendamiento, no del edificio: se muestra como advertencia y no cambia el resultado.",
      "class": "unit_or_tenancy"
    },
    {
      "condition": "un propietario vive en la propiedad y número de unidades es 2",
      "source_text": "Two-unit property in a single structure where the owner occupied one unit as principal residence at the beginning of the tenancy and continues in occupancy, and neither unit is an ADU or JADU",
      "fact_used": [
        "si un propietario vive en la propiedad",
        "número de unidades"
      ],
      "value": {
        "si un propietario vive en la propiedad": null,
        "número de unidades": "21"
      },
      "fact_source": {
        "si un propietario vive en la propiedad": "no owner data in the sample",
        "número de unidades": "units column"
      },
      "certainty": {
        "si un propietario vive en la propiedad": "no está en los datos",
        "número de unidades": "exacto (registro del tasador)"
      },
      "outcome": "no",
      "note": "Esta exención no aplica.",
      "class": "building"
    },
    {
      "condition": "tipo de edificio es casa móvil",
      "source_text": "Homeowner of a mobilehome, as defined in Section 798.9",
      "fact_used": [
        "tipo de edificio"
      ],
      "value": {
        "tipo de edificio": "edificio de apartamentos"
      },
      "fact_source": {
        "tipo de edificio": "inferred: the assessor classes the parcel as a multi-unit apartment building, not as a single-family home or condominium units"
      },
      "certainty": {
        "tipo de edificio": "inferido del código de uso"
      },
      "outcome": "no",
      "note": "Esta exención no aplica.",
      "class": "building"
    },
    {
      "condition": "antigüedad del edificio (años) es menor que 15",
      "source_text": "Units constructed within the last 15 years (rolling)",
      "fact_used": [
        "antigüedad del edificio (años)"
      ],
      "value": {
        "antigüedad del edificio (años)": "entre 99 y 100"
      },
      "fact_source": {
        "antigüedad del edificio (años)": "year_built 1926 as certificate-of-occupancy proxy, as of 2026-10-01"
      },
      "certainty": {
        "antigüedad del edificio (años)": "aproximado (se usa el año de construcción)"
      },
      "outcome": "no",
      "note": "Esta exención no aplica.",
      "class": "building"
    },
    {
      "condition": "el edificio tiene una restricción de asequibilidad",
      "source_text": "Units restricted by deed, regulatory restriction or recorded document limiting affordability to low or moderate-income households",
      "fact_used": [
        "una restricción de asequibilidad"
      ],
      "value": {
        "una restricción de asequibilidad": null
      },
      "fact_source": {
        "una restricción de asequibilidad": "the use code does not say"
      },
      "certainty": {
        "una restricción de asequibilidad": "no está en los datos"
      },
      "outcome": "no",
      "note": "Se presume que no existe: los datos del tasador no muestran evidencia (presunción de estatus especial).",
      "class": "special_status",
      "special_status_presumption": true
    },
    {
      "condition": "tipo de propietario es uno de not real estate trust, not corporation, not LLC with corporate member y (el edificio tiene uso unifamiliar o el edificio tiene propiedad en condominio)",
      "source_text": "Single-family homes and condominiums not owned by a real estate trust, corporation, or LLC with at least one corporate member, where the landlord gave written notice of exemption",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "unknown",
      "note": "Depende de la unidad o del contrato de arrendamiento, no del edificio: se muestra como advertencia y no cambia el resultado.",
      "class": "unit_or_tenancy"
    },
    {
      "condition": "requiere un dato que no tenemos: subject to Los Angeles RSO",
      "source_text": "Units already subject to the City's RSO",
      "fact_used": [],
      "value": {},
      "fact_source": {},
      "certainty": {},
      "outcome": "no",
      "note": "Se refiere a la Ordenanza de Estabilización de Arrendamientos de Los Ángeles (RSO), que no cubre este edificio.",
      "class": "other_law"
    }
  ],
  "precedence": {
    "superseded": true,
    "governed_by": "SF-RENT-01",
    "governing_title": "Rent Ordinance rent increase limitations – exempt tenancies",
    "basis": "other_law",
    "same_law_as": null,
    "interaction": "Does not apply to housing under local rent control (consistent with Civ. Code Ch. 2.7, § 1954.50 et seq.) that restricts annual increases to less than this section's cap. It does not expand or limit local governments' authority to regulate rents under Chapter 2.7. Waivers are void. Does not apply to units subject to the Los Angeles RSO; the JCO does not regulate rent increases. [Yields to: BRK-RENT-01, BRK-RENT-02, LA-RENT-01, LA-RENT-02, LA-RENT-03, LA-RENT-04, SF-RENT-01, SNA-RENT-01]",
    "may_yield_to": [],
    "conflict_flag": false,
    "conflict_note": null,
    "note": "CA-RENT-01 tiene una exención para viviendas cubiertas por otra ley, y SF-RENT-01 cubre este edificio. La precedencia del Módulo A también indica que cede ante SF-RENT-01."
  },
  "status_steps": [
    {
      "step": "stage",
      "value": "enacted",
      "note": "Etapa legislativa: promulgada."
    },
    {
      "step": "effective_date",
      "date": "2024-04-01",
      "origin": "literal",
      "quote": "This section shall become operative on April 1, 2024.",
      "raw": "operative on April 1, 2024",
      "rule_applied": null,
      "calendar_source": null,
      "verified": true,
      "source_doc_id": "D024",
      "note": "Fecha de vigencia indicada en el texto: \"This section shall become operative on April 1, 2024.\""
    },
    {
      "step": "status",
      "value": "in_force",
      "note": "Estado al 1 de octubre de 2026: vigente."
    }
  ],
  "confidence_breakdown": {
    "rule": {
      "value": 0.9,
      "reason": "Confianza de la extracción de la regla (cita textual y referencia validadas)."
    },
    "coverage": {
      "value": 0.72,
      "factors": [
        {
          "factor": 0.8,
          "reason": "Se usa el año de construcción en lugar de la fecha del Certificado de Ocupación."
        },
        {
          "factor": 0.9,
          "reason": "El resultado depende de la presunción de estatus especial."
        }
      ]
    },
    "geocoding": {
      "value": 1.0,
      "reason": "Geocodificador del Censo: coincidencia exacta."
    },
    "combined": 0.648,
    "needs_review": false
  },
  "provenance": {
    "doc_id": "D024",
    "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1947.12",
    "retrieved_at": "2026-10-01T22:35:00+00:00",
    "quoted_span": "Subject to subdivision (b), an owner of residential real property shall not, over the course of any 12-month period, increase the gross rental rate for a dwelling or a unit more than 5 percent plus the percentage change in the cost of living, or 10 percent, whichever is lower, of the lowest gross rental rate charged for that dwelling or unit at any time during the 12 months prior to the effective date of the increase.",
    "citation": "Cal. Civ. Code § 1947.12",
    "prompt_version": "a-0.4.0",
    "model": "claude-opus-5-5",
    "snapshot": "a-0.4.0",
    "supporting_quotes": [
      {
        "doc_id": "D040",
        "role": "merged",
        "quoted_span": "A\nnnual rent increases are limited to no more than 5% plus the percentage change in the cost of living for the region in which the property is located, or 10% whichever is lower)"
      },
      {
        "doc_id": "D040",
        "role": "administrative",
        "quoted_span": "Effective August 1, 2024 to July 31, 2025, the maximum allowable increase is\n8.9%"
      },
      {
        "doc_id": "D040",
        "role": "administrative",
        "quoted_span": "Previously, from August 1, 2023 to July 31, 2024 the maximum annual increase for units subject to AB 1482 was 8.8%"
      }
    ],
    "coverage_compiler": {
      "model": "claude-haiku-4-5",
      "prompt_version": "cx-0.4.0"
    },
    "human_review": []
  }
}
```

### `GET /timeline/{address_id}?from=YYYY-MM-DD&to=YYYY-MM-DD&lang=`
Dated changes in the rules that reach one address. Defaults: `from` = 2024-10-01 (24 months
before 2026-10-01), `to` = 2028-12-31. Candidate dates: every effective, enactment and sunset
date of the rules in the address's jurisdiction stack (corpus, manifest-attested and hour-16
rules), plus the days a building-age cutoff flips for this building. For each date `d` the
result of every rule at `d − 1` is compared with its result at `d` using the same engine as
`/lookup` (so each event matches `/lookup?as_of=` on both sides).

| Field | Meaning |
|---|---|
| `events` | sorted by date: `{date, team_rule_id, title, category, category_label, level, attested, before, after, before_label, after_label, status_line, date_origin (literal \| derived \| calendar_default), conflict_flag, conflict_note, past}`; `past` = on or before 2026-10-01; `before` / `after` also `omitted` (no longer / not yet covered) |
| `by_year` | the same events grouped by year |
| `next_change` | first event after 2026-10-01 (null if none) |
| `pending` | pending bills that would cover the address — no date: "pending bill, not law" / "sin fecha: proyecto de ley, no es ley" |
| `from`, `to`, `reference_date`, `count`, `lang`, `disclaimer` | |

Errors: `422` for a bad date or `from` after `to`; `404` for an unknown address.

**Example — `GET /timeline/A0489?lang=en` (Hoboken, real response):**

```json
{
  "address": {
    "address_id": "A0489",
    "street": "204 GRAND ST",
    "postal_city": "Hoboken",
    "state": "NJ",
    "city": "Hoboken, NJ",
    "dataset_city": "Hoboken, NJ"
  },
  "from": "2024-10-01",
  "to": "2028-12-31",
  "reference_date": "2026-10-01",
  "lang": "en",
  "disclaimer": "Not legal advice. This prototype summarizes public housing law for information only; check the cited source and consult a qualified professional before acting.",
  "events": [
    {
      "date": "2025-07-01",
      "team_rule_id": "HOB-ALG-A1",
      "title": "Hoboken, NJ: algorithmic rent setting law named by the starter pack (text not in corpus)",
      "category": "algorithmic_rent_setting",
      "category_label": "ALGORITHMIC",
      "level": "city",
      "attested": true,
      "before": "not_yet_effective",
      "after": "applies",
      "before_label": "not yet in force",
      "after_label": "applies",
      "status_line": "In force since 2025-07-01",
      "date_origin": "literal",
      "conflict_flag": true,
      "conflict_note": "Possible preemption by NJ-ALG-01 once effective (change_tests conflict_with; participant guide §9); possible preemption conflict with NJ-ALG-01, flagged for human review",
      "past": true
    },
    {
      "date": "2026-01-20",
      "team_rule_id": "NJ-FEE-01",
      "title": "Residential rental property application fee not to exceed $50",
      "category": "application_screening_fees",
      "category_label": "SCREENING FEE",
      "level": "state",
      "attested": false,
      "before": "pending",
      "after": "not_yet_effective",
      "before_label": "pending bill",
      "after_label": "not yet in force",
      "status_line": "Not in force yet — takes effect 2026-05-01",
      "date_origin": "literal",
      "conflict_flag": false,
      "conflict_note": null,
      "past": true
    },
    {
      "date": "2026-05-01",
      "team_rule_id": "NJ-FEE-01",
      "title": "Residential rental property application fee not to exceed $50",
      "category": "application_screening_fees",
      "category_label": "SCREENING FEE",
      "level": "state",
      "attested": false,
      "before": "not_yet_effective",
      "after": "applies",
      "before_label": "not yet in force",
      "after_label": "applies",
      "status_line": "In force since 2026-05-01",
      "date_origin": "derived",
      "conflict_flag": false,
      "conflict_note": null,
      "past": true
    },
    {
      "date": "2026-07-20",
      "team_rule_id": "NJ-ALG-01",
      "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
      "category": "algorithmic_rent_setting",
      "category_label": "ALGORITHMIC",
      "level": "state",
      "attested": false,
      "before": "pending",
      "after": "not_yet_effective",
      "before_label": "pending bill",
      "after_label": "not yet in force",
      "status_line": "Not in force yet — takes effect 2027-07-01",
      "date_origin": "literal",
      "conflict_flag": true,
      "conflict_note": "possible preemption conflict with the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), flagged for human review",
      "past": true
    },
    {
      "date": "2027-07-01",
      "team_rule_id": "NJ-ALG-01",
      "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
      "category": "algorithmic_rent_setting",
      "category_label": "ALGORITHMIC",
      "level": "state",
      "attested": false,
      "before": "not_yet_effective",
      "after": "applies",
      "before_label": "not yet in force",
      "after_label": "applies",
      "status_line": "In force since 2027-07-01",
      "date_origin": "derived",
      "conflict_flag": true,
      "conflict_note": "possible preemption conflict with the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), flagged for human review",
      "past": false
    }
  ],
  "by_year": {
    "2025": [
      {
        "date": "2025-07-01",
        "team_rule_id": "HOB-ALG-A1",
        "title": "Hoboken, NJ: algorithmic rent setting law named by the starter pack (text not in corpus)",
        "category": "algorithmic_rent_setting",
        "category_label": "ALGORITHMIC",
        "level": "city",
        "attested": true,
        "before": "not_yet_effective",
        "after": "applies",
        "before_label": "not yet in force",
        "after_label": "applies",
        "status_line": "In force since 2025-07-01",
        "date_origin": "literal",
        "conflict_flag": true,
        "conflict_note": "Possible preemption by NJ-ALG-01 once effective (change_tests conflict_with; participant guide §9); possible preemption conflict with NJ-ALG-01, flagged for human review",
        "past": true
      }
    ],
    "2026": [
      {
        "date": "2026-01-20",
        "team_rule_id": "NJ-FEE-01",
        "title": "Residential rental property application fee not to exceed $50",
        "category": "application_screening_fees",
        "category_label": "SCREENING FEE",
        "level": "state",
        "attested": false,
        "before": "pending",
        "after": "not_yet_effective",
        "before_label": "pending bill",
        "after_label": "not yet in force",
        "status_line": "Not in force yet — takes effect 2026-05-01",
        "date_origin": "literal",
        "conflict_flag": false,
        "conflict_note": null,
        "past": true
      },
      {
        "date": "2026-05-01",
        "team_rule_id": "NJ-FEE-01",
        "title": "Residential rental property application fee not to exceed $50",
        "category": "application_screening_fees",
        "category_label": "SCREENING FEE",
        "level": "state",
        "attested": false,
        "before": "not_yet_effective",
        "after": "applies",
        "before_label": "not yet in force",
        "after_label": "applies",
        "status_line": "In force since 2026-05-01",
        "date_origin": "derived",
        "conflict_flag": false,
        "conflict_note": null,
        "past": true
      },
      {
        "date": "2026-07-20",
        "team_rule_id": "NJ-ALG-01",
        "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
        "category": "algorithmic_rent_setting",
        "category_label": "ALGORITHMIC",
        "level": "state",
        "attested": false,
        "before": "pending",
        "after": "not_yet_effective",
        "before_label": "pending bill",
        "after_label": "not yet in force",
        "status_line": "Not in force yet — takes effect 2027-07-01",
        "date_origin": "literal",
        "conflict_flag": true,
        "conflict_note": "possible preemption conflict with the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), flagged for human review",
        "past": true
      }
    ],
    "2027": [
      {
        "date": "2027-07-01",
        "team_rule_id": "NJ-ALG-01",
        "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
        "category": "algorithmic_rent_setting",
        "category_label": "ALGORITHMIC",
        "level": "state",
        "attested": false,
        "before": "not_yet_effective",
        "after": "applies",
        "before_label": "not yet in force",
        "after_label": "applies",
        "status_line": "In force since 2027-07-01",
        "date_origin": "derived",
        "conflict_flag": true,
        "conflict_note": "possible preemption conflict with the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), flagged for human review",
        "past": false
      }
    ]
  },
  "next_change": {
    "date": "2027-07-01",
    "team_rule_id": "NJ-ALG-01",
    "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
    "category": "algorithmic_rent_setting",
    "category_label": "ALGORITHMIC",
    "level": "state",
    "attested": false,
    "before": "not_yet_effective",
    "after": "applies",
    "before_label": "not yet in force",
    "after_label": "applies",
    "status_line": "In force since 2027-07-01",
    "date_origin": "derived",
    "conflict_flag": true,
    "conflict_note": "possible preemption conflict with the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), flagged for human review",
    "past": false
  },
  "pending": [],
  "count": 5
}
```

**Example — `GET /timeline/A0489?lang=es` (real response):**

```json
{
  "address": {
    "address_id": "A0489",
    "street": "204 GRAND ST",
    "postal_city": "Hoboken",
    "state": "NJ",
    "city": "Hoboken, NJ",
    "dataset_city": "Hoboken, NJ"
  },
  "from": "2024-10-01",
  "to": "2028-12-31",
  "reference_date": "2026-10-01",
  "lang": "es",
  "disclaimer": "No es asesoría legal. Este prototipo resume leyes públicas de vivienda solo con fines informativos; revise la fuente citada y consulte a un profesional calificado antes de actuar.",
  "events": [
    {
      "date": "2025-07-01",
      "team_rule_id": "HOB-ALG-A1",
      "title": "Hoboken, NJ: algorithmic rent setting law named by the starter pack (text not in corpus)",
      "category": "algorithmic_rent_setting",
      "category_label": "ALGORITMOS",
      "level": "city",
      "attested": true,
      "before": "not_yet_effective",
      "after": "applies",
      "before_label": "aún no vigente",
      "after_label": "aplica",
      "status_line": "Vigente desde el 2025-07-01",
      "date_origin": "literal",
      "conflict_flag": true,
      "conflict_note": "Possible preemption by NJ-ALG-01 once effective (change_tests conflict_with; participant guide §9); posible conflicto de preempción con NJ-ALG-01, marcado para revisión humana",
      "past": true
    },
    {
      "date": "2026-01-20",
      "team_rule_id": "NJ-FEE-01",
      "title": "Residential rental property application fee not to exceed $50",
      "category": "application_screening_fees",
      "category_label": "CUOTA DE EVALUACIÓN",
      "level": "state",
      "attested": false,
      "before": "pending",
      "after": "not_yet_effective",
      "before_label": "pendiente",
      "after_label": "aún no vigente",
      "status_line": "Aún no vigente — entra en vigor el 2026-05-01",
      "date_origin": "literal",
      "conflict_flag": false,
      "conflict_note": null,
      "past": true
    },
    {
      "date": "2026-05-01",
      "team_rule_id": "NJ-FEE-01",
      "title": "Residential rental property application fee not to exceed $50",
      "category": "application_screening_fees",
      "category_label": "CUOTA DE EVALUACIÓN",
      "level": "state",
      "attested": false,
      "before": "not_yet_effective",
      "after": "applies",
      "before_label": "aún no vigente",
      "after_label": "aplica",
      "status_line": "Vigente desde el 2026-05-01",
      "date_origin": "derived",
      "conflict_flag": false,
      "conflict_note": null,
      "past": true
    },
    {
      "date": "2026-07-20",
      "team_rule_id": "NJ-ALG-01",
      "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
      "category": "algorithmic_rent_setting",
      "category_label": "ALGORITMOS",
      "level": "state",
      "attested": false,
      "before": "pending",
      "after": "not_yet_effective",
      "before_label": "pendiente",
      "after_label": "aún no vigente",
      "status_line": "Aún no vigente — entra en vigor el 2027-07-01",
      "date_origin": "literal",
      "conflict_flag": true,
      "conflict_note": "posible conflicto de preempción con the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), marcado para revisión humana",
      "past": true
    },
    {
      "date": "2027-07-01",
      "team_rule_id": "NJ-ALG-01",
      "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
      "category": "algorithmic_rent_setting",
      "category_label": "ALGORITMOS",
      "level": "state",
      "attested": false,
      "before": "not_yet_effective",
      "after": "applies",
      "before_label": "aún no vigente",
      "after_label": "aplica",
      "status_line": "Vigente desde el 2027-07-01",
      "date_origin": "derived",
      "conflict_flag": true,
      "conflict_note": "posible conflicto de preempción con the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), marcado para revisión humana",
      "past": false
    }
  ],
  "by_year": {
    "2025": [
      {
        "date": "2025-07-01",
        "team_rule_id": "HOB-ALG-A1",
        "title": "Hoboken, NJ: algorithmic rent setting law named by the starter pack (text not in corpus)",
        "category": "algorithmic_rent_setting",
        "category_label": "ALGORITMOS",
        "level": "city",
        "attested": true,
        "before": "not_yet_effective",
        "after": "applies",
        "before_label": "aún no vigente",
        "after_label": "aplica",
        "status_line": "Vigente desde el 2025-07-01",
        "date_origin": "literal",
        "conflict_flag": true,
        "conflict_note": "Possible preemption by NJ-ALG-01 once effective (change_tests conflict_with; participant guide §9); posible conflicto de preempción con NJ-ALG-01, marcado para revisión humana",
        "past": true
      }
    ],
    "2026": [
      {
        "date": "2026-01-20",
        "team_rule_id": "NJ-FEE-01",
        "title": "Residential rental property application fee not to exceed $50",
        "category": "application_screening_fees",
        "category_label": "CUOTA DE EVALUACIÓN",
        "level": "state",
        "attested": false,
        "before": "pending",
        "after": "not_yet_effective",
        "before_label": "pendiente",
        "after_label": "aún no vigente",
        "status_line": "Aún no vigente — entra en vigor el 2026-05-01",
        "date_origin": "literal",
        "conflict_flag": false,
        "conflict_note": null,
        "past": true
      },
      {
        "date": "2026-05-01",
        "team_rule_id": "NJ-FEE-01",
        "title": "Residential rental property application fee not to exceed $50",
        "category": "application_screening_fees",
        "category_label": "CUOTA DE EVALUACIÓN",
        "level": "state",
        "attested": false,
        "before": "not_yet_effective",
        "after": "applies",
        "before_label": "aún no vigente",
        "after_label": "aplica",
        "status_line": "Vigente desde el 2026-05-01",
        "date_origin": "derived",
        "conflict_flag": false,
        "conflict_note": null,
        "past": true
      },
      {
        "date": "2026-07-20",
        "team_rule_id": "NJ-ALG-01",
        "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
        "category": "algorithmic_rent_setting",
        "category_label": "ALGORITMOS",
        "level": "state",
        "attested": false,
        "before": "pending",
        "after": "not_yet_effective",
        "before_label": "pendiente",
        "after_label": "aún no vigente",
        "status_line": "Aún no vigente — entra en vigor el 2027-07-01",
        "date_origin": "literal",
        "conflict_flag": true,
        "conflict_note": "posible conflicto de preempción con the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), marcado para revisión humana",
        "past": true
      }
    ],
    "2027": [
      {
        "date": "2027-07-01",
        "team_rule_id": "NJ-ALG-01",
        "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
        "category": "algorithmic_rent_setting",
        "category_label": "ALGORITMOS",
        "level": "state",
        "attested": false,
        "before": "not_yet_effective",
        "after": "applies",
        "before_label": "aún no vigente",
        "after_label": "aplica",
        "status_line": "Vigente desde el 2027-07-01",
        "date_origin": "derived",
        "conflict_flag": true,
        "conflict_note": "posible conflicto de preempción con the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), marcado para revisión humana",
        "past": false
      }
    ]
  },
  "next_change": {
    "date": "2027-07-01",
    "team_rule_id": "NJ-ALG-01",
    "title": "Forbidding the Algorithmic Inflation of Rent (FAIR) Act – prohibition on algorithmic rent coordination",
    "category": "algorithmic_rent_setting",
    "category_label": "ALGORITMOS",
    "level": "state",
    "attested": false,
    "before": "not_yet_effective",
    "after": "applies",
    "before_label": "aún no vigente",
    "after_label": "aplica",
    "status_line": "Vigente desde el 2027-07-01",
    "date_origin": "derived",
    "conflict_flag": true,
    "conflict_note": "posible conflicto de preempción con the Hoboken, NJ local ordinance (Hoboken Code ch. 158, Art. II), marcado para revisión humana",
    "past": false
  },
  "pending": [],
  "count": 5
}
```

### `GET /conflicts`
For human review: `module_a_conflicts`, `flagged_rules`, `preemption_pairs`,
`open_questions` (participant guide §9), `human_review` (the register of manual corrections).

### `GET /audit`
Provenance: extraction snapshot (prompt version, model, effort, date, cost, documents), rule
counts by status, coverage compiler and plain-language model/prompt, human-review entries
applied, geocoder settings.
