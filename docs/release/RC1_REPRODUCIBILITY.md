# RC1 reproducibility and operations

## Requirements and install

Requires Python 3.12+ and `uv` 0.8.0. From `signalpost-starter-kit` in a fresh clone:

```bash
uv sync --frozen --extra m08-test
```

The lockfile pins the runtime/test environment. No credentials are needed for the deterministic tests, M07 replay, M08 gold, local UX, crash/resume, or offline scale gate.

## One-command research run

From any current working directory, use the checkout's launcher and explicit input/output paths:

```bash
/absolute/path/to/checkout/signalpost-starter-kit/.venv/bin/python \
  /absolute/path/to/checkout/signalpost-starter-kit/run_signalpost.py \
  --input /absolute/path/to/companies.jsonl \
  --output /absolute/path/to/output.jsonl \
  --live-brreg --live-websites
```

The current fixed release live smoke is reproducible with:

```bash
/absolute/path/to/checkout/signalpost-starter-kit/.venv/bin/python \
  /absolute/path/to/checkout/signalpost-starter-kit/scripts/run_m02_foundation_smoke.py \
  --output /absolute/path/to/smoke-report.json --live-websites
```

The smoke script uses the checked-in 100-company fixture and its release fallbacks. The live M09 evidence is frozen against implementation SHA `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194` and preserved under `/private/tmp/signalpost-m09-final-cold100-9ab896f.artifacts-artifacts` on the execution host; see [the report](M09_LIVE_SMOKE_PASS_2026-10-05.md). Do not interpret a new invocation as required to reproduce the recorded historical run.

## Previous state and material change

The canonical CLI accepts an optional `--previous-state` path and writes state with `--state-output`. For refresh evaluation, preserve the previous state artifact and pass it explicitly to the next run. A no-prior-state invocation reports baseline mode; source failures do not erase previously supported facts. The deterministic recorded-snapshot replay command is:

```bash
python3 scripts/run_refresh_replay.py \
  --manifest tests/fixtures/refresh-snapshots.json \
  --output out/refresh-replay.json
```

It verifies 12 recorded scenarios (6 changes and 6 nonchanges), complete change provenance, stable IDs, and repeat idempotency without network access.

## Optional local UX

```bash
/absolute/path/to/checkout/signalpost-starter-kit/.venv/bin/python \
  /absolute/path/to/checkout/signalpost-starter-kit/run_signalpost_web.py \
  --data /absolute/path/to/output.jsonl --host 127.0.0.1 --port 8000
```

Search, model inference, paid APIs, ATS providers, external jobs/activity providers, social/restricted platforms, and browser automation remain disabled. The UX reads saved canonical output and makes no outbound requests.

## Configuration fallbacks and authority

Builderr's exact input/output schema, duplicate-number semantics, frozen registry location/licence/as-of/retention terms, resource injection, cutoff behavior, cross-run state handoff, required UX host, search/model access, job-provider permissions, source-retention rules, and revision cutoff timezone remain unresolved. See [the open questions](../builderr-questions.md) and [contract matrix](../contract-matrix.md). Until Builderr supplies authoritative runtime values, the active defaults are one envelope per input row, JSONL output, 1,800 seconds hard, 1,350 seconds soft, 300 seconds completion reserve, `12 * N + 1,000` physical requests, zero paid cost, conservative cutoff, live BRREG fallback where no frozen snapshot is supplied, and disabled search/models/providers.

## Source-rights and cost declaration

The machine-readable [source-rights manifest](source-rights-manifest.json) and [source-rights register](../source-rights.md) are authoritative for this candidate. Enabled sources are official exact-organisation BRREG GET endpoints and bounded exact-company-owned public websites under the centralized gateway. Paid API cost is `$0`; model usage is `none`; no credentials are required. Website access remains subject to source terms, robots, crawl delay, exact-identity proof, and fail-closed handling. Search remains disabled/unpromoted.
