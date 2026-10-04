# Signalpost

This repository starts from Builderr's supplied runnable reference in [`signalpost-starter-kit/`](signalpost-starter-kit/). The engineering authority is [`CODEX_SIGNALPOST_FINAL_IMPLEMENTATION_PLAN_AUDITED.md`](CODEX_SIGNALPOST_FINAL_IMPLEMENTATION_PLAN_AUDITED.md); current Builderr contract captures and the M00 reconciliation are under [`docs/`](docs/).

## M00 results

- Contract/repository audit: [`docs/contract-matrix.md`](docs/contract-matrix.md)
- Starter keep/refactor/adapt/quarantine map: [`docs/audit/starter-component-map.md`](docs/audit/starter-component-map.md)
- Reproducible 200-company registry website audit: [`docs/audit/m00-website-opportunity.md`](docs/audit/m00-website-opportunity.md)
- Decisions and unresolved contract inputs: [`docs/decisions/M00.md`](docs/decisions/M00.md)
- Builderr questions prepared for follow-up: [`docs/builderr-questions.md`](docs/builderr-questions.md)

The starter README contains setup, sample refresh replay and local run commands. Its historic prototype scorers and compact output example are reference material; they do not supersede the current Builderr evaluator contract or the audited implementation plan.
## M01/M02 runtime

From the repository root, with the locked starter environment installed:

```sh
PYTHONPATH=. signalpost-starter-kit/.venv/bin/python -m signalpost.run \
  --input signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl \
  --registry-snapshot signalpost-starter-kit/tests/fixtures/m01/registry.jsonl \
  --output signalpost_output.jsonl
```

The runner accepts JSON, JSONL, CSV, TSV, and plain text inputs. `--previous-state` reads a validated canonical M07 history artifact; `--state-output` writes the next canonical JSON artifact atomically. The SQLite resume checkpoint is internal and separate (`--checkpoint`, or the default path formed by appending `.checkpoint.sqlite` to the state output path). Baseline runs without a prior artifact publish no synthetic additions. A failed or incomplete source preserves earlier facts, and only complete official role/workplace collections can confirm those removals. The provisional evaluator change names remain in `signalpost/adapter.py`. `--config`, `--evidence-cutoff`, and `--network-policy` are also available; corresponding input/output/config/cutoff/network settings can be supplied with `SIGNALPOST_*` environment variables. The frozen registry fixture demonstrates deterministic offline operation. Add `--live-brreg` to fetch exact-organisation entity, normalized accounts, roles, and paginated workplaces through the centralized M01 gateway. An optional `--registry-snapshot` is streamed and hashed; set `--registry-snapshot-as-of` and `--registry-source-url` when the supplied Builderr snapshot does not carry those fields per row.

Run the fixed 100-company foundation smoke and save a report outside the checkout:

```sh
PYTHONPATH=. signalpost-starter-kit/.venv/bin/python \
  signalpost-starter-kit/scripts/run_m02_foundation_smoke.py \
  --output /tmp/signalpost-m02-foundation-smoke.json
```

M02 decisions and unresolved inputs are listed in [the M02 decision record](docs/decisions/M02.md). BRREG source rights and required attribution are documented in [BRREG structured sources](docs/sources/brreg.md).
