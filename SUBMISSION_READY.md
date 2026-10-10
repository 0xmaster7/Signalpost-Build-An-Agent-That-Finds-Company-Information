# RC1 submission checklist

## M12 re-checkpoint (2026-10-10)

**Disposition remains HOLD; this packet is not ready for submission.** The current release-preparation source is `afade4bcc7935886e7cec7a8ba24cd5b800904ea` on `codex/signalpost-m12`. Exact-SHA CI run [38040538880](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/38040538880) passed for that SHA. The M11 commit changed documentation only; no current-source 100-company live smoke has been run after the later production remediation. The historic M09 and post-Sol live reports remain historical evidence and do not satisfy that current-source gate.

M12 offline checks and the reason for the hold are recorded in [the M12 final-freeze checkpoint](docs/release/M12_FINAL_FREEZE_CHECKPOINT.md). No final submission SHA is declared. The cold 100-company smoke requires a separate explicit authorization; no Builderr submission or revision slot was used.

**Historical M09 disposition: HOLD.** The M09 operational candidate passed its then-authorized live cohort. This section preserves that historical record; the M12 update above is the current status. This file does not authorize or record an external submission.

## Candidate identity

- Implementation SHA exercised by the final live run: `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194`.
- Branch: `codex/m00-contract-audit`.
- RC1 package commit: `17d3b207f532e67262f0f9b92bb220551a3fea61`; the remote branch matched this exact SHA.
- Exact-SHA CI: [run 37245631189](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/37245631189) — all jobs passed.
- The final completion-record commit contains only readiness/CI documentation updates; its exact SHA and CI are reported in the M09 completion record.
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
| Repository access / RC1 package remote commit / CI | READY | Remote branch matched package SHA `17d3b207f532e67262f0f9b92bb220551a3fea61`; exact-SHA CI run 37245631189 passed. |
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
