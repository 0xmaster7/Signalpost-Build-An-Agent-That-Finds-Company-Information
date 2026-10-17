# Signalpost — maximum verified coverage remediation, 2026-10-17

## A. Repository and scope

Starting checkpoint: `771e01722d3aa6f1d23686e4e9e846445dec1b02`, branch `codex/m12-final-sol-remediation`. The source checkpoint is the commit containing this report; resolve it with `git rev-parse HEAD` and require its exact-SHA GitHub Actions run. The preceding exact-SHA CI was [39033059408](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/39033059408).

All implementation and executions were on pancakes. No new live company-data requests, providers, credentials, paid services, source rights, UI design changes, evaluator envelope changes, licensing changes, visibility changes or submission. The historical 193/200 authorization is CLOSED; its unused seven requests were not reused. The 32 sealed original live evidence files still match their hashes.

Evidence: [scorecard](evidence/coverage-20261017/scorecard.json), [33 source-adjudicated statements](evidence/coverage-20261017/source-adjudication.json), [repeat acceptance](evidence/coverage-20261017/repeat-acceptance.json), [official documentation receipts](evidence/coverage-20261017/documentation-receipts.json). The full original-source replay, source receipts, scripts and logs remain outside Git at `/home/azureuser/projects/signalpost-coverage-remediation-20261017/`; the original live evidence remains untouched in its original directory. Raw response bodies are not added to the repository.

BRREG-derived statements: Source: Brønnøysund Register Centre (Brønnøysundregistrene), retrieved 2026-10-17, licensed under NLOD 2.0. This attribution concerns source data; the project's code licensing is unchanged.

## B. Financial coverage

Inspected all 62 preserved account records containing 1,465 numeric amount nodes, the current [BRREG OpenAPI](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs) (version 1.1.16), and BRREG's [archived reference project](https://github.com/brreg/regnskapsregister-api), including its mapper, XML numeric model, service, utility and older specification. Retrieved documentation is preserved on the VM with URL/time/size/SHA receipts; this was documentation research, not company acquisition.

The current specification exposes numeric amounts, currency, accounting period and company/group type, but no authoritative unit/scale statement was found. The archived code copies numeric values and does not establish a current, versioned whole-currency-versus-thousands contract. Currency alone cannot resolve scale. No financial normalization or withholding rule was relaxed: numeric coverage remains **0/20**, filing metadata **18/20, 434 claims, 62 records**. A BRREG statement/versioned contract binding these endpoint amounts to explicit units, or a separately approved source with explicit scale, is required before promotion. PDFs/OCR and new providers were not acquired.

## C. Website discovery and ownership

All ten historical BRREG candidates already reached the gateway. The root problem is not simply missing candidate mapping: only Tenden had sufficient accepted operator proof in the captured corpus. Manager sites, weak identity, unavailable contact pages, the Otra 403 and exhausted exploration remain distinct outcomes.

Implemented exact-duplicate candidate suppression; contact-page priority over repetitive about pages; redirect-final-URL tracking; child-route classification (careers under `/om-oss` now remains careers); word-boundary classification (`depresjon` is not press); and post-verification careers/news/products priority. A controlled two-request case now reaches exact typed contact proof where the baseline spent its second request on an unhelpful about page.

With direct careers **and** news links, optional child sitemap indexes are deferred to spend the bounded content pass on those surfaces. Sitemap-only discovery retains its existing fallback. **Tradeoff:** this favors first-family reach over archive depth; it can miss items found only in child indexes. It is not a promise of exhaustive crawling or a live recall gain. No new candidate provider or host permission was enabled.

The operator acceptance function and publication graph are unchanged. Mentions, customer/partner relationships, footer-only identity, unsupported trading names and group-domain inference do not become ownership proof. Resource/query binding and shared page-only scope remain enforced. Real saved-source accepted websites remain **1/20**.

## D. Company-linked profiles

Saved-source profile reach remains **1/20, three links**, without requesting the social platforms. Corrected a demonstrable citation defect: a profile supplied only by target-identified Organization `sameAs` now cites the structured property rather than a nonexistent HTML anchor. A controlled schema-only profile verifies the relationship and locator without a platform request. Directory or name-only matches and registry profile candidates remain unpromoted under the existing publication policy.

## E. Hiring

Job/activity extraction now recognizes canonical `http(s)://schema.org/` type URLs and exact same-document JSON-LD graph references. Conflicting, missing, cyclic or rival employer definitions do not establish target employment; unknown namespaces are rejected. Existing explicit employer, title, URL, date, status and deduplication rules still apply. No career page alone becomes a vacancy, and no missing status becomes open.

HTML returned by a declared feed is processed as HTML using the downloaded bytes, rather than discarded and downloaded again. Successful actual feeds are excluded from the page-fetch queue. An unusable smaller feed fetch does not suppress a legitimate larger HTML page fetch. Non-RSS/Atom document roots cannot supply feed activity.

Two controlled, explicitly synthetic cases recover a job and a dated announcement at unchanged three/four-request caps; the baseline published neither. Full production CLI/evaluator coverage includes the namespace/reference case. Actual preserved live hiring remains **0/20**: no supported current posting was recovered from those bytes. Tenden's `app.cvideo.no` and Enova's Jobbnorge destination are separate, unapproved ATS origins. Current ATS host/mode allowlists are empty. Their acquisition rights, public endpoint/tenant binding, reuse terms and any cost contract remain unverified; public links do not authorize collection. They were not fetched or activated.

## F. Dated activity and registered business descriptions

Dated-activity reach remains **0/20** in the real saved corpus. Generic legal advice, out-of-window/future items, undated recruitment text and mere target mentions are not converted to dated company events. Publication dates still require explicit supported source fields; retrieval and sitemap modification times remain insufficient.

A larger demonstrated extraction omission was in official entity responses: **all 20 contain `aktivitet`, and 13 contain `vedtektsfestetFormaal`; the baseline dropped both**. These are now `registered_business_activity` and `registered_purpose` claims in canonical `identity_brand`, family `business_description`. Complete source arrays are retained as one registered statement each: line wrapping does not inflate atomic activity counts. They are not current dated events, ownership evidence or financial metrics. Malformed/empty shapes and contact/identifier-bearing text are withheld, exact identity anchoring and ENK registration-address exclusion remain intact. Each claim cites the exact source array pointer, entity URL, response hash and source snapshot. Deterministic synthesis labels them as registered statements and joins only source text; no LLM or invented explanation is involved.

## G. Request and runtime performance

The identical corpus contains 143 preserved response receipts, 139 unique URLs and 5,489,952 saved bytes, including 62 accounts, 202 roles and 34 workplaces. Privacy-redacted support copies are identified as such; replay evidence hashes bind to the actual replayed bytes. Four five-company production CLI runs use the original configurations and cutoff, fresh state/checkpoints, actual scheduler/gateway/publication code, a captured-response transport, retained production pacing and a socket guard denying external connections. Uncaptured URLs raise an explicit offline error; no replacement 404/source content is invented.

| Measured replay | Before 771e017 | After |
|---|---:|---:|
| Output rows | 20 | 20 |
| Mock transport attempts | 151 | 149 |
| Uncaptured URL attempts, including retries | 9 | 13 |
| Sum of sequential wave wall times | 75.09 s | 73.90 s |
| Worker-active company p50 | 5.659 s | 5.690 s |
| Worker-active company p95, nearest rank | 12.347 s | 9.133 s |
| Process CPU | 13.005 s | 12.353 s |
| Peak RSS | 159,196 KiB | 156,864 KiB |
| Available claims | 2,676 | 2,712 |
| Available claims / mock attempt | 17.72 | 18.20 |

Worker time excludes queue/finalization. The p50 is slightly worse; the wall improvement is modest. Missing-capture outcomes differ as priorities change. These measurements do **not** establish real network speed, real request savings, recall, or official runtime; the historical measured live runtime remains 130.48 seconds, worker p50/p95 8.70/26.25 seconds and 193 total approved attempts including checks/refresh.

Two real budget defects were also fixed. First, multiple pinned-address attempts could occur inside one transport call/reservation. Each connection now consumes its own paced gateway retry, reservation and ledger entry; IPv4 is preferred, DNS/public-IP validation and TLS host binding remain. Default retry limits now bound address fallback, so an endpoint reachable only through a later address may be withheld rather than silently exceeding budget. Second, scheduled website requests now carry company context into the existing budget guard. Per-company caps apply to optional sources; concurrent scopes reset safely. Budget denials are not cached as shared-host robots policy, and in-flight work with different bounded company contexts is isolated. Source permissions, robots rules and global/per-host caps remain authoritative.

## H. Accuracy and provenance

Independent source interpretation reviewed the registered text for all 20 companies. All **33 new registered claims** match their preserved authoritative arrays and exact-company evidence; zero mismatches or unresolved new statements. The final 20 canonical envelopes validate through the publication graph and round-trip exactly to produced evaluator rows. All **2,676 prior available claim values and multiplicities** are preserved. Three additional description claims bind to already captured, distinct document metadata; they are not three new companies.

Tests cover rival/mixed employer IDs, conflicting/missing graph references, unknown namespaces, date boundaries, duplicate records, malformed and contact-bearing statements, ENK privacy, source caps, feed/HTML classification, physical address accounting, concurrent company fairness, shared-host robots and full evaluator output. The historical 2,670 registry-value matches, six website/profile checks and two unresolved municipality support-copy checks remain historical evidence, not a new population precision estimate. There is no defined real-world recall denominator or new official score.

## I. Coverage comparison

Company counts below use the same 20 identities. Historical numbers are the original live run, not a live run of this source commit.

| Information | Historical live / before replay | After saved-source replay | New live validation |
|---|---:|---:|---|
| Exact legal identity | 20/20 | 20/20 | Not authorized/performed |
| Industry or supported business description | 19/20 | 20/20 | Not performed |
| Registered business-activity statements | 0 published | 20/20; 20 claims | Not performed |
| Registered purpose statements | 0 published | 13/20; 13 claims | Not performed |
| Financial filing metadata | 18/20 | 18/20; 434 claims | Not performed |
| Numeric financial metrics | 0/20 | 0/20 | Not performed |
| Roles | 20/20 | 20/20; 1,654 claims | Not performed |
| Workplaces | 19/20 | 19/20; 215 claims | Not performed |
| Verified websites | 1/20 | 1/20 | Not performed |
| Company-linked owned profiles | 1/20 | 1/20; three links | Not performed |
| Current hiring / dated public activity | 0/20 / 0/20 | 0/20 / 0/20 | Not performed |

The useful gain is business-specific source text across the cohort, including the fund without an industry classification, not a claim of 20 newly covered official scoring families. Builderr's hidden checked fields/parser and resulting score remain unknown. The controlled hiring/activity recovery is separately labeled synthetic in the scorecard.

## J. Remaining opportunities and authorization

1. **Existing-provider live revalidation:** highest immediate feasibility, $0 paid APIs. Proposed five-company recheck: Lunner `912427730`, Modum Bad `970107592`, Tenden `959704996`, Otra Kraft `955007514`, Enova `983609155`; maximum **80 physical attempts total**, including robots, redirects, address retries and any independent checks; estimated 2–5 minutes, not guaranteed. Only existing entity/accounts/roles/subunits endpoints and registry-listed website origins, robots and bounded permitted same-site sitemap/feed/page links. Fresh state, central guard and request ledger, no PDFs/search/ATS/social collection or new provider. **Requires new explicit approval; nothing has started.**
2. **Financial unit contract:** potentially largest factual-depth gain (1,465 captured numeric nodes), small implementation only after authoritative, versioned scale proof. Cost/rights of any alternative are not presumed approved. Existing withholding remains.
3. **Exact-site ownership reach:** stronger contact-page acquisition and verified operator evidence could unlock website/profile/jobs/activity breadth. The saved corpus does not justify changing footer/operator or group-scope policy. New source or publication-policy expansion requires approval; no unsupported acceptance rule is proposed.
4. **ATS integration:** potential job reach after ownership is proven. `app.cvideo.no` / Jobbnorge need separate host, tenant/employer, rights, transport and cost decisions. Implementation and benefit are not established, and no new source is activated.

## K. Release evidence

Final local suite: **484 tests and 237 subtests passed**, one existing third-party pyRdfa UTC deprecation warning. Focused source/budget tests, M06 provenance gate and M08 gold passed. Five-company repeat from the new saved state retained eight registered statements with **zero changes**. Existing M07/M09/crash-resume/cardinality/financial/ownership/security/UI tests remain included in the full suite. The source export installed its locked dependencies in a fresh environment and launched the evaluator from `/tmp`, producing four fixture rows; final clean-clone route/process acceptance and all required release gates are also required in exact-SHA CI before release acceptance.

The UI, model and evaluator adapter source hashes match the starting checkpoint. Repository stays PRIVATE; no PR, merge, force-push, public release or competition submission. Engineering improvements are ready for bounded live revalidation once exact-SHA CI is green. Competitive external-source coverage remains limited and is not established by this offline replay.
