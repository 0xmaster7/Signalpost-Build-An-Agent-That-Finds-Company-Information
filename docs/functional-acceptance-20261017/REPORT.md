# SIGNALPOST — OFFICIAL REQUIREMENTS & FUNCTIONAL ACCEPTANCE REPORT

## 1. Official requirements

The current [challenge page](https://builderr.ai/challenges/signalpost) and [participant brief](https://builderr.ai/starter-briefs/signalpost.md) require a reproducible agent accepting organizer-selected Norwegian company numbers and returning a terminal profile for every input. Seven profile sections are specified; unavailable information must remain explicitly unavailable, not become invented values. These are structural and evidence requirements, not a promise that every company has every category populated.

The [evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md), especially Output contract and Official-run checks, confirms six states, claim provenance, idempotent refresh, preserved evidence, pinned installation and one evaluator command. Exact JSON keys/schema, extra-field rules, path/environment injection, numeric resource limits, snapshot mount and prior-state handoff are not published in the linked materials. No mandatory participant API/container/hosted service was found. The current official archive contains a minimal claims/evidence example and a different executable module/profile batch envelope; neither establishes a unique hidden evaluator schema. The contract's npm Local checks are unavailable in the Python participant archive and are not assumed to be its execution command.

The [published scoring section](https://builderr.ai/challenges/signalpost#scoring) assigns 50 recall/coverage, 30 precision/evidence, 12 synthesis and 8 UX. Coverage uses 70% company and 30% fact recall within each family. Qualification is 65 overall on an official run. Low recall is not a separate eligibility bar; an internal promotion rule must not be described as an organizer rule. There is no official score for this implementation. The page shows Oct 21 closing while the revision text says Oct 18; this report does not invent a deadline timezone or reconcile distinct dates silently.

[Global rules](https://builderr.ai/guidelines) give the challenge precedence and distinguish reproducibility from qualification. They do not create a general requirement to publish code or transfer ownership. Repository visibility stays PRIVATE. The [source policy](https://builderr.ai/starter-briefs/signalpost-sources.md) governs exact attribution and permitted access. The [playbook](https://builderr.ai/starter-briefs/signalpost-agent-playbook.md) explicitly offers reference architecture, not a mandated framework. Models, Scrapy, browser crawling, search and PDFs are not silently turned into implementation prerequisites.

Exact source URLs, hashes, inspected starter members and capture times are in [sources.json](sources.json). Current raw captures remain on pancakes outside the checkout; historical vendor captures were not overwritten.

## 2. Requirements traceability matrix

[TRACEABILITY.md](TRACEABILITY.md) contains 31 source-linked rows, with confirmed, starter-inferred, internal, reference-only and unknown authorities separated. Every row names production behavior, existing/added tests, independently executed evidence, status and limitations. [traceability.json](traceability.json) is the same machine-readable matrix. PASS means the stated behavior passed; it does not convert missing information into coverage or certify a hidden parser.

Mandatory public envelope sections are confirmed; mandatory nested keys and optional-field rules remain unpublished. Confidence appears in the starter example, but no official probability calibration or acceptance threshold is published. Our verification score denotes a deterministic rule, not a calibrated probability. Current field names and defaults are internal until the organizer supplies its runtime output contract.

## 3. Actual end-to-end execution

The separate [acceptance runner](../../signalpost-starter-kit/scripts/validate_signalpost_functionality.py) invokes real CLI processes and HTTP servers without importing production test helpers. It independently parses JSON and checks ordering, per-input cardinality, identity/evidence binding, section presence, terminal states, source metadata and supported summary references.

Passing scenarios include single/plain input, arrays, starter JSON wrapper, CSV, leading zeros, duplicate rows, malformed JSONL rows, invalid IDs, missing frozen records, unfamiliar CWD, stdout JSON, stderr/exit behavior, restart, an explicit prior snapshot, one meaningful controlled change, and repeat idempotency. Normal completed batches exit 0 even when individual rows fail; missing input exits 2 with stderr. Controlled 404, 403 and timeout transports produce not_available, blocked and failed envelopes without dropping output. A partial-source replay publishes supported identity/accounts/workplaces while role failure stays explicit.

Actual HTTP FIND now finds exact organisation numbers. COMPARE keeps company identities and dimensions separate; missing financials remain not comparable. VERIFY supports the actual legal name and contradicts another name with canonical evidence. A mixed valid/invalid batch opens in the dashboard, exposes rejected inputs separately, and retains valid profiles. Unknown-company history no longer returns unrelated events. Historical before/after evidence is retained in controlled change events; arbitrary time-travel profile queries are not implemented or claimed as an official requirement.

Desktop/mobile Chromium checks on the VM rendered the actual application at 1366 and 375 px. Profile overflow was 1475/1363 px before repair; evidence overflow was 702 px on mobile. FIND/profile/evidence now fit their respective viewport widths. [Browser measurements](browser-layout.json), [mobile profile](mobile-profile.png) and [mobile evidence](mobile-evidence.png) are retained. Browser tooling/libraries were temporary test tools, outside the runtime lock and system installation; runtime setup does not require Playwright. The shared preview twice timed out, so VM Chromium was used.

Clean final-source clone/install/acceptance and exact-SHA CI are recorded in the final freeze receipt and handoff. Historical release results are not relabelled as this source.

## 4. Real company research quality

The preserved four-company baseline/refresh remains the primary observed run: EQUINOR ASA (923609016), NORSK RIKSKRINGKASTING AS (976390512), PARS INVEST AS (995854600), and NORDVEST INSTALLASJON AS (926627708). It contains 908 available claims, 18 financial records/126 metadata claims, 44 role rows/355 role-field claims, and 57 workplaces/361 workplace-field claims. Sites/profiles, numeric financial metrics, jobs and activity are zero in that sample. Its unchanged refresh emitted no spurious events. It is not population recall or an official benchmark.

This mission used 19 additional approved requests: two robots-only attempts under generic access, six existing structured-source requests, and eleven checks of the same four companies' identity/roles/subunits. Total authorization usage is 78/80; no further company-data request is authorized by this report. The initial generic-access attempt correctly stopped on unavailable robots; repeating with production's existing narrow BRREG profile returned 200. Source policy was not changed. Raw role documents were checked in memory without retaining unnecessary personal data.

Current official entity responses agree with all four legal identities. Role response hashes match the original source bytes: 223 role fields matched literally; 41 person-name fields require the documented join projection; 91 old locators were invalid and have been corrected. That is not an independent audit of every normalized fact. The source replay yields 278 supported Equinor claims with role-source failure, including newly recovered municipality fields. It is a replay of retained official responses plus a controlled failure, not a second live company cohort.

Coverage classification: legal identity works; municipality omission and industry filtering were actual bugs and are repaired. Financial record metadata works, but numerical results are withheld because explicit unit/scale proof is absent from the approved response contract. That is a financial coverage gap, not proof that the company has no accounts. The official source policy lists annual-account copies, while the approved internal acquisition policy disables PDFs pending a source/retention decision; this is not an official ban on PDFs. Websites are unresolved or lack registry candidates, not confirmed absent. Hiring/activity extraction is gated behind accepted exact-site proof; no reached approved evidence supports those claims. External discovery/jobs/news connectors are disabled, so these categories have authorization/source-support gaps, not verified zero activity.

No material wrong-company association was confirmed in the assessed records. Complete real-company field precision and population coverage remain insufficiently evidenced; the source-binding checks and controlled regressions must not be advertised as complete human adjudication.

## 5. Implemented fixes

Confirmed failure paths and minimal corrections:

- Frozen CSV crashed in a redundant JSON-only pre-read; the streaming reader now handles canonical/native Norwegian CSV and JSONL keys.
- The public starter's organisation_numbers JSON wrapper was treated as one malformed input; it now expands into ordered rows.
- Frozen-only execution ignored supplied snapshot dates/source metadata and could publish post-cutoff identity; it now binds dates, honours the source parameter and withholds invalid/future-dated identity.
- Main search ignored organisation numbers; exact numeric searches now select the requested company.
- Unknown-company history fell back to all companies; explicit unknown scope now returns no events.
- Failed invalid-input rows prevented dashboard launch; they are now separately displayed diagnostics, never fabricated company profiles.
- Municipality values were read from the wrong level; nested official address values and their exact pointers are now preserved.
- Industry filtering/verification compared a dict with a code string; queries now use the source object's code and preserve citations.
- A no-response status of 0 violated snapshot validation; it is now represented as absent HTTP status.
- Unexpected-worker fallback metadata violated the closed synthesis schema and aborted publication; it now uses the existing recognized operational field, preserving one failed terminal result per input.
- Role record-root pointers ended with an invalid trailing slash and organisation holders used a person-name pointer; both are corrected, with explicit projection methods retained.
- Long canonical values overflowed the desktop/mobile viewport; wrapping fixes this without hiding facts.

Each path has a reproduction or direct pre-fix source observation, targeted regression/measurement, and relevant production-path verification. The frozen-role locator regression checks person and organisation holders against actual source-shaped objects; historical bad locators were not rewritten. No source, paid provider, credential, financial-unit assumption, architecture or ownership policy was introduced.

## 6. Evaluator compatibility

Confirmed public semantic requirements and JSON parsing are independently exercised. Current internal adapter fields, six-state envelopes, source references, changes and exact cardinality validate. The official minimal example instead uses availability/id/top-level changes and an operations object; the executable starter emits modules/profile with different terminal terminology. Our canonical envelope has state/evidence_id/refresh.changes and an operations list. These are real format differences, not proof of rejection by an unavailable parser. No guessed compatibility aliases were added.

The exact runtime schema, extra-field policy, organizer argv/environment variables, resource numbers, frozen registry injection and persistent-state handoff remain UNVERIFIED. The official contract says the organizer supplies the output contract at run time. This code must be adapted against that actual contract when provided; current tests do not replace it.

## 7. Remaining deficiencies, ranked

P0/eligibility uncertainty: authoritative wire schema/invocation/resource inputs and organizer access to the private exact commit are unverified. No remaining reproduced batch-dropping failure is known after the repairs; this does not certify an unpublished harness.

P1/refresh operation: strict state compatibility includes operational budget values. Expanding a default one-company batch to two changes the fallback request budget and rejects prior state with an explicit incompatibility error. Pinning the same explicit budget across both runs successfully compares the old company and baselines the new one. This workaround is verified. Global snapshot/source settings also belong to the current strict fingerprint. Seamless changing-budget compatibility would require a deliberate state-compatibility/migration change; the approved contract was retained rather than silently weakened.

P1/coverage: no promotable financial metrics or verified sites/jobs/activity in the four-company sample. Financial PDF/source rights, discovery and job/news provider permissions require specific decisions before implementation/acquisition. No new approval is inferred from the official list of preferred source categories.

P2/usefulness: the evidence-backed summary remains technical and verbose, the web app explores saved output rather than researching arbitrary new numbers in-page, the primary-industry filter is not general multi-code search, and arbitrary as-of profile querying is absent. These are product limits, not secret evaluator requirements or separate qualification thresholds. Official synthesis/UX scores and competitive recall remain unknown.

## 8. Final engineering checkpoint

All changes were made on pancakes on codex/m12-final-sol-remediation, starting at d8f13f3d8aa4fccd96f9024956a237aa0a0e782e. Local full acceptance: **445 tests / 206 subtests**, with one existing third-party deprecation warning; independent real-process/HTTP/failure scenarios pass. M07 replay, M08 gold, M06 scale/provenance, crash/resume and historical receipt gates passed. The final code is frozen before commit; the final handoff and external FUNCTIONAL_FREEZE_RECEIPT.json give the exact commit, remote match, clean status and exact-SHA CI. No document attempts to contain its own commit hash. Historical release/vendor evidence remains unchanged.

Full logs, raw permitted source responses, screenshots, source receipts, controlled outputs and the final receipt are preserved outside the checkout at /home/azureuser/projects/signalpost-release-evidence/functional-20261017 on pancakes. Portable summaries are [results.json](results.json) and the traceability files. VM-local raw evidence is not automatically accessible to organizers.

## 9. Decision

Software operates for the declared CLI/state/read-only-dashboard workflow, including the repaired failure paths. Official semantic requirements are substantially implemented; required information coverage is PARTIAL, and the exact evaluator interface remains UNVERIFIED. A sparse but honest profile can be eligible under the published rules; it is not evidence of competitive recall or qualification.

Readiness for the organizer's exact evaluation is UNVERIFIED until the actual output/runtime contract and private access are confirmed. Use a stable explicit configuration for refresh; decide deliberately whether to change state compatibility if budgets/snapshot settings vary. Coverage expansion needs approved source-specific work, especially financial statement units and permitted discovery/hiring/activity evidence. Keep the repository PRIVATE. No PR, merge, force push, visibility change, paid integration, external message or competition submission was performed.
