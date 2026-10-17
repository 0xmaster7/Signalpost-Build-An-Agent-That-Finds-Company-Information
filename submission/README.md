# Signalpost submission and demonstration guide

Status: prepared for owner review; external submission HOLD. No email, Builderr submission, revision slot, visibility change, new provider, or paid service was used.

## Version and access

Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information

Branch: `codex/m12-final-sol-remediation`.

Accepted UI design checkpoint: `64f69071b241614a1826c342ef65020db7a125d4`. The historical dry run was documentation/evidence only; subsequent narrowly scoped live-acceptance corrections are recorded in the [live research report](../docs/release/LIVE_RESEARCH_QUALITY_2026-10-17.md). Its frozen baseline was `f73dcfc01cff6e75888ede7351b6338da2e392d9`. Resolve the exact package commit with `git rev-parse HEAD`; the final owner handoff names that immutable SHA and its exact-SHA CI. Do not submit a moving branch, an older implementation checkpoint, or a private VM receipt as the package identifier.

**Current package:** [submission dry-run report](DRY_RUN.md), [artifact index](ARTIFACTS.md), [historical 100-company report index](HISTORICAL_100_COMPANY_SMOKE.md), and [unsent submission draft](DRAFT_SUBMISSION.md). Everything required to read the report and reproduce the offline checks is tracked in this repository. Raw historical live output is not bundled or claimed available.

**Important:** GitHub's default branch is the older `codex/m00-contract-audit`. Select `codex/m12-final-sol-remediation` and pin the exact final package SHA; the bare repository homepage is not the frozen submission version.

The repository is PRIVATE. The authenticated collaborator listing contained only the owner `0xmaster7`; organizer access is not verified. The owner must approve and arrange appropriate reviewer access, then verify cloning the exact SHA with organizer credentials. Do not assume that sharing this URL grants access. Repository visibility must not change without owner approval. The project has no declared repository code licence; third-party/data notices do not grant a licence for the project's own code.

## Fresh setup (Linux/macOS, Python 3.12+)

Clone using credentials that actually have access, and pin the package SHA from the final handoff:

```sh
git clone --branch codex/m12-final-sol-remediation   https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information.git
cd Signalpost-Build-An-Agent-That-Finds-Company-Information
# Before submission: git checkout THE_EXACT_PACKAGE_SHA_FROM_THE_HANDOFF
```

If `uv` 0.8.0 is already installed, skip this bootstrap. Otherwise fetch the pinned upstream installer and install inside the checkout without changing shell profiles:

```sh
curl --fail --silent --show-error --location https://astral.sh/uv/0.8.0/install.sh --output /tmp/signalpost-uv-install.sh
UV_INSTALL_DIR="$PWD/.signalpost-tools" UV_NO_MODIFY_PATH=1 sh /tmp/signalpost-uv-install.sh
export PATH="$PWD/.signalpost-tools:$PATH"
```

This path was tested on the Azure VM where `python3 -m venv` fails because ensurepip is missing. It requires curl and a supported POSIX platform. The source installer and dependency downloads require outbound HTTPS. No sudo, system Python package changes, or API keys are needed. Python 3.12 is the tested runtime; CI uses Python 3.12 and uv 0.8.0.

Install exactly the lockfile environment:

```sh
cd signalpost-starter-kit
uv sync --frozen --extra m08-test
cd ..
```

The optional extra supports local HTTP verification. Runtime launch does not require pytest. To run the complete test suite, additionally install the same pinned runner as CI:

```sh
cd signalpost-starter-kit
uv pip install --python .venv/bin/python pytest==9.1.1
PYTHONPATH=.. .venv/bin/python -m pytest -q
cd ..
```

## Exact evaluator command

Input `companies.jsonl` contains one string organisation number per row:

```json
{"organisation_number":"923609016"}
{"organisation_number":"976390512"}
```

From the root:

```sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py   --input companies.jsonl --output output.jsonl --state-output state.json   --checkpoint checkpoint.sqlite --live-brreg --live-websites
```

The launcher also works from any directory when all paths are absolute. JSON, CSV, TSV and one-number-per-line text inputs are supported. IDs remain strings. Output contains exactly one ordered terminal envelope per input row, including duplicates and failed rows. Do not deduplicate the evaluator output.

The current output has `input_ref`, `organisation_number`, `terminal_state`, `sections`, `claims`, `evidence`, `source_snapshots`, `refresh`, `synthesis`, `errors`, `operations`, `run`, and `batch`. Sections are identity/brand, accounts/history, leadership/workplaces, website/owned profiles, hiring/activity, claims/evidence/states, and refresh/changes. Each available claim has exact entity/scope, a verification rule, and evidence/snapshot references; financial metrics additionally require supported dimensions. Only the canonical evidence-supported summary is published. This is the tested repository schema, not a verified organizer JSON Schema. Mapping remains isolated in `signalpost/adapter.py`.

A supplied frozen registry is optional: add `--registry-snapshot PATH`, `--registry-snapshot-as-of ISO_DATE`, and `--registry-source-url URL` using actual organizer-provided values and rights. Without a supplied snapshot, the documented fallback is the official live BRREG foundation. There is no bundled authoritative registry download or hidden credential.

## Budget, cutoff, refresh, resume

Growing batches now preserve refresh history across operational budget changes; independent frozen runs verified 1,000 → 1,100 companies, subset retention and repeat idempotency. Source and provenance configuration remain strict, and checkpoints still require the identical run. Legacy state can migrate only with its exact original source/configuration and budget; perform that matching handoff before changing its batch size. See the [final evaluator acceptance](../docs/final-evaluator-acceptance-20261017/REPORT.md) for evidence and the remaining unpublished organizer parser/handoff details.

Fallbacks are 1,800 seconds hard / 1,350 soft / 300 completion reserve; `12*N+1000` physical requests; paid cost limit zero. Actual organizer resource inputs take precedence. A runtime JSON config can set `budget.physical_request_limit`, durations and cost; use `--config PATH`. Corresponding `SIGNALPOST_*` variables are supported. The launcher prints a machine-readable `batch_complete` report to stdout; capture it separately from the JSONL output.

Without `--evidence-cutoff`, the cutoff is run start. Undated facts retrieved later may be withheld; this explains the historical workplace coverage gap. Supply `--evidence-cutoff ISO_TIMESTAMP` only when that cutoff is actually authorized. The bounded final validation used the audited `2026-10-17T23:59:00+05:30` cutoff and published 57 exact-parent workplaces. Do not set a future cutoff merely to improve coverage; use the organizer's actual cutoff for evaluation.

For a subsequent refresh, keep source/configuration flags compatible and use a new output/state/checkpoint:

```sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py   --input companies.jsonl --output refreshed.jsonl --state-output next-state.json   --checkpoint next-checkpoint.sqlite --previous-state state.json   --live-brreg --live-websites
```

The output/state files are JSONL/JSON respectively; the checkpoint is internal SQLite. Preserve the adjacent `.publication.json` marker with its pair. Baselines report `baseline_no_prior_state`; a prior-state refresh emits typed supported material changes. An incompatible prior configuration is diagnosed, not silently accepted. To resume an interrupted run, repeat its original invocation with the same paths/configuration/cutoff and add `--resume`; do not use a new checkpoint. Refresh makes external requests; resume can also make requests for unfinished rows.

## Five-minute demonstration without network

From the root, run the bundled offline command in the main README and launch the web application. The four fixture rows are synthetic, include a duplicate, and demonstrate exact cardinality rather than real coverage. In the browser, search an organisation number, open its profile, follow an evidence link and source URL, compare two companies, and verify a legal-name proposition. Unavailable facts remain unknown.

Run the recorded history replay:

```sh
cd signalpost-starter-kit
.venv/bin/python scripts/run_refresh_replay.py   --manifest tests/fixtures/refresh-snapshots.json --output /tmp/signalpost-refresh-demo.json
PYTHONPATH=.. .venv/bin/python scripts/evaluate_signalpost_m08.py --output /tmp/signalpost-gold.json
cd ..
```

The replay verifies 12 scenarios, six changes, no false positives/negatives, complete provenance and idempotency. For an already authorized real-data demo on pancakes, use the preserved four-company output identified in the validation report. That optional VM demonstration data is not a dependency of the submitted CLI or bundled offline demonstration. It is an observed live result, not a synthetic fixture. The local UI is read-only and makes no outbound requests. It must load real output before evidence/compare/history inspection. No public hosting service has been activated.

## Sources, cost and known limitations

Approved sources: official BRREG exact-organisation entity, accounts, roles and paginated subunits; bounded public company websites through the centralized gateway. Attribution and applicable NLOD terms are in `docs/source-rights.md`, `docs/sources/brreg.md`, `docs/data-licenses.md`, and `THIRD_PARTY_NOTICES.md`. Website-specific terms remain individually applicable, not globally licensed. Explicit robots disallow is enforced; ordinary website robots outages fail closed; only the documented narrow BRREG API outage exception applies. No forbidden platform scraping, PDF acquisition, source expansion or browser crawling was enabled.

Models: none. Paid APIs/services: none. Credentials required: none for research; private GitHub clone access is separate. Declared third-party API/model cost per official batch (1,000 or 1,100 companies): **$0**, because no paid API/model is enabled. This is configuration-based, not a measured full-scale live runtime/cost benchmark. Measured API cost was $0 for both the historical 100-company cohort and the final bounded sample; network/VM infrastructure is supplied by the execution environment and is not priced here. The configured paid cost cap is $0; this is not a promise that infrastructure is free.

The accepted historical 100-company report is `docs/release/M12_POST_REPAIR_LIVE_ACCEPTANCE_2026-10-10.md`: 100 outputs at its recorded older SHA, 459 physical requests, 347.077 seconds, one verified website, no numeric financial metrics, jobs or activity. Raw historical bundle bytes are unavailable on this VM; the packaged report and receipts remain historical evidence. No new 100-company cohort was run.

Historical bounded validation initially used 59/80 approved requests. Subsequent authorized checks brought the total to 78/80; this final dry run makes zero additional live company-data requests. The four-company evidence is historical, not a new acquisition or a population coverage estimate. All identities, role and workplace source bindings, output cardinality and publication graphs passed. No owned website, numeric financial metric, jobs or activity claim published in that sample. Website evidence on Equinor remained ambiguous; the other three had no registry candidate with keyless discovery disabled. Missing data is not evidence of absence. There is no official evaluator score, measured population recall, or independently adjudicated population website precision.

## Owner actions before submission

1. Arrange and verify organizer access to the exact private commit, or separately approve a visibility change. Confirm any required project code licence.
2. Confirm the organizer's actual evaluator schema, cutoff, runtime/resource injection and required hosting interface. The repository's current fallbacks are runnable but not authoritative answers.
3. Review the exact final SHA/CI and validation evidence; decide whether to submit despite the documented coverage/qualification HOLD.
4. Approve the actual external submission separately. Use repository URL, exact package SHA, evaluator command, source/model/cost declarations, historical smoke report, and this guide. Nothing is sent automatically.
