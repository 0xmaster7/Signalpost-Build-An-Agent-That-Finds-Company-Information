# Signalpost

This repository starts from Builderr's supplied runnable reference in [`signalpost-starter-kit/`](signalpost-starter-kit/). The engineering authority is [`CODEX_SIGNALPOST_FINAL_IMPLEMENTATION_PLAN_AUDITED.md`](CODEX_SIGNALPOST_FINAL_IMPLEMENTATION_PLAN_AUDITED.md); current Builderr contract captures and the M00 reconciliation are under [`docs/`](docs/).

## M00 results

- Contract/repository audit: [`docs/contract-matrix.md`](docs/contract-matrix.md)
- Starter keep/refactor/adapt/quarantine map: [`docs/audit/starter-component-map.md`](docs/audit/starter-component-map.md)
- Reproducible 200-company registry website audit: [`docs/audit/m00-website-opportunity.md`](docs/audit/m00-website-opportunity.md)
- Decisions and unresolved contract inputs: [`docs/decisions/M00.md`](docs/decisions/M00.md)
- Builderr questions prepared for follow-up: [`docs/builderr-questions.md`](docs/builderr-questions.md)

The starter README contains setup, sample refresh replay and local run commands. Its historic prototype scorers and compact output example are reference material; they do not supersede the current Builderr evaluator contract or the audited implementation plan.
## M01 runtime

From the repository root, with the locked starter environment installed:

```sh
PYTHONPATH=. signalpost-starter-kit/.venv/bin/python -m signalpost.run \
  --input signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl \
  --registry-snapshot signalpost-starter-kit/tests/fixtures/m01/registry.jsonl \
  --output signalpost_output.jsonl
```

The runner accepts JSON, JSONL, CSV, TSV, and plain text inputs. `--previous-state`, `--state-output`, `--config`, `--evidence-cutoff`, and `--network-policy` are available; corresponding input/output/config/cutoff/network settings can be supplied with `SIGNALPOST_*` environment variables. The frozen registry fixture demonstrates deterministic offline operation. Live BRREG integration is the M02 milestone. See [M01 implementation decisions](docs/decisions/M01.md) for contract uncertainty and runtime boundaries.
