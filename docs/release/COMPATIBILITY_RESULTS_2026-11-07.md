# Additive compatibility results — 7 November 2026

Base: `1da8befc56621d724ac54b6e56f23d696cf3b7f4`, documentation-only child of
runtime `f0902cb0cbb1a4cd5e9ac1d471f0c8459545ed73`. This work changes publication
compatibility and its consumers, not extraction, identity gates, claim IDs or
scheduler admission. Nothing was submitted or emailed.

## Environment and tests

Reused the exact venv installed by the earlier successful fresh clone:
`pancakes:/tmp/signalpost-presubmit-f0902cb-WiVaaM/repo/signalpost-starter-kit/.venv`.
Network policy is `direct`, as in that run; the failed initial attempt had
incorrectly selected trusted-proxy mode without a configured proxy.

Installed the declared test extra and documented pinned test runner:

```sh
cd signalpost-starter-kit
uv sync --frozen --extra m08-test
uv pip install --python .venv/bin/python pytest==9.1.1
PYTHONPATH=.. .venv/bin/python -m pytest -q
```

Final full-suite result: **1,358 passed, 252 subtests passed**, one upstream
`pyRdfa` UTC deprecation warning, 663.75 seconds. Focused consumer, identity-shape,
compatibility and hermetic replay selection: **143 passed, 28 subtests passed**.
Compatibility regressions fixed include wire aliases crossing strict model
boundaries, unknown section-state assertions, publication telemetry write
amplification, replay ordering dependencies, and consistent terminal aliases.
The unchanged starter validator's source has no diff from the base commit.

## Live gates

| Gate | Exit | Process seconds | Valid rows | Real supported rows | Duplicate claim IDs | Starter validator | Canonical graph / roundtrip |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 10, budget 18s | 0 | 16.87 | 10 | 10 | 0 | passed | passed / passed |
| 200, budget 360s | 0 | 332.41 | 200 | 200 | 0 | passed | passed / passed |

Live 10 counts: finance **10**, explicit FTE **0**, verified websites **0**, jobs
**0**. There were **35 physical requests**; internal runtime was 16.560 seconds.
The complete primary output committed; secondary state was incomplete. These
are counts, not scored recall or a coverage-improvement claim.

Live 200 counts: finance **196**, explicit FTE **0**, verified websites **0**,
jobs **1**. Physical requests: **584**; internal runtime: **331.700 seconds**.
The process self-exited normally, without the external safety timeout firing.
332.41 seconds is below both the 360-second budget and the 365.2-second runtime
gate. No retry was needed. FTE count was one in the older baseline and zero here;
no improvement or extractor change is claimed. This attempt recorded 199 document
deadline skips and one failure. The primary output committed; secondary state
and sealed live replay remain incomplete, not passed.

The 200 gate uses the same frozen first-200 input and configuration as the
332.033-second baseline. Input SHA-256:
`ffdc5ee5170b297feddf2811a166a64870ff0c1beb81d929f0913c561653081e`;
configuration SHA-256:
`6bc8c7126ce4d981042a78e58399f45b28b4b9ef70cdb19120a748ce45ecebca`.
The runtime threshold is 365.2 seconds (332 × 1.10), with an explicit 360-second
research budget. No new 1,000-company run is authorized in this cycle.

Runtime source identity, identical in the tested checkout and final local source:
`caa8a1bd529f8d8f585ef2256fef5d2143c1ef602bf70f76f21bb36383b415ad`.
Live measurements were taken on that working candidate before the final commit;
the final commit also includes this results documentation. They are not relabeled
as measurements of a later source-logic change.

### Live-200 phase evidence

| Phase | Completed | Failed | Deadline skipped | Wall seconds | Recorded requests |
| --- | ---: | ---: | ---: | ---: | ---: |
| Foundation | 200 | 0 | 0 | 8.155 | 4 |
| Finance | 200 | 0 | 0 | 70.601 | 200 |
| Official details | 96 | 0 | 104 | 60.305 | 193 |
| Annual documents | 0 | 1 | 199 | 111.308 | 8 |
| NAV batch | 200 | 0 | 0 | 49.522 | 18 |
| Wikidata batch | 200 | 0 | 0 | 10.672 | 2 |
| NAV application | 1 | 0 | 199 | 0.275 | — |
| Website verification | 39 | 4 | 157 | unmeasured | 159 |
| Website shallow | 0 | 0 | 200 | unmeasured | — |
| Jobs activity | 0 | 0 | 200 | unmeasured | — |

NAV/Wikidata are shared batch actions reflected in each company's status, not
200 separate traversals. Wall times overlap; do not sum them for runtime. Missing
or placeholder-zero phase wall metrics remain unmeasured. Recorded receipts
are not a claim of a sealed complete capture. Sanitized evidence:
[10](evidence/compatibility-20261107/live-10.json),
[200](evidence/compatibility-20261107/live-200.json).

Commands (private artifact directory abbreviated as `$E`):

```sh
./run.sh --input "$E/input.jsonl" --output "$E/output.jsonl" \
  --state-output "$E/state.json" --checkpoint "$E/checkpoint.sqlite" \
  --output-first --budget-seconds 18 --network-policy direct
```

For 200, use `--budget-seconds 360 --config "$E/config.json"` and
`--record-http "$E/capture"` with the same remaining arguments.

Unchanged validator, run on the original output rows without translation:

```sh
PYTHONPATH=signalpost-starter-kit/src signalpost-starter-kit/.venv/bin/python -c \
 'import json; from norway_company_agent.batch import validate_envelopes; rows=[json.loads(line) for line in open("OUTPUT.jsonl")]; print(json.dumps(validate_envelopes(rows, EXPECTED_COUNT), sort_keys=True))'
```

Live-10 validator output:

```json
{"checks": {"all_entity_states_terminal": true, "all_module_states_terminal": true, "exact_expected_count": true, "unique_organisation_numbers": true, "zero_silent_drops": true}, "invalid_states": [], "passed": true}
```

Canonical verification decodes every original output row, validates the complete
cross-envelope publication graph, checks globally unique top-level claim IDs,
and asserts `from_evaluator(to_evaluator(row), row.row_number) == row` for each
canonical decoded row. This does not claim recovery of unpublished internal
operational observations from evaluator JSONL.

## Contract differences and limits

See `LIMITATIONS.md` for the exact legacy/public mapping. Top-level `state` and
module states use the unchanged starter vocabulary; `terminal_state`, claim
availability and section states use the public vocabulary. The official private
parser's choice between `state` and `terminal_state` is unconfirmed. Run
`terminal_status` is the same legacy status, whereas the public example uses
`completed`; the example is not a formal enum schema. Profile output is the
supported deterministic summary, not fabricated source-module observations.

Confidence remains null where uncalibrated. The starter validator ignores it;
private-parser null acceptance is unproven. Unassessed sections retain original
null state and outcome in canonical aliases while exposing the requested public
`not_available` placeholder. Requests are company-attributed charged attempts;
shared batch requests are reported separately in the aggregate. Runtime and
completion timestamps describe a publication snapshot, not company CPU or proof
that all optional work completed. API charges are zero; compute cost is unpriced.

The original operation array is retained as `operation_log`. Internal query/web,
site export, profile and smoke consumers normalize aliases without changing
canonical checkpoint/history models or identity checks. Sealed synthetic replay
tests pass; this is not proof of new live-scale sealed replay or a committed
secondary state pair. Low FTE/website coverage and previous scale limitations
remain. Exact-commit CI and final branch/main status are reported separately.

Private evidence: `pancakes:/tmp/signalpost-compat-evidence-20261107-r2/`.
