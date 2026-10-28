# Reliability and finance dependency audit — 28 October 2026

## Step 0: before changing behavior

Starting public main: `5a6f53cfaf953d1be4d791c9c48af98ab6538d5f`. The previous experiment actually executed `d3aa87937f4589df88a3834a676fb95daba2a1ba`; `5a6f53c` recorded its failures and added the first publication guard. Both original runs remain unchanged.

`signalpost/brreg.py:fetch_company()` fetches the Regnskapsregisteret JSON endpoint once per company, as part of official foundation, before OCR. `financial_records()` preserves all returned filings, their own periods, SELSKAP/KONSERN scopes and versions. Explicit-unit metrics can publish directly. Missing-unit monetary metrics are withheld by the dimensional gate. Thus acquisition is not OCR-bound, but most publication is.

`signalpost/run.py:run()` defines `enrich().document_phase().annual_document()`, which awaits `signalpost/annual_accounts.py:enrich_company()` then calls `signalpost/financial_calibration.py:calibrate_company_financials()`. The latter requires two distinct nonzero PDF/API monetary agreements in the latest standalone filing before publishing other missing-unit metrics. Companies outside the document queue cannot calibrate. `annual_accounts._ocr_worker()` currently scans FTE notes and a separate page-2 monetary anchor; `reconcile()` returns financial and workforce candidates. Financial recovery therefore shares FTE's queue, subprocesses and deadline.

Registry identity, roles, workplaces and explicit-unit API metrics do not require PDF/OCR. The missing-unit recovery path and explicit FTE do. NAV jobs, Wikidata candidates and company website facts use network research, not OCR. Website facts still require ownership proof; candidates and registry URL-only declarations are not verified sites.

## Existing matched-run phase evidence

Source: [preserved aggregate report](evidence/phase-budget-20261027/matched-run.json), [summary](evidence/phase-budget-20261027/summary.json) and normalized per-company projection. No new live calls were used for this audit.

| Phase | Completed actions | Deadline-cancelled actions | Failed scheduler actions | Other status | Summed worker seconds |
| --- | ---: | ---: | ---: | --- | ---: |
| Official foundation, including structured accounts | 100 | 0 | 0 | No deferred actions | 611.932 |
| Website verification | 100 | 0 | 0 | No deferred actions; zero accepted sites | 1,148.410 |
| Website shallow | 0 results | No phase timeout | Unknown/missing counter | No accepted-site inputs | Not recorded |
| Jobs/activity | 0 results | No phase timeout | Unknown/missing counter | No accepted-site inputs | Not recorded |
| Annual documents | 45 | 2 | 0 | 51 eligible unscheduled; 2 without document records | 1,803.237 |
| NAV | One partial batch | Internal deadline | No detail failures | 32 pages, zero employer matches | 119.512 elapsed wall seconds |
| Wikidata | One completed batch | 0 | 0 | HTTP 200; four candidate URLs | Not recorded |

These are persisted counters, not a reconstructed unified ran/skipped/deadline_skipped schema. Document actions started for 47 companies; one completed action returned a failed document outcome despite scheduler `failed=0`. Shallow/activity had no eligible inputs; “100 skipped” would be a derived eligibility count, not a recorded scheduler count. Summed worker seconds overlap and cannot be substituted for phase wall time. Foundation/website/document/Wikidata wall durations are missing. The document cap was 900 wall seconds. Per-company document timings survive for 47 entries: processing sum 1,802.778 seconds and OCR sum 1,553.323 seconds; 53 entries lack timings. Batch runtime was 1,190.051 seconds, external orchestration elapsed 1,190.614 seconds and reported finalization 7.145 seconds.

NAV stopped at its 119.5-second internal deadline (119.512 elapsed), after 32 successful pages/32,000 items and 11 details; the next feed call was cancelled. It consumed 45 logical calls of a 512-call cap, below the 256-page limit. It left 6,554 entries unresolved. `feed_complete=false`, employer-index `complete=false`, `negative_coverage=false`. Zero published jobs is unknown/incomplete coverage, not a negative jobs assertion.

## Holdout traceback and missing collision objects

The private `holdout/stderr.log` preserves:

```text
signalpost/run.py:832 -> asyncio.run(enrich())
signalpost/run.py:826 -> envelope.__class__.model_validate(envelope.model_dump())
pydantic_core.ValidationError: claim identifiers must be unique within an envelope
input_ref: row:41
```

Organisation: `974396904`, CONSTRUCTOR NORGE AS. Exit 1 after 1,175.312 seconds. Its checkpoint retained 100 foundation shells at `baseline_done`; row 41's foundation has 107 claims and no duplicate IDs. All checkpoint synthesis contains only foundation observations. The pending output contains identifiers/execution states, not optional claims. No final envelopes or final state exist.

**The two colliding claim objects, duplicate identifier, values and provenance were never persisted and cannot be recovered.** Synthetic regression cases do not establish which live pair collided. Optional holdout coverage and phase timings are unknown, not zero. These gaps must remain explicit rather than filled using a later replay.

## Ordered implementation and measurement policy

Reliability lands before finance, OCR or discovery changes. Development validation uses synthetic/recorded fixtures, not repeated tuning on either 100-company benchmark. Final measurements freeze one implementation/configuration, run the original input hash once, then a fresh disjoint holdout not used for development, without edits between them. Any failed gates remain failures. Replay timings are not live runtime claims; an incomplete recording cannot support full offline coverage comparisons.

The new holdout was frozen at `2026-10-27T19:46:48.671564+00:00`, before finance/OCR/discovery changes, with seed `94bcdc2c7bd07214286ebe92c708be909d407fd8cbecf7b2f6248d6b8e030d18` and input SHA-256 `8ef2df33c4c275b18ac6c6f6ca754db0a8596755ba382bab4e6bb0f54eef44af`. It excludes both prior 100-company cohorts, uses the same archived AS-employer selection frame and includes no fixed six. No company outcomes from this new holdout have been consulted during implementation.

## Step 1 implementation

Content-derived claim identities use full SHA-256 over company, field/value, source/content, subject, period, scope, unit/currency and unit state. Equivalent product headings retain their established Unicode/whitespace equivalence; differing values, scopes, sources and periods remain distinct. Identical repeated website claims merge provenance; conflicting collisions still fail safely. Deterministic summary representatives no longer depend on opaque hash ordering.

Each completed optional company/subphase is now checkpointed with its typed context and validated envelope. Resume restores official account context and completed document/website stages, including acquired pages, rather than rebuilding from a foundation-only shell. NAV/Wikidata batch outcomes are durable too. Optional exceptions are isolated and retain official facts; deadline cancellations remain distinct. Reports add explicit optional phase counters and wall times. Checkpoint validation checks changed envelopes plus cached cross-company provenance signatures, avoiding revalidating every unchanged company's claims on every write.

These reliability changes alone do not establish live coverage improvement. The historical collision pair remains unknown. A process killed during an in-flight company can lose that unfinished action; completed, committed company/subphase results survive. Filesystem failure cannot guarantee persistence.

## Step 2: OCR-independent structured finance

`fetch_financial_statements()` now has its own checkpointed phase before optional OCR, with a fixed 180-second allowance and one reserved accounts request per pending company. Foundation acquisition reserves those requests/time instead of consuming them on optional registry work. Production foundation excludes accounts; the finance phase requests each company's endpoint once, retaining all returned years, actual reporting periods and separate company/group subjects. Resume reuses completed finance results.

Finite, identity/period/scope/version-valid metrics with absent unit metadata publish with `unit_assumed_currency=true` and a strictly validated `UNCALIBRATED` structured-API basis. They explicitly do not claim a documented API-wide unit contract or target-PDF validation. Explicit unit conflicts and invalid metadata are not overridden. Existing PDF agreements remain an optional diagnostic, never an acquisition/publication prerequisite.

Parent integration verification: **152 tests and 26 subtests passed**, including API-only publication, groups/years, strict assumption provenance, request reservations, optional fault injection and crash/resume. Reliability commit `747f6c4bcc56d01c7bb5f2d79741c097c2e75ce6` passed exact-SHA CI. These are offline correctness checks, not evidence of live coverage gains.

An initially incomplete finance mock in the focused reliability tests accidentally permitted calls to the official accounts endpoint. It was corrected before any benchmark, and the test suite now blocks public DNS/HTTP and isolates OCR caches. Those accidental adapter calls are not treated as coverage evidence or cohort measurements.
