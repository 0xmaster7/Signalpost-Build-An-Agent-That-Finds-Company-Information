# Final coverage improvement and submission acceptance — 17 October 2026

## Decision and scope

**NO-GO for an unconditional submission-ready claim.** Software remains runnable, but verified external coverage did not improve in this round. Organizer parser/handoff, public-artifact/access arrangements and owner contact remain unresolved. These are separate from passing engineering checks. No official score or qualification is claimed.

Baseline: 5de39259969bf94173ea9470c54996099605bb1b on codex/m12-final-sol-remediation, verified clean and equal to origin before work. The release keeps all production Python and accepted UI unchanged. Only dependency lock security updates and documentation/evidence are promoted. The final handoff supplies the immutable package SHA and exact-SHA CI; resolve this checkout with git rev-parse HEAD.

## Official resources and executable starter

Authoritative sources reviewed directly: [challenge](https://builderr.ai/challenges/signalpost), [brief](https://builderr.ai/starter-briefs/signalpost.md), [evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md), [source policy](https://builderr.ai/starter-briefs/signalpost-sources.md), [playbook](https://builderr.ai/starter-briefs/signalpost-agent-playbook.md), [learning guide](https://builderr.ai/starter-briefs/signalpost-learning-harness.md), [rules](https://builderr.ai/guidelines), and [linked basics](https://builderr.ai/start#agent-resources).

All five Markdown resources are byte-identical to the previous large-batch review; receipts include current URL, retrieval time, size and SHA-256. The challenge leaderboard is current, not reused as a score for Signalpost. Scoring remains 50 coverage, 30 precision/evidence, 12 synthesis, 8 UX; each external family weights company reach 70% and facts 30%. Qualification requires an official run and 65 points, and material wrong-company/fabricated-financial publication prevents an official run.

Downloaded the actual [starter archive](https://builderr.ai/signalpost-starter-kit.tar.gz), SHA-256 d48da9910ea7de07d2bf51ab265539a35fe07002a6c1ca5787df81316dfabbf6. Executed its saved refresh example: two expected changes, no false changes, idempotent repeat. Also executed scripts/run_competition_batch.py with two fictional registry-only rows, network sockets denied: two ordered envelopes, zero HTTP, successful validation.

The executable takes --organisations/--bulk and emits run_id/state/modules/profile. Its module states include complete, source_error and blocked_robots. Its OUTPUT_CONTRACT.md instead illustrates claims/evidence/changes with six availability states. Our launcher takes --input and emits the documented canonical six-state claim/evidence envelope. These are **confirmed interface differences**, not proof that Builderr requires the starter's particular executable schema. No adapter aliases were guessed.

The three npm check commands appear in the evaluation document, but neither downloaded starter nor this Python repository contains their package.json definitions. Their executable implementation and participant applicability are unverified; they were not falsely reported executed.

## Free-provider decisions

| Provider | Documentation/permission and reproducibility | Decision |
|---|---|---|
| [SearXNG](https://docs.searxng.org/dev/search_api.html) | Metasearch API; JSON depends on instance configuration. Software availability does not grant upstream engine automation rights. No approved reliable public instance or deployment exists here. | Not integrated: upstream rights, instance reliability/rate limits and self-hosting complexity unresolved. No instance benchmark. |
| [GDELT DOC](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Public news-discovery API with JSON; searches translated news, not a complete Norwegian company/domain index. Publisher access and exact article-subject proof remain separate. Current coverage/latency/rate behavior not benchmarked. | Not integrated: no demonstrated company coverage gain and no approved durable third-party article acquisition/publication contract. No company query made. |
| [Common Crawl](https://index.commoncrawl.org/) | Free known-URL index/archive; not general company-name discovery. [Terms](https://commoncrawl.org/terms-of-use) preserve underlying content restrictions. Historical captures do not establish current jobs or ownership. | Not integrated: weak fit for missing-domain discovery, archive freshness/rights work and rate-limited operations. No CDX/WARC benchmark. |
| [Marginalia](https://about.marginalia-search.com/article/api/) | Current API has a public development key with frequent rate limiting; free individual access is non-commercial CC-BY-NC-SA. Commercial terms differ. | Not integrated: no approved reproducible free commercial/evaluator arrangement; no API benchmark. |
| [Wikidata](https://www.wikidata.org/wiki/Wikidata:Data_access) | Structured data CC0; P2333 exact Norwegian organisation ID and P856 website can generate candidates. Scope qualifiers/multiple IDs/entities must abstain. Documented public service requires API etiquette. | Implemented and tested experimentally, then **rejected and excluded**: live robots explicitly disallows /sparql. No endpoint bypass or substitute API probe. |

No provider is enabled in the release. A live-approved experiment is not sufficient reason to promote an adapter that produces no supported gain. Optional-provider failure never dropped a company. The rejected adapter and its tests remain outside the repository as audit material, not hidden evaluator functionality.

## Coverage and company funnel

The [20-company funnel](evidence/final-coverage-20261017/company-funnel.json) gives each org/name, candidate/method, original robots/HTTP decision and downloaded pages, latest replay claim counts and missing-family reasons. It explicitly separates historical live diagnostics from later replay publication counts.

Historical funnel: all 20 identity anchors, ten registry website candidates, all ten reached the gateway; one verified website, three ambiguous, one HTTP 403, five verification-budget failures. Ten had no registry candidate. A discovered manager/parent page is not an owned subsidiary site.

Lunner lacked exact company-number operator proof in saved pages; contact bytes were not captured. Modum and Enova had branding/footer evidence but lacked permitted direct operator proof. Housing-manager pages do not prove the subject owns the manager domain. Otrakraft returned 403. Tenden alone passed and supplied three linked profiles. These are discovery, access, ownership and capture limitations; more parsing does not establish missing ownership evidence.

| Category | Starting 20-company saved replay | Current release, same evidence | New three-company live experiment |
|---|---:|---:|---:|
| Identity | 20/20; 340 claims | unchanged | 3/3; 54 claims |
| Registered activity/purpose | 20/20 activity; 13/20 purpose; 33 statements | unchanged | 3/3; 6 statements |
| Annual filing metadata | 18/20; 434 claims | unchanged | 3/3; 63 claims |
| Numeric financial values | 0/20 | unchanged | 0/3 |
| Roles | 20/20; 1,654 claims | unchanged | 3/3; 141 claims |
| Workplaces | 19/20; 215 claims | unchanged | 0/3 published; source responses retrieved, run-start cutoff withholding |
| Owned websites | 1/20; 6 claims including descriptions | unchanged | 0/3 |
| Company-linked profiles | 1/20; 3 claims | unchanged | 0/3 |
| Hiring | 0/20 | unchanged | 0/3 |
| Dated public activity | 0/20 | unchanged | 0/3 |

No new recall percentage or before/after live improvement is claimed. The preceding implementation already improved registered descriptions and retrieval efficiency; [its comparable replay](MAXIMUM_VERIFIED_COVERAGE_2026-10-17.md) remains historical evidence, not work relabelled as this round.

Financial limitation: 62 saved records contain 1,465 numeric nodes without authoritative scale. Currency/period/scope are insufficient to guess NOK versus thousands. Hiring/activity are constrained by missing verified owned source reach; a careers link is not a vacancy. Jobbnorge/CVideo adapters and PDFs remain disabled. Registered purpose is not dated news.

## New approved live experiment

User approved exactly three companies / 60 physical attempts / $0. Selection was sealed before requests: prefer official-universe rows without a website, then SHA256(seed + ':' + organisation_number), seed signalpost-free-discovery-v1, one per known employee band <20, 20–99, >=100, excluding 486 prior identifiers.

- 996501884 — RAKKERUNGAN BARNEHAGEDRIFT AS (12 employees in frozen universe).
- 979642296 — SPJELKAVIK HOTELLDRIFT AS (31).
- 950222905 — DRAMMEN PAPIR ENGROS AS (142).

Fresh state, production CLI/gateway/pacing/extraction/evaluator, no source mocks or cohort replacement. Research phase capped at 45 to reserve 15 of the authorized 60. **15 physical attempts consumed; 20 logical gateway calls; three ordered available terminal envelopes; $0 paid cost. Network phase is sealed closed.** No unused requests are being treated as a reusable testing allowance.

Central SQLite BEGIN IMMEDIATE reservations occur before each HTTPConnection.request, including redirects/retries/address attempts; HTTP outside gateway transport context is denied. Separate concurrent guard test: 75 synthetic reservations, exactly 60 accepted / 15 denied; sealed guard denied further attempts; zero HTTP. Initial self-test failed because system Python lacked dependencies; it was rerun successfully with the installed interpreter. The actual live process always used that interpreter and the active guard.

13 HTTP 200 responses and two transport failures, both BRREG robots attempts. Narrow documented structured-API outage exception applied to BRREG only. Wikidata robots returned 200 with explicit Disallow /sparql and /bigdata. No SPARQL query was sent; three logical discoveries stopped at policy. No new website was fetched, no paid/source expansion occurred.

Measured wall 11.6545 s, CPU 1.3721 s, peak RSS 87,344 KiB; 5 physical attempts/company. Official-foundation worker times 4.477–7.150 s; p50 5.108 s / nearest-rank p95 7.150 s (n=3, worker-active foundation time, not complete per-company latency). Published claim counts were 82, 82 and 100 (88/company on average); these are canonical claim atoms, not independently defined competition facts. HTTP transport failure rate was 2/15 (13.3%); all three logical Wikidata discoveries were policy-blocked. This is a three-company run with no website crawl, not evidence that 1,100 live companies fit an unpublished budget.

All 264 published registry claims were separately checked against preserved source bytes: 205 exact pointer-value matches; 17 explicit inactive flags, 17 typed holder relations, 12 joined person names, nine explicitly labelled record scopes and four address subsets. No production extraction functions generated this reference interpretation. No incorrect or unresolved value remained in that bounded review; no population precision/recall or completeness is inferred. Hash links retained; privacy-redacted support copies disclose raw-versus-saved hash differences. No confirmed wrong-company publication, unsupported numeric figure or new external fact.

Machine-readable [live result](evidence/final-coverage-20261017/discovery-live.json) and [physical ledger](evidence/final-coverage-20261017/discovery-http-ledger.json) are self-contained. Original responses remain private/run-scoped outside Git. An offline release replay using these same captured BRREG bytes preserved all 264 available values/dimensions under the same default run-start policy; [receipt](evidence/final-coverage-20261017/three-company-release-replay.json). Source sockets were denied. An explicit past-cutoff variant correctly withheld 60 claims and was not represented as a like-for-like baseline. Privacy-redacted source copies produce their own evidence hashes; source failures and absent capture were not replaced by invented data.

## Submission traceability

| Mandatory requirement / source | Implementation and proof | Result / remaining risk |
|---|---|---|
| Runtime unseen org batch; exactly one result — brief “Universe and run format”, evaluation “Output contract” | Input parser, ordered writer, CLI; current three-company live cardinality and independent subprocess acceptance | PASS repository contract; exact organizer parser BLOCKED |
| Seven sections and six explicit terminal states — brief “Required company envelope” | Canonical models/adapter, validated real output, failure/unknown/invalid fixtures | PASS structure; PARTIAL factual coverage |
| Correct identity, no invented financials — official-run checks | BRREG anchors, ownership gate, financial dimensions; 264 source-value checks plus retained adversarial regressions | PASS reviewed sample; population accuracy unproven |
| Sources, retrieval/reporting dates, snapshots — evaluation “Official-run checks” | Evidence IDs/hash/pointers and publication graph; source-byte review | PASS reviewed provenance; no invented effective dates |
| Idempotent refresh/prior evidence — same | Previous-state pair, checkpoint fingerprint, M07 and growing-batch acceptance | PASS controlled/stored evidence; no new live refresh in this experiment |
| Clean setup/pinned deps/one command — same, playbook “Common traps” | README + launcher + lockfile; clean exact-SHA clone/independent execution | Final receipt and exact-SHA CI required before handoff |
| 100-company result or report — brief “What to submit” | Self-contained historical report/index, original SHA and conditions | PASS artifact present; final-version 100-company live run NOT performed |
| Public artifact / reviewer access — official-run checks and rules | Repository intentionally PRIVATE | BLOCKED owner authorization/access; private acceptance not assumed |
| Declared sources, secrets, safe URLs — official-run checks/source policy | Gateway/robots/SSRF/redirect/privacy rules, source manifests, bounded Git secret scan and dependency audit | PASS bounded checks after lock repair; not an exhaustive security guarantee |
| Models/APIs/licences/cost/run instructions — brief “Submit” | README, third-party notices, draft, cost $0, no research credentials | PASS declarations; own-code licensing remains owner decision |
| Contact and external submission — brief “Submit” | Unsent email with CONTACT_NAME / CONTACT_EMAIL | BLOCKED owner details and send authorization |
| Fixed official runtime/network/resource budget — evaluation “Official run requirements” | Configurable bounded defaults, offline 1,100 evidence, independent failure handling | BLOCKED exact supplied limits unavailable; no live runtime guarantee |
| Find/compare/verify desktop/mobile — scoring UX | Actual saved-data dashboard browser interaction, route/XSS smoke | PASS observed workflows; no UI redesign |
| Official eligibility/65 score — brief scoring | Requires organizer official run | UNVERIFIED; no local test qualifies the entry |

## Dependency and exposure remediation

OSV audit found eleven known advisories in locked pypdf 6.16.1 and urllib3 2.7.0. Only those two lock entries/artifacts were updated to pypdf 6.19.0 and urllib3 2.8.0, confirmed against [pypdf maintainer advisory](https://github.com/py-pdf/pypdf/security/advisories/GHSA-v247-6f48-mgcj) and [urllib3 maintainer advisory](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77). No new acquisition or dependency service was added. The default/m08 installed environment was re-audited with OSV: zero known advisories remain. Uninstalled crawler/sentiment extras are not claimed audited. The first PyPI-service audit timed out; the successful OSV audit is the recorded result.

A bounded Git scan checked all 475 reachable blob objects for six high-confidence credential patterns and tracked paths for key/env/raw-body/database names: no matches. No secret values were printed or uploaded. This does not prove absence of every possible private datum. No raw live bodies or rejected experimental provider code is committed. Existing public fixture identities and source-value report contents remain clearly identified.

## Organizer clarification

“Will you consume our declared launcher and documented six-state claim/evidence JSONL, or require the starter executable's --organisations/--bulk interface and state/modules/profile structure? Please provide the parser/schema, frozen-registry format/metadata, cutoff, prior-state handoff and numeric network/runtime/resource budget. Are the three npm checks organizer-side only; if entrants must run them, where is the package containing their definitions?”

The public materials do not establish those details. Do not advertise verified official schema compatibility.

## Manual owner actions

1. Resolve the exact organizer handoff above and confirm public-artifact versus explicitly accepted private read-only access. Repository visibility has not changed.
2. Confirm contact name/email. Decide own-code licensing only if a grant is intended; no new licence was granted.
3. Review the disclosed weak external coverage and historical 100-company evidence. A current 100-company live run would require separate budget approval; none is manufactured here.
4. Once access/handoff and exact release checks are accepted, authorize any publication and send the prepared submission yourself or explicitly authorize that final action. No email, submission, PR, merge or release publication occurred.

## Reproduction and final evidence

See README for the exact launcher/install/test commands. All work, downloads, experimental implementation, live guard/bytes and measurements ran on pancakes outside Git until selected concise reports were added. Original 20-company evidence seals remain intact.

Current patched-environment full suite passed: 484 tests and 237 subtests in 216.85 s, with the existing pyRdfa UTC deprecation warning. Independent subprocess acceptance passed format/cardinality/order, invalid/malformed input, resume, refresh/growing/subset history, source 404/403/timeout/partial failure, saved-data UI and serialization checks. The [acceptance receipt](evidence/final-coverage-20261017/acceptance.json) includes scope and log hashes. Final clean exact-SHA clone/install and CI are verified after the commit and reported in the owner handoff; they are not preclaimed here. UI remains on VM loopback 127.0.0.1:18082 with its saved four-company dataset; no public hosting/firewall/tunnel service was introduced.
