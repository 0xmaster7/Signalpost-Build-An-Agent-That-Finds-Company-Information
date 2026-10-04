# RC1 submission checklist

**Disposition: HOLD.** The M09 operational release candidate has passed its final live cohort and is being packaged for independent audit. This file does not authorize or record an external submission.

## Candidate identity

- Implementation SHA exercised by the final live run: `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194`.
- Branch: `codex/m00-contract-audit`.
- Final package commit, remote SHA, and exact-SHA CI result are recorded in the release completion record after push/CI; see [M09 RC1 report](docs/release/M09_RC1_REPORT.md).
- Live smoke report: [M09 final live smoke](docs/release/M09_LIVE_SMOKE_PASS_2026-10-05.md).
- Benchmark and deterministic gates: [M09 RC1 benchmark](docs/release/M09_RC1_BENCHMARK_2026-10-05.md).

## Gate checklist

| Item | State | Evidence / detail |
|---|---|---|
| M00–M08 implementation and regression baseline | READY | Baseline preserved; full suite and M07/M08 gates pass on the frozen live SHA. |
| 100-row cold live terminal output | READY | 100 ordered terminal envelopes and 100 state entries; complete publication path passes. |
| Claim/evidence/snapshot identity and provenance | READY | No duplicate IDs or wrong-company bindings; final graph validates for all 100 envelopes. |
| Financial and workplace publication checks | READY | 0 unsupported financials; 0 invalid workplace attributions. |
| Request, runtime, reserve, robots, and source policy | READY | 470 physical / 496 logical, under configured bounds; all purposes approved; explicit robots disallows 0; transport failures remain distinct. |
| Deterministic live-shape, adversarial, M07, M08, crash/resume, scale, and clean-install gates | READY | Exact results in the benchmark report. |
| Repository access / final remote commit / CI | PENDING | Must be verified against the final package SHA before M09 is reported complete. |
| Comparable evidence of materially higher external recall than starter/registry baseline | BLOCKED | Existing opportunity comparison measured no incremental accepted-domain gain from the bounded keyless path. The final smoke is not a comparable held-out recall benchmark; jobs/activity are not measured. See [recall opportunity report](docs/release/M09_RECALL_OPPORTUNITY.md). |
| Exact Builderr evaluator schema and duplicate-input rule | UNKNOWN | Provisional field naming remains isolated in the evaluator adapter; current fallback preserves one envelope per input row. |
| Frozen registry mount, licence, as-of date, and retention terms | UNKNOWN | Live BRREG is the documented fallback if no authoritative frozen snapshot is supplied. |
| Official resource injection, cutoff rules, prior-state handoff, and UX hosting contract | UNKNOWN | Current conservative defaults and explicit parameters remain in force. |
| Search/model key, approved search/job providers, and provider rights | UNKNOWN | Search, models, ATS, external jobs/activity, and paid APIs remain disabled. |
| External submission action | NOT DONE | No Builderr submission, email, or revision slot was used. |

## Current submission decision

**HOLD.** The audited plan calls for materially above-baseline measured external coverage before first submission. The available comparable audit does not establish that gain. The public score-mix arithmetic currently leaves 18.08/50 recall points to reach 65 if the 26.92 evidence, 12 synthesis, and 8 UX diagnostic scores apply; this is arithmetic only, not a local score prediction. The final smoke is not a comparable held-out recall benchmark. Keep search disabled and do not infer recall from abstention or this 100-company safety smoke. Revisit this decision only with comparable supported coverage evidence or authoritative Builderr evaluation feedback.

## Operational instructions

See [the reproduction guide](docs/release/RC1_REPRODUCIBILITY.md) for the pinned install, one-command research run, optional local UX, previous-state flow, current defaults, enabled sources, and cost declaration. See [the source-rights manifest](docs/release/source-rights-manifest.json) for machine-readable policy.
