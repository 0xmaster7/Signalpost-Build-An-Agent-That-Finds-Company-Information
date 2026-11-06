# Matched timing and FTE diagnosis — read-only saved artifacts

Baseline 725eb63 versus release b88473c (measured research implementation 676d6e5). Derived from private saved matched/live and matched-replay artifacts over authorized SSH; no live source requests, code edits, commits, deletes, capture changes or new replays. Output created only in /tmp/signalpost-timebox-diagnosis-20261107.

## Findings

All five lost positives (914631408, 923799206, 925733415, 997722094, 921257953) are candidate document deadline skips. All 18 candidate positives were already positive in baseline; no gains. This localizes the observed FTE loss to work not completed by the candidate, rather than demonstrating an extractor rejection of those five documents.

FTE transitions: {'retained': 18, 'absent_both': 77, 'lost': 5}. Every per-company published FTE value/period/scope/rule equals its own saved replay: True. This checks FTE subsets; exact full output/state identity is supported separately by existing replay receipts.

Process aggregate runtime: 1127.762 → 1595.038 seconds, delta 467.276. Published baseline 1128.650 is driver elapsed, while 1127.762 is process aggregate; candidate driver elapsed is 1596.053 versus process 1595.038. The release headline 466.388 mixes baseline driver and candidate process timing; like-for-like process increase is 467.276 seconds (driver increase 467.403).

## Phase wall timing

Seconds; not additive for baseline because document and network discovery overlap. official=0 is unused, not measured foundation time. Official details were part of baseline foundation and have a separate candidate pass.

| Phase | Baseline | Candidate | Difference |
|---|---:|---:|---:|
| official_foundation | 126.429 | 44.196 | -82.233 |
| financial_statements | 48.281 | 59.305 | +11.024 |
| official_details | unavailable/separate pass absent | 100.184 | not comparable |
| wiki_batch | 0.950 | 1.476 | +0.525 |
| nav_batch | 359.598 | 359.575 | -0.023 |
| nav_apply | 1.553 | 4.115 | +2.563 |
| website_verify | 189.978 | 180.112 | -9.866 |
| website_shallow | 0.000 | 0.000 | -0.000 |
| jobs_activity | 0.000 | 0.000 | -0.000 |
| annual_documents | 900.036 | 733.919 | -166.117 |
| finalization | 14.809 | 26.147 | +11.338 |

## Per-company FTE losses and gains

| Organisation | Transition | Baseline document outcome/reason | Candidate document outcome/reason |
|---|---|---|---|
| 914631408 | lost | completed: verified_document | deadline_skipped: phase_deadline_or_completion_reserve |
| 923799206 | lost | completed: verified_document | deadline_skipped: phase_deadline_or_completion_reserve |
| 925733415 | lost | completed: verified_document | deadline_skipped: phase_deadline_or_completion_reserve |
| 997722094 | lost | completed: verified_document | deadline_skipped: phase_deadline_or_completion_reserve |
| 921257953 | lost | completed: verified_document | deadline_skipped: phase_deadline_or_completion_reserve |

## Concrete components and causal limits

1. **Optional scheduling serialized:** baseline signalpost/run.py uses asyncio.gather(network_discovery_phase(), document_phase()); candidate iterates network_discovery_phase then document_phase. Baseline could hide roughly 360 s NAV plus 190 s website work under its 900 s document window; candidate pays those sequentially. This structural change explains why a shorter document phase can coexist with a substantially longer batch. The observed delta is not an isolated causal estimate: source responses, config, persistence, breadth/detail split and timings changed together.

2. **Deadline window shrank:** baseline config hard/soft/reserve = 2700/2214/486 s; candidate 1800/1500/300 s. OCR allocated 900.000 → 834.829 s, but candidate documents actually got only 733.919 s because allocation was computed before NAV/web then clipped by the remaining global research window. Baseline documents completed 35 successful phases + 1 transport failure, 62 deadline skips, 2 ineligible; candidate 28 successful + 1 failure, 69 deadline skips, 2 ineligible. The CSV distinguishes admission, processing and FTE publication.

3. **Worker contention:** baseline document scheduler and processor both limit to 2 workers. Candidate is core-bounded up to 4, hence still 2 on this measured two-core host (worker_limit in candidate CSV confirms where audited). No evidence supports blaming an increased OCR worker count here. Baseline concurrent networking/persistence could contend with OCR; candidate serialization removes overlap but sacrifices latency. Queue waits are scheduler waits, not direct CPU contention measurements. No sampled CPU/IO profile exists.

4. **Text attempts:** baseline already attempts searchable PDF text before OCR. Candidate changes object scanning to depth 8 and allows small images/forms, plus timing metrics. Therefore text-first is not wholly new. Candidate persisted 0 successful text-layer pages and 50 OCR pages; missing/interrupted metrics are not zeros. Recorded text checks must be compared with worker/OCR metrics below; the completed-worker text-check total is 0.004034 seconds, so these persisted checks do not explain the 467 s runtime increase. Interrupted checks remain unmeasured.

5. **Page ordering unchanged:** both commits verify cover page 1, then prioritize pages 5,4,6,3 before remaining pages, stopping at the first verified company FTE page. PARSER_VERSION, OCR_MODEL and FTE_STRATEGY strings are unchanged. Page order is a potential future cost lever, not an evidenced cross-version regression. No page-order or extractor tuning is recommended from this matched sample.

6. **Persistence and details:** candidate adds partial-envelope publication/checkpoint writes and a separate official-details phase. Foundation becomes faster, while details and finalization add wall cost. These counters locate overhead but do not isolate I/O latency. The scale run failed to finish even after its 1800-second configured total (external termination at 2100 seconds); completion reliability takes precedence over optional coverage.

## Recorded document metric aggregates

baseline: {"download_seconds": {"reported_rows": 0, "sum": 0}, "ocr_engine_seconds": {"reported_rows": 0, "sum": 0}, "ocr_pages": {"reported_rows": 0, "sum": 0}, "ocr_seconds": {"reported_rows": 36, "sum": 644.29}, "processing_seconds": {"reported_rows": 36, "sum": 1744.551}, "text_layer_pages": {"reported_rows": 0, "sum": 0}, "text_layer_seconds": {"reported_rows": 0, "sum": 0}, "worker_seconds": {"reported_rows": 0, "sum": 0}}

candidate: {"download_seconds": {"reported_rows": 29, "sum": 133.606685}, "ocr_engine_seconds": {"reported_rows": 29, "sum": 322.05067}, "ocr_pages": {"reported_rows": 29, "sum": 50}, "ocr_seconds": {"reported_rows": 29, "sum": 1147.772}, "processing_seconds": {"reported_rows": 29, "sum": 1282.062}, "text_layer_pages": {"reported_rows": 29, "sum": 0}, "text_layer_seconds": {"reported_rows": 29, "sum": 0.004034}, "worker_seconds": {"reported_rows": 29, "sum": 324.19902}}


Candidate has 9 internal OCR-deadline outcomes, totaling 810.468 recorded OCR request seconds, versus 10 baseline OCR-deadline outcomes. Candidate OCR request time includes waiting/timeout and is not engine CPU time. The baseline did not populate timeout OCR duration in its exception path; the candidate adds this in finally. Therefore 644.290 → 1147.772 OCR audit seconds is an instrumentation change as well as a workload change and must not be presented as an OCR engine slowdown. Candidate completed-worker text checks total only 0.004034 seconds; completed engine time is 322.051 seconds. Interrupted worker engine time is not reported.

PDF hash CSV columns are unavailable from these decoded document audit rows and remain blank. The existing release document-comparison receipt provides candidate hashes and only admits baseline comparisons when the same organisation has an identical non-null PDF hash. This diagnosis does not claim source-PDF equality for all 100 companies. Metric sums with reported_rows=0 mean unavailable, not measured zero.

## Replay compatibility

A full supported cross-version identical-capture replay is unavailable: signalpost/run.py checks capture implementation_identity against a hash of all signalpost Python sources plus pyproject.toml/uv.lock before replay, and raises on mismatch. The captures also encode request purpose/company/phase/timeouts, exact execution phase outcomes/allocations and output/state identity. Candidate adds official_details and changes request/execution structure. Disabling these checks would create a new experimental harness, not a supported exact replay. No such bypass or cross-version replay was performed. Existing baseline and candidate own-capture replays prove reproducibility only within their recorded implementation, not causal equivalence across versions.

Capture manifests: baseline 818 request keys / 861 saved physical attempts; candidate 749 keys / 763 attempts; common exact request keys 480, baseline-only 338, candidate-only 269. Matching request keys do not establish matching bodies. Actual network requests 861 → 763. Implementation identities: baseline 8ee241caa9741b69e12d81d7b8cd2621de5c0fd99d64bb0730a75831e9d545e8; candidate 4d01cd2f4339e77174a30f3352c2f624373f53a3c57833a8d9f2e5fa49ba4d76.

## Minimal correction priority (assessment only)

First bound finalization/persistence and publish partial/final status honestly under a monotonic total deadline; reserve a measured completion margin rather than treating 1800 seconds as a proven hard wall. Next make optional allocation correspond to actual start time: reserve a bounded document window before NAV/web depth, or interleave bounded optional quanta while keeping breadth and finance first. Moving documents ahead of the full NAV traversal is a minimal ordering candidate; recomputing allocation only after NAV avoids stale budgets but does not restore consumed time. Do not simply restore unrestricted overlap or increase workers on two cores. Any change needs deterministic offline deadline/cancellation/publication checks and a separately authorized validation cycle; no coverage gain or ≤1200 s runtime is established. Keep strict FTE/website publication rules, page order and site heuristics unchanged.

## Evidence paths

- Local release: /tmp/signalpost-final-20261105/docs/release/FINAL_RESULTS_2026-11-06.md and evidence/final-676d6e5/{matched.json,matched-replay.json,PHASES.md,document-comparison.json}.
- Baseline sanitized metadata: /tmp/signalpost-acceptance-public-725eb63/{reports.json,matched-per-company.jsonl,matched-replay-per-company.jsonl}.
- Private SSH pancakes roots: /home/azureuser/projects/signalpost-crashsafe-acceptance-725eb63 and /home/azureuser/projects/signalpost-final-acceptance-676d6e5; inspected matched/{report.json,invocation.json,stdout.log,envelopes.jsonl,checkpoint.sqlite,http-capture/manifest.json,http-capture/execution.json}, matched-replay/envelopes.jsonl, and root config.json. SQLite opened mode=ro&immutable=1; saved WAL was zero in inspected matched artifacts.
- Source comparison: git 725eb63..b88473c, especially signalpost/{run.py,annual_accounts.py,execution.py,recording.py}.

CSV contains all 100 matched companies, their own saved replay FTE outcomes, document statuses, phase/queue timing and available audit metrics. Blank metrics mean unavailable, not zero. FTE values are serialized lists to preserve periods/scope/rules. No private response bodies are exported.
