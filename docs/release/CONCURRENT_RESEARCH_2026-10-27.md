# Concurrent research and calibrated units — 27 October 2026

This treatment follows the [preregistered experiment](PHASE_BUDGET_PREREGISTRATION_2026-10-27.md). New coverage claims are withheld until its matched and holdout runs finish.

## Execution

Registry identity/workplace foundation remains checkpointed before optional work. NAV and Wikidata then run concurrently, before OCR. Website verification/shallow extraction/activity phases run alongside a two-process killable OCR pool, instead of waiting behind its queue. Completed website stages survive a later phase timeout.

Default reserves: NAV 120 seconds, Wikidata 12, websites 480; OCR at most 900 seconds and 65% of remaining soft research time. Source wrappers never spend the atomic-publication reserve. NAV also leaves a retry-aware request allowance for websites and one PDF per company. All limits are validated `RunBudget` fields and can be configured in its existing mapping or corresponding `SIGNALPOST_*` variables. The experiment uses the same overall budget as the baseline, with the new defaults as the treatment.

## NAV window index

One batch scan follows the whole 40-day feed window, bounded by 256 pages, its reserved time and request allowance. Embedded employer orgnr is indexed directly; missing employer information requires detail calls. Available results are joined by exact legal/workplace employer orgnr. Name matches only prioritize detail acquisition, never establish employer identity. Aliases outside the name shortlist can still be resolved while the remaining budget permits.

**A complete feed traversal is not necessarily a complete employer index.** If feed summaries omit orgnr and the detail/time/request cap is hit, `feed_complete` can be true while `complete` is false. The audit records unresolved entries, truncation and reasons. No implementation can truthfully claim all employers indexed without fetching the missing bindings; it must not exhaust website/OCR reserves to hide this limitation. Strict ACTIVE, expiry, dates, token/contact privacy and company/workplace proof remain intact. No negative jobs assertion is made, even after a completed scan.

## FTE and monetary anchors

The worker verifies cover identity, journal and actual filing period, then examines FTE candidate pages **5, 4, 6, 3, 7, 2**. The first acceptable company statement ends FTE scanning; conflicting statements on that page cause abstention. This intentionally replaces all-examined-page consensus in the production path, without claiming unread pages agree. Existing direct `reconcile()` consensus remains available to legacy callers.

Page 2 is a separate bounded monetary-anchor pass; it does not restart note scanning. Audit fields report actual examined pages, FTE pages, financial anchor pages, stopping reason and incomplete coverage. Queueing, startup and OCR share one deadline. Run-scoped cache keys include PDF SHA, filing context and parser/selection strategy, so partial results cannot masquerade as complete or be reused for another filing.

## Explicit unit assumptions and groups

After document enrichment, two distinct nonzero PDF/API metric agreements establish a company-local full-currency assumption. They require matching company, exact filing journal/period, currency, standalone scope, source hashes and locators. Zero-only anchors, conflicts, unknown/contradictory explicit units and ambiguous filing versions cannot calibrate.

Other eligible API rows for that company/currency can publish with **`unit_assumed_currency: true`** and a structured `unit_assumption_basis`. It names anchor claims, source snapshots, reference filing, period/scope/filer equality flags and multiplier 1. `target_pdf_validated` and `documented_api_unit_contract` remain explicitly false. An assumption is not a documented API contract or validation of every projected metric/year.

Group accounts retain their own `scope=group`, source path, actual period and scope/version-sensitive subject IDs. A missing-unit group projection is explicitly a cross-scope assumption, not company accounts relabelled as group or a claim that its group PDF was checked. Existing supported explicit group units are preserved; conflicts are not overridden. The evaluator JSON and refresh artifact retain these flags and validate their anchor graph.

An older regression fixture labelled a record “valid EUR” while explicitly declaring unit NOK; it now declares EUR. A separate regression verifies that EUR/NOK conflicts remain withheld. This is a fixture correction for the dimensional gate, not a relaxation to pass tests.

Production dependencies and the two-command setup/run wrappers are unchanged. No paid service, API key, system OCR dependency or company-specific tuning was added.

## Pre-run verification

An isolated checkout passed **667 tests and 237 subtests** in 218.85 seconds. A subsequent narrow correction allows independent monetary anchors to calibrate when the only document conflict is FTE; its financial/tooling regression set passed **30 tests**, including the new case. One existing pyRdfa UTC deprecation warning remains. Remote exact-commit CI and the two live outcome reports are verified separately; these local checks alone do not establish coverage or accuracy gains.
