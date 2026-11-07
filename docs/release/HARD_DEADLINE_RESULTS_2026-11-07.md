# Independent-watchdog acceptance — FAILED

**Not safe to submit as a replacement.** Frozen implementation `3e8a8a0f1a2b1383098079e8376b1c69aba93ffc` passed exact-commit CI (run `42302252805`) but failed the prerequisite live 200-company gate. No new 1,000-company run or full offline acceptance replay was launched. CI success is not successful live acceptance.

## Documented budget and root cause

The [budget search](OFFICIAL_BUDGET_SEARCH_2026-11-07.md) found no numeric organizer time, CPU, RAM or request limit in the locally captured official documents. Equal fixed resources are required; numeric limits and injection remain unresolved. Project defaults are not organizer limits. A full BRREG bulk CSV is documented, but no compatible small multi-company financial-query contract was established; bulk acquisition was not implemented or claimed.

The [read-only diagnosis](DEADLINE_DIAGNOSIS_2026-11-07.md) and [sanitized statistics](evidence/deadline-20261107/prior-run-statistics.json) show the previous 1,000-company run **did stop research at 1,530 seconds**. Its remaining completion path was unbounded. Foundation/finance request overlap peaked at two despite four scheduler workers; gateway pacing was 3 starts/second. Foundation mean/p95 were 1.770/1.152 recorded company-seconds; finance completed mean/p95 were 1.423/4.418. These worker measurements do not equal phase wall time. The long foundation outliers waited before their sub-second physical requests.

Recovery, canonical-state construction, repeated graph validation, per-row SQLite FULL commits, large partial-file rewrites and a whole-batch checkpoint rewrite for a single lookup added work after research. No surviving stack/profile proves which one dominated. The row-number SQLite joins are not evidenced as the cause.

## Changes tested

- Initial complete, contract-shaped atomic output remains one row per input, now with `unknown:not_started`; periodic atomic fsync/rename flushes and phase-boundary flushes retain complete cardinality.
- An independent POSIX helper requests research stop at 85%, finalization by 92%, and emergency SIGKILL at 98%. Emergency termination is nonzero and never an acceptance pass.
- Final envelopes, terminalized shells and finalization statuses share one SQLite FULL transaction. Batch lookup status writes are grouped and no longer recompose/rewrite every company. Validated encoded output is reused; large orchestration caches are released.
- Official BRREG host capacity/pacing is eight slots/eight starts per second with adaptive throttling. Website capacity and all extraction/identity rules are unchanged. Optional work requires foundation and financial phases to finish or record source failures for every company.
- Socket connect/read waits and physical-attempt awaits are capped at ten seconds; company-phase awaits use a thirty-second timeout. These are **not universal physical/CPU deadlines**: cancelled threads can outlive awaits and synchronous work can delay cooperative timers. CLI exit avoids waiting indefinitely for leftover executor threads.
- Cancellation and strict replay were tested with stalled-company and stalled-transport subprocess fixtures. Empty-claim synthetic tests do not prove finalization capacity for real financial envelopes.

## Live 200 result

Started **6 November 2026 22:08:05 UTC**. Input SHA-256: `ffdc5ee5170b297feddf2811a166a64870ff0c1beb81d929f0913c561653081e` (first 200 rows of the previously frozen 1,000). Budget: **360 seconds**. Independent-watchdog thresholds: **306 / 331.2 / 352.8 seconds** from the run origin.

- **200/200 ordered contract-shaped rows**, all 200 checkpoint shells terminalized, all **2,200 required company-phase status records**, **zero duplicate/conflicting/missing claim IDs**.
- Process exit **-9** at driver elapsed **354.431 seconds**. The independent helper logged `force_exit_uncommitted`; the external 400-second watchdog was not responsible.
- **No committed output/state pair, state file or completion aggregate**. Recording was not sealed and output/state identities had not been recorded. Correct final-cardinality and status counters do not make this a completed run.
- Counts in preserved output only: **finance 196, explicit FTE 0, verified websites 0, jobs 0**. Optional work was incomplete; zeros do not establish absence. No coverage improvement or regression is claimed.

### Persisted phase measurements

Counts are disjoint: failed attempts are removed from the legacy receipt's overlapping `ran` count, and deadline skips from its total `skipped` count. Seconds sum persisted company records, **not CPU time or additive phase wall time**. Batch timings are replicated per company. Phase wall times and total finalization wall time are unknown because no aggregate survived. Request counts are physical-attempt receipts, including cancellations.

| Phase | Ran | Skipped | Deadline skipped | Failed | Recorded company-seconds | Physical attempts |
|---|---:|---:|---:|---:|---:|---:|
| Foundation | 200 | 0 | 0 | 0 | 231.976 | 202 |
| Financial API | 200 | 0 | 0 | 0 | 511.913 | 200 |
| Official details | 87 | 113 | 0 | 0 | 403.930 | 176 |
| Wikidata batch | 200 | 0 | 0 | 0 | 222.278 (replicated) | 1 |
| NAV batch | 200 | 0 | 0 | 0 | 8872.148 (replicated) | 15 |
| NAV apply | 0 | 200 | 0 | 0 | 0 | 0 |
| Annual documents | 0 | 4 | 194 | 2 | 214.737 | 9 |
| Website verify | 45 | 0 | 155 | 0 | 779.166 | 162 |
| Website shallow | 0 | 199 | 1 | 0 | 0 | 0 |
| Jobs/activity | 0 | 200 | 0 | 0 | 0 | 0 |
| Finalization | 200 | 0 | 0 | 0 | 24.036 | 0 |

All **765** physical receipts were readable: 733 received, 16 cancelled, 8 transport errors and 8 timeouts. A readable receipt set is not a sealed, replay-proven capture.

The new failure is localized **after the atomic final checkpoint transaction but before the first output/state identity save and paired publication**. The source places identity-cache release/GC, cardinality/status collection and fresh-byte construction in this interval. No completed profile identifies a unique dominant operation. The 85%-to-98% interval supplies only **46.8 seconds** for a real 200-company completion tail; the synthetic fixtures did not establish that this was sufficient. Do not infer that checkpoint terminalization alone solved publication.

## Failed gates and remaining limits

The 200 prerequisite failed process success, committed pair/state, aggregate and sealed recording. Its process did terminate within the numeric budget, but by emergency kill, not successful self-completion. The 1,000 gate therefore remained **not run**, not passed; full exact offline acceptance replay is **unproven**. Replacement safety is **false** under the user's definition.

Read-only review also found that the helper starts after initial input/checkpoint/partial-output preparation and stops before final stream flush; those standalone CLI gaps remain. Synchronous DNS and cancelled transport threads are not universally bounded by the await timeout. The acceptance wrapper can leave a child running if interrupted outside its timeout handler. These issues prevent a universal guaranteed-finish claim. A report that allows complete failed envelopes is operational acceptance only, not successful research or precision qualification.

No FTE/website extractor, financial semantics or identity threshold was tuned. Pinned dependencies, models/APIs/licenses and the no-install `run.sh` contract remain unchanged. Install: `./setup.sh`. Run: `SIGNALPOST_TIME_BUDGET_SECONDS=1800 ./run.sh --input companies.jsonl --output output.jsonl`. This failed measurement does not make that command a guaranteed scored completion.

The original work window was **21:42:55–23:12:55 UTC on 6 November**. The subsequent context handoff resumed after that deadline; no further engineering or live run was started. A requested offline profile had not produced a terminal result and was cancelled during wrap-up. No new 200 attempt was launched. Raw artifacts remain private at `pancakes:/home/azureuser/projects/signalpost-hard-acceptance-3e8a8a0`; the [sanitized receipt](evidence/deadline-20261107/live-200-report.json) preserves hashes and gates. No email or submission was sent; the JBOX placeholder remains unset.
