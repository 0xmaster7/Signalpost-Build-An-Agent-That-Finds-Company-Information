# Crash-safe acceptance runner

`run_crashsafe_acceptance.py` launches the real repository `run.sh`. Its default
stage runs **one ten-company live smoke and its offline replay**, then stops.
`--prepare-only` freezes selection/configuration and launches no research. This
implementation has been tested with fixtures and mocked subprocesses only.

The archived original selection identifies the fixed six as `920710514`,
`924356715`, `930827088`, `952780093`, `992936916`, `993955299`. Four additional
active AS employers are sampled without replacement by seeded SHA-256 ranking
from the archived registry. The registry must match the original selection's
`source_file_sha256` (`f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece`).
The runner does not SSH, download a registry, or resample an existing receipt.

On pancakes, use the archived files directly. The parent should pass both frozen
100-company selections during preparation to exclude their members from the four
random additions, as required by the preregistration. Passing a holdout for
exclusion does not authorize a holdout run or inspect its research outcomes.

```sh
repository=/path/to/frozen/checkout
acceptance_root=/home/azureuser/projects/signalpost-crashsafe-acceptance-20261101
selection_root=/home/azureuser/projects/signalpost-live-comparison-20261027/selection
holdout_selection=/home/azureuser/projects/signalpost-reliability-finance-20261028/holdout-selection
runner="$repository/signalpost-starter-kit/scripts/run_crashsafe_acceptance.py"

python3 "$runner" --root "$acceptance_root" --repository "$repository" \
  --registry "$selection_root/enheter.csv.gz" \
  --original-selection "$selection_root/selection.json" \
  --matched-selection "$selection_root" --holdout-selection "$holdout_selection" \
  --prepare-only

# Only after the parent has finished integration and frozen the implementation:
python3 "$runner" --root "$acceptance_root" --repository "$repository"
```

Preparation freezes HEAD, a hash of tracked/untracked source files, exact config
bytes, external timeout (default 3,000 seconds), input hash, sampling seed and
registry hash. Finish all implementation changes **before** preparing. The root
must be outside the checkout and private (0700). Default config is the
preregistered 2,700/2,214/486-second hard/soft/reserve budget, 2,000 physical
attempts, finance 180 seconds, NAV 360, Wikidata 12, websites 480, OCR 900 and
65% share. `--config FILE` freezes custom bytes instead. Reuse the same artifact
root; changing HEAD/source/configuration or a prerequisite artifact refuses work.

Each live invocation uses a new HOME/cache/OCR cache, checkpoint and HTTP capture.
Each replay uses its own HOME/cache/checkpoint and its live cohort's private OCR
cache, the same input/config/batch ID, and `--replay-http`. No `--resume` is used.
No stage, including an interrupted stage, may be retried in place.

The smoke execution gate requires ten complete final envelopes in input order,
all checkpoint shells terminalized, no batch aborts, no duplicate claim IDs or
inconsistent provenance IDs, complete durable phase metrics and a completion
aggregate. Isolated phase failures and failed finals are quality observations,
not batch aborts. Runtime <=1,200 seconds is reported separately for smoke.
Consistent shared evidence/snapshot IDs across envelopes are permitted by the
canonical graph contract; duplicates inside an envelope always fail.

Replay additionally requires exact **unmodified JSONL bytes and canonical state
bytes**, explicit zero HTTP/OCR misses/failures, zero actual network requests, a
sealed capture and empty missing/unconsumed request lists. Missing aggregate
fields fail; exit zero alone cannot satisfy this gate.

Large stages require separate explicit commands and persisted successful live
and replay reports. Matched additionally checks the original input hash. Holdout
requires successful matched execution and exact replay, a disjoint frozen input, no overlap with
observed smoke companies, and the parent's attestation that optional-data
outcomes have never been observed. The existing frozen holdout can be reused if
the parent confirms that condition.

```sh
python3 "$runner" --root "$acceptance_root" --repository "$repository" \
  --stage matched --allow-100 --matched-selection "$selection_root"

# Only after matched and matched replay pass, and the parent approves this cohort:
python3 "$runner" --root "$acceptance_root" --repository "$repository" \
  --stage holdout --allow-100 --holdout-selection "$holdout_selection" \
  --confirm-unobserved-holdout
```

Each large live cohort additionally gates finance >=95 companies, explicit FTE
>=50, verified website >=20, and runtime <=1,200 seconds. Coverage is not accuracy.
Coverage/runtime failure does not prevent measuring the untouched holdout when
structural and exact-replay prerequisites pass (`execution_gate_pass`). It still
makes the overall acceptance result fail (`gate_pass`).
There is no automatic next cohort, retry, or tuning between cohorts.

## Checkpoint and completion integration contract

The reader supports the parent's current SQLite `phase_status(phase,company,payload)`
schema. Every selected company must have an explicit committed record for
`official` (reported as `official_foundation`), `financial_statements`, `wiki_batch`,
`nav_batch`, `nav_apply`, `website_verify`, `website_shallow`, `jobs_activity`,
`annual_documents`, `finalization`. Payload requires `status`, `outcome`, nonnegative finite
`seconds`, and boolean `ran`, `skipped`, `deadline_skipped`, `failed`. It recognizes
the parent's distinct deadline-skip flag and aggregates it into total skips.
Explicit `ineligible`/`not_attempted` outcomes are counted; absent records fail.
Sanitized `traceback_sha256` values are retained, arbitrary reason strings are not.
Batch finalization timing comes from the completion aggregate; company seconds
are never presented as phase wall time.

Alternative reader adapters accept `company_phase_metrics` or `phase_metrics`
tables with company/organisation_number, phase, and numeric columns or a JSON
payload. Every record must supply integer `ran`, `skipped`, `deadline_skipped`,
`failed`, `ineligible`, `not_attempted`, plus `worker_seconds`, `wall_seconds`.
`ran + skipped == 1` and failure/skip subcounts must be consistent. A `run_meta`
key `company_phase_metrics` may instead contain a list of these records. Existing
`phase_results` alone is insufficient to prove complete counters.

The CLI must emit exactly one `batch_complete` JSON line with `output_cardinality`,
`runtime_seconds`, `finalization_seconds`; replay also requires `research_mode:
"replay"` and `actual_network_requests: 0`. Emit `http_misses`, `http_failures`,
`ocr_misses`, `capture_complete`, `missing_requests`, `unconsumed_requests` in a
`replay_complete`/`replay_failed` JSON event, or as top-level `batch_complete`
fields. The integrated CLI exposes these diagnostics; absent diagnostics fail
the wrapper rather than implying zero misses.

Per-stage `report.json` is the sanitized aggregate: statuses, coverage company
counts, process/runtime timings, durable phase counts/seconds, duplicate counts,
hashed collision evidence, sanitized traceback structure and artifact hashes.
Raw stdout/stderr, invocation command, SQLite, HTTP/PDF recordings and OCR caches
remain PRIVATE (root/dirs 0700, logs/receipts 0600); do not publish them. Failure
returns nonzero; structural failures prevent replay or subsequent cohorts. Wrapper failures also
persist sanitized evidence, and a refused repeat does not overwrite passed gates.

Run the dedicated tests without a live pipeline:

```sh
signalpost-starter-kit/.venv/bin/python -m pytest -q \
  signalpost-starter-kit/tests/test_crashsafe_acceptance.py
```
