# Live 100-employer comparison — 27 October 2026

## Result

Both unchanged applications completed successfully and emitted one terminal envelope per input on the same 100 organisation numbers. These are **published coverage observations, not independently labelled accuracy/recall results**. No claim does not mean no website, vacancy or FTE statement exists.

| Measurement | Signalpost | Arnav's SignalPost |
| --- | ---: | ---: |
| Companies with verified website claims, excluding URL-only/shared references | 0/100 | 25/100 |
| Companies with URL-only/shared references | 0/100 | 7/100 |
| Companies with published job postings | 0/100 | 3/100 |
| Distinct published postings | 0 | 25 |
| Companies with explicit FTE claims | 50/100 | 29/100 |
| Positive / zero FTE claims | 46 / 4 | 26 / 3 |
| Companies with financial claims | 77/100 | 98/100 |
| Financial claims, all returned periods/scopes | 891 | 5,579 |
| Financial claims, latest observed standalone period per company | 891 | 1,872 |
| Group financial claims, kept separate | 0 | 96 |
| Terminal envelopes / exit code | 100 / 0 | 100 / 0 |
| Runtime including cold research acquisition | 2,222.116 s | 811.057 s |
| Reported requests, accounting differs | 493 physical attempts | 514 reported requests |

Arnav's report labels 29 companies as having verified websites. We recompute **25** from available `official_website` claims with `identity_level=exact/strong`, excluding URL-only notes and parent/group relations. Its historical 9/100 website and 95/100 FTE figures are not reproduced targets for this different employer sample: this run exceeds the website number but publishes only 29 FTE claims. Its OCR allocation processed 32 of 98 planned filings and accepted 29 statements; this is not a 29% extraction success rate across all filings.

## Where coverage is lost

1. **Our optional website phases never ran.** All 100 checkpoints say `execution_state=deadline_skipped`, `reason=soft_deadline_or_completion_reserve`. The OCR queue consumed the research window. About 478 seconds of completion reserve remained, but it was not research time. This is scheduling/resource allocation, not evidence that the ownership gate rejected 100 websites.
2. **Our NAV scan was too small to establish coverage.** Four feed pages and one detail request yielded no confirmed matching jobs; its audit explicitly says partial coverage. Arnav scanned 78 feed pages and confirmed 25 ads for three employers. Its missing-status/default-active and expiry rules differ from ours: these are published postings, not independently proven currently open jobs.
3. **Wikidata contributed nothing to our baseline.** Its audit says `not_attempted` because of the research reserve. Arnav returned five entities in one request. The separately reproduced crawler/API routing bug is real, but was not the immediate failure in this run.
4. **Our structured monetary API gate withheld 6,295 metric attempts across returned records.** Structured accounts are already fetched, but without a supported denomination the pipeline relies on PDF financial extraction. Document states: 77 available, 18 blocked, two failed, one not available, two without a document record. The 891 published monetary claims cover 77 companies. Spurious `*_unit_state` warning strings are excluded from the withheld count.
5. **More OCR work bought FTE coverage at other phases' expense.** We requested 84 PDFs with two OCR workers; Arnav requested 32 with one worker. Ours published 50 explicit FTE claims versus 29. This is not a controlled parser-only comparison; the next experiment should reserve phase time and use the same chosen PDF set.

The three earlier discovery additions have no demonstrated positive published contribution here: zero NAV jobs, zero URL-only/shared references, no Wikidata attempt. There was no ablation, so we cannot estimate causal improvement over an earlier release.

## Per-company and field comparison

- [CSV: all 100 IDs, names, cohort flags and coverage counts](evidence/live-comparison-20261027/per-company.csv).
- [JSONL: monetary/FTE values, periods, scopes, website/job evidence metadata, other-field availability inventories and pipeline diagnostics](evidence/live-comparison-20261027/per-company.jsonl).
- [Machine-readable summary](evidence/live-comparison-20261027/summary.json).
- [Downloadable searchable 100-company HTML table](evidence/live-comparison-20261027/coverage.html).

Only top-level claims count, not repeated section copies. Job atoms are grouped into postings and NAV UUID duplicates are deduplicated. Registered headcount and generic employee statements are not FTE. Explicit zero is preserved.

Financial comparisons join metric, period, company/group scope and currency, convert declared denominations and check filing versions: **734 equal declared-dimension observations, 157 ours-only, 4,845 Arnav-only**, with no numeric disagreements among joinable observations. FTE: **17 equal, 33 ours-only, 12 Arnav-only**. Unlike periods, including our non-calendar filing periods versus Arnav's constructed calendar periods, remain separate. Missing observations are not numeric mismatches.

**Financial scale caveat:** Arnav uses returned currency as monetary unit. The public schema and bounded official-source review did not establish a universal exported multiplier contract. The 734 agreements support observed consistency for those matched observations, not a guarantee for every API field/company/year. `equal_declared_dimensions` does not mean independently verified accuracy. Evidence metadata completeness is structural, not a semantic audit. Returned history is recorded; three years are not promised for every company.

Other envelope fields are compared as field/availability inventories, not asserted to be value-equivalent across differently shaped leadership/address/object schemas. Full raw envelopes remain private because they may contain personal roles/contacts. The public projection omits those values and raw descriptions.

### The six-company cohort within this batch

Counts are Signalpost / Arnav; financial totals include all returned periods.

| Organisation | Company | Jobs | Verified sites | FTE claims | Financial claims |
| --- | --- | ---: | ---: | ---: | ---: |
| 930827088 | ROMERIKE BARNEHAGE - SOLHAUG AS | 0 / 0 | 0 / 0 | 1 / 1 | 12 / 55 |
| 924356715 | TRAFIKKDRIFT AS | 0 / 0 | 0 / 0 | 0 / 0 | 10 / 59 |
| 992936916 | KVISTE MASKIN AS | 0 / 0 | 0 / 0 | 1 / 1 | 14 / 60 |
| 952780093 | PAUL AS | 0 / 0 | 0 / 0 | 0 / 1 | 12 / 59 |
| 920710514 | LAUVVERKET AS | 0 / 0 | 0 / 1 | 0 / 0 | 0 / 59 |
| 993955299 | RISINGVEIEN MAT AS | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 59 |

Our historical four-of-six FTE result was a separate small run. This batch's two-of-six is not replaced with that older result: queue order and budget affect document completion.

## Frozen protocol and provenance

- Signalpost: `455d97925b3bcd4e7c47a643da5e4328a8299f5d`.
- Arnav: `d2666383328c1779973af9d74b1d0d9b884b66e4`, `Arnav020/SignalPost`, cloned and run without source edits.
- [Input](evidence/live-comparison-20261027/companies.jsonl) SHA-256: `acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076`.
- [Selection manifest](evidence/live-comparison-20261027/selection.json): 94 seeded random additions from 60,946 active AS entities with at least one registered employee, plus six fixed companies, shuffled before execution. No filing-year/website/outcome filter. This is not 100 independently random selections.
- Fresh official entity CSV: 1,179,224 records, SHA-256 `f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece`. Full registry not republished. Arnav independently downloaded the same entity-file hash.
- Same two-CPU Linux host, sequential runs, cold research caches, separate state and sanitized environment without personal tokens. Python 3.12.3, pinned dependencies, local RapidOCR, no system Tesseract. Numerical libraries limited to one thread/process; each app kept its own OCR-worker allocation.
- Both configured for 2,000 requests / 2,700 seconds, with 3,000-second external safety timeout. Our soft research limit was 2,214 seconds plus 486 seconds completion reserve. Different request accounting means these are not identical wire-level caps.
- Sampling/dependency installation excluded from runtime. Arnav's three cold bulk downloads included; no warm registry files supplied.
- Ours: 26 October 2026 19:08:25–19:45:28 UTC. Arnav: 19:45:28–19:58:59 UTC. Both are 27 October in Asia/Kolkata. Live source cutoffs are sequential, not identical snapshots.
- [Execution receipt/output hashes](evidence/live-comparison-20261027/execution.json), [our report](evidence/live-comparison-20261027/ours-run.json), [Arnav's report](evidence/live-comparison-20261027/arnav-run.json). Both source revisions unchanged afterward; tracked worktrees clean.

Stdlib tools: `signalpost-starter-kit/scripts/select_live_comparison.py`, `run_live_comparison.py`, `compare_live_envelopes.py`. Selector refuses rerandomization; supervisor refuses an existing execution; comparator verifies input/output hashes and source revisions. Reproduction needs archived code and available sources; new live responses need not reproduce these numbers.

## Next decision

Highest demonstrated priority: reserve optional-source time while OCR runs, with a measured PDF allocation. Fix Wikidata's narrowly scoped API/User-Agent bug separately, keeping company-site robots/ownership checks intact. Do not silently assume financial denominations, remove PDF financial capability, adopt first-hit FTE conflict semantics, or claim cache/bulk changes improve coverage without follow-up measurement. No second 100-company run was launched to improve these results.
