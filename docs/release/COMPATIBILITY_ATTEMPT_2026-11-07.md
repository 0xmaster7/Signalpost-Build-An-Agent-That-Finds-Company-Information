# Initial compatibility attempt — 14:43 UTC, 7 November 2026

This historical attempt is superseded by the resumed
[compatibility results](COMPATIBILITY_RESULTS_2026-11-07.md). The statements below
describe the initial stopped attempt, not the current candidate's status.

Base: `1da8befc56621d724ac54b6e56f23d696cf3b7f4`, documentation-only child of
runtime `f0902cb0cbb1a4cd5e9ac1d471f0c8459545ed73`. Candidate changes are
uncommitted; no candidate exact-commit CI exists. No commit or push was made.

## Smoke invocation and unchanged validator

On pancakes, working snapshot `/tmp/signalpost-compat-20261107-r2`, using the
first 10 rows of the previously frozen 1,000-company input:

```sh
E=/tmp/signalpost-compat-evidence-20261107-r2
./run.sh --input "$E/input10.jsonl" --output "$E/output10.jsonl" \
  --state-output "$E/state10.json" --checkpoint "$E/checkpoint10.sqlite" \
  --output-first --budget-seconds 18 --network-policy trusted-proxy
PYTHONPATH=signalpost-starter-kit/src signalpost-starter-kit/.venv/bin/python -c 'import json; from norway_company_agent.batch import validate_envelopes; rows=[json.loads(line) for line in open("/tmp/signalpost-compat-evidence-20261107-r2/output10.jsonl")]; result=validate_envelopes(rows,10); print(json.dumps(result,sort_keys=True)); raise SystemExit(0 if result["passed"] else 1)'
```

Process exit 0; `/usr/bin/time -p` real 3.77 seconds; internal runtime 3.473
seconds. Validator output, unchanged:

```json
{"checks": {"all_entity_states_terminal": true, "all_module_states_terminal": true, "exact_expected_count": true, "unique_organisation_numbers": true, "zero_silent_drops": true}, "invalid_states": [], "passed": true}
```

**This is not a successful live smoke:** no proxy was configured, so there were
zero physical requests and 10 failed rows. Errors explicitly report
`NetworkPolicyError: trusted-proxy mode has no configured proxy for this scheme`.
Finance/FTE/verified website/jobs available-company counts are all zero; they do
not measure extractor coverage. The primary output and state pair were committed
for these failure envelopes. No live improvement is claimed.

Strict reverse-adapter and publication-graph validation accepted all 10 rows.
The full-suite command was:

```sh
cd signalpost-starter-kit
PYTHONPATH=.. .venv/bin/python -m pytest -q
```

It could not start: `No module named pytest` (exit 1). No tests are reported as
passed. Verification stops here: no 200-company run, no 1,000-company run, no
replay and no candidate CI. The 19:45 IST 1,000-company launch cutoff had already
passed before this resumed implementation cycle.

## Contract uncertainty

See `LIMITATIONS.md` for the source-derived legacy/public mapping and measurement
scope. The supplied validator ignores confidence, evidence completeness and
research success. Its structural acceptance is not proof of private official
parser acceptance. Public example differences remain: legacy top-level state,
uncalibrated null confidence, nullable unknown measurements and snapshot timing
semantics. No formal private schema/parser was supplied. Existing canonical
fields are retained, except the specifically requested `operations` object
replaces the array, preserved under `operation_log`.

**Safe to submit this candidate: no.** Larger live runtime, full tests, exact
replay and exact-commit CI remain unproven. Nothing was submitted or emailed.
