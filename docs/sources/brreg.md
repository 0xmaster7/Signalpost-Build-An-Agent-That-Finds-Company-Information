# BRREG structured sources and attribution

Reviewed 2026-10-03.

Production M02 uses the public Central Coordinating Register API at `data.brreg.no` for exact legal-entity lookup, roles, and subunits, plus the public Register of Company Accounts normalized endpoint. Requests use the M01 `NetworkGateway`; no starter-kit direct HTTP helper is called from production code.

The CCR API documentation states that its open data is offered under the Norwegian Licence for Open Government Data (NLOD) 2.0. BRREG's datasets and APIs page states the open-data datasets follow NLOD. Preserve source URL, retrieval time, response or source-row SHA-256, exact JSON pointer, extraction method, and the NLOD 2.0 rights marker with structured facts. Runtime response bodies are held only for the run/checkpoint and are not added as a persistent general-purpose cache by this milestone.

Robots handling follows audited plan §11.1 for ordinary crawling: an explicit disallow blocks, while a robots transport/server failure returns `ROBOTS_UNREACHABLE` and skips non-essential website crawling. The M02 structured API profile is narrowly limited in the gateway to documented BRREG API URL paths on `data.brreg.no`. It still blocks explicit robots disallows and oversized/challenge/unusable robots responses, and remains subject to the M01 security, rate, redirect, host allowlist, and request-ledger controls. Only transport failures and 5xx responses permit those structured API paths to proceed; arbitrary website requests cannot use this profile.

Use attribution in downstream product output equivalent to: “Source: Brønnøysund Register Centre (Brønnøysundregistrene), retrieved [date], licensed under NLOD 2.0.” Keep this attribution attached to BRREG-derived sections when the provisional evaluator adapter is replaced.

Sources:

- [BRREG Central Coordinating Register API documentation](https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html)
- [BRREG datasets, APIs, and NLOD licence statement](https://www.brreg.no/bruke-data-fra-bronnoysundregistrene/datasett-og-api/)
- [BRREG normalized annual-accounts API documentation](https://data.brreg.no/regnskapsregisteret/regnskap/swagger-ui/swagger-ui/index.html?urls.primaryName=aarsregnskap)
- [BRREG organisation-number specification](https://www.brreg.no/en/about-us-2/our-registers/about-the-central-coordinating-register-for-legal-entities-ccr/about-the-organisation-number/)

Only public role name, role, role dates, and an associated organisation number are normalized. Birth dates, national identifiers, private addresses, and other person-register fields are discarded. Entity/subunit/group relationships remain explicitly scoped and never change the requested legal-entity anchor.
