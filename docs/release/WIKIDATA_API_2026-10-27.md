# Wikidata API routing correction — 27 October 2026

Implemented only after both unchanged [100-employer baseline runs](LIVE_COMPARISON_2026-10-27.md) completed. The baseline measurements remain attached to source `455d97925b3bcd4e7c47a643da5e4328a8299f5d`; they do not measure this correction.

## Exact diagnosis

The old adapter requested `https://query.wikidata.org/sparql?query=<URL-encoded SELECT DISTINCT ... P2333 ... P856 ...>&format=json`. The crawler fetched **`https://query.wikidata.org/robots.txt`**, then evaluated `/sparql?query=...&format=json` against its rules. The actual default header was **`SignalpostBot/1.0 (+contact pending)`**, not the BRREG-specific User-Agent. A prior bounded probe recorded `robots_disallowed`. In the 100-company baseline the call did not reach that check: OCR exhausted its research window first.

## Correction and boundaries

- `wikidata_sparql_api` is a documented-API profile, not a general crawler exemption. It accepts only HTTPS `query.wikidata.org`, default/443 port, exact `/sparql`, purpose `wikidata_batch_candidates`, and exactly one nonempty `query` plus `format=json`. No credentials, fragments or additional/duplicate parameters. It checks the raw URL before canonicalization can remove fragments.
- The adapter sends `Signalpost/1.0 (company-research; https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/issues)`. This is a public project/contact URL, not an invented email address.
- This exact API request does not fetch or evaluate crawler robots. Ordinary company websites still enforce robots, including explicit disallows and failure states.
- Public-address/SSRF validation, allowlists, pacing, request/response limits, twelve-second adapter timeout, 429 handling and ledger accounting remain in the existing gateway. A changed redirect is rejected before a second request; there is no alternate-host, proxy-rotation or WAF/challenge workaround.
- At most 200 companies / 1,000 rows / 1 MiB are processed. P2333/P856 metadata remains candidate-only: it cannot publish ownership, social profiles, headcount or company-site content without the existing gate.
- Source-policy fingerprint changes invalidate incompatible old refresh artifacts rather than silently mixing policies.

References: [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy), [SPARQL service](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service), [query limits](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/query_limits). Endpoint availability is not guaranteed by a compliant request. No post-fix 100-company coverage claim is made.

## Verification

- Isolated candidate checkout: **564 tests and 237 subtests passed**, 218.13 seconds. One existing third-party pyRdfa UTC deprecation warning. Includes eight benchmark-comparator tests, endpoint-shape/redirect/SSRF/robots separation checks, unchanged NAV tests and the existing full regression suite.
- One bounded post-fix production-adapter call for the frozen 100 IDs returned **HTTP 200**, four website candidates for four companies, one physical request, and no crawler-robots request. [Probe receipt](evidence/live-comparison-20261027/wikidata-postfix-probe.json). These are candidates, not four verified websites or a repeated company benchmark.
- Financial/FTE parsing, page order, persistent OCR caching, bulk registry acquisition and scheduler allocation are not changed in this patch. Their next experiment should follow the baseline findings rather than mask them.
