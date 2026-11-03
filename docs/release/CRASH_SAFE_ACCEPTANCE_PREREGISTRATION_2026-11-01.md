# Crash-safe acceptance protocol — 1 November 2026

The previous frozen implementation produced zero final envelopes on both cohorts. The subsequent `d6320174abfee97d1029d5e5b899555080a2ebba` duplicate-observation repair has offline evidence only. No new coverage improvement is assumed.

## Required order

1. Implement and test per-company isolation for foundation acquisition, foundation projection, every optional phase, and finalization. Persist phase outcome, elapsed seconds, sanitized reason and traceback hash immediately. Ordinary phase exceptions must not prevent complete final envelopes for every parsed input. Invalid CLI/input files and unrecoverable storage/process termination are distinguished from isolated research failures.
2. Freeze a ten-company smoke input: the original six plus four random active AS employers from the archived official registry frame. Exclude both hundred-company cohorts from the four additions. Record seed, selection time, frame hash and input hash before any live outcome is inspected.
3. Run that smoke command once with private HTTP/PDF recording. Gate: ten complete valid final envelopes, no aborted rows, no duplicate claim IDs, and persisted status/seconds for every company and required phase. Report isolated phase failures even if final envelopes exist; do not equate completed envelopes with factual coverage.
4. Require hermetic offline replay and byte-for-byte identical final envelope output after a successful live smoke. No normalization that drops disputed facts or replay that merely returns recorded envelopes qualifies. Missing request keys, incomplete captures and OCR-cache misses are failures, not permission to fetch live data.
5. Only if the smoke and replay gates pass, run the original matched 100 with recording; replay it offline and compare exact output. Only after that replay succeeds, run the disjoint holdout 100. Freeze implementation and configuration throughout these cohorts; no company-specific tuning or intervening edits.

If the smoke fails, stop live execution and report traceback/collision evidence. If replay fails, stop before larger cohorts. No automatic retries, resampling after outcomes, or silent replacement of failed receipts.

## Inputs, resources and reporting

The matched input remains SHA-256 `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076`. The previously frozen disjoint holdout remains SHA-256 `8ef2df33c4c275b18ac6c6f6ca754db0a8596755ba382bab4e6bb0f54eef44af`: its prior attempt stopped during foundation, before optional coverage measurement. It has not been used to tune extraction. This is a held-out coverage cohort, not a claim that no registry observation was ever seen.

Use the same fixed resource configuration for matched and holdout: 2,700-second hard execution ceiling, 2,214-second soft research limit, 486-second completion reserve, 2,000 physical attempts, finance up to 180 seconds, NAV 360, Wikidata 12, websites 480, OCR at most 900 and 65% of remaining soft time. The acceptance runtime remains **1,200 seconds**; a longer completed run fails it. Installation and selection are excluded from research runtime. Smoke limits and input hashes must be recorded in its receipt before launch.

Report per attempted cohort: final envelopes, duplicate count, per-company phase status counts and summed seconds, batch phase wall times where available, financial/FTE/verified-website/jobs company coverage and end-to-end process runtime. On each hundred-company cohort the coverage gates are finance >=95, explicit company FTE >=50 and verified websites >=20. Assumed-unit monetary claims remain explicitly flagged, company and group scope remain separate, and coverage is not independent accuracy.

Unattempted cohorts and phases are unmeasured, not zero coverage. A fast abort is not a runtime pass. Distinguish actual checkpoint metrics from inferred eligibility counts and HTTP worker-duration sums from phase wall time. Publish only sanitized receipts/reports; raw responses, PDFs, contacts and checkpoint stores remain private. Push the implementation and honest report to public `main` and verify CI on the exact resulting commit.
