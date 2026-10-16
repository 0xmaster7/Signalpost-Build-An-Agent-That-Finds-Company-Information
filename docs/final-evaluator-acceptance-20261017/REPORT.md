# Signalpost — final evaluator and coverage acceptance

This acceptance extends checkpoint `d05a10ca11b1d30746af13eee1d4eb665776fefb`. It supersedes that checkpoint's budget-fingerprint limitation, without rewriting historical release evidence. The source commit containing this report is identified by `git rev-parse HEAD`; the exact-commit installation/CI receipt is preserved outside the checkout in the release-evidence archive and reported with the final handoff.

## Organizer contract and executable starter

The [official challenge](https://builderr.ai/challenges/signalpost), [evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md) and [brief](https://builderr.ai/starter-briefs/signalpost.md) require a runtime-supplied company-number batch, one terminal result per company, identity/claims/evidence/source snapshots/refresh/errors, six availability states, pinned clean installation and a single runnable command. The official set may grow from 1,000 to 1,100 under the supplied cutoff/network/resource policy. The contract does not publish a JSON Schema, exact parser field names, resource numbers or invocation/handoff protocol. Scoring is 50 recall/coverage, 30 precision/evidence, 12 synthesis and 8 UX; qualification requires 65 overall on an official run. This report does not estimate an official score.

I extracted the [official runnable archive](https://builderr.ai/signalpost-starter-kit.tar.gz) and executed its real `scripts/run_competition_batch.py` from an unrelated directory, with a controlled native BRREG gzip CSV, JSON `organisation_numbers` wrapper and only offline `registry,accounting_obligation` modules. Exit 0, two ordered results, zero requests, all five built-in validation checks passed. Its entrypoint and `src/norway_company_agent/batch.py` are byte-identical to the repository copies. Source hashes, stdout report and actual terminal outputs accompany this report.

| Surface | Actual runnable starter | Signalpost production |
|---|---|---|
| Command | `scripts/run_competition_batch.py --organisations ... --bulk ... --output ... --profiles-output ... --report ... --run-id ... --expected-count 2 --modules registry,accounting_obligation` | Declared `run_signalpost.py --input ... --registry-snapshot ... --output ... --state-output ...` |
| Frozen bulk | gzip CSV required by this entrypoint | Native CSV, gzip CSV and JSONL supported |
| Terminal object | `run_id, organisation_number, state, started_at, completed_at, modules, profile` | Six-state canonical envelope, seven sections, claims/evidence/snapshots/refresh/synthesis/errors and run/batch accounting |
| Observed result state | `complete` | `available` |
| Validation | Count, uniqueness, entity/module terminal states, no drops | Ordered row cardinality, six states and publication/provenance graph validation |
| Stdout | JSON batch report | JSON batch report; output rows written separately to JSONL |

The starter's example envelope is a third format, distinct from its executable output. The published evaluation contract's six-state vocabulary is also distinct from the starter's executable terminal vocabulary. Therefore these artifacts cannot establish one authoritative wire schema. Signalpost is not a drop-in replacement for the starter's flags or `validate_envelopes` function; no official text found requires that replacement interface. No confirmed scoring-blocking parser incompatibility is established, and private-parser compatibility remains UNVERIFIED. No aliases or speculative serializer were added. The same native gzip fixture and wrapper were independently processed by production: two ordered `available` results, exit 0 and zero requests.

Prepared organizer clarification (not sent): “Will you execute our declared `run_signalpost.py --input ... --output ... --state-output ...` command and consume its documented six-state evidence envelope, or require the runnable starter's flags and `state/modules/profile` output? Please provide the accepted output parser/schema and batch, cutoff, budget, frozen-registry and prior-state handoff interface.”

## Growing-batch correction and acceptance

Confirmed root cause: the previous history fingerprint included the derived `12*N+1000` request cap and all operational budgets. Growing a batch changed the hash and rejected valid prior history. The repair separates semantic evidence configuration from operational run limits. The source-policy hash, registry source/date, network mode, live provider flags, discovery flag and non-budget runtime settings remain strict. All effective budgets, exact input bytes, snapshot hash, cutoff and prior-state bytes remain in the checkpoint fingerprint. This does not allow a different run to resume the same checkpoint.

New artifacts use the existing state schema with a versioned semantic compatibility hash. Exact-matching old operational fingerprints can migrate; original artifact references and every retained evidence/snapshot/observation remain intact. Legacy opaque hashes with changed configuration are still rejected explicitly. To carry a legacy artifact into a differently sized batch, first perform one matching-configuration handoff using its original batch and budget, then use the migrated state for growth. No arbitrary old fingerprint is accepted.

Independent actual processes, controlled fictional companies, no acquisition:

| Run | Output rows | Stored companies | Changes | Result |
|---|---:|---:|---:|---|
| Baseline | 1,000 | 1,000 | 0 | PASS |
| Expanded batch | 1,100 | 1,100 | 1 controlled name change | PASS |
| Subset refresh | 2 | 1,100 | 0 | PASS; untouched company state byte-equivalent |
| Full repeat | 1,100 | 1,100 | 0 | PASS; no spurious events |

Reproduce the fictional scale scenarios with `signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/scripts/validate_signalpost_growing_scale.py --output-dir /tmp/signalpost-growing-scale-new`. Use a fresh output path.

All exited 0 with exactly ordered terminal results. The changed company retained prior/current evidence. These are frozen-registry scale checks, not a claim that 1,100 live companies fit the organizer's unpublished network budget. Additional launcher regressions cover duplicate rows, budget/config changes, exact legacy migration with original reference, changed source rejection and changed checkpoint rejection. A rights-decision change remains incompatible. Independent CI process acceptance now includes expanding/subset batches as well as resume, source errors, JSON serialization and HTTP UI workflows.

## Demonstrated coverage corrections

Native frozen BRREG legal form was read through a misspelled key; title-case bulk names and websites were also omitted from the website input adapter. The official starter's `sampling.normalize_row` explicitly supports `Navn`, `Hjemmeside`, `organisasjonsform.kode` and `Organisasjonsform.kode`. Production now forwards these documented fields and nested `organisasjonsform.kode` correctly. The ENK address exclusion receives the correct legal form. Tests verify native forms and source-bound website candidates; candidate URLs still require the existing ownership gate. This fixes a supplied-snapshot retrieval/input defect, with no demonstrated real-company coverage delta claimed.

## Missing coverage, ranked by practical impact

1. **Websites/profiles:** the native-input mapping bug above is fixed. In the preserved four-company run, three companies lack registry-listed candidates; discovery was disabled by the scoped live authorization. Equinor's reached pages lacked the required resource-bound typed owner proof; the preserved inspection does not establish a safe ownership false negative. The historical cohort also lost many candidates to robots/transport unavailability. Search/alternate providers and changing rights policy are not authorized remedies. Ownership is unchanged.
2. **Numeric financials:** preserved Equinor response SHA-256 `fda20c0880f7585fcf5f950813eeb83682e37f4048b607171f2b41894c46bd6b` has six records, 42 numeric candidates, USD currency and 42 absent unit states. Currency supplies no scale. The source parser retains record metadata and withholds numerical metrics correctly. A source with explicit statement units, such as separately approved annual-account copies, needs its acquisition/retention decision and extractor; no PDF or provider was added.
3. **Hiring:** no accepted website in the four-company sample, so the authorized exact-employer extraction path was not reached. No independently approved ATS/job provider is enabled. This is a source reach/capability gap, not evidence of no vacancies; approved structured-job fixtures retain positive and negative coverage.
4. **Dated activity:** same website reach constraint. Historical accepted-site candidates included undated and out-of-window items, which cannot support current dated claims. No reproducible extraction bug or available valid date was demonstrated in the saved corpus. No independent news provider is enabled.

The preserved four-company output has 908 claims: 18 account records/126 financial-metadata claims, 44 role rows/355 role-field claims, and 57 workplaces/361 workplace-field claims. Verified websites, numeric financial metrics, jobs and activity are zero. Coverage is substantially incomplete; this is neither population recall nor an official score. All four legal identities are correct in checked official evidence, but this report does not independently certify every historic source value. See the preceding [functional report](../functional-acceptance-20261017/REPORT.md) for source-value verification bounds. Raw historical 100-company bundle bytes remain unavailable on this VM; original reports/receipts are preserved.

No new company-data requests were used: authorization remains 78 of 80. No source contract, ownership rule, paid service, credential, architecture or repository visibility changed. No external submission or organizer message was sent.

## Acceptance limits and recommendation

The independent process acceptance passed single/array/wrapper/CSV inputs, duplicate/invalid/missing rows, ordered cardinality, six terminal states, JSON parsing, claim-evidence-snapshot bindings, real saved source replay, resume, controlled changes, repeat idempotency, source 404/403/timeout/partial failures, process exit codes and actual HTTP dashboard FIND/VERIFY/evidence/COMPARE/history behavior. Source faults replace only transport/DNS and perform zero live requests. Clean exact-commit installation, focused/full deterministic gates and exact-SHA CI are required in the final freeze receipt; a dirty development measurement is not labeled exact-SHA evidence.

Recommendation: **READY WITH DISCLOSED LIMITATIONS** for submitting a reproducible engineering candidate. Private evaluator acceptance and competitive recall remain unverified. Organizer confirmation of the actual parser/handoff is the remaining contract question. The important coverage work requires evidence/source decisions, rather than weakening verification. The repository stays PRIVATE and access by Builderr is not claimed without confirmation. User approval is still required for any external submission or visibility change.
