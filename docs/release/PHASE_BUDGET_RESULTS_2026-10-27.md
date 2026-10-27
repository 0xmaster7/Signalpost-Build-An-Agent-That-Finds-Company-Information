# Phase-budget experiment results — 27 October 2026

**Matched cohort: FAIL. Fresh holdout: EXECUTION FAILED, no final envelopes.** The public implementation has not demonstrated the preregistered coverage gates. Faster completion and more monetary observations did not preserve company/FTE coverage. Neither run was repeated, and no implementation changes occurred between them.

## Frozen design

Implementation: [`d3aa87937f4589df88a3834a676fb95daba2a1ba`](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/commit/d3aa87937f4589df88a3834a676fb95daba2a1ba). Its [exact-SHA CI passed](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/40531696007), with 668 tests and 237 subtests. Offline correctness did not predict live acceptance.

The [preregistration](PHASE_BUDGET_PREREGISTRATION_2026-10-27.md) required websites ≥20, financial companies ≥95, explicit company FTE ≥50, elapsed time ≤1,200 seconds and 100 valid terminal envelopes. All gates were required. The [implementation](CONCURRENT_RESEARCH_2026-10-27.md) bundles scheduling, NAV indexing, early-stop OCR and company-local monetary calibration; this is **not a component-isolating ablation**. Live-source drift is a confounder.

Both runs used the same two-CPU host, frozen configuration, empty research caches, separate sanitized homes, no inherited service keys and numerical-library threads limited to one. They ran sequentially. Limits remained 2,000 requests, 2,700 seconds hard, 2,214 seconds soft and 486 seconds publication reserve; new internal phase caps were part of the treatment. Installation and sample selection are excluded from elapsed research time.

| Cohort | Input SHA-256 | UTC start | Elapsed / exit |
| --- | --- | --- | --- |
| Original 100, including fixed six | `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076` | 15:32:05.450825 | 1,190.614 s / 0 |
| Fresh disjoint 100 | `2d75e5728b753cecfd8a2e7adf9df0d8d8e89fa83e8ea7855be4cbf962c3a9f4` | 15:51:56.329321 | 1,175.312 s / 1 |

The holdout was frozen at 06:51:10.936291 UTC, before either run. It samples active AS employers with at least one disclosed registered employee, excludes all original 100 and has no forced six or financial/website outcome filter. Both selections use the archived registry frame SHA-256 `f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece`: 60,946 eligible companies among 1,179,224 records. Fresh means disjoint from this matched cohort, not guaranteed absent from every historical dataset.

## Matched coverage

Baseline and unchanged competitor measurements come from the [earlier same-input comparison](LIVE_COMPARISON_2026-10-27.md). The competitor was not rerun. These are observed coverage counts, not independently established precision or recall.

| Outcome | Signalpost baseline | Signalpost treatment | Arnav, earlier run | Treatment gate |
| --- | ---: | ---: | ---: | --- |
| Companies with verified websites | 0 | 0 | 25 | FAIL (≥20) |
| Companies with jobs / distinct jobs | 0 / 0 | 0 / 0 | 3 / 25 | Secondary |
| Companies with explicit FTE | 50 | 28 | 29 | FAIL (≥50) |
| Companies with monetary financial claims | 77 | 42 | 98 | FAIL (≥95) |
| All-period monetary observations | 891 | 2,491 | 5,579 | Not a company-coverage gate |
| Latest standalone monetary observations | 891 | 858 | 1,872 | Same dimensions only |
| Group monetary observations | 0 | 22 | 96 | Separate group scope |
| Elapsed seconds | 2,222.116 | 1,190.614 | 811.057 | PASS (≤1,200) |
| Final terminal envelopes | 100 | 100 | 100 | PASS (100) |

Treatment FTE includes 25 positive values and three explicit zeros. All 100 final envelopes were terminal `available`; that does not mean every optional section was available.

Of 2,491 monetary observations, **2,100 are explicitly assumption-backed**, across 39 companies, and 391 use document/explicit-unit support. Directly supported monetary claims exist for 42 companies. These categories overlap at company level. Calibration broadened periods/metrics for successfully processed companies; it did not recover the missing companies. Assumptions are not API-wide unit guarantees or PDF validation of each projected value. Group observations remain separately scoped. Comparing 2,491 all-period observations with the competitor's 1,872 latest-standalone observations would be misleading.

## Where coverage was lost

- **OCR throughput:** 51 companies were `document_not_scheduled`, two were deadline-cancelled, one PDF fetch failed, two had no document record, 43 had available verified documents and one verified document was `not_available`. There were 48 PDF requests versus 84 in the baseline. Of 44 processed documents, 25 examined three pages, 16 seven pages and three five pages; 28 stopped early. Early-stop worked locally but did not offset the lower OCR wall allocation on this host. The FTE gate failed rather than holding the baseline lead.
- **Website attribution, not a skipped phase:** verification actions ran for all 100 companies, with 123 successful website-page HTTP 200 responses, but no accepted owned-site claims. The scheduler's `stage_results.verified=100` counts processed actions, not verified websites. There were 21 companies with registry/shared URL-only references; these do not count as owned sites. Candidate audit events included 118 `robots_unreachable`, 45 `ambiguous`, 22 `candidate_policy_rejected` and two `blocked_robots`; 65 companies had a `ROBOTS_UNREACHABLE` error. Review-reason events included 26 insufficient direct ownership proofs, 13 unsupported publisher relationships, seven name-only/missing-address-and-subject-ID cases and four conflicting structured identities. These are events, not disjoint company counts. Ownership and company-site robots safeguards were not relaxed.
- **NAV remained partial:** 32 completed pages, 32,000 feed items, 11 detail fetches, zero matched jobs and 6,554 unresolved entries at the 119.512-second deadline. The audit records 45 logical calls; an additional feed call was cancelled. Both `feed_complete` and employer-index `complete` were false. The full-window objective was **not achieved**; zero published jobs is not evidence that the companies had none.
- **Wikidata:** the documented API returned HTTP 200 in one batch request with four candidate URLs. Its response hash matched the earlier probe. API access succeeded, but candidates did not become verified ownership claims.
- **Monetary calibration:** 39 companies calibrated; three lacked sufficient anchors and three had document conflicts. The remaining 55 had no calibration audit. Generalizing units without company-local evidence was not used to meet the target.

These observations suggest bottlenecks, not isolated causal effect sizes. No further tuning or live rerun was performed for this experiment.

## Holdout failure and post-run repair

The fresh run exited 1 at 16:11:31.641573 UTC while merging optional website results for row 41, organisation `974396904` (CONSTRUCTOR NORGE AS). Envelope validation reported **“claim identifiers must be unique within an envelope”** at the website merge. There is no final evaluator output or final state artifact. Its private checkpoints contain 100 foundation shells at `baseline_done`, not 100 completed research results.

Optional OCR and website observations were still in memory and were not checkpointed before validation failed. Their coverage is **unknown**, not zero, and cannot be reconstructed from the surviving foundation checkpoints. No holdout per-company research projection is published. A successful offline replay cannot recover the lost observations. This failed generalization attempt remains in the record and was not rerun with a patched implementation.

A subsequent, separately versioned repair deduplicates semantically identical website claim IDs while preserving all provenance, rejects conflicting collisions, and validates optional merges on a copy. An invalid optional graph now retains verified official facts and records `WEBSITE_PUBLICATION_GRAPH_REJECTED` instead of aborting the batch. Ownership, evidence and envelope validation requirements remain intact. The exact duplicate field in the failed live memory is unknown; this is a general invariant repair, **not a live-verified reproduction or a holdout pass**.

Offline validation of the repair passed **672 tests and 237 subtests** in 218.55 seconds, including four new identity/provenance and malformed-optional-graph regressions. One existing dependency deprecation warning remains. Exact post-repair commit CI is verified separately.

## Public artifacts

All paths below are contact-free projections/aggregate receipts, not raw evaluator envelopes:

- [Summary and gate outcomes](evidence/phase-budget-20261027/summary.json).
- [Matched per-company CSV](evidence/phase-budget-20261027/matched-per-company.csv): website/jobs/FTE/finance counts, assumptions, group observations, document state/pages.
- [Matched per-company JSONL.gz](evidence/phase-budget-20261027/matched-per-company.jsonl.gz): normalized period/scope/value/evidence metadata, before-counts and pipeline diagnostics. Use `gzip -dc matched-per-company.jsonl.gz` to read it.
- [Frozen execution receipt](evidence/phase-budget-20261027/experiment.json), [configuration](evidence/phase-budget-20261027/matched-budget.json) and [matched aggregate runtime report](evidence/phase-budget-20261027/matched-run.json).
- [Holdout selection receipt](evidence/phase-budget-20261027/holdout-selection.json), [input](evidence/phase-budget-20261027/holdout-input.jsonl) and [failure receipt](evidence/phase-budget-20261027/holdout-failure.json).

The execution receipt's outer `completed` means orchestration ended; its holdout child is explicitly `failed`, not successful. Local host paths in receipts are reproducibility metadata, not credentials. Public projections exclude contacts, raw pages/PDFs, private checkpoints, tokens and credentials; contact/token pattern scans found none. Full original outputs/checkpoints remain private on the benchmark host. Neither repository visibility nor submission status changed.
