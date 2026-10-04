# M09 RC1 benchmark and verification record

## Source under test

- Frozen implementation and live-smoke SHA: `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194`.
- Branch: `codex/m00-contract-audit`; working tree was clean for the live run and deterministic gates.
- Live cohort and resource measurements are in [the final live smoke report](M09_LIVE_SMOKE_PASS_2026-10-05.md).

## Deterministic release gates

| Gate | Result |
|---|---|
| Complete unittest suite, final post-package rerun | PASS — 358 tests in 135.123 s; 69 subtests; 0 failed subtests, failures, or errors |
| M09 tests | PASS — 12 tests |
| Extended live-shape production-path gate | PASS — 2 tests, source transport replaced only by deterministic fixtures |
| Synthesis multiplicity and citation mutation cases | PASS — included in complete suite and M09/live-shape tests |
| Prior M09 collision/provenance regressions | PASS — claim ID, evidence ID, claim-to-snapshot linkage, snapshot context, and multi-page synthesis |
| Wrong-company adversarial and provenance mutation tests | PASS — included in complete suite |
| Financial validation and gateway/robots/budget tests | PASS — included in complete suite |
| M07 refresh replay | PASS — 12 rows; 6 expected events, TP=6, FP=0, FN=0; full event provenance; deterministic IDs; replay idempotent |
| M08 independent gold | PASS — 4-company gold; find, compare, verify accuracy 1.0; zero unsupported assertions; citation completeness 1.0 |
| M08 local UX/XSS smoke | PASS — live output loaded for 100 companies; launch/profile/evidence/compare/verify/changes/XSS checks passed |
| Crash/resume | PASS — real CLI interrupted after 25, 50, and 90 durable rows; all resumed outputs matched uninterrupted semantics and preserved 100-row order/cardinality |
| Offline scale and budget gate, corrected provenance verifier | PASS — fresh output report SHA-256 `c1982f5f4f3bb72eb28eb6a05e1a7eeb6fdd141ed82eef11faa353551596bb67`; 1,000 and 1,200 operational writes; 10,000-row dry run; scheduler simulations and budget stress modes preserved official cardinality; physical network requests 0 |
| Clean-install launcher from unrelated directory with `PYTHONPATH` unset | PASS on the pre-package clean-install baseline; final gate repeated the launcher from `/private/tmp` with a frozen local registry row and zero physical requests |
| Evaluator adapter and final publication graph | PASS for all 100 live envelopes |
| `compileall` / `py_compile` | PASS |
| `git diff --check` | PASS after package changes |

The focused M09 plus expanded production-path live-shape rerun passed **14 tests** in 101.587 seconds. The final complete suite was independently counted by a custom `unittest` result class; it reports 358 tests, 69 passing subtests, 0 failures, and 0 errors in 135.123 seconds. The scale report was generated from implementation SHA `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194` with documentation-only package changes present; the corrected M06 verifier passed.

### Offline runner measurements

These are parser/writer and scheduler measurements, not live coverage or identity measurements.

| Mode | Rows | Ordered terminal output | Runtime | Peak RSS | Physical requests |
|---|---:|---:|---:|---:|---:|
| Operational write | 1,000 | 1,000 | 6.030 s | 118.65 MiB | 0 |
| Operational write | 1,200 | 1,200 | 7.954 s | 136.14 MiB | 0 |
| Offline dry run | 10,000 | 10,000 | 87.188 s | 787.86 MiB | 0 |

The 1,000-row scheduler budget-pressure mode completed all 1,000 official work items, preserved cardinality, starved none, and deferred optional work when its logical allowance was exhausted. Identity safety is explicitly `not_measured` in these synthetic scheduler scenarios. The stress modes and corrected M06 provenance/scale verifier are part of the final gate.

## Accepted-domain and recall decision

The comparable, stratified opportunity corpus contains **200 companies**. Registry-listed websites yielded 1 accepted exact domain; registry plus the bounded keyless `.no` candidate yielded the same 1, for **0 incremental company coverage**, **0 new accepted exact domains**, and **0 observed wrong-company promotions**. No incremental verified atomic-claim gain was measured from the added keyless candidates. M05 measured 0 job companies, 0 activity companies, and 0 new companies with either family. This is a small structured audit corpus, not an independently human-adjudicated random sample. A population confidence interval is therefore **not estimated**. The final live cohort's 17 structurally target-bound website claims are descriptive live observations and are not directly compared with this baseline.

The current public board arithmetic is 26.92 evidence + 12 synthesis + 8 UX = 46.92 points; 65 qualification points imply an arithmetic remainder of 18.08/50 for recall under that mix. This is not a calibrated local score or a prediction. Search remains disabled/unpromoted because there is no reproducible rights-approved provider configured. First submission remains **HOLD** pending comparable evidence of materially higher external coverage or authoritative Builderr feedback.

## Known M09 fixes carried in the release

1. Page-specific website claims include canonical fact-value identity; distinct headings cannot collide, and duplicate claim IDs fail envelope validation.
2. Verified URL/domain claims carry every supporting candidate-evidence snapshot ID into the claim provenance.
3. BRREG snapshot IDs include organisation and endpoint context so identical bodies from different companies/endpoints cannot alias.
4. Synthesis groups equivalent same-company observations into one sentence while retaining all supporting claim IDs and evidence IDs; validation checks complete per-claim citation coverage and rejects duplicate sentences, altered wording, missing/foreign claims, and incomplete citations.
5. The deterministic live-shape suite models cross-page repeated facts, page-specific sources, structured plus visible observations, distinct facts, and company isolation through the full production path.
6. Smoke validation derives permitted request purposes and external family names from the canonical policy constants; it rejects unapproved purposes and cannot silently skip families by alias mismatch.

Earlier failed cohorts and their reports are preserved at [M09 live retry failure](M09_LIVE_RETRY_FAILURE_2026-10-04.md), [provenance failure](../audit/m09-live-provenance-failure.md), and [synthesis failure](../audit/m09-live-synthesis-failure.md). The preserved-cohort offline replay is [documented separately](M09_PRESERVED_COHORT_OFFLINE_REPLAY_2026-10-04.md).

## Coverage and submission decision

The 100-company smoke is a safety, terminal-output, and bounded live-foundation check. It is not a held-out recall benchmark. The existing 200-company opportunity comparison measured no incremental exact-domain gain from the bounded keyless candidate path over registry-listed websites; the current cohort does not establish a comparable population-level gain. Jobs/activity remain unmeasured in this live cohort. Therefore the [submission decision remains HOLD](M09_RECALL_OPPORTUNITY.md) until comparable release evidence demonstrates material external coverage above the starter/registry baseline or official Builderr feedback changes that requirement. No local score is converted into an official score.
