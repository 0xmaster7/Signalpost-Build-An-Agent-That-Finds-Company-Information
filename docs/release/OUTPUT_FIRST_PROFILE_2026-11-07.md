# Output-first diagnosis — 7 November 2026

Read-only profiling used the preserved 200-company attempt at runtime commit
`3e8a8a0f1a2b1383098079e8376b1c69aba93ffc`. No new cohort requests were made
for this diagnosis. Worker-second sums are not phase wall durations.

| Saved breadth measurement | Seconds | Seconds/input | Physical attempts |
| --- | ---: | ---: | ---: |
| Foundation receipt span | 30.366976 | 0.151835 | 202 (200 entities, two robots failures) |
| Finance receipt span | 67.969828 | 0.339849 | 200 |
| Combined receipt span | 98.458827 | 0.492294 | 402 |
| Run start through breadth completion, bounded from surviving receipts | 99.426469–100.826953 | 0.497132–0.504135 | — |

The claimed 1.5–1.8 seconds/input was not breadth-only elapsed time. The saved
evidence does not establish the <=0.5-second target: the bounded range straddles
it. Both phases had seven peak overlapping receipt intervals, with one active
request per company. Request-start spacing had an approximately 125 ms floor
(eight starts/second). Average overlap was 5.659 foundation and 3.160 finance.
Finance transport averaged 1.0464 seconds/request; foundation averaged 0.8273.

The finalization path withheld the primary output commit until canonical state,
repeated graph validation, serialization, checkpoint terminalization, recording
identity preparation and sealing had finished. All 200 shells terminalized,
but the watchdog killed that process before the output/state publication marker
and aggregate. A terminalized SQLite shell was not an output commit.

A separate pure-function profile of the first 30 saved envelopes measured
15.61 ms/input for `Envelope.model_validate`, 92.93 ms/input for `to_evaluator`,
and 8.94 ms/input for `company_state`. The evaluator conversion invoked graph
validation four times and profile construction three times per input. These
are sample measurements, not a full-batch completion bound. A separate explicit
GC sample took 0.080827 seconds and collected zero objects; it does not establish
that GC caused the production failure.

The replacement reuses already validated encoded rows, prepares a full fsynced
snapshot before deadline promotion, and commits primary JSONL before secondary
work. Promotion is fixed-count renames/directory fsyncs, not whole-batch row
validation. Its reserve is measured, with a 10% floor. Official documented
comma-separated entity collection requests reduce foundation request count;
finance retains eight per-company workers and gateway pacing/Retry-After rules.
No extractor or website identity thresholds change.

Private detailed profiling receipts remain at
`pancakes:/tmp/signalpost-timing-20261107/`. Live performance, clean termination
and state/replay completeness of the replacement require separate measurements.
No official numeric organizer wall/CPU/RAM/request budget was found; 360/1800
seconds are project acceptance budgets, not claimed organizer allocations.
