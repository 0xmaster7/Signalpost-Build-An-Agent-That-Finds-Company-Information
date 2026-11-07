# Signalpost limitations — updated 7 November 2026

**Latest operational output gate PASSED:** [measured report](docs/release/OUTPUT_FIRST_RESULTS_2026-11-07.md), runtime `f0902cb0cbb1a4cd5e9ac1d471f0c8459545ed73`, exact-runtime CI green. Live 200/1000 returned 200/1000 valid primary envelopes, exit 0 in 332.033/1659.034s, zero duplicate IDs. Counts: finance196/983, explicit FTE1/8, verified websites0/0, jobs1/1. These are counts, not coverage/precision claims. **Both state pairs, checkpoint terminalization and sealed replay remain incomplete.** This is safe only under the latest primary-output operational definition; original coverage and replay gates do not thereby pass. The 1000 capture contains one incomplete website attempt. A blocked pre-ack fsync or different resources can still overrun; no universal deadline guarantee exists. Finance retries are disabled, so Retry-After retry behavior is not established for that phase. The 200 breadth target <=0.5s/input passed; it is not certified at 1000. Preparation and historical notes below are superseded by this measured status.

Strict recording/replay and frozen-fixture workflows keep paired-state behavior unless `--output-first` is supplied explicitly; ordinary live CLI research uses output-first by default.

**Current output-first candidate: acceptance PENDING.** The production CLI defaults to `--output-first` for non-replay runs. Complete, validated, ordered JSONL is committed before secondary canonical state/pair and recording finalization. Exit code **0 means valid complete output, not research success**, complete research, coverage, accuracy or successful secondary finalization. `state_incomplete: true` means state/recording may remain unfinished; it must not be presented as a committed state pair or replay-ready capture. Unknown, blocked and incomplete research stays explicit rather than becoming zero.

Total budget defaults to **1.8 seconds/input**, including finalization. `--budget-seconds` overrides `SIGNALPOST_TIME_BUDGET_SECONDS`, then legacy `SIGNALPOST_BUDGET_SECONDS`, then configured total. The output-first reserve is **max(2 × (measured per-row preparation time × N + measured full-output flush time), 10% of budget)**. It is an estimate, not an I/O guarantee. The watchdog **never sends TERM/KILL before complete-output acknowledgement**. A blocked pre-acknowledgement `fsync` can therefore overrun the budget; no universal hard deadline is guaranteed.

BRREG entity preloading uses **100-entity chunks** and existing single-entity fallback; finance uses **eight workers**, subject to configured HTTP concurrency. These scheduling changes do not change identity, ownership or extraction rules and establish no live coverage improvement.

New live acceptance is pending: **200 inputs / 360 seconds**, then **1,000 / 1,800 seconds only if the 200-input output gate passes**. The parent will supply live results and the exact implementation-commit report. Historical candidates below remain failed; the new output contract does not retroactively pass them.

**Historical 7 November gate FAILED:** [200-company independent-watchdog result](docs/release/HARD_DEADLINE_RESULTS_2026-11-07.md). Green CI on `3e8a8a0` does not supersede live failure: emergency SIGKILL at354.431seconds, no committed state pair or aggregate. All200checkpoint shells terminalized and IDs were unique; publication still did not finish. New1,000-company acceptance and full replay were not run. Startup/final-flush watchdog gaps, synchronous DNS and transport-thread lifetime remain limitations. No universal completion guarantee or replacement safety is claimed.

**Historical 7 November measured follow-up FAILED:** [bounded-run evidence](docs/release/TIMEBOX_RESULTS_2026-11-07.md). The single live 1,000-company run required external termination at 1,830.864 seconds. Only 728 checkpoint shells terminalized; the final state pair, aggregate and complete finalization counters are missing. Preserved output counts: finance935, FTE0, websites0, jobs0; optional zeros do not prove absence. No scale replay or second live run occurred. This is **not safe to submit as a replacement**; 15% reserve and synthetic SIGTERM tests do not establish real-scale finalization or a universal 30-second recovery bound.

**Historical 7 November time-boxed remediation:** the earlier 15% reserve/85% cutoff and synthetic recovery tests did not establish real-scale completion or a universal 30-second recovery bound. That scheduling description is superseded by output-first publication above. Website/FTE coverage remains low; no measured improvement is claimed.

**Historical 6 November acceptance FAILED; not submission-ready.** The [final live report](docs/release/FINAL_RESULTS_2026-11-06.md) and sanitized receipts supersede preparation-only statements and historical baseline results.

## Historical 6 November measured coverage and scale

Research implementation `676d6e513b70c0e3cbf8e884602ad7e5674d5df9` remained unchanged across all final cohorts. Matched/fresh each finalized 100/100 envelopes with zero duplicate IDs and exact offline output/state replay. Finance companies were 98/93, explicit FTE 18/19, verified websites 0/1, jobs 3/2; runtime 1595.038/1584.378 seconds. These are company coverage counts, not independently scored recall or precision.

The live 1000-company run **timed out at 2100.355 seconds**, beyond its configured 1800-second total. It preserved 1000 partial rows, but no final state pair, aggregate or terminalized checkpoint shells. Annual-document counters are missing for 153 companies and finalization counters for all 1000. Financial acquisition deadline-skipped 442 companies. No scale coverage analysis, replay, tuning or retry was performed. The exact blocked instruction is unknown because no sampled stack survived. A complete-shaped partial row is not a successfully finalized/scored envelope.

The CLI total-budget controls and early atomic flush exist, but **hard-wall finalization is not reliable at measured live scale**. Do not promise scored completion at 1000–1100 inputs. Official numeric resources and parser compatibility remain unverified. Matched FTE regressed from 23 to 18 and runtime rose from 1128.650 seconds; no live improvement is claimed. Both cohorts miss FTE>=50, websites>=20 and the 20-minute target; fresh also misses finance>=95.

## Acquisition and precision

- Finance uses structured accounts JSON independently of OCR, preserving period and company/group scope. Missing-unit currency assumptions stay explicitly flagged; they are not an official denomination guarantee. Fresh gaps were six API404s and one HTTP500.
- OCR/text-layer tests do not prove higher live throughput. Matched persisted zero usable text-layer pages, 50 OCR pages and 69 deadline-skipped documents. Sampled PDFs were scans, not proof all filings are scans. Abstain on group/conflicting/ambiguous FTE. Employee headcount is not FTE.
- Verified sites require strict ownership. Registry-declared URLs, name-derived candidates and shared sites are not verified ownership. DNS failures and identity rejection dominate matched attempts. The sole fresh positive was manually checked against cached BRREG and exact JSON-LD identity: zero wrong-site positives observed out of one reviewed, **not an all-field accuracy audit**.
- NAV feed traversal can finish while details remain unresolved. No found posting never means zero vacancies. Current sources cannot reconstruct arbitrary historical cutoffs.
- Robots/rights restrictions, outages, PDF formats, rendering needs and budget exhaustion limit coverage. Missing/blocked/ambiguous/failed must remain distinct and never become zero.

## Installation, costs, models and rights

Run `./setup.sh`, then `./run.sh --input companies.jsonl --output output.jsonl`. CPython3.12+, curl and outbound HTTPS are prerequisites. The implementation-commit clean clone passed first/repeated setup, locked modules, real local OCR without Tesseract, unrelated-CWD execution and no installation during run. Exact package-commit checks are tracked separately, never implied by older receipts.

No required LLM, paid API, personal API key, Docker or sudo. Local RapidOCR inference is a model dependency, not “no models.” API billing is assumed $0 under public-source terms, not a measured bill; CPU, RAM, disk, network and hosting are not priced. The failed 35-minute scale attempt does not establish a successful batch cost.

See the [package](docs/release/SUBMISSION_PACKAGE_2026-11-05.md), [source rights](docs/source-rights.md) and [third-party notices](THIRD_PARTY_NOTICES.md). PDFium component notices and OCR model notices must remain. BRREG/NLOD2, NAV-specific terms, WikidataCC0 and company-site rights differ; robots permission is not redistribution permission. No project-code license is declared and this document grants none.

Keep HTTP/PDF captures, tokens, caches, private evaluator envelopes and SQLite outside Git. URL/DNS/redirect protections reduce SSRF risk but are not a deployment security audit. Public site exports were reference/hash/secret-pattern checked, not blanket privacy/license certified.

## Site and handoff limitations

The 100-company compact bundle is 1,922,922 bytes but contains only three facts/company: it omits 15,164 facts and all summaries. Upload the whole `site-data/` directory to JBOX for full profiles/sources/compare. Full files retain supported canonical summaries; richer `summary.profile` survives privacy redaction in only eight files. No deployed JBOX URL or new fallback site is claimed.

Historical acceptance remains failed; current output-first live acceptance is pending and is not a submission-ready claim. The parent must record the new gated measurements and exact commit before drawing a replacement-safety conclusion. No email/submission occurred; the email remains a draft and **NOSEND** applies. Owner contact, recipient, JBOX URL and qualification decision remain owner tasks. Deadline: **7 November2026, 18:00 IST (12:30 UTC)**; no organizer extension is inferred.
