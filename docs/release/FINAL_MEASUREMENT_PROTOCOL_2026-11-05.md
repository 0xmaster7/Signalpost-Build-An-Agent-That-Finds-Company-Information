# Final measurement protocol — 5 November 2026

This protocol separates implementation freeze and input preparation from all
research outcomes. `run_final_acceptance.py --prepare-only` makes no subprocess
call and performs no network, OCR, or research work. The parent owns live runs,
manual wrong-company review, report export, and publication.

## Frozen inputs and population

Use the archived registry at
`/home/azureuser/projects/signalpost-live-comparison-20261027/selection/enheter.csv.gz`
with SHA-256
`f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece` and its
original `selection.json`. The matched input must be the archived
`companies.jsonl` with SHA-256
`acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076`.

The default smoke input contains the six fixed original companies and four
seeded selections. Fresh-100 and scale-1000 are independent, without-replacement
samples from the same frame. All additions exclude the matched input, every
directory passed with `--exclude-selection`, and all other frozen cohorts.
Sampling uses eligible active Norwegian AS employers with at least one
registered employee. It applies no optional-data, website, finance, or document
outcome filters. This frame does not establish generalization beyond active AS
employers. Seeds, frame and source hashes, exact input hashes, repository HEAD
and source hash, configuration bytes/hash, budget, and stage sizes are persisted
before outcomes exist.

Pass the parent's prior holdout and smoke selections with repeated
`--exclude-selection` arguments. Exclusions are read only to verify and record
their inputs. Never overwrite a preparation root or stage artifact. If the
implementation, config, or selection changes, prepare a new root and document
the reason; do not repair or replace an existing receipt.

```sh
python3 signalpost-starter-kit/scripts/run_final_acceptance.py \
  --root /private/new/final-acceptance-root \
  --repository /path/to/frozen/repository \
  --registry /home/azureuser/projects/signalpost-live-comparison-20261027/selection/enheter.csv.gz \
  --original-selection /home/azureuser/projects/signalpost-live-comparison-20261027/selection/selection.json \
  --matched-selection /home/azureuser/projects/signalpost-live-comparison-20261027/selection \
  --exclude-selection /path/to/prior-holdout-selection \
  --exclude-selection /path/to/prior-smoke-selection \
  --seed 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --prepare-only
```

The output root must be new, private (mode `0700`), and outside the repository.
The default run budget is 1,800 seconds, configurable with
`--budget-seconds` during preparation. The value and configuration are frozen
in the manifest. Live BRREG and website research run with
an 8,000-physical-attempt cap, leaving capacity beyond the identity/API breadth
requests for 1,100 companies. This is a local measurement setting, not an
organizer-provided allowance. `official_details` is a required durable phase.
`run.sh` is invoked with
HTTP recording enabled. Each live stage has private HOME, XDG, OCR and NAV
caches, logs, capture, state, and checkpoint. Replay uses the same source,
batch, budget, config, and warm OCR/NAV caches with strict HTTP replay. Replay
must match the fresh envelope JSONL bytes and state bytes, consume the complete
capture, report zero HTTP/OCR misses and failures, and make zero network calls.

## Execution order and authorization

Run one command for each stage. Smoke is the default ten-company stage.
Matched, fresh, and scale each require `--allow-stage`. Fresh and scale also
require persisted passing matched execution and exact replay. Scale has no
coverage gate or coverage report. The wrapper will not launch later stages,
retry a stage, replace a selection, or automatically increase a cohort.

```sh
python3 signalpost-starter-kit/scripts/run_final_acceptance.py --root /private/new/final-acceptance-root
python3 signalpost-starter-kit/scripts/run_final_acceptance.py --root /private/new/final-acceptance-root --stage matched --allow-stage
python3 signalpost-starter-kit/scripts/run_final_acceptance.py --root /private/new/final-acceptance-root --stage fresh --allow-stage
python3 signalpost-starter-kit/scripts/run_final_acceptance.py --root /private/new/final-acceptance-root --stage scale --allow-stage
```

Stop after a failed execution or replay gate. No tuning is permitted between
the final cohorts. A failed measurement threshold is reported as a failed
measurement; it does not authorize resampling or a retry. Keep all source logs,
captures, PDFs, OCR data, checkpoints, and raw envelopes private. The wrapper
writes only sanitized aggregate reports. It never copies raw claims or contact
details into its report. Exception messages and arbitrary URLs are excluded.

## Gates and reporting

Every cohort requires exact final cardinality and input order, zero duplicate
claim IDs, complete durable phase counters, and one final envelope per input.
The helper checkpoint reader validates explicit `phase_status` records and
reads the SQLite checkpoint in read-only mode. Smoke is ten rows: six original
plus four sampled. Matched is the exact archived input. Fresh is a new 100-row
sample. Each 100-company cohort reports finance-company coverage (gate >=95),
explicit FTE coverage (gate >=50), and verified-website coverage (gate >=20).
These are measurement gates, not accuracy estimates. Wrong-company attribution
is `UNKNOWN` until the parent completes manual review; do not report it as zero.

For 100-company stages the sanitized report includes a document table with
organisation number, document SHA-256, worker seconds, text-layer page count,
OCR page count, and resolution method, where those values were persisted. It
also includes linearly interpolated p50/p95 per-company phase seconds. The
company-phase percentile excludes shared `nav_batch` and `wiki_batch` time;
foundation timings are queue-inclusive when the checkpoint provides them.
The report also gives p50/p95 of each company's summed recorded phase seconds;
these sums exclude shared batch phases and are not end-to-end wall latency.
Batch phase wall time and finalization wall time are reported separately and
are not added to per-company worker totals.

Scale-1000 measures only row count/order, duplicates, runtime, budget outcome,
durable phase statuses/counters, and timing percentiles. Its report contains no
coverage aggregate or per-company fact count. It does not inspect coverage to
decide inclusion or success. `document_table` is limited to the 100-company
stages. Population and generalization limits remain explicit.

The 100-company run budget defaults to 1,800 seconds. Reports distinguish
process elapsed time, pipeline runtime, phase worker time, and shared phase
wall time. Raw exception messages, source URLs, claims, and contact information
must not be copied into public reports. The parent may publish sanitized report
JSON and the document-level aggregate table after review; private checkpoints
and full logs are not publication artifacts.

`phase_status_counts` is disjoint: `ran` means successful phase execution,
`skipped` excludes deadline skips, and failures have their own count. Native
checkpoint counters are also retained: their `ran` includes failed attempts
and their `skipped` includes deadline skips. Shared batch-phase company seconds
repeat the same shared duration for each company; do not sum these as wall time.

## Offline unit verification

The dedicated test file uses local synthetic registry frames and a mocked
subprocess. It does not call a live service or launch `run.sh`:

```sh
uv run --no-project --with pytest --python .venv/bin/python -m pytest -q \
  signalpost-starter-kit/tests/test_run_final_acceptance.py
```
