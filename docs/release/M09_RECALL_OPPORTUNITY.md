# RC1 recall opportunity and source decision

## Measured evidence

The comparable cohort is the 200-row stratified opportunity sample, SHA-256 `cee97e17af7e8b2d9dc9f5ee60548b9e186a11a2e485469446219ea10a1e38ed`.

| Path | Candidates | Accepted exact domains | Incremental exact-domain coverage | Wrong-company publications |
|---|---:|---:|---:|---:|
| Registry website only (M04 audited comparison) | 21 | 1 | baseline | 0 |
| Registry plus one bounded keyless `.no` candidate | 98 | 1 | 0 companies | 0 |
| Search provider | 0 | 0 | 0 | 0 |
| Jobs / public activity (M05) | — | 0 companies | 0 claims | 0 |

The keyless rule added 77 candidate domains, but none produced an additional exact-company domain. M04 recorded a zero-company accepted-domain gain over registry-only. M05 then found no job or public-activity claims in the cohort; its claim denominator is zero, so it provides no precision estimate. These observations do not prove population-wide zero coverage, but they do show no measured gain over the starter/registry-only baseline in the current release evidence.

## Audit corrections and limits

The original M00 fast opportunity artifact reported 9 exact identities among 16 fetched HTML homepages, but it omitted structured data and did not retain crawl-delay measurements. Its own method report calls the accepted count a conservative lower bound and not a precision benchmark. The corrected M03 utility and identity logic parse structured data, enforce subject-scoped proof and record/honor crawl delays. Use the M03/M04 results (1 accepted exact domain in 200 companies) for current coverage decisions; do not use the M00 count as an RC1 acceptance rate.

The M03/M04 live runs recorded 80 `ROBOTS_UNREACHABLE` candidates in the registry-plus-keyless comparison, 12 ambiguous cases, 2 blocked cases, 105 not available, and 1 available exact domain. Website transport failures remained fail closed. Search remains disabled because no reproducible, rights-approved provider/credential is configured. The bundled M08 four-company gold and synthetic adversarial tests are regression evidence, not population recall.

## Gate implication

The audited plan says RC1 should be submitted only when safe and when measured external coverage is materially above the starter/registry-only baseline. The current measurements show zero incremental accepted-domain coverage from the deterministic keyless path and zero job/activity claims. Therefore the first-submission gate is **HOLD** even if the live BRREG identity and release safety gates pass. No search/model/source expansion is authorized in M09, and no local score is substituted for an official evaluation.
