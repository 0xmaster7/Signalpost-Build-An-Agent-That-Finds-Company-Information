# M12 final-freeze checkpoint

## Authorized live attempt update (2026-10-10)

The user authorized one cold fixed-cohort 100-company live smoke at `7a8e1690793f4f7e1b5c36f07daea1bf0443c787`. It reached live BRREG for all rows and stayed within limits (459 physical / 485 logical requests; 352.625 seconds), but failed during final evaluator serialization on source-derived BRREG identity/status fields absent from the closed synthesis allowlist. It did not commit a paired output/state artifact. The failure, per-source measurements, correction, offline canonical-envelope replay, and evidence-handling note are recorded in [the M12 live smoke outcome](M12_LIVE_SMOKE_FAILURE_2026-10-10.md). No second live cohort was run.

The schema fix is narrowly limited to the observed BRREG observation fields; unknown synthesis keys still fail closed. The preserved 100-envelope checkpoint passes current offline synthesis/evaluator/publication-graph validation after the fix. This replay does not retroactively pass the live gate: M12 remains **HOLD** pending a separately authorized live run of the repaired source. The run's original publication marker remains `publishing`.

Date: 2026-10-10
Status: `HOLD` — engineering preparation recorded; not ready for submission
M12 source SHA evaluated: `afade4bcc7935886e7cec7a8ba24cd5b800904ea`
Branch: `codex/signalpost-m12`

## M11 checkpoint carried forward

M11 completed without a production promotion because no candidate satisfied the audited promotion gates. The M11 report is [M11 calibration and ablation](M11_CALIBRATION_ABLATION_REPORT.md). Commit `afade4bcc7935886e7cec7a8ba24cd5b800904ea` is documentation-only relative to M10's code baseline. Its pushed branch had exact-SHA GitHub Actions run [38040538880](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/38040538880), result `success`. The `starter` job passed all steps, including the complete starter tests, M07 replay, M08 gold, M03–M06 gates, clean-CWD evaluator, and UX smoke.

## M12 offline release checks

| Check | Result | Evidence / limit |
|---|---|---|
| Complete local suite | PASS — 389 tests, no failures/errors | `signalpost-starter-kit/tests`, run on M11 source SHA. |
| M07 refresh replay | PASS — 12 scenarios, 6 expected events, TP=6, FP=0, FN=0; provenance and idempotency passed | `/private/tmp/m11-refresh-output.json`; replay source SHA `afade4bcc7935886e7cec7a8ba24cd5b800904ea`. |
| M08 gold evaluation | PASS — four fixture profiles; find/compare/verify 1.0, unsupported assertions 0, citation completeness 1.0 | `/private/tmp/m11_m08_gold_evaluation.json`; fixture regression only, not live coverage evidence. |
| Fresh scale gate | PASS — 1,000 and 1,200 operational writes; 10,000-row offline dry run; stress modes A–D; zero physical requests | Report `/private/tmp/m12-m06-scale-afade4bcc7935886e7cec7a8ba24cd5b800904ea.json`, SHA-256 `db4adc543eb6044a2b1df3065a5b6391e88be7fb7dce457de19b06177a81d4ef`; source SHA `afade4bcc7935886e7cec7a8ba24cd5b800904ea`; clean source tree; M06 provenance verifier passed. Runtime: 1,000 rows 7.899 s; 1,200 rows 10.816 s; 10,000 rows 79.135 s. Synthetic identity is `not_measured`. |
| Durable RC1 evidence packaging | PASS | `scripts/verify_rc1_evidence.py` validated historical receipts. This does not make the historic live smoke current. |
| Clean installation | PASS | Exported source at the M12 SHA; `uv sync --frozen --extra m08-test` installed the lockfile in a fresh environment. Python 3.13.5, uv 0.8.0. |
| Exact launcher/run-command path | PASS, offline fixture mode only | From `/private/tmp`, with `PYTHONPATH` unset, the documented launcher ran a four-row fixture against the frozen registry fixture: 4 ordered envelopes, 0 physical requests, exit 0. The release command with live flags was not run. |
| Dependency and source-rights review | PASS for no-diff review | No dependency, source-rights, model, provider, or runtime configuration change occurred. Lockfile SHA-256 `40d47bd127ba8673b19d03276d7aa9cd96d2a35bd04cfc226ef8f40d22506633`; source-rights manifest SHA-256 `a9fba251210ddc0b4ce55699afa29c94c13a4fe7f041e4f352edcedfe7859b73`. |
| Secret pattern scan | No matches | Checked current tracked files for common private-key, AWS-key, GitHub-token, and API-key forms. No dedicated `gitleaks`, `trufflehog`, or `detect-secrets` executable was installed; this is not a comprehensive history scan. |

The M06 verifier also rejects the previously checked-in historical `docs/audit/m06-scale-benchmark.json` because its 10,000-row record does not prove one distinct company per input row. That historical file was not changed. The fresh M12 report passes the current verifier and is preserved separately under `/private/tmp`.

## Live and submission gates

The one authorized M12 live attempt is the failed current-source attempt described above. It does not satisfy the 100-company complete-publication gate. No earlier live report was overwritten or reclassified, and no additional cohort was executed after the failure.

The audited submission decision remains `HOLD`: the comparable opportunity study did not demonstrate materially higher external coverage than the registry/starter baseline, and no official Builderr score or adjudicated run feedback exists. M11 found no supported safe change that would improve that result. The M12 live attempt additionally failed final publication, though its captured canonical data passes the fixed offline replay. No final release SHA is declared, and this is not `READY_FOR_USER_SUBMISSION`.

The next live gate is one cold 100-company smoke on an explicitly selected clean SHA using the fixed M09 cohort and existing limits/source policy. That is substantial external traffic. The previous one-shot smoke authorizations do not authorize another run. The user's mission authorizes implementation and ordinary release work, but does not explicitly authorize this fresh cohort. Stop here for authorization before any live request.

## Current declarations

- Production code, runtime configuration, dependency lock, and source-rights policy: unchanged in M10/M11/M12.
- Paid cost and model usage: `$0`; none.
- Search, ATS, browser automation, paid providers, PDF acquisition, and new credentials: disabled/not used.
- BRREG financial unit/scale semantics, frozen-registry injection details, exact evaluator mapping questions, and Builderr run-specific feedback remain unresolved under their documented conservative fallbacks.
- No Builderr contact, submission, or revision slot was used. Independent Sol High audit remains pending and must follow a genuinely ready candidate; it has not been performed here.
