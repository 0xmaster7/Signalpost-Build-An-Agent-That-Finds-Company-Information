# Signalpost

Signalpost researches Norwegian companies by organisation number and produces ordered, evidence-backed JSONL output. The CLI fetches approved official BRREG data and optionally verifies registry-listed websites. The local web application explores saved results; it does not perform live research.

**Current release preparation:** [submission and demo guide](submission/README.md), [validation report](docs/release/FINAL_RELEASE_VALIDATION_2026-10-17.md), and [machine-readable evidence](docs/release/FINAL_VALIDATION_2026-10-17.json). Submission remains HOLD: organizer access to this private repository and the authoritative evaluator schema are unverified; website, financial-metric, jobs, and activity coverage remain limited. Nothing has been submitted.

## Install and run

Requirements: Git, Python 3.12+, outbound HTTPS for installation/live research, and `uv` 0.8.0. No API credentials or paid services are required. The [submission guide](submission/README.md) includes a tested standalone `uv` bootstrap for machines without pip/venv.

From `signalpost-starter-kit`:

```sh
uv sync --frozen --extra m08-test
```

From the repository root, run the bundled offline example (four rows, including a duplicate; fictional fixture identities):

```sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py   --input signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl   --registry-snapshot signalpost-starter-kit/tests/fixtures/m01/registry.jsonl   --output /tmp/signalpost-output.jsonl --state-output /tmp/signalpost-state.json
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost_web.py   --data /tmp/signalpost-output.jsonl --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 for find, profiles, citations, compare, verify, and change history. For real-company research and evaluator invocation, use the exact commands and cutoff/budget explanation in the [submission guide](submission/README.md). Live invocations make external requests; the completed validation approval is not an ongoing testing allowance.

## Contracts and evidence

The authority is [the audited implementation plan](CODEX_SIGNALPOST_FINAL_IMPLEMENTATION_PLAN_AUDITED.md), with [contract reconciliation](docs/contract-matrix.md), [source rights](docs/source-rights.md), and [source policy](docs/release/source-rights-manifest.json). The evaluator adapter in `signalpost/adapter.py` implements the current repository contract; official Builderr field names remain unconfirmed.

Historical release reports remain under [docs/release](docs/release), including the accepted [100-company M12 smoke](docs/release/M12_POST_REPAIR_LIVE_ACCEPTANCE_2026-10-10.md). That smoke tested its recorded historical SHA, not this final source. The original raw bundle is not present on this Azure VM. Preserved reports and hash receipts must not be represented as fresh revalidation of unavailable raw bytes.

[Starter component audit](docs/audit/starter-component-map.md), [website opportunity audit](docs/audit/m00-website-opportunity.md), [M00 decisions](docs/decisions/M00.md), and [open organizer questions](docs/builderr-questions.md) preserve the earlier project context. Experimental starter scripts are outside the canonical launcher and must not be used to bypass the approved source contracts.
