# Compiled coverage conditions and exemptions (review)

Model `claude-haiku-4-5`, prompt `cx-0.4.0`. Conditions are ANDed (rule covers the building), exemptions ORed (rule does not apply). Scope `building` is evaluated; `unit_or_tenancy` is a caveat; `other_law` is deferred to precedence (B3).

| rule | kind | scope | origin | original text | predicate | irreducible |
|---|---|---|---|---|---|---|
| BRK-ALG-P1 | condition | building | llm | residential dwelling units | `TRUE` |  |
| BRK-ALG-P1 | exemption | unit_or_tenancy | llm | Products or processes that publish aggregated, anonymous rental data without recommending rents, fees, occupancy rates or other lease terms are not coordinated pricing algorithms | `MISSING[product type and whether it makes recommendations]` | **yes** |
| BRK-ALG-P1 | exemption | unit_or_tenancy | llm | Products used to set rent or income limits under affordable housing guidelines of a local, state, or federal government or other political subdivision are excluded | `MISSING[product use for government affordable housing programs]` | **yes** |
| BRK-ALG-P1 | exemption | unit_or_tenancy | llm | Products or processes used for market research for project financing, appraisals, or research, testing, or training for software development are excluded | `MISSING[product use for market research, appraisals, or software development; whether competitor data is input to recommendations]` | **yes** |
| BRK-DEP-01 | condition | building | llm | residential rental | `TRUE` |  |
| BRK-DEP-01 | exemption | building | llm | Golden Duplex | `units == 2` |  |
| BRK-DEP-01 | exemption | unit_or_tenancy | code | Owner shares a kitchen or bath with the tenant and lived on the property when the tenancy started | `owner_occupied == true` |  |
| BRK-DEP-01 | exemption | unit_or_tenancy | llm | Tenancies started after Nov 7, 2018 on owner-occupied ADU properties | `(units <= 2 AND MISSING[whether property contains an ADU and is owner-occupied])` |  |
| BRK-DEP-01 | exemption | building | code | University rental units such as dormitories | `owner_type == "university"` |  |
| BRK-DEP-01 | exemption | building | code | Nonprofit cooperative | `owner_type in ["nonprofit cooperative"]` |  |
| BRK-FEE-01 | condition | building | llm | residential rental | `TRUE` |  |
| BRK-FEE-02 | condition | building | llm | residential rental | `TRUE` |  |
| BRK-FEE-02 | condition | review | llm | Applies to existing tenants and pre-existing households | `MISSING[whether the tenant or household is existing/pre-existing]` | **yes** |
| BRK-JUST-01 | condition | building | llm | fully covered residential rental units; partially covered residential rental units | `TRUE` |  |
| BRK-JUST-01 | exemption | unit_or_tenancy | llm | Units where the tenant shares kitchen or bath facilities with the landlord are exempt from the Rent Ordinance only if the landlord lived in a unit on the same property at the start of the tenancy. | `owner_occupied == true` |  |
| BRK-JUST-01 | exemption | building | llm | Golden Duplex: duplex owner-occupied on December 31, 1979, with an owner currently living in one unit | `(units == 2 AND owner_occupied == true AND co_date <= "1979-12-31")` |  |
| BRK-JUST-01 | exemption | unit_or_tenancy | code | Owner shares a kitchen or bath with the tenant and lived on the property when the tenancy started | `owner_occupied == true` |  |
| BRK-JUST-01 | exemption | unit_or_tenancy | llm | Tenancies started after Nov 7, 2018 on properties where one unit is an ADU and either unit is owner-occupied | `(units <= 2 AND owner_occupied == true)` |  |
| BRK-JUST-01 | exemption | building | code | University rental units such as dormitories | `owner_type == "university"` |  |
| BRK-JUST-01 | exemption | building | code | Nonprofit cooperative | `owner_type in ["nonprofit cooperative"]` |  |
| BRK-RENT-01 | condition | building | code | certificate_of_occupancy_on_or_before = 1980-06-30 | `co_date <= "1980-06-30"` |  |
| BRK-RENT-01 | condition | building | llm | residential rental | `TRUE` |  |
| BRK-RENT-01 | exemption | unit_or_tenancy | llm | Single-family home with a tenancy that began on or after January 1, 1996 (no rent control) | `(use.single_family == true AND MISSING[tenancy start date on or after 1996-01-01])` |  |
| BRK-RENT-01 | exemption | building | code | Most condominiums (no rent control) | `use.condo == true` |  |
| BRK-RENT-01 | exemption | building | llm | Units with Section 202 or Section 811 subsidies, or with Rental Supplement Program / Section 8 Loan Management Set Aside / Project-based Section 8 subsidies in a project with a HUD-insured or HUD-held mortgage | `MISSING[subsidy type and HUD mortgage status]` | **yes** |
| BRK-RENT-01 | exemption | building | llm | Golden Duplex: duplex owner-occupied on December 31, 1979, with an owner currently living in one unit | `(units == 2 AND owner_occupied == true AND MISSING[whether the property was owner-occupied on December 31, 1979])` |  |
| BRK-RENT-01 | exemption | unit_or_tenancy | code | Owner shares a kitchen or bath with the tenant and lived on the property when the tenancy started | `owner_occupied == true` |  |
| BRK-RENT-01 | exemption | unit_or_tenancy | llm | Tenancies started after Nov 7, 2018 on properties where one unit is an ADU and either unit is owner-occupied | `(units <= 2 AND owner_occupied == true AND MISSING[tenancy start date after 2018-11-07 and whether one unit is an ADU])` |  |
| BRK-RENT-01 | exemption | building | code | University rental units such as dormitories | `owner_type == "university"` |  |
| BRK-RENT-01 | exemption | building | code | Nonprofit cooperative | `owner_type in ["nonprofit cooperative"]` |  |
| BRK-RENT-02 | condition | building | llm | fully covered residential rental units | `TRUE` |  |
| BRK-RENT-02 | exemption | unit_or_tenancy | llm | Units where the tenant shares kitchen or bath facilities with the landlord are exempt from the Rent Ordinance only if the landlord lived in a unit on the same property at the start of the tenancy. | `MISSING[tenant shares kitchen or bath with landlord and landlord lived on property at start of tenancy]` | **yes** |
| BRK-RENT-02 | exemption | building | llm | Partially covered units (e.g., new construction with certificate of occupancy issued after 1980, most single-family homes and condominiums) have no rent ceiling. | `(co_date > "1980-12-31" OR use.single_family == true OR use.condo == true)` |  |
| BRK-RENT-02 | exemption | building | llm | Units with Section 202, Section 811, or HUD-insured/held mortgage projects with Rent Supplement, Section 8 Loan Management Set Aside, or Project-based Section 8 subsidies are only partially covered because federal/state law or regulation prohibits rent control. | `MISSING[property is Section 202, Section 811, or has HUD-insured/held mortgage with Rent Supplement, Section 8 LMSA, or Project-based Section 8]` | **yes** |
| BRK-SCRN-01 | condition | building | llm | residential rental | `TRUE` |  |
| BRK-SCRN-01 | exemption | building | code+llm | Owner-occupied properties of 1-3 units where an owner of record lives in one of the units as their primary residence | `(owner_occupied == true AND units <= 3)` |  |
| BRK-SCRN-01 | exemption | building | code | Owner-occupied exemption applies only to properties with between 1 and 3 units | `units <= 3` |  |
| BRK-SCRN-01 | exemption | unit_or_tenancy | llm | Lifetime sex offenders | `MISSING[whether the applicant or tenant is a lifetime sex offender]` | **yes** |
| BRK-SCRN-01 | exemption | building | code | Limited exemptions for public housing/Section 8 properties | `(owner_type == "government" OR use.section8 == true)` |  |
| BRK-SCRN-01 | exemption | unit_or_tenancy | llm | Units under a rental agreement allowing owners to move back to their home in accordance with BMC 13.76.130 A.9 | `MISSING[whether the unit is subject to an owner move-back rental agreement per BMC 13.76.130 A.9]` | **yes** |
| BRK-SCRN-01 | exemption | unit_or_tenancy | llm | Units occupied by existing tenant(s) seeking to sublet or add/replace roommates | `MISSING[whether the unit is occupied by an existing tenant seeking to sublet or add/replace roommates]` | **yes** |
| CA-ALG-01 | exemption | other_law | code | "Person" does not include the end consumer of a product or service. | `owner_type in ["end consumer"]` |  |
| CA-DEP-01 | condition | building | llm | residential rental | `TRUE` |  |
| CA-DEP-01 | exemption | building | code+llm | Landlords who own only two rental properties with no more than four residential units total, held by a natural person, family trust, or LLC whose members are all natural persons, may charge up to two months' rent | `(owner_type in ["natural person", "family trust", "LLC with all natural-person members"] AND units <= 4)` |  |
| CA-DEP-02 | condition | building | code | units_max = 4 | `units <= 4` |  |
| CA-DEP-02 | condition | building | llm | residential rental | `TRUE` |  |
| CA-DEP-02 | exemption | building | llm | Landlord must own only two rental properties | `MISSING[number of rental properties owned by the landlord]` | **yes** |
| CA-DEP-02 | exemption | building | llm | Ownership must be held by a natural person, family trust, or LLC where all members are natural persons | `(owner_type == "natural_person" OR owner_type == "family_trust" OR owner_type == "llc_natural_persons")` |  |
| CA-DEP-03 | condition | building | llm | residential rental property used as the tenant's dwelling | `TRUE` |  |
| CA-DEP-03 | exemption | unit_or_tenancy | code | Small landlords (a natural person or an LLC whose members are all natural persons, owning no more than two residential rental properties with no more than four rental units in total) may instead collect up to two months' rent, unless the tenant is a service member | `owner_type in ["natural person", "LLC with all natural-person members"]` |  |
| CA-DEP-03 | exemption | unit_or_tenancy | llm | Does not apply to security collected or demanded before July 1, 2024 | `MISSING[date security was collected or demanded]` | **yes** |
| CA-DEP-03 | exemption | unit_or_tenancy | llm | An advance payment of at least 6 months' rent is allowed on leases of 6 months or longer | `MISSING[lease term length and advance payment amount]` | **yes** |
| CA-DEP-03 | exemption | unit_or_tenancy | llm | Mutually agreed fees for alterations the tenant requests are allowed | `MISSING[whether fees are for tenant-requested alterations and are mutually agreed]` | **yes** |
| CA-DEP-03 | exemption | unit_or_tenancy | llm | An advance payment of at least six months' rent is allowed if the lease term is six months or longer | `MISSING[lease term length and advance payment amount]` | **yes** |
| CA-DEP-03 | exemption | unit_or_tenancy | llm | Agreed fees for alterations the tenant requests are not prohibited | `MISSING[whether fees are for tenant-requested alterations and are agreed]` | **yes** |
| CA-DEP-04 | condition | building | llm | residential rental property used as the tenant's dwelling | `TRUE` |  |
| CA-DEP-04 | condition | review | llm | Applies only to tenants who are service members, as defined in Military and Veterans Code Section 400. | `MISSING[tenant status as a service member]` | **yes** |
| CA-DEP-05 | condition | building | llm | residential rental property used as the tenant's dwelling | `TRUE` |  |
| CA-DEP-05 | exemption | unit_or_tenancy | llm | Supporting documents are not required if deductions for repairs and cleaning total $125 or less | `MISSING[whether deductions for repairs and cleaning total $125 or less]` | **yes** |
| CA-DEP-05 | exemption | unit_or_tenancy | llm | Supporting documents are not required if the tenant validly waived them | `MISSING[whether the tenant validly waived supporting documents]` | **yes** |
| CA-DEP-06 | condition | building | llm | residential rental property used as the tenant's dwelling | `TRUE` |  |
| CA-DEP-06 | condition | building | human_review | The landlord must own no more than two residential rental properties with no more than four dwelling units offered for rent in total. | `units <= 4` |  |
| CA-DEP-06 | exemption | unit_or_tenancy | llm | Does not apply if the prospective tenant is a service member | `MISSING[whether the prospective tenant is a service member]` | **yes** |
| CA-DEP-06 | exemption | unit_or_tenancy | llm | Does not apply to security collected before July 1, 2024 | `MISSING[date the security deposit was collected]` | **yes** |
| CA-FEE-01 | condition | building | llm | residential rental | `TRUE` |  |
| CA-FEE-01 | exemption | unit_or_tenancy | llm | Applies to owners of residential rental property and their agents, and to applicants, including guarantors and cosigners. | `MISSING[whether the party is an owner, agent, applicant, guarantor, or cosigner]` | **yes** |
| CA-FEE-02 | condition | review | llm | The maximum screening fee for 2026 is $68.96. | `MISSING[whether the fee charged is within the annual statutory maximum]` | **yes** |
| CA-JUST-01 | condition | building | llm | residential rental | `TRUE` |  |
| CA-JUST-01 | exemption | building | code+llm | Single-family homes and condominiums not owned by a real estate trust, corporation, or LLC with at least one corporate member, with written notice to tenant | `(owner_type in ["not real estate trust", "not corporation", "not LLC with corporate member"] AND (use.single_family == true OR use.condo == true))` |  |
| CA-JUST-02 | condition | building | code | building_age_min_years = 15 | `building_age >= 15` |  |
| CA-JUST-02 | condition | building | llm | residential real property | `TRUE` |  |
| CA-JUST-02 | exemption | building | code | Transient and tourist hotel occupancy; housing in nonprofit hospitals, religious facilities, extended care facilities, licensed residential care facilities for the elderly, adult residential facilities; dormitories owned and operated by higher education institutions or K-12 schools | `(use_class == "hotel_transient" OR use_class == "hospital" OR use_class == "religious_facility" OR use_class == "care_facility" OR use_class == "care_facility" OR use_class == "care_facility" OR use_class == "dormitory")` |  |
| CA-JUST-02 | exemption | unit_or_tenancy | code | Tenant shares bathroom or kitchen facilities with an owner who maintains their principal residence at the property | `owner_occupied == true` |  |
| CA-JUST-02 | exemption | building | code+llm | Single-family owner-occupied residence where the owner-occupant rents no more than two units or bedrooms (including ADU/JADU), or a mobilehome | `(owner_occupied == true AND ((use.single_family == true AND units <= 2) OR use_class == "mobilehome"))` |  |
| CA-JUST-02 | exemption | building | code | Duplex (two units in a single structure) where the owner occupied one unit as principal residence at the start of the tenancy and continues to do so, and neither unit is an ADU/JADU | `units <= 2` |  |
| CA-JUST-02 | exemption | building | code+llm | Separately alienable property (e.g., single-family home or condo) not owned by a REIT, a corporation, an LLC with at least one corporate member, or mobilehome park management, where tenants received the required written exemption notice | `(owner_type in ["natural person", "non-corporate owner"] AND (use.single_family == true OR use.condo == true))` |  |
| CA-JUST-02 | exemption | building | code | Deed-restricted or regulatory-restricted affordable housing for very low, low, or moderate income households, or housing under an affordable housing subsidy agreement | `use.affordable == true` |  |
| CA-JUST-02 | exemption | other_law | llm | Property subject to a local just cause ordinance adopted on or before September 1, 2019, or a more protective one adopted or amended after that date | `MISSING[property is subject to a qualifying local just cause ordinance]` | **yes** |
| CA-JUST-02 | exemption | building | llm | Homeowner of a mobilehome as defined in Section 798.9 | `(use_class == "mobilehome" AND units == 1)` |  |
| CA-JUST-02 | exemption | building | llm | Housing with a certificate of occupancy issued within 15 years (except mobilehomes) | `(building_age < 15 AND use_class != "mobilehome")` |  |
| CA-JUST-03 | condition | building | llm | residential units demolished for new construction | `TRUE` |  |
| CA-JUST-03 | condition | review | llm | Only lower-income households (80% AMI or below). | `MISSING[household income relative to area median income (AMI)]` | **yes** |
| CA-RENT-01 | condition | building | code | building_age_min_years = 15 | `building_age >= 15` |  |
| CA-RENT-01 | condition | building | llm | residential real property | `TRUE` |  |
| CA-RENT-01 | exemption | building | code | Housing deed- or regulatory-restricted as affordable housing for very low, low, or moderate income persons, or subject to an affordable housing subsidy agreement | `(use.affordable == true OR use.affordable == true)` |  |
| CA-RENT-01 | exemption | building | code | Dormitories owned and operated by an institution of higher education or a K-12 school | `use_class == "dormitory"` |  |
| CA-RENT-01 | exemption | other_law | llm | Housing subject to local rent or price control under Chapter 2.7 that restricts annual increases to less than subdivision (a) | `MISSING[subject to stricter local rent control]` |  |
| CA-RENT-01 | exemption | building | llm | Housing issued a certificate of occupancy within the previous 15 years, unless it is a mobilehome | `(building_age < 15 AND NOT use_class == "mobilehome")` |  |
| CA-RENT-01 | exemption | unit_or_tenancy | code | Residential property alienable separate from any other dwelling unit (including mobilehome) where owner is not a REIT, corporation, LLC with a corporate member, or mobilehome park management, and tenants received the required written exemption notice | `owner_type in ["individual or entity other than REIT, corporation, LLC with corporate member, or mobilehome park management (separately alienable unit, with notice)"]` |  |
| CA-RENT-01 | exemption | building | code+llm | Two-unit property in a single structure where the owner occupied one unit as principal residence at the beginning of the tenancy and continues in occupancy, and neither unit is an ADU or JADU | `(owner_occupied == true AND units == 2)` |  |
| CA-RENT-01 | exemption | building | llm | Homeowner of a mobilehome, as defined in Section 798.9 | `use_class == "mobilehome"` |  |
| CA-RENT-01 | exemption | building | llm | Units constructed within the last 15 years (rolling) | `building_age < 15` |  |
| CA-RENT-01 | exemption | building | llm | Units restricted by deed, regulatory restriction or recorded document limiting affordability to low or moderate-income households | `use.affordable == true` |  |
| CA-RENT-01 | exemption | unit_or_tenancy | code+llm | Single-family homes and condominiums not owned by a real estate trust, corporation, or LLC with at least one corporate member, where the landlord gave written notice of exemption | `(owner_type in ["not real estate trust", "not corporation", "not LLC with corporate member"] AND (use.single_family == true OR use.condo == true))` |  |
| CA-RENT-01 | exemption | other_law | llm | Units already subject to the City's RSO | `MISSING[subject to Los Angeles RSO]` |  |
| CA-SCRN-01 | condition | building | llm | housing accommodation | `TRUE` |  |
| CA-SCRN-01 | exemption | unit_or_tenancy | llm | A written or oral inquiry about the level or source of income is not source-of-income discrimination | `MISSING[whether the landlord made only an inquiry vs. a discriminatory decision based on source of income]` | **yes** |
| CA-SCRN-01 | exemption | unit_or_tenancy | llm | Subdivision (o) does not limit an owner's ability to ask for information to verify employment, request landlord references, or verify identity | `MISSING[whether the landlord's request was for verification of employment, landlord references, or identity verification]` | **yes** |
| CA-SCRN-02 | exemption | building | code+llm | An owner who occupies the home and rents to one additional person may exclude applicants based on protected characteristics, but still may not publish discriminatory statements, notices, or advertisements. | `(owner_occupied == true AND units == 2)` |  |
| CAM-SCRN-01 | exemption | building | code+llm | 2-family dwellings when the owner lives there are exempt | `(owner_occupied == true AND units == 2)` |  |
| CAM-SCRN-01 | exemption | duplicate | llm | Exemption for 2-family dwellings when the owner lives there | `(units == 2 AND owner_occupied == true)` |  |
| JC-RENT-01 | condition | building | code | units_min = 5 | `units >= 5` |  |
| JC-RENT-01 | condition | review | llm | Other permitted exemptions exist under the ordinance but are not described on this page | `MISSING[other exemptions under the Jersey City Rent Control Ordinance]` | **yes** |
| JC-RENT-01 | exemption | building | code | All 1-4 unit properties are exempt from rent control | `units <= 4` |  |
| JC-RENT-01 | exemption | duplicate | llm | All 1-4 unit properties are exempt from rent control | `units <= 4` |  |
| LA-JUST-01 | condition | building | llm | residential rental | `TRUE` |  |
| LA-JUST-01 | condition | review | llm | Applies to a tenancy only once the tenant has lived in the unit at least six months or the original lease expired, whichever comes first | `MISSING[tenant tenure and lease expiration date]` | **yes** |
| LA-JUST-01 | exemption | other_law | llm | Units regulated by the City's Rent Stabilization Ordinance (RSO) are not covered by the JCO | `MISSING[whether unit is subject to RSO]` | **yes** |
| LA-JUST-01 | exemption | unit_or_tenancy | code | Transient hotels, licensed care facilities, fraternity or sorority houses, owner's roommate, certain cooperatives, some non-profit homeless facilities or short-term substance abuse treatment centers, and some HACLA or government-owned properties are excepted [owner's roommate] | `MISSING[owner's roommate]` | **yes** |
| LA-JUST-01 | exemption | building | code | Transient hotels, licensed care facilities, fraternity or sorority houses, owner's roommate, certain cooperatives, some non-profit homeless facilities or short-term substance abuse treatment centers, and some HACLA or government-owned properties are excepted | `(use_class == "hotel_transient" OR use_class == "care_facility" OR use_class == "dormitory" OR use.coop == true OR use_class == "shelter_transitional" OR (use_class == "hotel_transient" AND use_class == "care_facility") OR owner_type == "government")` |  |
| LA-JUST-01 | exemption | duplicate | llm | Transient hotels | `use_class == "hotel_transient"` |  |
| LA-JUST-01 | exemption | duplicate | llm | Licensed care facilities | `use_class == "care_facility"` |  |
| LA-JUST-01 | exemption | duplicate | llm | Fraternity or sorority houses | `MISSING[whether property is a fraternity or sorority house]` | **yes** |
| LA-JUST-01 | exemption | duplicate | llm | Owner's roommate | `MISSING[whether tenant shares kitchen or bathroom with owner]` | **yes** |
| LA-JUST-01 | exemption | building | llm | Cooperatives under certain circumstances | `MISSING[specific circumstances under which cooperative exemption applies]` | **yes** |
| LA-JUST-01 | exemption | building | llm | Some non-profit facilities for the homeless | `MISSING[whether property is a non-profit homeless facility]` | **yes** |
| LA-JUST-01 | exemption | duplicate | llm | Short-term substance abuse treatment centers | `MISSING[whether property is a short-term substance abuse treatment center]` | **yes** |
| LA-JUST-01 | exemption | duplicate | llm | Some HACLA or government-owned properties | `MISSING[whether property is owned by HACLA or government]` | **yes** |
| LA-JUST-02 | condition | building | llm | RSO rental units; JCO rental units | `TRUE` |  |
| LA-JUST-02 | condition | review | llm | FMR threshold depends on the bedroom size of the rental unit. | `MISSING[bedroom size of the unit and current FMR threshold for that size]` | **yes** |
| LA-JUST-03 | condition | building | code | certificate_of_occupancy_on_or_before = 1978-10-01 | `co_date <= "1978-10-01"` |  |
| LA-JUST-03 | condition | review | llm | Replacement units under LAMC Section 151.28 are also covered by the RSO | `MISSING[whether unit is a replacement unit under LAMC Section 151.28]` |  |
| LA-JUST-04 | condition | building | llm | residential rental (RSO units) | `TRUE` |  |
| LA-JUST-04 | condition | review | llm | Applies to units covered by the Rent Stabilization Ordinance | `MISSING[units subject to Los Angeles Rent Stabilization Ordinance]` |  |
| LA-JUST-05 | condition | building | llm | residential rental (JCO units) | `TRUE` |  |
| LA-JUST-05 | condition | review | llm | Applies to units covered by the Just Cause Ordinance. | `MISSING[whether units are subject to the Los Angeles Just Cause Ordinance]` |  |
| LA-JUST-06 | condition | building | llm | single-family dwelling (JCO) | `use.single_family == true` |  |
| LA-JUST-06 | exemption | building | llm | The owner does not own no more than four dwelling units plus one single-family home on a separate lot in L.A. | `MISSING[total number of dwelling units owned by the owner, and whether one is a single-family home on a separate lot in L.A.]` | **yes** |
| LA-RENT-01 | condition | building | code | certificate_of_occupancy_on_or_before = 1978-10-01 | `co_date <= "1978-10-01"` |  |
| LA-RENT-01 | condition | review | llm | RSO units: first built on or before October 1, 1978, plus replacement units under LAMC Section 151.28. | `MISSING[whether the unit is a replacement unit under LAMC Section 151.28]` |  |
| LA-RENT-02 | condition | building | code | certificate_of_occupancy_on_or_before = 1978-10-01 | `co_date <= "1978-10-01"` |  |
| LA-RENT-02 | condition | building | llm | apartment; condominium; townhome; duplex; two or more single-family dwellings on same parcel; hotel/motel/rooming/boarding house rooms occupied >30 days; residential units attached to commercial building; ADU; JADU; mobile homes; RVs in mobile home parks | `(use_class == "apartment_building" OR use.condo == true OR use_class == "hotel_transient" OR use.single_family == true OR use.mixed_use == true OR use_class == "mobilehome")` |  |
| LA-RENT-02 | condition | review | llm | Applies to rental properties first built on or before October 1, 1978, plus replacement units under LAMC Section 151.28 | `(co_date <= "1978-10-01" OR MISSING[replacement unit status under LAMC Section 151.28])` |  |
| LA-RENT-02 | exemption | building | code | Rent amount is not regulated for condominium and townhome tenancies that commenced after December 31, 1995 | `(use.condo == true OR use.condo == true)` |  |
| LA-RENT-02 | exemption | duplicate | llm | Rent amount not regulated for condominium and townhome tenancies that commenced after December 31, 1995 | `MISSING[tenancy commencement date]` | **yes** |
| LA-RENT-02 | exemption | unit_or_tenancy | llm | Landlords can apply for a Luxury Exemption based on rent charged on or before May 31, 1978 | `MISSING[historical rent amount charged on or before May 31, 1978]` | **yes** |
| LA-RENT-03 | condition | building | code | certificate_of_occupancy_on_or_before = 1978-10-01 | `co_date <= "1978-10-01"` |  |
| LA-RENT-03 | exemption | other_law | llm | Replacement units under LAMC Section 151.28 are covered by the RSO even if built after October 1, 1978 | `MISSING[whether the unit is a replacement unit under LAMC Section 151.28]` | **yes** |
| LA-RENT-04 | condition | building | code | certificate_of_occupancy_on_or_before = 1978-10-01 | `co_date <= "1978-10-01"` |  |
| LA-RENT-04 | condition | review | llm | Replacement units under LAMC Section 151.28 | `MISSING[whether the building contains replacement units under LAMC Section 151.28]` | **yes** |
| LA-RENT-05 | condition | building | llm | residential rental | `TRUE` |  |
| LA-RENT-05 | condition | review | llm | Applies to rental units subject to the City of Los Angeles RSO | `MISSING[whether units are subject to the Los Angeles Rent Stabilization Ordinance]` | **yes** |
| MA-DEP-01 | condition | building | llm | residential real property | `TRUE` |  |
| MA-DEP-01 | exemption | building | code | Leases, rentals, occupancies or tenancies of 100 days or less for a vacation or recreational purpose | `use_class == "hotel_transient"` |  |
| MA-DEP-01 | exemption | duplicate | llm | Vacation or recreational leases or rentals of 100 days or less. | `MISSING[whether the lease is a vacation or recreational rental of 100 days or less]` | **yes** |
| MA-FEE-01 | condition | building | llm | residential rental | `TRUE` |  |
| MA-FEE-01 | condition | review | llm | Applies to fees for finding dwelling accommodations or tenants through licensed brokers/salespersons. | `MISSING[whether a fee was charged by a licensed broker/salesperson and which party originally hired and contracted with the broker]` | **yes** |
| MA-FEE-02 | condition | building | llm | residential real property | `TRUE` |  |
| MA-FEE-02 | condition | review | llm | Covers payments to the landlord or to the landlord's agent. | `MISSING[Covers payments to the landlord or to the landlord's agent.]` |  |
| MA-FEE-02 | exemption | building | code | Leases, rentals, occupancies or tenancies of 100 days or less for a vacation or recreational purpose | `use_class == "hotel_transient"` |  |
| MA-FEE-02 | exemption | duplicate | llm | Vacation or recreational leases or rentals of 100 days or less. | `MISSING[whether the tenancy is a vacation or recreational rental of 100 days or less]` | **yes** |
| MA-JUST-F1 | condition | review | llm | Would apply in the city of Boston; scope not described. | `MISSING[property location]` | **yes** |
| MA-RENT-01 | exemption | other_law | code | Permitted rent control regulation may not apply to any rental unit owned by a person or entity owning less than ten rental units | `(units < 10 AND MISSING[owner's total rental units (portfolio)])` |  |
| MA-RENT-01 | exemption | other_law | llm | Permitted rent control regulation may not apply to any rental unit with a fair market rent exceeding $400 | `MISSING[fair market rent]` | **yes** |
| MA-RENT-F1 | condition | review | llm | Would apply in the city of Boston | `MISSING[city or location of the property]` |  |
| MA-SCRN-01 | condition | building | llm | rental accommodations | `TRUE` |  |
| NJ-ALG-01 | condition | building | llm | residential dwelling unit | `TRUE` |  |
| NJ-ALG-01 | exemption | building | code | Residential dwelling unit does not include inpatient medical care, licensed long-term care, or detention or correctional facilities | `(use_class == "hospital" OR use_class == "care_facility" OR use_class == "detention")` |  |
| NJ-ALG-01 | exemption | unit_or_tenancy | code | Coordinator does not include a government entity setting or limiting rents through affordability controls in accordance with law | `owner_type in ["government entity applying affordability controls"]` |  |
| NJ-ALG-01 | exemption | duplicate | llm | Residential dwelling units exclude inpatient medical care, licensed long-term care, and detention/correctional facilities | `(use_class == "hospital" OR use_class == "care_facility" OR use_class == "detention")` |  |
| NJ-ALG-01 | exemption | unit_or_tenancy | llm | Coordinating function excludes use of competitively sensitive information solely for research/statistical analysis/testing not used to set prices | `MISSING[information is used solely for research/statistical analysis/testing and not to set prices]` | **yes** |
| NJ-ALG-01 | exemption | unit_or_tenancy | llm | Coordinating function excludes free public rent estimates | `MISSING[rent estimates are free and public]` | **yes** |
| NJ-ALG-01 | exemption | unit_or_tenancy | llm | Coordinating function excludes real estate brokerage databases available on equal terms that do not set/recommend prices or collect sensitive info for that purpose | `MISSING[database is a real estate brokerage database available on equal terms without price-setting/recommendation or sensitive information collection]` | **yes** |
| NJ-ALG-01 | exemption | unit_or_tenancy | llm | Algorithmic device excludes non-AI spreadsheets requiring human analysis and databases that only query unprocessed data | `MISSING[device is a non-AI spreadsheet requiring human analysis or a database that only queries unprocessed data]` | **yes** |
| NJ-DEP-01 | condition | building | llm | residential rental; mobile homes | `TRUE` |  |
| NJ-DEP-01 | exemption | building | code+llm | Owner-occupied two- or three-family dwellings are exempt from the Security Deposit Law unless the tenant opts in | `(owner_occupied == true AND (units >= 2 AND units <= 3))` |  |
| NJ-DEP-01 | exemption | duplicate | llm | Owner-occupied two- or three-family dwellings are exempt from the Security Deposit Law unless the tenant opts in | `(units >= 2 AND units <= 3 AND owner_occupied == true)` |  |
| NJ-DEP-02 | condition | building | llm | residential rental; mobile homes | `TRUE` |  |
| NJ-DEP-02 | exemption | building | code+llm | Owner-occupied two- or three-family dwellings are exempt (unless the tenant opts in by written request) | `(owner_occupied == true AND (units >= 2 AND units <= 3))` |  |
| NJ-DEP-02 | exemption | building | code | Owner-occupied dwellings with three or fewer units | `units <= 3` |  |
| NJ-DEP-03 | condition | building | llm | residential rental | `TRUE` |  |
| NJ-DEP-03 | condition | review | llm | Applies to tenants terminating leases early as victims of domestic violence | `MISSING[whether the tenant is a domestic violence victim terminating under the Safe Housing Act]` |  |
| NJ-DEP-03 | exemption | building | code | Does not apply to transient or seasonal rentals | `(use_class == "hotel_transient" OR use_class == "hotel_transient")` |  |
| NJ-DEP-03 | exemption | duplicate | llm | Transient or seasonal rentals | `MISSING[whether the unit is a transient or seasonal rental]` |  |
| NJ-FEE-01 | condition | building | llm | residential rental property for dwelling purposes | `TRUE` |  |
| NJ-FEE-01 | exemption | building | code | Dwelling unit located in a one-family or two-family dwelling offered for rent | `units <= 2` |  |
| NJ-FEE-01 | exemption | unit_or_tenancy | code | Licensee of the New Jersey Real Estate Commission, unless the licensee is the landlord of the residential rental property | `owner_type in ["New Jersey Real Estate Commission licensee (non-landlord)"]` |  |
| NJ-FEE-01 | exemption | duplicate | llm | A dwelling unit in a one-family or two-family dwelling offered for rent | `units <= 2` |  |
| NJ-JUST-01 | condition | building | llm | residential rental; single-family homes; mobile homes; mobile home park land; apartments; rooming and boarding homes | `TRUE` |  |
| NJ-JUST-01 | exemption | building | code+llm | Two- or three-unit owner-occupied premises with two or fewer rental units may be exempt | `(owner_occupied == true AND (units <= 3 AND units >= 2))` |  |
| NJ-JUST-01 | exemption | building | code | Owner-occupied premises with three or fewer units | `units <= 3` |  |
| NJ-JUST-01 | exemption | building | code | Hotel, motel, or guest house rented to transient guests or seasonal tenants (unless occupant has no alternate residence and lives there continually) | `(use_class == "hotel_transient" OR use_class == "hotel_transient" OR use_class == "hotel_transient" OR use_class == "hotel_transient" OR use_class == "hotel_transient")` |  |
| NJ-JUST-01 | exemption | unit_or_tenancy | llm | Unit held in trust for a developmentally disabled immediate family member who permanently occupies it | `MISSING[whether the unit is held in trust for a developmentally disabled immediate family member who permanently occupies it]` | **yes** |
| NJ-JUST-02 | condition | building | llm | buildings converted to condominium, cooperative or fee simple ownership | `(use.condo == true OR use.coop == true)` |  |
| NJ-JUST-02 | condition | review | llm | Tenant must be 62+ before conversion recording, permanently disabled, or a qualifying disabled veteran, have lived in the building at least one year before conversion recording, and have family income not more than 3x county per capita income or $50,000, whichever is greater | `MISSING[tenant age, disability status, veteran status, tenancy start date, family income, county per capita income, conversion recording date]` | **yes** |
| NJ-RENT-01 | condition | building | llm | residential rental | `TRUE` |  |
| NJ-RENT-01 | condition | review | llm | Applies in context of eviction for nonpayment of rent increase under the Anti-Eviction Act. | `MISSING[coverage under New Jersey Anti-Eviction Act]` | **yes** |
| NJ-RENT-02 | condition | building | llm | buildings converted to condominium, cooperative or fee simple ownership | `MISSING[whether the building has been converted to fee simple ownership (not captured by available facts)]` | **yes** |
| NJ-RENT-02 | exemption | unit_or_tenancy | llm | Increases to cover new services or amenities are not prohibited | `MISSING[whether a rent increase covers new services or amenities (tenant/transaction-level determination, not a building fact)]` | **yes** |
| NJ-RENT-03 | condition | building | llm | newly constructed multiple dwellings | `(units >= 2 AND building_age <= 30)` |  |
| NJ-RENT-03 | exemption | review | llm | Exemption lasts 30 years from completion of construction. | `building_age <= 30` |  |
| NJ-SCRN-01 | exemption | building | code+llm | Rental of a single apartment or flat in a two-family dwelling where the other unit is occupied by the owner as his/her residence at the time of rental | `(owner_occupied == true AND units == 2)` |  |
| NJ-SCRN-01 | exemption | unit_or_tenancy | code | Preference given to persons of the same religion by a religious organization in the sale, lease or rental of real property | `owner_type in ["religious organization"]` |  |
| NJ-SCRN-01 | exemption | building | code | Rooms in an owner- or resident-occupied single home; residences exclusively for one sex | `((use.single_family == true AND owner_occupied == true) OR MISSING[use type: single-sex residence])` |  |
| NJ-SCRN-01 | exemption | building | llm | Age-restricted housing as to familial status | `use.elderly == true` |  |
| NJ-SCRN-01 | exemption | building | llm | Residences planned exclusively for one sex | `MISSING[whether the residence is exclusively designated for one sex]` | **yes** |
| NJ-SCRN-02 | condition | building | llm | residential rental | `TRUE` |  |
| NJ-SCRN-02 | exemption | building | code+llm | Dwelling units in owner-occupied premises of not more than four dwelling units are excluded from the definition of rental dwelling unit | `(owner_occupied == true AND units <= 4)` |  |
| NJ-SCRN-02 | exemption | unit_or_tenancy | llm | Methamphetamine manufacture or production on federally assisted housing premises and lifetime sex offender registration requirements are exempt from the screening restrictions at any stage | `MISSING[federally assisted housing status, nature of conviction (methamphetamine manufacture/production on federally assisted premises, lifetime sex offender registration requirement)]` | **yes** |
| SD-ALG-P1 | condition | building | llm | residential rental property | `TRUE` |  |
| SD-ALG-P1 | exemption | unit_or_tenancy | llm | Software or product that publishes reports on rental rates or occupancy levels from aggregated historical nonpublic competitor data more than 90 days old, or from public information, and does not recommend rates or occupancy levels for future leases or renewals, is not an algorithmic device. | `MISSING[software characteristics (aggregation of data >90 days old or public data; absence of recommendations for future leases/renewals)]` | **yes** |
| SD-ALG-P1 | exemption | unit_or_tenancy | llm | Software or product used to establish rental rates or income limits in accordance with local, state, or federal affordable housing program guidelines is not an algorithmic device. | `use.affordable == true` |  |
| SD-JUST-01 | condition | building | code | building_age_min_years = 15 | `building_age >= 15` |  |
| SD-JUST-01 | condition | building | llm | residential rental property | `TRUE` |  |
| SD-JUST-01 | exemption | building | code | Transient and tourist hotel occupancy; short-term residential occupancy | `(use_class == "hotel_transient" OR use_class == "hotel_transient")` |  |
| SD-JUST-01 | exemption | building | code | Deed- or agreement-restricted affordable housing, or subsidized affordable housing (Section 8 is not exempt) | `(use.affordable == true OR use.affordable == true)` |  |
| SD-JUST-01 | exemption | building | code | Mobilehomes subject to the Mobilehome Residency Law | `use_class == "mobilehome"` |  |
| SD-JUST-01 | exemption | building | code | Nonprofit hospital, religious facility, extended care facility, licensed residential care facility for the elderly, adult residential facility, nonprofit transitional housing | `(use_class == "hospital" OR use_class == "religious_facility" OR use_class == "care_facility" OR use_class == "care_facility" OR use_class == "care_facility" OR use_class == "shelter_transitional")` |  |
| SD-JUST-01 | exemption | building | code | Dormitories owned and operated by an institution of higher education or a K-12 institution | `use_class == "dormitory"` |  |
| SD-JUST-01 | exemption | unit_or_tenancy | code | Tenant shares bathroom or kitchen facilities with a landlord who maintains their principal residence at the property | `owner_occupied == true` |  |
| SD-JUST-01 | exemption | building | code+llm | Single-family residence occupied by the landlord as principal residence (renting no more than two bedrooms, two ADUs or two JADUs), including a mobilehome | `(owner_occupied == true AND (units == 1 OR (units <= 2 AND use.single_family == true)))` |  |
| SD-JUST-01 | exemption | building | code | Property with two dwelling units in a single structure where the landlord occupies one unit as principal residence from the start of the tenancy and continues to live there | `units == 2` |  |
| SD-JUST-01 | exemption | building | llm | Housing issued a certificate of occupancy within the previous 15 years, unless it is a mobilehome | `(building_age < 15 AND use_class != "mobilehome")` |  |
| SD-JUST-01 | exemption | unit_or_tenancy | code | Separately alienable residential rental property whose landlord is not a REIT, a corporation, an LLC with at least one corporate member, or mobilehome park management, and where tenants received the required written exemption notice | `owner_type in ["natural person", "other non-corporate owner"]` |  |
| SF-ALG-01 | condition | building | llm | residential | `TRUE` |  |
| SF-JUST-01 | condition | building | llm | residential rental | `TRUE` |  |
| SF-JUST-01 | condition | review | llm | Applies to rental units covered by the Rent Ordinance, including some tenancies exempt from rent increase limits: units with first Certificate of Occupancy after June 13, 1979, Costa-Hawkins-eligible tenancies, and tenancies with rent regulated by another government agency. | `MISSING[whether the unit is covered by the Rent Ordinance, has a CO after June 13, 1979, is Costa-Hawkins-eligible, or is regulated by another government agency]` |  |
| SF-JUST-01 | exemption | other_law | llm | Exemptions limited to specific circumstances within individual just causes (e.g., illegal-use cause excludes mere occupancy of an unwarranted unit or a single cured short-term rental violation); general exemptions from the just cause requirement are not stated in the document. | `MISSING[which specific circumstances within each just cause apply to this unit]` |  |
| SF-RENT-01 | condition | building | code | certificate_of_occupancy_on_or_before = 1979-06-13 | `co_date <= "1979-06-13"` |  |
| SF-RENT-01 | condition | building | llm | residential rental | `TRUE` |  |
| SF-RENT-01 | exemption | building | code | Newly constructed rental units that first obtained a Certificate of Occupancy after June 13, 1979 | `co_date > "1979-06-13"` |  |
| SF-RENT-01 | exemption | unit_or_tenancy | llm | Tenancies eligible for a rent increase under the Costa-Hawkins Rental Housing Act | `MISSING[Costa-Hawkins eligibility]` | **yes** |
| SF-RENT-01 | exemption | other_law | llm | Some tenancies where the rent is regulated by another government agency | `MISSING[rent regulated by another government agency]` | **yes** |
| SF-SCRN-01 | condition | building | llm | affordable housing | `use.affordable == true` |  |
| SF-SCRN-01 | condition | review | llm | Protects residents with arrest or conviction history in affordable housing decisions; the page gives no other coverage details. | `MISSING[whether the resident has arrest or conviction history and how it affects the decision]` | **yes** |
| SNA-JUST-02 | condition | building | code | building_age_min_years = 15 | `building_age >= 15` |  |
| SNA-JUST-02 | condition | building | llm | residential rental | `TRUE` |  |
| SNA-JUST-02 | condition | review | llm | Applies after 30 days of tenancy | `MISSING[days of tenancy for the specific tenant or lease]` | **yes** |
| SNA-JUST-02 | exemption | building | llm | Housing produced in the last 15 years is exempt | `building_age < 15` |  |
| SNA-JUST-02 | exemption | building | code | Deed-restricted affordable housing, hotel and transient occupancy, hospital and care facilities, dormitories, and other shared living quarters are exempt | `(use.affordable == true OR use_class == "hotel_transient" OR (use_class == "hospital" AND use_class == "care_facility") OR use_class == "dormitory" OR use_class == "dormitory")` |  |
| SNA-JUST-02 | exemption | duplicate | llm | Deed-restricted affordable housing is exempt | `use.affordable == true` |  |
| SNA-JUST-02 | exemption | duplicate | llm | Hotel and transient occupancy is exempt | `use_class == "hotel_transient"` |  |
| SNA-JUST-02 | exemption | duplicate | llm | Hospital and care facilities are exempt | `(use_class == "hospital" OR use_class == "care_facility")` |  |
| SNA-JUST-02 | exemption | duplicate | llm | Dormitories are exempt | `use_class == "dormitory"` |  |
| SNA-JUST-02 | exemption | duplicate | llm | Other shared living quarters are exempt | `MISSING[whether the unit is part of a shared living quarters arrangement]` | **yes** |
| SNA-RENT-01 | condition | building | llm | residential rental; mobile home spaces | `TRUE` |  |
| SNA-RENT-01 | exemption | building | llm | Residential buildings constructed after February 1, 1995 are exempt from the rent cap | `co_date > "1995-02-01"` |  |
| SNA-RENT-01 | exemption | building | llm | Mobile home spaces offered for rent after January 1, 1990 are exempt from the rent cap | `MISSING[date mobile home space was first offered for rent]` | **yes** |
