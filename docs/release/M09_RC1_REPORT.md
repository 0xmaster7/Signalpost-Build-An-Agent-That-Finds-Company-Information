# Signalpost M09 — Release Candidate 1 report

M09's final cold 100-company host-context run reached terminal evaluator publication and passed the live release gates on frozen implementation SHA `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194`. The final release packet and deterministic gates are recorded in [the live smoke report](M09_LIVE_SMOKE_PASS_2026-10-05.md) and [the RC1 benchmark](M09_RC1_BENCHMARK_2026-10-05.md).

## Artifact index

- Live input/output/state/ledger hashes, identity, provenance, synthesis, financial, roles/workplaces, website/network, and resource results: [M09 final live smoke](M09_LIVE_SMOKE_PASS_2026-10-05.md).
- Full local test, M07/M08, crash/resume, scale, and defect-fix record: [M09 RC1 benchmark](M09_RC1_BENCHMARK_2026-10-05.md).
- Reproduction, previous-state use, command examples, fallback configuration, and cost/source declarations: [RC1 reproducibility guide](RC1_REPRODUCIBILITY.md).
- Enabled/disabled sources and rights assumptions: [machine-readable source-rights manifest](source-rights-manifest.json) and [source-rights register](../source-rights.md).
- Current first-submission decision: [SUBMISSION_READY.md](../../SUBMISSION_READY.md).
- Historical failure evidence is retained in [the October 4 release failure report](M09_LIVE_RETRY_FAILURE_2026-10-04.md), [the earlier provenance failure](../audit/m09-live-provenance-failure.md), and [the earlier synthesis failure](../audit/m09-live-synthesis-failure.md).

## Disposition

The operational RC1 gate passes after exact-SHA CI is confirmed for the package commit. The first-submission decision remains **HOLD**: the existing recall comparison did not demonstrate materially higher external coverage than the starter/registry baseline, and this live smoke is not a comparable held-out recall benchmark. No submission was made; Builderr-controlled unknowns remain explicit.
