# Recorded live baseline — 3 November 2026

Frozen implementation: `725eb6375feb0529da4cbe4f73bff05bd6e693f2`.
This is historical evidence, not a measurement of the subsequent implementation.

| Cohort | Envelopes | Finance | Explicit FTE | Verified websites | Jobs | Live seconds | Replay seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Smoke | 10/10 | 10 | 8 | 0 | 0 | 401.748 | 14.262 |
| Matched | 100/100 | 98 | 23 | 0 | 3 | 1128.650 | 161.709 |
| Previous holdout | 100/100 | 99 | 29 | 0 | 3 | 1134.574 | 169.887 |

Both hundred-company cohorts missed FTE >=50 and verified websites >=20.
All three runs produced complete final cardinality, zero aborted inputs and zero
duplicate claim IDs. Replays recomputed identical envelope and state bytes with
zero HTTP/OCR misses, network calls or unconsumed capture attempts. No tuning
occurred between those cohorts. The previous holdout is excluded from new fresh
sampling; it is no longer an unseen cohort.

Exact-commit CI succeeded:
https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/41618143811
(898 tests and 237 subtests). Its M06 aggregate offline-scale step took
2h36m35s; green CI did not establish acceptable scalability.

The matched document phase had 35 successful runs, two ineligible companies,
62 deadline-skipped phases and one isolated transport failure. Its 900-second
allocation limited FTE coverage. The previous holdout had 39 successful runs,
one ineligible company and 60 deadline-skipped phases. Some completed document
outcomes also reached internal OCR deadlines; successful phase execution is not
equivalent to finding FTE.

Matched website research produced 116 `robots_unreachable` candidate decisions,
21 URL-only registry-declared candidates and no verified websites. Candidate
counts are not disjoint company counts. See the
[website diagnosis](WEBSITE_DIAGNOSIS_2026-11-05.md) for the later cause breakdown.
NAV traversed all 78 feed pages on each hundred-company run, but exhausted its
359.5-second allowance resolving details. Unresolved entries remained unknown;
three positive-job companies do not imply that the others had zero vacancies.

## Provenance

- Matched input SHA256: `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076`.
- Previous holdout input SHA256: `8ef2df33c4c275b18ac6c6f6ca754db0a8596755ba382bab4e6bb0f54eef44af`.
- Smoke input SHA256: `23eedfa9e30073ade459b1271071863fbed7aac22d292beaf50d274d384a0a3f`.
- Frozen source SHA256: `7fd3ce3c528be93089f1e77ece8f9c74bf2a13c887f4c1e35945cc11c6e90dee`.
- Configuration SHA256: `8bea1bf324b67266735599c3e0f9bd583e062c5d0cdc52bb61875ac2a95eb73c`.

Transcribed from the sanitized `RESULTS.md` and reports prepared for that
release, retained locally at `/tmp/signalpost-acceptance-public-725eb63`.
Private source artifacts remain on `pancakes` at
`/home/azureuser/projects/signalpost-crashsafe-acceptance-725eb63`.
Those filesystem paths describe artifact provenance, not public download links.
Raw captures, PDFs, full private envelopes and checkpoints are not published.
Coverage is not an independent wrong-company or accuracy audit. No causal
per-change ablation or new field-by-field comparator run is claimed.
