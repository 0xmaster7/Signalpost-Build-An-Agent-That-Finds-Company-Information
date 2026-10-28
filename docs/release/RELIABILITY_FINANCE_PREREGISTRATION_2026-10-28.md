# Reliability and independent finance: frozen measurement protocol

Written before either new live run. The experiment receipt records the exact source commit, configuration hash, input hashes and start times. No implementation or configuration changes are allowed between cohorts; both run once even if the first fails.

## Cohorts

1. Original 100 employers, including the six-company cohort: input SHA-256 `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076`.
2. Fresh 100 active AS employers with disclosed employees, excluding both previous cohorts. Selection was frozen before development outcomes were consulted, at `2026-10-27T19:46:48.671564+00:00`. Input SHA-256 `8ef2df33c4c275b18ac6c6f6ca754db0a8596755ba382bab4e6bb0f54eef44af`; seed `94bcdc2c7bd07214286ebe92c708be909d407fd8cbecf7b2f6248d6b8e030d18`. Archived registry frame SHA-256 `f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece`.

## Acceptance gates on each cohort

- Exactly 100 valid final envelopes, no aborted batch or duplicate claim IDs.
- At least 95 companies with monetary financial claims; distinguish assumed units from directly documented units, company from group scope, and historical from latest-period counts.
- At least 50 companies with explicit company-level FTE, including explicit zero but not headcount.
- At least 20 companies with verified websites, excluding registry-declared URL-only and shared-site references.
- End-to-end live runtime at most 1,200 seconds, excluding installation and sampling.
- All tests and CI pass on the frozen source commit. Missing gates are reported as failures, not relaxed retrospectively.

## Fixed resources and interpretation

Retain the prior comparable configuration: 2,700 seconds hard, 2,214 soft, 486 completion reserve, 2,000 physical requests. The 1,200-second acceptance gate is deliberately stricter than the execution ceiling: a completed slower run fails runtime. Reserve finance up to 180 seconds (clamped to 25% of remaining soft time for very small configurations), NAV 360, Wikidata 12, websites 480. OCR is capped at 900 seconds and 65% of remaining soft research time, with two killable workers. Wikidata precedes discovery; NAV overlaps OCR; website work follows NAV and overlaps remaining OCR. No monetary OCR prerequisite remains.

Each cohort starts with fresh state, HTTP research acquisition and a separate cold OCR cache. Private HTTP/PDF capture is enabled; raw captures, tokens, contact data and checkpoints are not published. NAV truncation is unknown/incomplete, never a no-jobs assertion. Source failures and phase counts/timings are reported separately from coverage.

After both runs, strict offline replay may use each capture and its warm OCR cache with separate outputs/checkpoints. A missing response or cache entry fails closed. A deadline-limited capture may not cover branches reached by faster replay; report this limitation rather than silently using live HTTP. Replay time is not live runtime.

The before/after comparison measures the bundled implementation. Synthetic stepwise regression tests establish mechanisms, not component-specific live gains. Neither earlier captures nor final captures necessarily support a controlled per-step ablation; list any unproven attribution explicitly. No retries or cohort-specific tuning are allowed. The earlier unchanged competitor benchmark remains historical evidence, not a fresh synchronized comparator.
