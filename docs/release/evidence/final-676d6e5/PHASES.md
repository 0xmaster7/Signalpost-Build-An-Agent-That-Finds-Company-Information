# Per-phase receipts — frozen implementation 676d6e5

Derived from adjacent sanitized JSON; statuses are disjoint. `ran` means completed execution, not positive facts. `skipped` includes ineligible work. Missing statuses are not invented zeros. Company-seconds sum recorded work, not wall time; NAV/Wiki shared durations repeat once per company and must not be summed as real batch cost. Scale statuses are incomplete and its rows are partial, not finalized. `official=0` in the raw wall map is an unused aggregate slot, not measured zero foundation time. Foundation wall time is unavailable in that slot. Percentiles exclude shared NAV/Wiki, but foundation timing semantics include queued work where recorded; these are not end-to-end latency percentiles.

## Smoke

| Phase | Ran | Skipped | Deadline-skipped | Failed | Company seconds | Phase wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| official_foundation | 10 | 0 | 0 | 0 | 24.783 | unavailable |
| financial_statements | 10 | 0 | 0 | 0 | 18.087 | 5.519 |
| official_details | 9 | 1 | 0 | 0 | 35.110 | 10.016 |
| wiki_batch | 10 | 0 | 0 | 0 | 7.628 | 0.763 |
| nav_batch | 10 | 0 | 0 | 0 | 3595.480 | 359.548 |
| nav_apply | 0 | 10 | 0 | 0 | 0.000 | 0.000 |
| website_verify | 10 | 0 | 0 | 0 | 12.593 | 5.350 |
| website_shallow | 0 | 10 | 0 | 0 | 0.000 | 0.000 |
| jobs_activity | 0 | 10 | 0 | 0 | 0.000 | 0.000 |
| annual_documents | 9 | 1 | 0 | 0 | 323.497 | 213.188 |
| finalization | 10 | 0 | 0 | 0 | 1.310 | unavailable |

## Matched

| Phase | Ran | Skipped | Deadline-skipped | Failed | Company seconds | Phase wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| official_foundation | 100 | 0 | 0 | 0 | 171.063 | unavailable |
| financial_statements | 100 | 0 | 0 | 0 | 217.428 | 59.305 |
| official_details | 80 | 20 | 0 | 0 | 378.748 | 100.184 |
| wiki_batch | 100 | 0 | 0 | 0 | 147.557 | 1.476 |
| nav_batch | 100 | 0 | 0 | 0 | 35957.550 | 359.575 |
| nav_apply | 3 | 97 | 0 | 0 | 1.882 | 4.115 |
| website_verify | 100 | 0 | 0 | 0 | 1036.324 | 180.112 |
| website_shallow | 0 | 100 | 0 | 0 | 0.000 | 0.000 |
| jobs_activity | 0 | 100 | 0 | 0 | 0.000 | 0.000 |
| annual_documents | 28 | 2 | 69 | 1 | 1483.461 | 733.919 |
| finalization | 100 | 0 | 0 | 0 | 16.633 | unavailable |

Recorded company-work sum p50/p95 (seconds): 17.25 / 109.803. Scale values reflect incomplete counters.

## Fresh

| Phase | Ran | Skipped | Deadline-skipped | Failed | Company seconds | Phase wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| official_foundation | 100 | 0 | 0 | 0 | 170.468 | unavailable |
| financial_statements | 99 | 0 | 0 | 1 | 208.746 | 56.670 |
| official_details | 84 | 16 | 0 | 0 | 384.882 | 100.645 |
| wiki_batch | 100 | 0 | 0 | 0 | 1192.737 | 11.927 |
| nav_batch | 100 | 0 | 0 | 0 | 35955.430 | 359.554 |
| nav_apply | 2 | 98 | 0 | 0 | 0.385 | 2.260 |
| website_verify | 100 | 0 | 0 | 0 | 1472.546 | 207.331 |
| website_shallow | 1 | 99 | 0 | 0 | 11.621 | 13.173 |
| jobs_activity | 1 | 99 | 0 | 0 | 0.355 | 0.540 |
| annual_documents | 28 | 7 | 65 | 0 | 1376.134 | 689.037 |
| finalization | 100 | 0 | 0 | 0 | 14.357 | unavailable |

Recorded company-work sum p50/p95 (seconds): 21.724 / 132.501. Scale values reflect incomplete counters.

## Scale

| Phase | Ran | Skipped | Deadline-skipped | Failed | Company seconds | Phase wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| official_foundation | 999 | 0 | 0 | 1 | 1794.948 | unavailable |
| financial_statements | 558 | 0 | 442 | 0 | 1836.137 | unavailable |
| official_details | 58 | 500 | 442 | 0 | 477.477 | unavailable |
| wiki_batch | 1000 | 0 | 0 | 0 | 5163.574 | unavailable |
| nav_batch | 1000 | 0 | 0 | 0 | 15534.323 | unavailable |
| nav_apply | 0 | 1000 | 0 | 0 | 0.000 | unavailable |
| website_verify | 0 | 0 | 1000 | 0 | 84.502 | unavailable |
| website_shallow | 0 | 1000 | 0 | 0 | 0.000 | unavailable |
| jobs_activity | 0 | 1000 | 0 | 0 | 0.000 | unavailable |
| annual_documents | 0 | 451 | 396 | 0 | 57.095 | unavailable |

Recorded company-work sum p50/p95 (seconds): 1.895 / 6.204. Scale values reflect incomplete counters.
