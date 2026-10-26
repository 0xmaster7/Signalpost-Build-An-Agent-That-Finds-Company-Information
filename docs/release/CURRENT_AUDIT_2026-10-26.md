# Current audit and reference comparison — 26 October 2026

Baseline: [`a9d0bc8`](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/commit/a9d0bc8b4aad5d1d7baec58f2ad20aa4686315a6), canonical `main`. Remote fetched; worktree clean before changes; no active coding process found. This is a code/test and saved-document review, not a new live benchmark or an exhaustive security audit.

## Issues and disposition

| Priority | Finding | Action / remaining work |
| --- | --- | --- |
| High | Workforce parser accepted essentially one template phrase; explicit average-FTE and company-FTE statements were missed. | Fixed: additional whole-row Norwegian FTE grammars, with confidence, company, year and conflict checks. Headcount and missing-decimal guesses remain excluded. |
| High | `NOK 1 000 000` matched the thousands prefix in the scale parser. JSON reconciliation normally withheld mismatches, but the unit interpretation itself was wrong. | Fixed: consume complete explicit scale; reject unsupported or contradictory suffixes; retain the adjacent Note/year-column layout. |
| High | OCR semaphore waiting was outside the supplied processing deadline. Queued tasks could start OCR after their time allowance. | Fixed: queue, startup and execution share one timeout; expired workers are killed; slots are released; queued cache reuse is checked again. |
| High | Latest measured cohort still has 0/6 verified websites, profiles, jobs and dated activity. Discovery, permitted access and exact ownership proof limit the downstream crawl. | Unresolved coverage gap. Next step: a separately measured same-cohort discovery/contact-page investigation; do not turn mentions or group websites into ownership proof. |
| Medium | OCR is limited to seven prioritized pages/90 seconds; continuation-page headers and other workforce prose can remain unsupported. | Bounded limits retained. Next step: a labeled saved-document corpus for continuation-page/column handling before widening extraction. No fresh coverage percentage is claimed. |
| Medium | Two business-description tests relied on execution before a fixed October 17 cutoff. They failed on October 26 despite unchanged production behavior. | Fixed fixture acquisition clock; added a regression proving later observations remain excluded by explicit historical cutoffs. |
| Medium | Foundation retrieval still makes per-company calls; bulk registry loading could save requests on large batches. | Not implemented here: requires a streaming bulk adapter, provenance/cutoff mapping, privacy handling and download-size accounting. Existing 1,100-company tests are offline and do not prove live-scale performance. |
| Release | Official Builderr parser compatibility/resource limits and a licence grant for this project's own code remain unresolved in release documentation. | Owner/organizer decisions remain; no official score or licence grant is invented. |

## Arnav reference: what changed and what is better

GitHub default-branch history and a fresh clone both identify [`Arnav020/SignalPost@169cc6b35851cd0336fb9d70b5617253354f0473`](https://github.com/Arnav020/SignalPost/tree/169cc6b35851cd0336fb9d70b5617253354f0473). Its latest commit is **16 October 2026**: there are **no newer commits** than the previously investigated version. No repository licence was declared at inspection; no reference source code was copied.

| Reference approach | Assessment and our action |
| --- | --- |
| Multiple explicit FTE statement formats in `signalpost/workforce.py` | Useful breadth. Independently implemented additional formats, retaining OCR-box confidence, exact filing identity, reporting year, company scope and cross-page conflict checks. We do not adopt O-to-zero or lost-decimal repair. |
| Bulk entity/role/workplace registry loading in `signalpost/registry.py` | Promising for large batches. Its published run reused cached bulk files; the 417-request figure excludes acquisition of those cached files. Not a like-for-like speed/request comparison with our live cohorts. Streaming integration remains follow-up work. |
| Broader website identity tiers in `signalpost/website.py` | Its smoke artifact records nine verified sites/100 companies. Several tiers use less restrictive evidence than ours. We retain typed ownership and shared-entity protections; neither project's historical sample establishes comparative precision. |
| NAV, Wikidata and directory discovery | Its artifact records 85 NAV feed pages and **zero confirmed NAV companies**, one Wikidata entity and one directory page. These are historical artifacts, not newly reproduced source accessibility or demonstrated broad job coverage. No unverified provider was activated. |

The reference's smoke report records **95 accepted workforce results/100 inputs**; this is its recorded parser output, not an independently verified FTE accuracy rate. Its extractor also supports employee headcount and stops at the first accepted page. Our latest measured **4/6 FTE** result uses a different cohort and stricter checks; these fractions must not be ranked as equivalent tests.

## Verification

- Focused annual-document and coverage regressions: **31 tests + 14 subtests passed**.
- Six-filing saved-source comparison: **71 financial claims and 4 FTE claims unchanged** between baseline and updated parsers over identical fresh local OCR. Zero physical HTTP requests. [Hash-bound receipt](evidence/current-audit-20261026/saved-filing-regression.json).
- Full suite: **513 tests + 237 subtests passed** in 259.33 seconds; one existing third-party pyRdfa UTC deprecation warning.
- Independent evaluator/process/failure/refresh acceptance: **passed**, using controlled transport with zero actual HTTP requests.
- Commands: `PYTHONPATH=.. .venv/bin/python -m pytest -q` from `signalpost-starter-kit`; `signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/scripts/validate_signalpost_functionality.py --output-dir /tmp/signalpost-audit-20261026-acceptance` from the repository root.
- Final exact-SHA CI is verified after push and linked in the handoff; local passes are not a preclaim of remote success.
- No new live company requests, paid services, provider integrations or dependency changes. Existing live results in [RESULTS.md](../../RESULTS.md) remain historical measurements of the earlier implementation.
- Added cases cover million/thousand scale, unsupported units, alternate FTE phrasing, historical-year/headcount/group/low-confidence rejection, distant-row rejection, OCR queue timeout and worker cleanup.

The resulting changes improve demonstrated parsing and deadline behavior. They do not establish higher overall live coverage than the reference implementation.
