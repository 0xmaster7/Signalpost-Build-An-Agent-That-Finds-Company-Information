# Reliability/finance experiment: acceptance failed

## Frozen execution and failures

Both cohorts ran the same immutable, exact-CI-green source `2ec51c948752a16484127fe8d353a4a382c60e71`, sequentially with no intervening edits or outcome tuning. [CI](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/40700668085) passed setup twice, local OCR, the full suite, contracts and publication checks. The corresponding VM suite passed **811 tests and 237 subtests**. The [preregistration](RELIABILITY_FINANCE_PREREGISTRATION_2026-10-28.md) and [ordered audit](RELIABILITY_FINANCE_AUDIT_2026-10-28.md) explain resources and historical evidence. Configuration SHA-256: `8bea1bf324b67266735599c3e0f9bd583e062c5d0cdc52bb61875ac2a95eb73c`.

Before research, two bootstrap launches exited 2 in 0.004 seconds each because the shared test environment lacked the setup receipt required by `run.sh`. Those receipts were preserved separately. A fresh project-local setup initially hit a package-download timeout, then succeeded using cached wheels and a longer download timeout; repeat setup and the pinned-version/local-OCR/offline-wrapper verifier passed. `run.sh` performed no installation. These infrastructure failures are not successful research runs and are not hidden.

The subsequent actual live attempts both exited 1 during official foundation projection:

| Measure | Matched 100 | Fresh holdout 100 |
| --- | ---: | ---: |
| Process elapsed seconds | 6.885 | 6.077 |
| Final envelopes | 0/100 | 0/100 |
| Pending checkpoint shells | 100 | 100 |
| Completed checkpoint envelopes | 0 | 0 |
| Captured physical HTTP attempts | 9 | 9 |
| Received / transport error / cancelled | 5 / 2 / 2 | 5 / 2 / 2 |
| Summed captured HTTP seconds | 5.700420 | 5.570940 |
| Finance / explicit FTE / verified website companies | Unknown | Unknown |
| Overall acceptance | **FAIL** | **FAIL** |

Input hashes remain exactly `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076` and `8ef2df33c4c275b18ac6c6f6ca754db0a8596755ba382bab4e6bb0f54eef44af`. Neither input was resampled. The holdout was selected before development and excluded both previous cohorts.

## Phase statuses and timings

| Phase | Matched | Holdout | Timing interpretation |
| --- | --- | --- | --- |
| Official foundation | Ran; fatal projection exception | Ran; fatal projection exception | Complete phase wall time and per-company counters unavailable after abort |
| Structured finance | Not reached | Not reached | No accounts HTTP requests captured |
| Wikidata | Not reached | Not reached | No SPARQL HTTP requests captured |
| NAV | Not reached | Not reached | No feed requests captured; whole-window indexing untested |
| Website verification/shallow/jobs | Not reached | Not reached | No website HTTP requests captured |
| Annual PDF/FTE OCR | Not reached | Not reached | No PDF requests captured |
| Finalization | Not reached | Not reached | No final publication |

Each capture contains three entity attempts, two roles, two subunits and two robots attempts. These are request counts, **not** persisted scheduler `ran/skipped/deadline_skipped/failed` company counts. No phase deadline caused these aborts. Missing counters/timings are unknown, not manufactured zeros. HTTP duration sums are not phase wall time. Historical matched-rerun counts, OCR time and NAV's 32-page time-limit stop remain in the ordered audit.

## Reproduced collision and generic repair

The traceback ends at `run._live_envelope()` during `checkpoint_writer()` inside the official-foundation scheduler, with `Envelope` rejecting duplicate claim identifiers at `row:1`. This is a new, reproducible foundation failure, not proof of the original missing October-27 collision pair.

Offline inspection of the matched capture recovered repeated `role.role_group_code`, `role.role_group` and `role.last_changed` claims. Group metadata was projected once per role. Identical content correctly acquired identical deterministic IDs, but the BRREG producer appended it repeatedly instead of merging evidence. This is **not a SHA-256 collision**.

For example, two actual colliding projections had these common public, non-personal fields:

```json
{
  "claim_id": "937060092:fact:3d228065e99525597334abcb1f69f866e71ba432f2d0893387bf198cf920f309",
  "organisation_number": "937060092",
  "subject_id": "937060092",
  "field": "role.role_group_code",
  "value": "STYR",
  "scope": "person_role",
  "as_of": "2026-01-29T00:00:00Z",
  "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/937060092/roller",
  "json_pointer": "/rollegrupper/1/type/kode",
  "content_sha256": "6a79727f07c496efb3e1999f552ad689e56864697a0c2eacedf8dcde701642f0"
}
```

Their evidence IDs were respectively `937060092:leadership_workplaces:32:6a79727f07c4` and `937060092:leadership_workplaces:40:6a79727f07c4`. Five occurrences shared this ID. The repair merges all five evidence links into one claim and retains genuinely different values, pointers, sources and scopes. Conflicting semantic payloads under the same ID still raise rather than being silently discarded. Six new fixture tests cover repetition, distinct facts and a deliberately forced semantic conflict. **96 focused tests and 26 subtests passed.**

The captured first company's repaired projection contains **71 claims and 71 unique IDs**, with all five links retained for the illustrated group-code claim. No company-specific research rules or thresholds changed. The repair was made only after both failed runs ended. Neither cohort was rerun after repair, respecting the one-run measurement protocol; its live acceptance remains unproven.

The integrated repair suite passed **817 tests and 237 subtests** on the VM, with one third-party deprecation warning. This is offline regression evidence, not a substitute for a completed live run.

## Per-step before/after evidence

| Step | Before | After implementation | Live effect isolated? |
| --- | --- | --- | --- |
| 0: audit | Original holdout collision objects/timings missing | Dependencies, surviving timings and gaps documented | Not an intervention |
| 1: reliability | Previous holdout aborted with no optional checkpoint | Offline fault/resume/identity tests pass; new live foundation duplicate exposed and repaired offline | **No; live reliability failed** |
| 2: independent finance | Previous matched finance 42/100; earlier baseline 77/100 | API-only publication/reservation and scope/unit tests pass | **Unknown: phase never ran** |
| 3: FTE OCR | Previous matched FTE 28/100; earlier baseline 50/100 | FTE-only ordering, early stop, persistent cache and deadlines tested | **Unknown: phase never ran** |
| 4: discovery | Previous matched websites 0/100; NAV partial at 32 pages | Reserved discovery/concurrency, feed-first traversal and tier logging tested | **Unknown: phase never ran** |
| 5: replay | No strict private full-pipeline capture path | Fixture pipeline/transport tests pass; failed live prefix reproducible offline | **No full live replay/ablation possible** |

The historical unchanged competitor run had 98 financial-company, 29 explicit-FTE and 25 verified-website companies. It was not rerun here, and is not a synchronized comparison with this failed experiment. Coverage is not independently measured accuracy; assumed financial scale is not an official unit guarantee.

## Replay outcome and unmet gates

After the generic repair, strict offline replay of the matched capture exited **1 in approximately 3 seconds**, with `http_misses=395`, `http_failures=2`, `ocr_misses=0`, and no final publication. The capture stops during foundation and includes cancelled attempts; it cannot supply the rest of 100 companies or optional branches. Replay made no live HTTP fallback. Its partial checkpoint demonstrates the repaired duplicate handling, **not** valid full-batch coverage. No PDFs were captured, so warm-cache FTE replay and per-step coverage ablations remain unproven.

- **100 final envelopes / no aborted runs: FAIL** on both actual live attempts; also disclose the two bootstrap failures.
- **Finance >=95, explicit FTE >=50, verified websites >=20: NOT DEMONSTRATED** on either cohort because acquisition never reached those phases. Do not relabel unknown coverage as zero.
- **Runtime <=1,200 seconds: NOT AN ACCEPTANCE PASS**; a fast abort is not a completed benchmark.
- **No duplicate IDs: FAIL** on the frozen live source; only the later generic repair has offline evidence.
- **Tests/exact-SHA CI:** frozen source passed; the later repair/report commit requires its own CI, linked from the final release response.

No further live calls, retries, resampling or cohort-driven threshold changes were used to turn these failures into a pass. Raw HTTP responses, contacts, full envelopes, tokens and SQLite files remain private. There are no per-company final JSONL/CSV results to publish; the absence itself is reported. The machine-readable public receipt is [summary.json](evidence/reliability-finance-20261028/summary.json).
