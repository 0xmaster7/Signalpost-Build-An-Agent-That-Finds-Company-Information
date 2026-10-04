# M09 live run provenance failure

This records the single host-context live cohort run authorized after the DNS diagnosis. It is a failed run, not an RC1 quality measurement.

- Source commit: `499c2c902a3f74152a0f5d50a0ea873e1cb0c6fd`
- Fixed cohort: `signalpost-starter-kit/tests/fixtures/m02/foundation-input.jsonl` (100 distinct companies; SHA-256 `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`)
- Configuration: existing release fallback (hard 1,800 seconds, soft 1,350 seconds, 300-second completion reserve, 2,200 physical requests, zero paid cost)
- Failure point: `signalpost/run.py` validating the website-enriched envelope for `row:11`
- Validation error: `claim source snapshots must include every evidence snapshot`
- Identity, financial, role/workplace and website quality results: not measured by a completed release report

The smoke wrapper uses a temporary directory for canonical output and state. The uncaught validation error exited that context and removed those temporary files before a report or request ledger was written. The exception was preserved in the run output; raw envelopes, state, and final physical/logical request totals were not available after termination. No totals are inferred here.

Reproduction with a local envelope fixture confirmed the mismatch: a verified website URL claim included BRREG candidate evidence whose snapshot ID was absent from the claim's `source_snapshot_ids`. The envelope validator rejected that claim. The fix carries the candidate evidence's snapshot ID into both verified URL and domain claims; the regression test validates the resulting complete envelope.

No further live cohort was run after this failure.
