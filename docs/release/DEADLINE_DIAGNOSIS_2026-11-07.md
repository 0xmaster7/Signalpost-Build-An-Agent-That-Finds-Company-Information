# Frozen-run diagnosis: 1,800-second deadline / 728 terminalized rows

## Finding and scope

The supported failure mechanism is an **unbounded completion path after a research-only deadline**. The 85% signal stopped research, but did not impose a deadline on recovery, canonical-state construction, per-row validation/checkpointing, or paired publication. At external termination, the process had durably finalized envelope 729, while only shells 1–728 were durably terminalized. It had not reached paired publication. This is a completion-budget failure, not evidence that the research signal failed.

The source identifies substantial synchronous validation, serialization and durable-write work on that path. The capture does **not** contain a profiler, stack at termination, or stage wall timers sufficient to identify a single dominant CPU/I/O operation. Claims that a particular SQLite fsync, Pydantic validator, SQL join, thread join, or partial rewrite alone caused the overrun would exceed the evidence.

Read-only investigation; no source edits, source execution, replay, or live service requests. SSH was used only to read the existing frozen source and private run artifacts. Local output is this report and sanitized aggregate statistics, `/tmp/signalpost-90min-stats.json`; no response bodies, company names, credentials or cookies were copied into them.

- Operative checkout: `/tmp/signalpost-final-20261105`, commit `a72c96de5a0cb4d45e3753185c043fc36b5f5760`.
- Failed source: `fc39bb01483e54e85e836c72ff3faa8312ac99c3`, remote checkout `pancakes:/tmp/signalpost-bounded-fc39bb0`.
- Frozen evidence: `pancakes:/home/azureuser/projects/signalpost-bounded-source-fc39bb0/live/{invocation.json,report.json,checkpoint.sqlite,checkpoint.sqlite-wal,http-capture/*,envelopes.jsonl.publication.json}` and adjacent `config.json`.
- The committed run.py, operations.py, network.py, models.py, deadlines.py, recording.py, adapter.py, history.py and financial_calibration.py are identical between fc39bb0 and a72c96d. Source references below are **fc39bb0 line numbers**, read with `git show`, independent of concurrent working-tree edits.
- SQLite opened with `mode=ro`, with the existing WAL visible. All 2,027 captured attempt records and the two metadata files passed their stored SHA-256 wrapper checks. This verifies internal consistency, not a sealed complete run: manifest `complete=false`.

## Actual execution settings

The manifest's effective `request_configuration.budget`, rather than the input config alone, establishes:

| Setting | Actual value |
|---|---:|
| Hard budget | 1,800 seconds |
| Research/soft budget | 1,530 seconds |
| Completion reserve | 270 seconds |
| Global HTTP slots | 32 |
| Slots per host | 2 |
| Foundation / finance / official-details workers | 4 each |
| BRREG initial pacing | 3 starts/second, at least 0.333333 seconds apart |
| Physical request ceiling | 8,000 |
| Logical, per-company, per-host request ceilings | unset |
| Paid-cost ceiling | 0 |
| Gateway timeout / retry default | 20 seconds / 1 retry |
| Finance retries | 0 during the finance phase |
| Finance allocation actually recorded | 800 seconds |
| Official-details allocation actually recorded | 68.552366 seconds |
| Later website / OCR allocations | 8.395119 / 5.456827 seconds |
| Later NAV allocation | 2.497709 seconds |

Input config specified soft=1,500/reserve=300 and financial_seconds=180. `--budget-seconds 1800` invokes `_with_global_budget` (run.py:54), replacing the split with 85%/15%. Finance allocation uses `max(financial_seconds, pending_companies * 0.8)` (run.py:985–990): with 1,000 pending companies, 800 seconds was actually reserved. Reading 180 seconds from config would misdescribe this execution.

The gateway host limiter and `_pace` apply inside the global semaphore (network.py:607–612, 817). The scheduler's four workers therefore did not imply four simultaneous BRREG requests. Captured start-to-retrieval intervals have maximum overlap **2** for foundation, finance and details. Foundation start gaps: minimum 0.333366, median 0.420401 seconds; finance: minimum 0.333429, median 0.553096. These intervals include capture bookkeeping and are observations of recorded intervals, not server-side concurrency measurements.

BRREG document processing changes host pacing to one start per 2.1 seconds, restoring 3/second after its phase (run.py:1382,1401). Only one annual-document attempt was captured, cancelled at research termination, so sustained document pacing cannot be measured. There were no captured 429/503 responses in these phases, hence no captured response-based adaptive slowdown trigger. Robots attempts failed twice for BRREG; no BRREG robots response supplied a crawl-delay.

## Per-company duration distributions

Percentiles use linear interpolation at `(n-1)*p`. Seconds are elapsed wall time accumulated by the existing worker/phase instrumentation, **not CPU time**. Overlapping workers cannot be summed into batch wall time. The finance completed population includes 404/no-data outcomes.

| Recorded population | n | mean | p50 | p90 | p95 | p99 | max | sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Foundation, all ran (999 completed, 1 failed) | 1,000 | 1.770324 | 0.810793 | 1.067393 | 1.151843 | 1.502749 | 452.084860 | 1,770.323686 |
| Finance, completed | 947 | 1.423118 | 0.932822 | 3.112610 | 4.418256 | 5.251415 | 7.279736 | 1,347.692423 |
| Finance, all inputs including 53 deadline skips | 1,000 | 1.347692 | 0.928104 | 3.018092 | 4.316357 | 5.223993 | 7.279736 | 1,347.692423 |
| Official details, completed | 35 | 3.304717 | 1.874164 | 6.283875 | 6.553149 | 7.673978 | 8.104312 | 115.665085 |
| Finalization statuses durably recorded | 729 | 0.135441 | 0.098093 | 0.141817 | 0.190462 | 0.314241 | 8.284133 | 98.736407 |

Foundation outliers are input rows **3 and 4**, at 451.755570 and 452.084860 seconds. Their individual entity attempts took only 0.764420 and 0.761485 seconds and completed at the very end of foundation. This establishes a long pre-response scheduling/wait interval, not a 452-second remote response. The host condition limiter has no FIFO admission guarantee (network.py:154 onward); however, the frozen evidence does not expose the suspended stacks, so the exact waiting primitive and a unique starvation explanation are not proven.

For a second independent view, sum captured request `elapsed_ms` by company:

| Population | n | mean | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|
| Foundation, including attributed robots attempts | 1,000 | 0.802230 | 0.763168 | 1.090780 | 1.381501 | 1.686566 |
| Finance, companies with an attempt, including cancellations | 949 | 1.242076 | 0.772262 | 4.298517 | 5.081335 | 7.122653 |

Request elapsed starts after the capture reservation writes and excludes preceding admission/pacing; asynchronous response observation can include event-loop delays. It is not pure network latency. Foundation phase timing ends before `on_complete` publication. Finance `persist_phase` adds publication work to the saved status before the subsequent `save_phase` and partial update (run.py:833–885). Consequently foundation and finance status seconds have different coverage, and neither table measures the complete end-to-end cost per company.

## Requests per company: physical attempts, not estimates

Capture files are **physical attempt records** (`variant_policy=ordered-physical-attempts`). Retry settings are not observed retry counts. Logical gateway totals/cache hits cannot be recovered exactly from these records alone.

| Phase | Physical attempts | Companies with attempts | Distribution across 1,000 inputs |
|---|---:|---:|---|
| Foundation | 1,002 | 1,000 | 999 companies × 1; 1 company × 3 (entity + 2 shared robots attempts) |
| Finance | 949 | 949 | 949 × 1; 51 × 0 |
| Official details | 73 | 37 | 36 × 2; 1 × 1; 963 × 0 |
| Annual documents | 1 | 1 | 1 × 1; 999 × 0 |
| Wikidata batch | 1 | batch scope | Not a request per input |
| NAV batch | 1 | batch scope | Not a request per input |
| Total | **2,027** | — | Includes robots and cancelled attempts |

Foundation requests: 1,000 entity HTTP 200, plus 2 robots transport errors attributed to the first company context. Thus mean requests/company is 1.002, p50/p95/p99=1, max=3; the shared robots attribution is not three independent company research calls.

Finance requests: **935 HTTP 200 + 12 HTTP 404 + 2 cancelled = 949**. Durable outcomes: 947 completed + 53 deadline skipped. The two cancellations explain why 949 attempted companies exceed 947 completed companies; 51 had no recorded finance attempt. Across all inputs mean=0.949, p50/p95/p99/max=1. Among attempted companies all counts are 1. The 53 saved skips have zero seconds after bookkeeping replacement; zero does not establish that no work was attempted.

Details: 71 HTTP 200, 2 cancelled; 35 durable completions and 965 deadline skips. Wikidata: one HTTP 200 for a query requesting 200 companies, with 800 omitted; marking its batch phase completed for all 1,000 is not evidence of 1,000 researched Wikidata companies. NAV captured only a cancelled robots request. No website verify/shallow/jobs requests were captured.

## Timeline and why the reserve did not finish the run

All times UTC. Runtime clock in the capture starts at **20:51:42.098111**; the outer invocation began 0.371 seconds earlier.

- Foundation last response: **20:59:15.023137**, about 452.925 seconds after runtime start.
- Finance first/last response observations: **20:59:15.934041–21:12:37.553194**. The 800-second phase timeout includes synchronous completion hooks and waiting; saved worker seconds are not its wall duration.
- Details first/last response observations: **21:12:38.743446–21:13:47.760969**.
- Wikidata response: **21:14:05.269043**, elapsed 1,343.171 seconds. The batch source elapsed recorded for every company is 5.486672 seconds. Summing those 1,000 identical statuses gives 5,486.672 seconds, **not** the source wall duration.
- The later website allocation of 8.395119 seconds implies `available_research` was evaluated at elapsed approximately **1,521.604881** (run.py:1313 onward), about **178.434 seconds after the Wikidata response**. Between them the code records 1,000 individually committed batch statuses, composes all rows and saves their envelopes. The gap is supported; division into status fsync, composition, validation and persistence time is unavailable.
- Research alarm target: **21:17:12.098111** (1,530 seconds). Annual-document cancellation observation: **21:17:12.109575**. Execution controls persist `bounded_frontier.reason="deadline"`, retaining 1,983 phase results: 1,000 foundation + 947 finance + 35 details + 1 Wikidata batch. This establishes the deadline recovery path actually ran.
- Outer invocation terminated with **exit -15**, `external_timeout=true`, at **21:22:12.606269**, elapsed **1,830.864 seconds** from invocation start. Hard 1,800-second contract missed by 30.864 seconds. Approximately 300.5 seconds elapsed from the intended research boundary to termination; exact start time of the per-row finalization loop is absent.

The durable boundary is more precise than the report's headline count:

- shells 1–728: `terminalized`; shells 729–1000: `baseline_done`;
- finalization statuses 1–729: `completed` (729 statuses);
- checkpoint envelope **729 already has current_state_ref, synthesized summary and RESEARCH_INCOMPLETE**, establishing its finalized payload was committed;
- checkpoint envelope **730 has no current_state_ref or summary**, and remains the baseline payload;
- therefore termination occurred **after the durable put for 729 and before the durable finalization-status commit for 730**. Row 729's shell update was not durably committed. This does not identify the active Python/C frame.

Published `envelopes.jsonl` is 485,318,083 bytes with 1,000 rows, while its marker remains `status=partial`, `canonical_pair_committed=false`. There is no state.json, completion aggregate, capture sealing or paired commit marker. Complete cardinality and recognized terminal states in a provisional artifact do not satisfy finalization/publication.

## Source trace: loops, graph validation, commits, rewrites and joins

1. **Deadline covers research only.** run.py:1607 wraps `asyncio.run(guarded_enrich())` in `signal_deadline(soft_seconds-elapsed)`. `ResearchDeadline` is a BaseException and escapes ordinary Exception handlers. deadlines.py:85–91 disables the timer and restores prior signal handlers on context exit. run.py:1613 then recovers checkpoint data and continues outside that deadline. There is no corresponding hard timer or deadline gate around run.py:1694–1785. `ResearchDeadline.finalizing()` exists but is not invoked by this run.py. No supported evidence says a second research alarm should stop finalization.

2. **Async cleanup is part of the unmeasured boundary.** `guarded_enrich` stops and awaits the partial flusher in `finally` (run.py:1598); its flusher forces publication in its own `finally` (operations.py:791). `asyncio.run` also performs its normal task/executor shutdown; the transport uses `asyncio.to_thread`. None of the frozen artifacts times this shutdown or supplies thread stacks. A blocked thread join cannot be claimed as the cause: the later durable finalization rows show cleanup and recovery were passed. Any delay before those rows remains unallocated.

3. **Recovery and canonical state work precede the finalization timer.** run.py:1640 reloads every checkpoint envelope with model validation; run.py:1694–1709 builds/merges all canonical company states, serializes the whole state artifact and computes its hash. `company_state` dumps claims/evidence/snapshots and hashes/groups claim semantics (history.py:225); artifact_payload dumps all company states (history.py:350). This whole preparation is outside both the research timer and recorded per-company finalization seconds.

4. **Repeated full-envelope validation is real, but each put is not a whole-batch revalidation.** `_finalize_company` synthesizes, calls `validate_batch_publication_graph([envelope])`, then `to_evaluator`, which revalidates the envelope again (run.py:84–106; adapter.py:52 onward). `checkpoint.put` calls `_EnvelopeIdentityIndex.prepare`, performing another dump/revalidate and building evidence/snapshot signatures before model_dump_json and SQLite replacement (operations.py:303,441). `Envelope` validation checks the complete provenance graph and calls financial-unit validation (models.py:308–366). Its per-claim scan of all evidence and the per-financial-claim metadata scan of all claims (financial_calibration.py:179) are repeated Python joins with potentially multiplicative per-envelope cost. The incremental cross-envelope identity index already exists; it does not scan/revalidate all 1,000 envelopes on every put. These are source-established work patterns, not profiled percentages of this failure.

5. **Finalization commits are split.** For each row, run.py:1732 first saves phase status with its own transaction; 1735 calls `checkpoint.put` with another transaction; 1736 issues a shell UPDATE without an immediate commit. That shell change is normally committed by the next row's status transaction, or the final loop commit (1737). SQLite uses WAL and `synchronous=FULL` (operations.py:361–362). The observed finalized envelope 729 / terminalized shell 728 difference is exactly compatible with this non-atomic ordering. At least 1,458 successful per-row status/put transactions were traversed for the 729 durable finalized envelopes, with further writes before and after the loop.

6. **The finalization metric excludes the expensive tail around it.** The per-row stopwatch is read when constructing arguments for `save_phase_status`, before that status commit, `checkpoint.put` validation/serialization/commit and shell update. Consequently the 98.736407-second sum does not measure the 729-row terminalization loop wall time. The aggregate `finalization_started` is set only at run.py:1751, **after** all rows and shell updates, so even a completed run's `finalization_seconds` excludes recovery, canonical-state preparation and the entire per-row loop. In this run it was never emitted. There is no sound subtraction yielding an exact SQLite-time figure.

7. **Partial publication rewrites the full artifact.** `PartialEnvelopePublisher` defaults to 25 updates or 5 seconds, with a forced final flush (operations.py:724–799). It caches serialized unchanged rows, but `flush` still atomically writes all rows, fsyncs the file, replaces it, and fsyncs its directory, plus writes/fsyncs a partial marker. Foundation and `persist_phase` callbacks run synchronously within scheduler worker completion, so they delay other coroutine progress (operations.py:584–589; run.py:1063,881). At the observed artifact size, each late flush can copy roughly 485 MB. Exact flush count and total write time/bytes are not recorded; multiplication by an assumed flush count would be conjecture.

8. **Batch publication and capture bookkeeping also run synchronously.** `batch_phase` loops over 1,000 `save_phase_status` calls, then calls `save_phase` with every newly composed envelope (run.py:936–946). This performs full-batch composition/validation/serialization and durable storage even for the single Wikidata result. The ~178-second interval above bounds a mixed bookkeeping interval, not just Wikidata HTTP time. HTTP recording itself writes/fsyncs an attempt reservation, the growing manifest, then the response artifact per attempt (recording.py:93,139–173); its time is partly outside captured request elapsed. These mechanisms explain why sums of HTTP seconds cannot account for total run wall time without further instrumentation.

9. **SQLite joins are straightforward state selection, not an evidenced Cartesian explosion.** operations.py:420/424 join envelopes to shells USING(row_number), with both row_number columns primary keys. Those paths are called on resume; this invocation did not specify `--resume`. Deadline recovery uses `checkpoint.rows()` ordered by row_number (operations.py:484), not those joins. In-memory provenance/metadata joins described above do execute during validation. No query-plan/stack evidence supports blaming the row-number SQL joins for this run.

10. **Paired publication remains additional work after all 1,000 rows.** run.py:1752 validates the complete batch; 1756 joins freshly serialized evaluator rows into one bytes object for capture identity; sealing and paired state/output publication follow at 1765/1783. None had been reached at the durable boundary. Fixing only the last 272 shell states would not establish that the remaining serialization, fsync and pair-commit work fits the budget.

Evidence of scale: checkpoint envelope payloads total 481,225,757 SQLite text characters; retained phase-result payloads include 220,776,158 finance characters and 29,545,966 foundation characters. Database file: 750,071,808 bytes; WAL: 444,065,992 bytes. These demonstrate substantial retained/rewritten data, but file sizes are not a measurement of cumulative I/O or fsync latency.

## Separate failure and limits on causal claims

One foundation company has `BRREG_PUBLICATION_GRAPH_REJECTED`, reason **"official publication failed: ValueError"**, traceback fingerprint `b8a923035ebb34d0b5ad54ea40adee27daf6ccff1ea7429a58046e0626107e57`. The public failure helper intentionally retains only exception type and traceback hash (phases.py:12). Empty stdout/stderr and report `failure_evidence.traceback_frames=[]` provide no underlying frames or original ValueError message. Therefore the specific rejected invariant is unknown, and there is no evidence that this isolated failure caused the deadline overrun. Likewise the 12 finance 404s are recorded no-data outcomes, not evidence of the completion failure's cause.

The defensible parent-edit target is the completion contract: budget and time the **entire** recovery/finalization/publication path, atomically couple final envelope/status/shell progress, and reduce the repeated synchronous publication work while preserving graph checks and crash durability. The present evidence supports investigating indexed validation joins, batched status commits, partial-flush policy and capture bookkeeping, but does not support promising a particular speedup or calling any one of them the measured dominant bottleneck. Any 90-minute extrapolation would be unsupported by this single 30-minute failed run; the requested filename is retained without treating it as a measured 90-minute result.
