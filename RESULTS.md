# Signalpost — Results

## Latest (7 November 2026)

Runtime: **`82703d348e894ed68bf9873404a7900886440398`**, frozen throughout this documentation-only revision. Organizer Soham confirms v1 `a9d0bc8` is on record, with proposed revision **2 of 5** applicable to later runs. Official budget: **45 minutes and 2,000 requests per 100 companies (20/input)**. This revision email has not been sent.

### Live measurements

Counts below are companies with supported finance / explicit FTE / verified website / jobs claims, not precision, recall or official scores.

| Inputs | Runtime | Exit | Process seconds | Valid rows | Duplicate claim IDs | Unchanged starter validator | Finance / FTE / website / jobs | State pair |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 10 | `82703d3` source-equivalent candidate | 0 | 16.87 | 10 | 0 | pass | 10 / 0 / 0 / 0 | incomplete |
| 200 | `82703d3` source-equivalent candidate | 0 | 332.41 | 200 | 0 | pass | 196 / 0 / 0 / 1 | incomplete |
| 1,000 — new run A | exact `82703d3` fresh clone | **1** | **598.86** | 1,000 surviving snapshot | 0 | pass on snapshot | 915 / 0 / 0 / 0 | **not committed** |

10/200 provenance and exact earlier commands: [compatibility report](docs/release/COMPATIBILITY_RESULTS_2026-11-07.md), [10 receipt](docs/release/evidence/compatibility-20261107/live-10.json), [200 receipt](docs/release/evidence/compatibility-20261107/live-200.json). These measurements preceded the final source commit; runtime implementation identity was checked equal. Historical `f0902cb0cbb1a4cd5e9ac1d471f0c8459545ed73` returned 1,000 valid rows in 1659.034 seconds (finance983/FTE8/websites0/jobs1), but its legacy starter shape was rejected; see [output-first report](docs/release/OUTPUT_FIRST_RESULTS_2026-11-07.md). Do not label it a compatibility pass.

### Run A: failed environmental completion check, no retry

Started **17:45:46 UTC**, ended **17:55:44 UTC**, 7 November. New shared-object Git clone with empty runtime environment, detached at the exact hash; `./setup.sh` successfully installed pinned production dependencies and checked PDF/OCR. No budget/config/network-policy override was supplied. Default was **1,800 seconds**, not the organizer's maximum.

```sh
git clone --shared /home/azureuser/projects/signalpost /tmp/signalpost-revision2-20261107/repo
cd /tmp/signalpost-revision2-20261107/repo
git checkout --detach 82703d348e894ed68bf9873404a7900886440398
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

The frozen 1,000-input file SHA-256 is `c8d231c304a80151e569667c6a797ae38861ca69dc00ad787f18e619cff77927`. The command was timed with `/usr/bin/time -p`, with stdout/stderr redirected outside the checkout. This VM also ran the requested full tests and two small refresh checks concurrently; it was **not an isolated performance benchmark**.

**Failure:** `OSError: [Errno 28] No space left on device` in `operations.py:prepare_bytes`, reached from periodic `prepare_output()` while research was shutting down. The filesystem had only about 1.7 GB free before setup; installing the fresh environment and growing checkpoint/output/atomic temporary files exhausted it. Disposable old test/dependency files were removed, but not soon enough to prevent the failure. This is an environment failure, not evidence of a fixed scheduler or a successful official run. No code, extractor or identity changes, and **no second 1,000-company attempt**.

The last atomic output is 1,000 parseable, canonical-decoder-valid rows: 998 public `available`, 2 `failed`; zero duplicate top-level claim IDs. Unchanged starter returned all five checks true. **Marker remains `status: partial`, `output_committed: false`, `canonical_pair_committed: false`, `state_incomplete: true`.** No canonical state pair or final aggregate exists; this is not a successful terminal publication. Checkpoint shells: 1,000 `baseline_done`, not terminalized. Persisted phase outcomes: official 998 completed/2 failed; finance991 completed/9 failed. Output counts above describe only the surviving snapshot, not all checkpoint-supported facts.

Snapshot SHA-256: `8eda7cb1a927693e431ef31ce62abf72cafc779dd29af8eb1e86e4136abe59a5`. Verification completed in47.587seconds, decoding all rows and running the original `norway_company_agent.batch.validate_envelopes` on the whole original output. Private raw outputs/checkpoints remain outside Git at `pancakes:/tmp/signalpost-revision2-20261107/`.

### Requests and budget accounting

Earlier completed gateway aggregates: **35/10 = 3.50**, **584/200 = 2.92 physical attempts/input**, including shared requests, versus the confirmed **20/input** batch allowance. These are measured averages, not a promise for another batch.

Run A produced **no final gateway aggregate**, so its total physical attempts and exact requests/input are **unavailable**. Published per-company snapshots sum to934, maximum2, but exclude shared traffic and later attempts: **not the total and not proof of cap compliance**. Neither source receipt counts nor the checkpoint can recover the lost gateway ledger. No request-budget compliance claim is made for failed run A.

### Organizer-style repeat command / refresh

Two live 10-company commands were run in the **same working directory** with the same input/output and the default18-second budget, retaining the state/checkpoint folder, without `--previous-state` or `--resume`. Both committed primary output, but neither committed a canonical state pair. Their internal runtimes were16.705/16.728seconds; gateway attempts22/29 (2.20/2.90 per input).

The second output reports **`refresh.mode: baseline_no_prior_state`**, `previous_state_ref: null`, empty retained-claim IDs and no change events: **it did not automatically use the first run's state**. All1,174 earlier evidence IDs reappear for the unchanged sources, but **zero earlier evidence records survive byte-for-byte**; retrieval timestamps are new. Reappearing content-derived IDs do not establish preserved historical evidence.

Refresh requires an explicit **`--previous-state PATH`** (or `SIGNALPOST_PREVIOUS_STATE`) pointing to a successfully committed canonical prior state; interruption resume separately requires `--resume`. The organizer's repeated default command supplies neither. **Retaining the folder alone does not pass the requested refresh flow.** Output-only markers cannot substitute for canonical paired state. No code fix was authorized in this cycle.

### Documented command verification

Fresh clone setup, live smoke/repeat, unchanged starter validation, offline fictional demo and dashboard startup were exercised against exact `82703d3`. Test-runner installation from the README was also exercised after run A ended: project-local uv0.8.0, `sync --frozen --extra m08-test`, then `uv pip install --python .venv/bin/python pytest==9.1.1`.

**Full suite: 1,358 passed, 252 subtests passed, one third-party pyRdfa deprecation warning, 876.38 seconds.** Fresh-clone source/tests were exercised using the previously provisioned pinned test venv, so as not to modify the live run's environment during execution:

```sh
cd /tmp/signalpost-revision2-20261107/repo/signalpost-starter-kit
PYTHONPATH=.. /tmp/signalpost-presubmit-f0902cb-WiVaaM/repo/signalpost-starter-kit/.venv/bin/python -m pytest -q
```

This is not described as a full-suite execution inside the newly installed venv. The README's test-extra/pytest installation was separately verified successfully inside that fresh venv after run A ended. The ordinary same-venv full-suite command is also the exact-commit CI workflow command; its final status is reported with the documentation commit.

The README's exact offline `./run.sh --registry-snapshot ...` command returned0 with4 rows and zero network attempts. Its exact dashboard command on port8000 returned **HTTP200**, then was stopped. Both10-company repeated outputs passed the unchanged validator. Their hashes are `52079346bd5539fa29b4c39ff5557679fb98e875c8f1bd1b48076c473d1ba1f0` and `a94e2698583828e2159e4071d6e9a02541af0131b57cb5c558159926ecb482d6`.

Unchanged starter command on original run A rows (no translation or wrapper validator):

```sh
PYTHONPATH=signalpost-starter-kit/src signalpost-starter-kit/.venv/bin/python -c 'import json; from norway_company_agent.batch import validate_envelopes; r=validate_envelopes([json.loads(x) for x in open("output.jsonl")],1000); print(json.dumps(r,sort_keys=True)); assert r["passed"]'
```

Result: `{"checks":{"all_entity_states_terminal":true,"all_module_states_terminal":true,"exact_expected_count":true,"unique_organisation_numbers":true,"zero_silent_drops":true},"invalid_states":[],"passed":true}`. This validates the surviving snapshot's structural legacy checks, **not successful final commitment**. The official private parser is not this small structural validator. All remaining example differences are in [OUTPUT_CONTRACT_CHECK.md](docs/OUTPUT_CONTRACT_CHECK.md).

## History

**Latest measured candidate, 6 November 2026: acceptance FAILED.** See the [final live report](docs/release/FINAL_RESULTS_2026-11-06.md): matched/fresh100 each finalized and replayed exactly, but FTE18/19, websites0/1 and runtime1595/1584 seconds miss targets; fresh finance93 also misses. Live scale1000 timed out with1000 partial rows and no final state pair. No coverage improvement or submission readiness is claimed. Sections below preserve historical experiments, not current acceptance.

Signalpost researches Norwegian companies by organisation number and returns evidence-backed JSONL profiles.

## Historical 27 October experiment: failed acceptance

The [27 October phase-budget results](docs/release/PHASE_BUDGET_RESULTS_2026-10-27.md) preserve both preregistered runs. Matched coverage fell from 50 to **28 FTE companies** and 77 to **42 financial companies**; verified websites and jobs remained zero. Runtime improved to **1,190.614 seconds**, with 100 terminal envelopes. Monetary breadth reached 2,491 observations, including 2,100 explicitly assumption-backed and 22 separately scoped group observations. Only runtime/cardinality gates passed.

The fresh disjoint holdout **failed with duplicate claim IDs during optional website publication**, exit 1 after 1,175.312 seconds, with no final envelopes. Optional observations were not checkpointed and their coverage is unknown. It was not rerun. A post-run deduplication/publication guard passed 672 offline tests and 237 subtests; that does not turn the failed holdout into a pass. [Matched per-company CSV](docs/release/evidence/phase-budget-20261027/matched-per-company.csv) and [JSONL.gz](docs/release/evidence/phase-budget-20261027/matched-per-company.jsonl.gz) are available. Public `main` has not demonstrated the live acceptance gates.

## Live evaluation results

The [earlier 27 October matched 100-employer benchmark](docs/release/LIVE_COMPARISON_2026-10-27.md) compared Signalpost versus Arnav's unchanged repo on identical inputs, including the six-company cohort. Companies with verified-site claims: 0/25; jobs: 0/3; FTE: 50/29; financials: 77/98. Our OCR queue exhausted the optional website research window in that baseline. Per-company CSV/JSONL and exact versions are included; these are coverage counts, not established accuracy.

### Historical six-company measurement

Same six previously unseen Norwegian AS employers, selected before source outcomes; previous release `8076e1b` versus latest measured implementation `72e8c05`, retained in release `59cbada`.

| Metric | Previous | Latest |
| --- | ---: | ---: |
| Companies tested | 6 | 6 (same cohort) |
| Financial claims | 14 | 71 |
| Financial metric types | 3 published | 17 published |
| Workforce FTE coverage | 4/6 companies | 4/6 companies |
| Registered workplace claims | 0 | 37 facts across 6/6 companies |
| Verified websites | 0/6 companies | 0/6 companies |
| Public profiles | 0/6 companies | 0/6 companies |
| Jobs | 0/6 companies | 0/6 companies |
| Dated activity | 0/6 companies | 0/6 companies |
| Runtime | 183.226 s | 199.148 s (197.547 acquisition + 1.601 publication) |
| HTTP requests | 34 physical attempts | 34 physical attempts; publication: 0 |

Latest publication used checkpoint resume after a serialization repair. Timings are observations, not a controlled speed comparison. A separate interrupted run used 32 attempts; total research budget consumed: 100 attempts.

## What improved

| Area | Measured improvement |
| --- | --- |
| Financial extraction | 57 additional claims; all six companies gained facts |
| Financial breadth | Added balance-sheet and income-statement metrics, including assets, receivables and payroll |
| Exact-parent workplaces | 6 location claims + 1 postal-address claim + 30 linked registry facts; registered records, not observed offices |

## Evidence

- [Latest live evaluation report](docs/release/FINAL_CAPABILITY_INTEGRATION_2026-10-17.md) and [measured summary](docs/release/evidence/capability-integration-20261017/summary.json).
- [Historical 100-company smoke-test report](docs/release/M09_LIVE_SMOKE_PASS_2026-10-05.md): earlier version `9ab896f`; different cohort, excluded from this comparison.
- [Exact release commit: 59cbada](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/commit/59cbada1457f0ff93b265638f037f79df6578c25) and [passing exact-SHA CI](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/39059298958).

## Limitations

- Six employers are a small, non-representative cohort; population accuracy and recall are not established.
- Verified websites, public profiles, jobs and dated activity: zero coverage in this cohort; FTE unavailable for 2/6 companies.
- OCR-ambiguous financial values are withheld; official Builderr parser compatibility and score remain unverified.
