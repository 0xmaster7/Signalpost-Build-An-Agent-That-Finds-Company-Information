# Current submission dry-run status — 2026-10-17

Accepted product checkpoint: `64f69071b241614a1826c342ef65020db7a125d4`. The UI has owner acceptance and is frozen. The final package adds documentation/evidence only; its exact commit and CI are named in the owner handoff (`git rev-parse HEAD`).

**Engineering dry run: see [current results](submission/DRY_RUN.md). External submission remains HOLD pending owner authorization, verified organizer access, contact completion and acceptance/clarification of the unpublished parser/handoff.** No submission, repository publication, access change or licence grant has been performed. The repository remains PRIVATE.

Use the [artifact index](submission/ARTIFACTS.md), [run guide](submission/README.md), [self-contained historical 100-company report](submission/HISTORICAL_100_COMPANY_SMOKE.md), and [unsent submission draft](submission/DRAFT_SUBMISSION.md). Historical reports below are earlier checkpoints, not current package identifiers. Current approved live-test usage is 78/80; this dry run adds zero company-data requests. Coverage limits are disclosed; no official score or qualification is claimed.

---

# Historical status records (preserved)

# Current final mission status — 2026-10-17

**HOLD for external submission.** The repaired implementation is `4e5aacbb1d9793095e6c89eb06f56b496324c814`; the documentation package has its own final SHA and requires exact-SHA green CI, reported in the handoff. See [the current validation report](docs/release/FINAL_RELEASE_VALIDATION_2026-10-17.md), [machine-readable sample evidence](docs/release/FINAL_VALIDATION_2026-10-17.json), and [submission/demo instructions](submission/README.md).

433 tests/198 subtests passed after the ownership repair. A bounded live baseline/refresh and single-company run used 59 of 80 approved requests across four distinct companies, publishing exact official identities, roles and 57 workplaces at the explicit audited cutoff. The four-company sample published no verified websites, financial metrics, jobs or activity. This does not establish materially improved held-out recall or an official score.

Organizer access to the PRIVATE repository and the authoritative evaluator schema remain unverified. No external submission, email, PR, merge, visibility change, paid integration or new source was performed. All historical release records below are preserved as historical evidence; they do not supersede this current status.

---

# RC1 submission checklist

## M12 post-repair acceptance (2026-10-10)

**M12 live acceptance passed; competition submission remains HOLD.** The single authorized post-repair cold cohort ran at `7d4fe04867cd746389c48a47f360afd7ac4b8fb1`: 100 ordered terminal evaluator envelopes, 100 matching state companies, 459 physical / 485 logical requests, 347.077 seconds, committed output/state marker with matching retained hashes, and zero structural wrong-company/provenance/workplace failures. The repaired closed synthesis adapter passed all 100 rows. The role freshness mapping published eligible source-dated role claims. Financial metrics, workplaces beyond the cutoff, jobs, and activity remain withheld or unmeasured under the current evidence and policy. See the [M12 post-repair live acceptance report](docs/release/M12_POST_REPAIR_LIVE_ACCEPTANCE_2026-10-10.md) and [M12 final-freeze checkpoint](docs/release/M12_FINAL_FREEZE_CHECKPOINT.md).

The preceding attempt at `7a8e1690793f4f7e1b5c36f07daea1bf0443c787` remains a historical failure and is preserved in [the M12 failed-run report](docs/release/M12_LIVE_SMOKE_FAILURE_2026-10-10.md); this later run does not rewrite it. The exact source live-tested is not yet the final documentation-packet commit. No Builderr submission or revision slot was used. Final competition submission remains **HOLD** pending stronger comparable coverage evidence and the independent Sol High audit.

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
