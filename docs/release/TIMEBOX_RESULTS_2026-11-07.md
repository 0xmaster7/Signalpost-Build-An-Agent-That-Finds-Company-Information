# Bounded-run result — 7 November 2026

**FAILED. Not safe to submit as a replacement.** The single authorized live 1,000-company source run did not self-terminate within its 1,800-second budget. Its external watchdog terminated it after **1,830.864 seconds**, exit **-15**. There is no committed output/state pair, final state file, completion aggregate or complete finalization counters. Exact offline replay was not started because the live gate failed. No second live run or coverage tuning was performed.

## Frozen implementation and protocol

- Research implementation: `fc39bb01483e54e85e836c72ff3faa8312ac99c3`. Subsequent commits change test fixtures and documentation only; no runtime edits occurred during measurement.
- Input: the existing frozen 1,000 active AS employer cohort; SHA-256 `c8d231c304a80151e569667c6a797ae38861ca69dc00ad787f18e619cff77927`.
- Actual source run began **6 November 2026 20:51:41 UTC / 7 November 02:21:41 IST**. The 60-minute work timebox began at 20:29:21 UTC and ends at 21:29:21 UTC / 02:59:21 IST.
- Total budget: 1,800 seconds; research allocation: 1,530 seconds; finalization reserve: 270 seconds. No paid API or LLM was used.
- An earlier wrapper preflight exited before source calls because its environment lacked the setup stamp. It was not a live source run. The actual run used the existing verified stamped environment; this was not a new clean-machine installation.
- Private raw captures/checkpoint remain outside Git. The sanitized [machine receipt](evidence/timebox-20261107/live-report.json) records artifact hashes and failed gates. Its `final_envelopes` label counts complete-shaped rows, **not** a successfully committed final batch.

## Observed gates

| Gate | Result |
|---|---|
| Ordered complete-shaped output rows | 1,000/1,000 preserved |
| Terminalized checkpoint rows | 728/1,000; 272 remain `baseline_done` |
| Final state pair / committed publication | Missing / false |
| Completion aggregate | Missing |
| Complete company-phase counters | Failed: finalization has 729 records, not 1,000 |
| Duplicate / conflicting / missing claim IDs | 0 / 0 / 0 in preserved output |
| Self-exit within 1,800 seconds | Failed: external SIGTERM at 1,830.864 seconds |
| Exact live/offline replay | Not run; live prerequisite failed |
| Safe replacement under requested definition | **No** |

The output holds 999 available-shaped rows and one isolated foundation failure (`BRREG_PUBLICATION_GRAPH_REJECTED`). That failed company did not abort the other companies. A complete-shaped row is not proof that finalization finished. One finalization status was persisted before its corresponding shell transition, explaining 729 status records versus 728 terminalized shells.

### Counts only, not coverage improvement

Preserved output contains financial claims for **935** companies, explicit FTE for **0**, verified websites for **0**, and jobs for **0**. The optional zeros are observations in incomplete output, **not evidence that the companies have no employees, websites or jobs**. There was no matched-cohort rerun or new claim of improved recall/precision. Wrong-company accuracy was not independently audited.

## Persisted phase statuses and seconds

Disjoint status counts below separate `ran` from `failed`; the machine receipt's legacy `ran` includes failed attempts. Seconds are sums of persisted company records, **not phase wall times**. Batch-level timings replicated onto companies, particularly Wikidata, must not be summed as actual CPU time or used to reconstruct runtime. Phase wall times, total process runtime and finalization wall time are unavailable because the completion aggregate was never written.

| Phase | Ran | Skipped | Deadline skipped | Failed | Recorded company-seconds |
|---|---:|---:|---:|---:|---:|
| Foundation | 999 | 0 | 0 | 1 | 1770.324 |
| Financial API | 947 | 0 | 53 | 0 | 1347.692 |
| Official details | 35 | 0 | 965 | 0 | 115.665 |
| Wikidata | 1000 | 0 | 0 | 0 | 5486.672 (replicated batch timing) |
| NAV batch | 0 | 0 | 1000 | 0 | 0 |
| NAV apply | 0 | 0 | 1000 | 0 | 0 |
| Annual documents / FTE | 0 | 0 | 1000 | 0 | 0 |
| Website verification | 0 | 0 | 1000 | 0 | 0 |
| Website shallow | 0 | 0 | 1000 | 0 | 0 |
| Jobs/activity | 0 | 0 | 1000 | 0 | 0 |
| Finalization | 729 | 0 | 0 | 0 | 98.736; 271 status records missing |

Foundation and finance breadth did not finish well inside budget: finance deadline-skipped 53 companies. Research interruption reached checkpoint recovery, but recovery/terminalization exceeded the reserve. Observed resident memory rose above 5 GB with swapping on the shared measurement host; no sampled stack or isolated causal measurement establishes how much time was validation, serialization, disk publication or swapping. The earlier serialization diagnosis does not prove that restoring concurrency fixes scale finalization.

## Regression diagnosis and bounded changes

The [saved-artifact diagnosis](TIMEBOX_DIAGNOSIS_2026-11-07.md) compares baseline `725eb63` with `b88473c` and includes [all 100 per-company outcomes](evidence/timebox-20261107/per-company.csv). All five lost FTE positives were document deadline skips. Text-layer work totaled only 0.004034 seconds in the measured sample; page ordering and the two-worker limit were unchanged. Serialized discovery/OCR and a shorter document window are supported explanations. Each version's FTE output agrees with its own saved replay. A new cross-version replay from an identical capture was **not** completed: the stored source/control identities differ. This is not a controlled causal ablation.

Changes retained reliability fixes, added the POSIX research interrupt/SIGTERM recovery path, a 15% reserve and linear default, reduced repeated checkpoint serialization, and restored discovery/OCR overlap. No website/FTE extractor, ownership threshold or cohort-specific rule was tuned. Synthetic 100/1,000-row deadline/SIGTERM/replay tests passed, but did not predict successful live finalization or establish a 30-second SIGTERM bound for the real checkpoint. SIGTERM arrived during finalization after the research signal context had ended and terminated the process.

## Validation, package and unproven items

- Eight updated fixture tests passed, as did the corrected isolated deadline fixture. The local broad run had **1089 passed, 20 failed, 252 subtests passed**: 19 failures required missing macOS OCR/PDF modules/fonts, plus the deadline fixture subsequently fixed. This is **not** an all-tests pass.
- Exact commit `781ee14b231087e3680f209b063aacfe9733a7ba` CI had **1108 passed, one deadline-fixture failure**. The fixture correction at `48ade4072ed30cfd1c2d28cc4a1ce54b15dc7426` passed the complete starter-test step in CI run `42295260306`, but the workflow was still running at the timebox. Exact final-package CI must be checked independently. No full green CI claim is made here.
- A genuine timing-sensitive short-budget NAV replay completeness edge remains unresolved: captured NAV requests can remain unconsumed when the phase is marked deadline-skipped. Full-pipeline fixture budgets do not prove that edge correct.
- Pinned dependencies and wrappers are unchanged: install `./setup.sh`; run `SIGNALPOST_TIME_BUDGET_SECONDS=1800 ./run.sh --input companies.jsonl --output output.jsonl`. `run.sh` installs nothing. The measured failure means this command is **not a reliable completion guarantee**.
- The [limitations](../../LIMITATIONS.md), [package](SUBMISSION_PACKAGE_2026-11-05.md) and [unsent email draft](../../SUBMISSION_EMAIL_DRAFT.md) retain low-coverage warnings and the `[JBOX_SITE_URL]` placeholder. No email or submission was sent.
- Final state publication, complete counters, self-termination, exact replay at scale, all-green exact-commit CI, universal 30-second SIGTERM recovery and replacement safety remain failed or unproven. Work stops at the requested timebox; no additional engineering/live retry is authorized by this result.
