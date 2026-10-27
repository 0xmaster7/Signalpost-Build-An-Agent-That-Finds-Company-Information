# Signalpost — Results

Signalpost researches Norwegian companies by organisation number and returns evidence-backed JSONL profiles.

## Latest experiment: failed acceptance

The [27 October phase-budget results](docs/release/PHASE_BUDGET_RESULTS_2026-10-27.md) preserve both preregistered runs. Matched coverage fell from 50 to **28 FTE companies** and 77 to **42 financial companies**; verified websites and jobs remained zero. Runtime improved to **1,190.614 seconds**, with 100 terminal envelopes. Monetary breadth reached 2,491 observations, including 2,100 explicitly assumption-backed and 22 separately scoped group observations. Only runtime/cardinality gates passed.

The fresh disjoint holdout **failed with duplicate claim IDs during optional website publication**, exit 1 after 1,175.312 seconds, with no final envelopes. Optional observations were not checkpointed and their coverage is unknown. It was not rerun. A post-run deduplication/publication guard passed 672 offline tests and 237 subtests; that does not turn the failed holdout into a pass. [Matched per-company CSV](docs/release/evidence/phase-budget-20261027/matched-per-company.csv) and [JSONL.gz](docs/release/evidence/phase-budget-20261027/matched-per-company.jsonl.gz) are available. Public `main` has not demonstrated the live acceptance gates.

## Live evaluation results

The [earlier 27 October matched 100-employer benchmark](docs/release/LIVE_COMPARISON_2026-10-27.md) compared Signalpost versus Arnav's unchanged repo on identical inputs, including the six-company cohort. Companies with verified-site claims: 0/25; jobs: 0/3; FTE: 50/29; financials: 77/98. Our OCR queue exhausted the optional website research window in that baseline. Per-company CSV/JSONL and exact versions are included; these are coverage counts, not established accuracy.

### Historical six-company measurement

Same six previously unseen Norwegian AS employers, selected before source outcomes; previous release `8076e1b` versus latest measured implementation `72e8c05`, retained in release `59cbada`.

| Metric | Previous | Latest |
| --- | ---: | ---: |
| Companies tested | 6 | 6 (same cohort) |
| Financial claims | 14 | 71 |
| Financial metric types | 3 published | 17 published |
| Workforce FTE coverage | 4/6 companies | 4/6 companies |
| Registered workplace claims | 0 | 37 facts across 6/6 companies |
| Verified websites | 0/6 companies | 0/6 companies |
| Public profiles | 0/6 companies | 0/6 companies |
| Jobs | 0/6 companies | 0/6 companies |
| Dated activity | 0/6 companies | 0/6 companies |
| Runtime | 183.226 s | 199.148 s (197.547 acquisition + 1.601 publication) |
| HTTP requests | 34 physical attempts | 34 physical attempts; publication: 0 |

Latest publication used checkpoint resume after a serialization repair. Timings are observations, not a controlled speed comparison. A separate interrupted run used 32 attempts; total research budget consumed: 100 attempts.

## What improved

| Area | Measured improvement |
| --- | --- |
| Financial extraction | 57 additional claims; all six companies gained facts |
| Financial breadth | Added balance-sheet and income-statement metrics, including assets, receivables and payroll |
| Exact-parent workplaces | 6 location claims + 1 postal-address claim + 30 linked registry facts; registered records, not observed offices |

## Evidence

- [Latest live evaluation report](docs/release/FINAL_CAPABILITY_INTEGRATION_2026-10-17.md) and [measured summary](docs/release/evidence/capability-integration-20261017/summary.json).
- [Historical 100-company smoke-test report](docs/release/M09_LIVE_SMOKE_PASS_2026-10-05.md): earlier version `9ab896f`; different cohort, excluded from this comparison.
- [Exact release commit: 59cbada](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/commit/59cbada1457f0ff93b265638f037f79df6578c25) and [passing exact-SHA CI](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/39059298958).

## Limitations

- Six employers are a small, non-representative cohort; population accuracy and recall are not established.
- Verified websites, public profiles, jobs and dated activity: zero coverage in this cohort; FTE unavailable for 2/6 companies.
- OCR-ambiguous financial values are withheld; official Builderr parser compatibility and score remain unverified.
