# Final candidate measurements — acceptance FAILED

Measured research implementation: **`676d6e513b70c0e3cbf8e884602ad7e5674d5df9`**.
Later commits change tests, the independent validation harness, documentation and public exports only; they do not change research, dependencies or launchers. This report is not a qualification, official score or submission. **The candidate is not submission-ready: the live 1,000-company run timed out.** No research changes or retries were made after observing fresh/scale outcomes.

## Live outcomes

| Cohort | Finalized envelopes | Finance companies | Explicit FTE companies | Verified websites | Jobs companies | Runtime seconds | Exact offline replay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Smoke | 10/10 | not summarized | not summarized | not summarized | not summarized | 607.411 | passed, 22.466 s |
| Matched | 100/100 | 98 | 18 | 0 | 3 | 1595.038 | passed, 294.645 s |
| Fresh | 100/100 | 93 | 19 | 1 | 2 | 1584.378 | passed, 328.571 s |
| Scale, operational only | **not finalized; 1000 partial rows preserved** | not measured | not measured | not measured | not measured | **watchdog terminated at 2100.355 s** | not run |

All three smaller runs exited zero, produced ordered final output/state pairs, persisted all required company-phase counters, and had zero duplicate claim IDs and zero aborted inputs. Optional phase failures remain visible: one matched document phase and one fresh finance phase failed, without aborting either batch. All three replays freshly serialized identical output **and state bytes**, with zero missing HTTP/OCR requests, zero live network calls and sealed, fully consumed recordings. Exact replay proves reproducibility of these observations, not their accuracy or coverage sufficiency.

Scale preserved 1000 ordered, complete-shaped partial envelopes with zero duplicate IDs, but had no final state pair or batch aggregate. Its publication marker says `status=partial`, `canonical_pair_committed=false`; all 1000 checkpoint shells remain `baseline_done`. **Do not count these as 1000 successfully finalized/scored results.** The numeric `final_envelopes=1000` in the raw runner receipt counts rows and does not override the failed execution/publication gates.

## Acceptance gates and causes

- **100% final envelopes:** passed at 10/100/100; failed at 1000. The 1800-second internal total did not bound post-deadline persistence/finalization. External watchdog sent SIGTERM after 2100 seconds (exit -15). Stderr/stdout were empty, so no terminal traceback or sampled stack survived. The last durable phase is annual documents: only 847/1000 document statuses exist, and all finalization statuses are absent. This is consistent with being interrupted during document-result bookkeeping/publication, but the exact blocked instruction is **unproven**. The SQLite file was approximately 698 MB plus 292 MB WAL and partial JSONL approximately 318 MB: substantial persistence cost exists, but a causal I/O profile was not captured. No scale retry or tuning was performed.
- **Finance >=95:** matched passed at 98; fresh failed at 93. Six fresh companies received accounts API 404 (no accounts returned), and one received HTTP 500. These seven gaps were not withheld by an OCR/unit gate. At scale, 442 finance phases were deadline-skipped; identity breadth therefore did not become financial breadth for every input. Scale financial coverage was deliberately not inspected.
- **Explicit FTE >=50:** failed, 18 matched / 19 fresh. Matched had 69 deadline-skipped document phases; fresh had 65. Depth scheduling spent its earlier budget on NAV and discovery, leaving too little document throughput. Strict abstention and unsuccessful/expensive OCR also contribute. Registry employee counts are not FTE.
- **Verified websites >=20:** failed, 0 matched / 1 fresh. Matched candidate audit contains 102 DNS robots failures, with further network/robots and identity rejections detailed below. Name-derived domains often do not exist; published URL-only candidates are not verified websites. Identity gates were not relaxed to manufacture coverage.
- **Runtime <=20 minutes:** failed on both 100-company cohorts (26.58 / 26.41 minutes). Both stayed within the configured 30-minute total, which is a project budget, not an organizer guarantee. Scale exceeded even that budget and the external watchdog. Builderr's numeric time/resource allowance remains unstated/unverified.
- **Duplicate IDs:** zero in all observed output rows. **Wrong-company verified-site publications:** zero observed among the single manually reviewed positive, not an independent all-field precision audit.
- **Exact replay:** passed for smoke/matched/fresh; unavailable for scale because its capture/publication was interrupted.
- **CI:** consult exact package-commit Actions status; implementation and CI evidence are distinguished below. A green test run cannot cure these failed live gates.

## Matched before/after — regression, not a causal ablation

| Matched cohort | Finance | FTE | Verified websites | Jobs | Runtime seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline `725eb6375feb0529da4cbe4f73bff05bd6e693f2` | 98 | 23 | 0 | 3 | 1128.650 |
| Frozen implementation `676d6e513b70c0e3cbf8e884602ad7e5674d5df9` | 98 | 18 | 0 | 3 | 1595.038 |

Finance was unchanged; FTE fell by five companies and runtime rose by 466.388 seconds. This is **not an improvement**. Multiple changes and different source/scheduling conditions were measured together. No individual scheduler/text/OCR/cache/candidate change has an isolated causal live effect estimate. The fresh cohort is not the old baseline holdout and must not be compared as a paired sample.

## FTE document evidence

[Per-document comparison](evidence/final-676d6e5/document-comparison.json) joins only the same company and a **non-null identical PDF hash**; null means unavailable/unattempted, not zero. Processing includes acquisition and OCR, so survivorship and changed scheduling prevent an overall speedup claim. Matched persisted 98 document audit rows, including unattempted rows: 69 without a resolution method, 19 labeled OCR, 10 not processed. Persisted page counters show **0 text-layer pages and 50 OCR pages**; unreported interrupted work must not be inferred as zero. Nineteen OCR-method documents do not imply nineteen published FTE claims: publication has additional checks.

The 29 rows with processing timings total 1282.062 seconds (median 20.237); download time totals 133.607 seconds and OCR engine time 322.051 seconds. For the 19 OCR-method documents, median worker time is 12.379 seconds, maximum 69.962. Three captured PDFs were inspected read-only: sampled pages 1/5 had no text characters and one full-page image, so text-first could not help those pages. This is not evidence that all PDFs are scans. No text-layer throughput improvement was demonstrated live.

## Websites and NAV

Matched candidate sources: name-derived `.no` 123, registry email 31, registry live URL 21, Wikidata 4, workplace contact 11. These are candidate attempts, not distinct companies. Robots causes: DNS 102, connect 4, timeout 4, transport 4, HTTP 403 2, real disallow 2, 404/no rules 9, allowed 41, pre-fetch policy rejection 22. Candidate decisions: robots unreachable 114, unusable 2, blocked 2, ambiguous 33, conflicting identity 16, HTTP rejection 1, candidate-policy rejection 22. Identity tiers: not evaluated 134, registry-declared 16, ambiguous 21, conflict 19. Counters describe different stages and are not interchangeable. The earlier 116 unreachable decisions and comparator's 25 positives are traced in [the pre-fix diagnosis](WEBSITE_DIAGNOSIS_2026-11-05.md); old eight unknown network causes cannot be reconstructed as known subtypes.

Fresh's one verified site is **BYPOST AS, 989383167, https://bypost.no/**. Official BRREG declares that URL; captured same-document JSON-LD binds `Organization`, legal name Bypost AS, identifier 989383167 and its own domain. Page SHA-256: `208bc37a1b8a1d956a4626ebbded75e2c075b38c35f7792e7148299a37e7018e`. No conflicting subject IDs/shared-domain evidence was found in that cached review. This review covers one positive website, not all facts or undiscovered sites. Raw HTML remains private.

Matched NAV traversed 80 feed pages and fetched 68 details. Feed traversal completed, but unresolved details left overall coverage incomplete (`complete=false`, `negative_coverage=false`). Three employers had supported jobs. Missing jobs remain unknown, never a negative hiring claim. NAV's approximately 359.6-second allocation materially competes with later depth; no post-measurement tuning was done.

## Frozen protocol and evidence

All inputs/configuration were frozen before outcomes. Original six are included in smoke/matched. Fresh and scale exclude matched, old holdouts/smokes and each other. Random additions are active AS employers with registered employees >=1 in the archived registry frame, not all legal entities; archived eligibility may have changed. No optional-coverage filter was used. No edits or retries occurred between final cohorts.

- Matched input SHA-256: `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076` (original unchanged).
- Smoke: `42042a9e849ca264981bcf6c72bc30d21e686e668dcd296e66ca9ed5dfb2bfc7`.
- Fresh: `1c07c5f5678b25f3b982972acf730e05a088e850d46ccf775d1d610d5a42c4f8`.
- Scale: `c8d231c304a80151e569667c6a797ae38861ca69dc00ad787f18e619cff77927`.
- Source SHA-256: `96d59f973f6c76a4e19dd0e1f6ec2b2fe88fce633f0bf25b608f36bbfe0c0dff`; config: `6bc8c7126ce4d981042a78e58399f45b28b4b9ef70cdb19120a748ce45ecebca`.
- Total budget 1800 seconds, soft 1500, reserve 300; physical HTTP attempt cap 8000, external watchdog 2100. Machine: Linux, 2 CPU cores, approximately 7.7 GB RAM. No LLM or paid API required. API billing assumed $0; VM/network/storage costs not priced.

Sanitized [JSON receipts](evidence/final-676d6e5/) and the [per-phase status/timing appendix](evidence/final-676d6e5/PHASES.md) preserve all gates, disjoint statuses, timings, percentile definitions and artifact hashes. Raw HTTP/PDFs, checkpoints, tokens and full evaluator envelopes remain private at `/home/azureuser/projects/signalpost-final-acceptance-676d6e5` on the authorized host. Reports contain counts/metadata, not raw source bodies. Do not confuse synthetic/offline CI scale tests with the failed live scale attempt.

## Installation, tests and public site data

Implementation validation: 1089 tests and 252 subtests passed on the two-core host before measurement. Fresh clone at the implementation commit passed first/repeated setup, locked versions, actual local OCR without Tesseract, argument forwarding, unrelated working directory, useful failure handling and no installation by `run.sh`. Dependencies/wrappers remain unchanged. Subsequent CI found test assumptions about CPU count, a legacy gold fixture type, and an independent harness assumption about legitimately unknown leadership sections. Those validation-only fixes preserve strict publication and require explicit unknown states, not invented claims. Exact package-commit CI and final-clone receipts are linked separately when completed; no green status is implied in advance.

[Public site-data](../../site-data/README.md) contains 100 full per-company JSON files (about 33.9 MB total), an index and a compact **1,922,922-byte** bundle. The compact bundle retains three facts per company and omits 15,164 facts plus all 100 summaries; upload the **whole directory** for full profiles/evidence/compare, not bundle alone. Full files retain supported canonical summaries; only eight retain the richer `summary.profile` after privacy redaction. A total of 136 summary sentences was privacy-omitted. These are deliberate export limitations, not missing evaluator claims. Evidence references and index hashes were checked, and common secret patterns were absent. This is not a blanket privacy/license audit. See [JBOX prompt](../../JBOX_PROMPT.md), [source rights](../source-rights.md) and [notices](../../THIRD_PARTY_NOTICES.md).

## Remaining unproven / owner decision

The release has **not** met requested FTE, website, fresh finance, 20-minute, or live scale completion gates. Global hard-wall finalization is disproven on this scale attempt. Official parser compatibility, numeric organizer resources, independent all-field precision, full transitive licensing and a deployed JBOX site remain unproven. No further research edits were made against fresh/scale observations. A separately authorized engineering/measurement cycle is required for remediation; do not present this candidate as accepted. Email remains unsent and no Builderr submission was made.
