# Phase-budget experiment — preregistered 27 October 2026

Frozen before either new live run. Baseline implementation `455d97925b3bcd4e7c47a643da5e4328a8299f5d`; baseline plus Wikidata API correction `6fc69c37102e8b732816ca865b1cef419e8e8b9b`.

## Acceptance gates

On the original 100-employer input, **all** of these gates are required for an overall pass:

- At least **20/100 companies with verified website claims**, excluding URL-only/shared/group references. This defines “near 25” in advance; ownership checks are not relaxed to reach it.
- At least **95/100 companies with monetary financial claims**. Separately report directly supported versus `unit_assumed_currency` observations, latest standalone periods, historical periods and group scope. Assumption-backed coverage is not relabelled independently verified accuracy.
- At least **50/100 companies with explicit company FTE statements**. Headcount does not count; report positive and explicit-zero values separately.
- Runtime **at most 1,200 seconds**, including cold research acquisition but excluding installation and sampling.
- Exactly 100 terminal envelopes, valid provenance/identity/scope/period contracts, no personal contacts or tokens in published artifacts. No claim is manufactured to meet a gate.

Jobs are a secondary outcome: report companies and distinct active-confirmed postings, scanned pages, window coverage and truncation. No minimum job count is required. Zero output remains unknown, not evidence of no jobs.

## Runs and frozen inputs

1. Rerun the exact original bytes once: SHA-256 `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076`. Same two-CPU host, 2,000-request limit, 2,700-second hard budget, 2,214-second soft budget and 486-second completion reserve as the baseline; empty research cache/state. The new phase caps are part of the treatment, not installation time.
2. Then run one **fresh disjoint random 100**, sampled from active AS employers with at least one registered employee, without the forced six. Freeze its seed, input hash and exclusions before observing its research results. Use the same immutable implementation, configuration and host. Do not tune against the first rerun before the holdout. Report the same gates on this holdout as a generalization check, not as an opportunity to retry until green.

The combined treatment changes scheduling, NAV indexing, FTE early-stop and financial calibration together. This is a before/after bundled-treatment comparison, **not a component-isolating ablation**, and live-source drift is a confounder. Do not attribute a measured gain to a single change without a later controlled component experiment. The unchanged competitor run is retained, not repeated.

Holdout selection was frozen at **2026-10-27T06:51:10.936291+00:00**, before either treatment run: input SHA-256 `2d75e5728b753cecfd8a2e7adf9df0d8d8e89fa83e8ea7855be4cbf962c3a9f4`, seed `47ddf63cbdf4602a0c31c2454013b376bb7ac6378a9e5e815bf2feecdf87aa1d`. All 100 original benchmark organisations are excluded; no fixed cohort is added. Both samples use the same archived official registry frame hash `f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece`. “Fresh” means disjoint from the matched cohort, not a new registry download or a guarantee that no company appeared in any historical dataset.

## Intended resource policy

Reserve batch NAV (120 seconds), Wikidata (12 seconds) and website research (480 seconds) before starting OCR. NAV/Wikidata run first, concurrently with each other after registry identity/workplace bindings exist. Then network-only website phases and the killable two-process OCR pool run concurrently. OCR receives at most 65% of remaining soft research time and a 900-second wall cap; no source may spend the atomic-output reserve. Request/time limits can make NAV partial; report that rather than claiming the whole window was indexed.

FTE candidate order is pages 5, 4, 6, 3 before fallbacks, after required identity verification. Stop at the first explicit acceptable company-level statement, retaining same-page conflict and confidence checks. A bounded additional monetary-anchor pass is separately identified; early FTE stopping does not prove unread pages agree.

Financial units are empirically calibrated per company from nonzero matching PDF/API anchors. Publication of generalized API amounts must retain the explicit assumption flag and its evidence basis, actual reporting periods and separate legal-entity/group subjects. An assumption is not an official API-wide scale guarantee. Explicit unit conflicts or invalid metadata must not be overridden merely to meet coverage targets.
