# Crash-safe recording and replay integration

The parent integration is implemented in `run.py`, `execution.py`,
`operations.py` and the OCR wrapper. Synthetic end-to-end tests compare freshly
computed complete JSONL and state bytes with DNS and transport forbidden during
replay. This is not a claim that live smoke or cohort replay has passed.
Admission, batch budgets, source timestamps, negative DNS outcomes and OCR audit
controls are recorded; company fact graphs and saved final outputs are never
used as replay inputs. Finalization failures are isolated per company. Replay
errors still publish complete failed envelopes before returning nonzero.

Transport implementation owns `network.py`, `recording.py`, the dedicated
recording tests, and timestamp-only changes in BRREG, website, and annual PDF
adapters. The checklist below documents the integration contract and remaining
live verification. No live calls are needed for synthetic tests.

## What is implemented

New captures use manifest version 2. Existing version 1 stores are rejected;
they cannot prove complete request accounting and must not be rewritten.
Every gateway transport attempt reserves its sequence position **before I/O**
and atomically writes an incomplete receipt. It then records received raw bytes
(including PDFs, redirects, 429 and 5xx bodies), timeout, connection failure,
cancellation, or unexpected transport failure. Exceptions' messages and request
authorization headers are never captured. A crash leaves an incomplete receipt.
Cancellation replays as `CancelledError`; phase scheduling/application still
requires the trace below. Unexpected transport exceptions remain visible but
cannot seal a successful capture; replay rejects them rather than guessing an
exception class/message or fabricating its result.

Request identity contains explicit `method: GET`, canonical URL with its exact
query spelling, ordered decoded parameter pairs (including duplicates/blanks),
source policy, company scope, conditional date, and effective transport settings.
This is a GET-only gateway; future methods/bodies need a separately audited key
policy. Query credentials are refused before I/O. Stores stay private (0700/0600)
and outside Git; NAV public-token **response bodies** remain private raw input.
Execution metadata is also private: callers must supply no credential fields.

`gateway.observed_at` is the exact timestamp saved in the physical receipt,
scoped to the calling task and gateway. Coalesced callers inherit that timestamp.
BRREG, PDF, HTML, and XML-feed evidence use it. Previously downloaded HTML keeps
its original timestamp when parsed later. NAV already used this API.
Ledger IDs/durations are captured and restored. Replay yields one event-loop
checkpoint for in-flight coalescing without a sleep, DNS, proxies, or HTTP.
It still applies URL, SSRF literal/local-host, robots, redirect, allowlist, and
source-profile policies; a replay miss never falls back to the network.

## Integration contract, before claiming live byte identity

1. Restore `manifest["run"]` run-start/cutoff and validate input/config identities
   before work. Record the chosen batch ID and restore it on replay. Allocate
   envelope `created_at`, refresh attempt times, and frozen-registry retrieval
   times from a stable run clock or explicit recorded clock controls. Avoid
   globally monkeypatching time: operational wall deadlines still need a real
   monotonic clock. Reject incompatible code/extractor/OCR strategy identities.
   In particular, `_website_profile` must attach `retrieved_at` to frozen
   website candidates; otherwise `_source_evidence` still needs its compatibility
   wall-clock fallback. Always pass the restored explicit website evidence cutoff.
2. Record an execution trace with `recording.record_execution(name, value)`;
   replay reads it with `replay_execution(name)`. Suggested per-phase keys:
   `phase:<name>:schedule`, `phase:<name>:audit`, `row:<row>:clock`, plus `batch`.
   Schedule controls contain ordered admitted company/phase work, launch and
   result-application order, dependency decisions, deadline/budget skips,
   cancellations, and the phase's logical elapsed-time/budget observations.
   Live pacing often exhausts a deadline where instantaneous replay would
   admit another phase. Replay must follow recorded admission/skip decisions,
   execute every admitted extractor, and assert the observed request/result
   shape. Do not just disable deadlines and allow uncaptured work. A partial
   trace must fail, never silently skip work until misses reach zero.
3. **Reexecute real extractors.** HTTP responses and cache-only OCR page input
   are raw inputs. Recompute BRREG projection, OCR reconciliation, website/NAV
   extraction, graph validation, synthesis, refresh state, and serialization.
   Never load saved final envelopes or saved phase fact graphs as replay output.
   Before restoring audit-only timing/cache annotations, call
   `assert_identity("phase:<name>:<org>:facts", fresh_fact_bytes)` over the full
   newly computed semantic result (claims, evidence, snapshots, states, errors).
   On live capture this stores only SHA-256 and length; replay compares them.
4. OCR wall duration, processing duration, cache-hit flags, and scheduler audit
   timing are observational metadata, not evidence. A live cache miss becomes a
   replay warm-cache hit. Store those original audit controls explicitly and
   apply them only **after** fresh semantic identity succeeds. Otherwise exact
   envelope bytes will differ even when extracted facts match. Missing OCR pages
   must fail without workers/HTTP. Cache strategy/content identities must match.
5. Before publication, pass the exact fresh serialized JSONL bytes (same
   evaluator serializer, order, UTF-8, separators and trailing newline) to
   `assert_identity("envelopes", fresh_jsonl_bytes)`. Also assert state bytes if
   paired state identity is claimed. This helper returns no saved output. Do not
   weaken comparison to just claims or strip unexplained fields to make it pass.
6. After a successful live run, fully drain tasks, save controls and identities,
   then `recording.seal()`. On replay call `recording.assert_complete()` before
   writing successful artifacts. This requires a sealed capture, zero misses or
   invalid loads, and consumption of every indexed physical attempt. A swallowed
   extractor ReplayError therefore still prevents success. Do not seal a failed
   run, resume into a new capture without an explicit full-input trace, or treat
   an unsealed directory as a complete successful capture.

`assert_complete()` and `assert_identity()` raise `ReplayError`. The CLI should
catch this at its normal failure boundary, emit `recording.diagnostics()` (or
`gateway.replay_missing_requests`) and fail nonzero without publishing success.
Diagnostics include each missing **key, attempt position, full safe request
descriptor**, plus unconsumed request keys/positions; do not print only a count.
No credential hashes/headers or original exception text are in these entries.

## Validation and limits

Dedicated synthetic transport tests verify GET/parameter keys, exact missing-key
reports, failure/timeout/429/redirect/raw PDF accounting, initiation order,
incomplete crash receipts, unconsumed requests, sealed-capture requirements,
execution controls, fresh-byte mismatch rejection, identical replay ledger and
retrieval clocks, and real BRREG extractor claim/evidence/snapshot equality.
Replay tests forbid DNS, socket connects, proxy discovery, HTTP and sleeps.

Pancakes validation used the parent checkout's root `.venv/bin/python`
(`/tmp/signalpost-crashsafe-tests-20261101/.venv/bin/python`) with `PYTHONPATH`
and all test artifacts under `/tmp/signalpost-recording-tests-20261101`:

- Network/BRREG/budget/NAV/existing pipeline replay: 202 tests, 48 subtests passed.
- Recording plus website/PDF/OCR-adapter regressions: 109 tests, 16 subtests passed.
- Final recording suite after cancellation checkpoint hardening: 33 tests passed.
- Logs: `recording-regression-results.txt` and `recording-adapter-results.txt`
  and `recording-final-results.txt` in that isolated test directory. The
  historical frozen run was not modified.

Transport tests alone do **not** establish live end-to-end byte-identical
envelopes. Scheduler and OCR controls are integrated but require the live smoke
gate. Event-loop yielding helps normal coalescing but cannot reproduce arbitrary
live concurrency/deadline decisions. Hashes detect corruption, not rewriting by
the store owner. Recordings contain private source data and are not releasable
fixtures. No live-run identity claim is justified until the parent runs the
fresh-serialization digest gate against a successful sealed live capture.
