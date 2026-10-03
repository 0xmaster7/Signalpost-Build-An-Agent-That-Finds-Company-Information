# Source-rights register

Reviewed 2026-10-03. Machine-readable policy: [`config/source_policy.yaml`](../config/source_policy.yaml).

| Source | Acquisition | Rights and attribution | Retention | M02 use |
|---|---|---|---|---|
| Brønnøysund Register Centre Central Coordinating Register API | Documented public GET endpoints for exact entity, roles, and subunits through `NetworkGateway`; enforce explicit robots rules and gateway limits | NLOD 2.0; attribute Brønnøysund Register Centre and retrieval date | Response content is run-scoped; preserve source URL, response hash, JSON pointer, method, retrieval time and source snapshot metadata | Legal identity, public business roles, workplaces/subunits |
| Brønnøysund Register Centre Register of Company Accounts normalized endpoint | Documented public GET by exact organisation number through `NetworkGateway`; no annual-copy/PDF fan-out | Official registry source; preserve the published source terms and add BRREG attribution | Same transient response handling and provenance as above | All normalized filing records and periods returned by the endpoint |

The audited plan's robots transport/server failure rule is for non-essential website crawling: skip that origin and record `ROBOTS_UNREACHABLE`. M02's documented structured BRREG API calls are governed separately as official API requests. They remain subject to explicit retrieved robots disallows, host/path allowlisting, SSRF checks, rate limits, redirects, request accounting, and source terms. On a robots transport reset or 5xx, only the exact documented `data.brreg.no` structured API paths may continue; ordinary website and page requests remain fail-closed with the distinct `robots_unreachable` outcome. Oversized or challenge/unusable robots responses fail closed for the API too. A transport reset is never recorded as an explicit disallow.

M02 excludes person birth dates, national identifiers, private addresses, private contact details, and unrelated personal profiles. ENK business and postal registration addresses are omitted because they may be an owner's home address. Role names, role, dates, and public business relationships may be retained. The frozen Builderr snapshot's specific licence, source URL, as-of date, and retention terms remain parameters until supplied; do not infer that snapshot's licence from BRREG's API licence.

Attribution text for BRREG-derived facts: “Source: Brønnøysund Register Centre (Brønnøysundregistrene), retrieved [date], licensed under NLOD 2.0.”
