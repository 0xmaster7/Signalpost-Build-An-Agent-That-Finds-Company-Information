# M10 coverage investigation — offline evidence

Status: investigation complete; no new production source or extractor promoted. This report is based on the preserved RC1/post-Sol reports, checked-in code and fixtures, and official BRREG documentation. It is not a new live run or a replay of expired raw responses.

## Baseline

The corrected post-Sol 100-company release report recorded 283 account records and 1,875 candidate financial metrics, with zero canonical financial claims published because source unit/scale semantics were unavailable. Its runner did not retain raw account response bodies or separate missing, unsupported, and conflicting unit reasons. It recorded 51 website candidates: one accepted, three ambiguous, 46 `robots_unreachable`, and one source `unreachable`. It published no current jobs and no activity claims; the single accepted site had five undated and seven out-of-window activity candidates. These are cohort measurements, not population recall estimates. See [the preserved post-Sol live gate](POST_SOL_REMEDIATION_LIVE_GATE_2026-10-07.md) and [the recall opportunity report](M09_RECALL_OPPORTUNITY.md).

## Financial source contract

Production reads `GET https://data.brreg.no/regnskapsregisteret/regnskap/{organisation_number}` through `NetworkGateway`. The consumed response provides account figures and a `valuta` currency code. The official published schema for this key-figures API does not define a metric `enhet` or scale field; the API's account object schema is generic. Currency therefore cannot establish whether a numeric value is whole NOK or a scaled amount.

BRREG describes this key-figures API as a preview with no quality-of-service guarantees. The BRREG-owned API catalogue calls it a temporary research API that may be discontinued without notice; it covers key figures from the latest accepted account, ordinary presentation plans, and excludes consolidated figures. The repository was archived on 2025-11-18. This makes it an unstable source contract, but does not itself authorize a scale assumption.

The official current annual-account-copy API exposes PDF copies for the latest 15 years. I inspected one official sample URL (`936802176/2025`) using the read-only web viewer: it was served as a four-page PDF, but the viewer exposed no text lines, so this inspection did not establish actual metric/unit content. The documents may provide page-level statement evidence, but that remains unverified against an extractable report in this audit. The checked-in source policy currently allows only the normalized accounts endpoint and expressly excludes annual-copy/PDF fan-out. Official BRREG pages establish public availability of copies; the reviewed API docs do not establish that the existing NLOD dataset license and retention policy cover programmatic extraction and storage of facts from these PDF copies. No broader license or endpoint is inferred here.

**Decision:** retain fail-closed withholding for metrics without explicit unit/scale. Do not add PDF acquisition or use the starter POC in production until a source-rights/retention decision is approved and the exact PDF representation is evaluated. A future extractor can publish only values whose same-document evidence includes the account label, value, displayed unit/currency, reporting period, legal-entity or group scope, filing/version context, page number, and exact text/table locator. The raw amount and any named exact reversible normalization must both be retained. It must use the centralized gateway and PDF byte/MIME/magic checks. No model is necessary for this path.

The starter annual-report connector is not production-ready: it uses `urllib.request.urlopen` outside the gateway, derives source rights from a hard-coded `approved` label, accepts identity from URL plus a digit match in document text, has no statement/page locator on emitted observations, and optionally shells out to OCR. Its parsing routines may be used only as a test/reference corpus after those acquisition, attribution, identity, and evidence limitations are addressed.

## Website discovery and ownership

The preserved cohort's largest measurable loss is 46 candidates skipped because robots retrieval was unreachable. The audited policy requires ordinary website crawling to remain fail-closed and to record `ROBOTS_UNREACHABLE`; a transport error is not disallow evidence, but it is also not permission. No retries, alternate host, search result, browser, or proxy path is promoted to turn those skips into crawls. The report records no explicit robots disallow among this cohort's 23 robots outcomes; that does not change behavior for a future disallow.

The remaining measured cases were three ambiguous ownership outcomes, one source-unreachable candidate, and one accepted exact target site. Unknown website terms were recorded as unknown, not as a license. Existing production ownership assessment and adversarial tests require subject-scoped identity proof. Customer/supplier/footer references and incidental mentions do not prove ownership. No held-out fixture or preserved source response demonstrated an ownership false negative with a deterministic policy-supported fix; the six-company source-shaped gate is regression coverage, not evidence of a new live-domain gain.

## Jobs, activity, and profiles

The 100-company cohort had only one accepted website, limiting opportunities to observe job/activity extraction. No current job candidates were published. On the accepted site, five activity candidates lacked usable dates and seven were outside the configured window. Therefore the cohort cannot distinguish website reach from broader population source coverage, and it does not establish a job/activity recall rate. Production keeps current jobs tied to the exact accepted employer site, requires employer identity for structured job postings, honors explicit closed status and deadlines conservatively, and requires explicit dates plus target-scoped evidence for activity. No held-out structural defect demonstrating a safe extraction expansion was found. No ATS, external job source, or restricted social source is enabled.

## Model, browser, and additional-source evaluation

No paid or credentialed model/provider was used. The deterministic publication boundary remains authoritative; no model feature was required to address a demonstrated failure. Search remains disabled because the repository has no reproducible, rights-approved configured provider. Browser automation remains disabled: it would expand the request surface, and no measured JS-only high-value target plus permitted subrequest plan was evidenced. No additional org-number-keyed official source with a checked-in rights basis and reproducible offline/held-out delta was identified.

## M10 promotion result

No candidate component demonstrated a positive held-out coverage delta or a necessary production bug fix. Promoting one would require an unsupported source-scale assumption, a change to the approved rights/retention surface, or evidence not present in the preserved corpus. No production code, runtime configuration, provider, endpoint allowlist, or publication policy was changed in this investigation. Existing fail-closed controls remain the active fallback.

## Sources checked

- [BRREG account key-figures API OpenAPI specification](https://raw.githubusercontent.com/brreg/regnskapsregister-api/master/src/main/resources/specification/regnskapsregister.json) — record structure and fields; no metric unit/scale field.
- [BRREG key-figures API repository](https://github.com/brreg/regnskapsregister-api) — BRREG-owned description of the preview API and archive status.
- [BRREG API catalogue](https://github.com/brreg/openAPI/blob/master/specs/API-catalog.ttl) — temporary research API, limitations and NLOD catalog metadata.
- [Current BRREG annual-account-copy API documentation](https://data.brreg.no/regnskapsregisteret/regnskap/swagger-ui/swagger-ui/index.html?urls.primaryName=aarsregnskap) — PDF-copy endpoints and 15-year availability. An official four-page sample PDF was inspected, but its content was not extractable in the read-only viewer; no unit semantics are claimed from it.
- [BRREG information products](https://www.brreg.no/en/how-can-we-help-you/information-about-our-products/) — public account-copy information and document format limitations.
- [BRREG dataset and API license page](https://www.brreg.no/en/use-of-data-from-the-bronnoysund-register-centre/datasets-and-api/) — NLOD references for datasets and APIs; does not, in the reviewed text, resolve the specific PDF-copy acquisition/retention question recorded above.
