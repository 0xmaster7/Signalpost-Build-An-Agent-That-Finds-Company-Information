# Independent public discovery — 26 October 2026

Baseline: `99e7560e21f50236d3a8f692238ef27dea539c19`. These are independently implemented improvements, not copied competitor code. Arnav's current README revision is `d2666383328c1779973af9d74b1d0d9b884b66e4`; unlike the earlier audit, it now has newer commits. Its coverage numbers are not our measurements.

## Changes and boundaries

| Proposal | Disposition |
| --- | --- |
| Jobs without a verified website | Added official NAV v1 feed access with a runtime public token. Only current ACTIVE detail with future expiry, publication/modification dates and exact legal/workplace employer orgnr can publish. Workplace matches retain the official parent-relation evidence. |
| Tiered website publication | Existing direct ownership/content checks remain intact. Added separate `registry_declared_website_url` and `shared_website` registry-reference claims; neither permits content attribution, profile extraction or downstream crawling. Observed identity conflicts and cross-host redirects withhold fallback. |
| More discovery candidates | Registry email domains, workplace contacts and name-derived domains already existed. Added homepages from confirmed NAV employers and a single bounded P2333/P856 Wikidata batch adapter. Leads remain candidates until the existing ownership gate accepts them. |
| Wikidata access | **Currently blocked.** The live query endpoint's robots file disallows `/sparql`; the gateway respects that policy. Fixture tests establish adapter behavior, not usable live coverage. No Wikidata profiles or headcount are published from candidate metadata. |
| Financial API versus OCR | BRREG's structured accounts API already supplies filing records. PDF/OCR provides explicit unit/scope and statement reconciliation. Those safeguards and financial extraction are unchanged; removing them merely to increase counts would be unsafe. |
| FTE strategy | Existing seven-page priority includes pages 5, 4 and 6 after the identity pages; run-scoped document-hash caching and 2.1-second PDF pacing already exist. We retain cross-page conflict checks rather than stopping at the first statement. Persistent OCR caching and continuation-layout changes remain follow-up work. |
| Budgets and provisional output | Existing official-foundation checkpoints, completion reserve and ordered terminalization remain. NAV runs after foundation and before OCR, with a 20-second limit, four 1,000-item pages and eight unique detail attempts. Request reserves skip extra discovery under tight budgets. |
| Bulk registry and scale evidence | Streaming bulk registry/roles/workplaces integration and new 100/1,000-company live benchmarks remain unimplemented/unrun. Existing historical results are not relabelled as evidence for this update. |

## NAV coverage is deliberately partial

The API has no company filter and feed headers have no orgnr. A 40-day change window and exact-name shortlist limit detail requests; the detail's orgnr—not the name—confirms the employer. This can miss active ads, aliases, older postings and feeds beyond the page cap. Every scan records `negative_coverage: false`; no result means **unknown**, not “zero jobs.” A production-wide index/resumable six-month scan is separate work. FINN ads are not included in NAV's feed.

Previously observed vacancy UUIDs are refreshed before new discovery. A missing/deleted/unavailable individual ad does not abort other work. Unrefreshed NAV claims are not retained as current ads on refresh, and their disappearance does not invent a closed-job event. Identical detail content produces stable claim semantics despite a new retrieval time.

NAV descriptions, contact lists, raw responses and tokens are not persisted. Job-title contact strings are rejected. The token is held in memory, headers are restricted to exact HTTPS NAV API paths, and redirects are rejected before forwarding it. NAV data-use terms—not the server code's MIT licence—govern metadata use. See the [source-rights register](../source-rights.md).

The default `./run.sh` path enables these sources through the existing `--live-websites` production path. An explicit historical cutoff does not query current feeds to reconstruct past observations. Explicit registry-snapshot offline invocation still stays offline unless live flags are supplied. Dependencies, evaluator serialization, financial/workforce parsers and the no-install execution wrapper are unchanged.

The source-policy fingerprint changes with this release. Older incompatible state artifacts are rejected as refresh baselines rather than silently mixed; refresh idempotency is verified within the new policy.

## Verification

- Focused source/publication checks cover exact-employer versus wrong/missing employer, official workplace relations, expiry/dates, malformed/deleted detail, pagination, UUID deduplication, token/redirect protection, privacy, historical cutoffs, URL-only versus owned content and preserved conflict diagnostics.
- A controlled production-runner test publishes NAV jobs with **no website**, preserves duplicate/invalid-row cardinality and verifies **zero changes on identical refresh**. This uses fixtures, not a new live coverage benchmark.
- Bounded live probes through the production gateway returned HTTP 200 for public-token, authenticated feed and detail endpoints. The selected live detail did not provide an employer orgnr, so no employer-bound coverage gain is asserted. The same probe recorded Wikidata as `robots_disallowed`; five physical requests in total.
- Full suite: **542 tests and 237 subtests passed**, 218.98 seconds; one existing third-party pyRdfa UTC deprecation warning. Independent functionality/process/failure/refresh acceptance: **passed**, with controlled transport and zero real HTTP requests.
- A separate isolated checkout passed first-run setup, repeated setup, locked distribution checks, local PDF/OCR without Tesseract, unrelated-working-directory execution, four offline terminal rows, failure exit code 2 and **no installation during run**. The production-only verifier ran in a fresh environment rather than the test environment containing pytest.
- [Verification receipt](evidence/public-discovery-20261026/verification.json). Exact-commit CI is verified separately after publication; local success is not a claim of remote CI success.

The measured six-company coverage table in [RESULTS.md](../../RESULTS.md) remains historical. This update adds safe acquisition paths; it does not establish improved live cohort coverage, FTE accuracy or superiority over another implementation.
