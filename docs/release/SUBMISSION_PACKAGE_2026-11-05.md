# Submission package — 5 November 2026

Preparation from baseline `725eb6375feb0529da4cbe4f73bff05bd6e693f2`. Final package commit: **[FINAL_COMMIT_SHA]**. Final report: **[FINAL_REPORT_URL_OR_PATH]**. Authorized contact: **[CONTACT_NAME / CONTACT_EMAIL]**. JBOX site: **[JBOX_SITE_URL]**. Task deadline: **7 November 2026, 18:00 IST (12:30 UTC)**. The vendored competition brief has older October dates; this task deadline is not independent confirmation of an organizer extension.

Agent: **Signalpost**. Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information. Email remains an [unsent draft](../../SUBMISSION_EMAIL_DRAFT.md). No submission, publication or access change is recorded by this package.

## C1: install, run and budget contract

The existing root wrappers are the primary entry points:

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

`setup.sh` selects CPython 3.12+ (3.12 recommended), downloads project-local uv **0.8.0** with a platform-specific pinned SHA-256, and runs `uv --no-config sync --frozen --no-dev`. It installs no optional crawler/sentiment extra, uses no sudo, does not install Python or change shell profiles, and checks PDF/OCR imports and initialization. Supported bootstrap targets are Linux glibc and macOS on x86_64/arm64. `curl` and outbound HTTPS are installation prerequisites. `SIGNALPOST_PYTHON` selects an interpreter. Tools/cache/environment stay in the checkout.

`run.sh` validates the setup stamp against `pyproject.toml` and `uv.lock` and performs no installation. Without an explicit registry snapshot it supplies `--live-brreg --live-websites`. With `--registry-snapshot`, the caller must explicitly request any live paths. Relative input/output paths resolve from the caller's directory. Profiles go to `output.jsonl`; stdout carries a distinct JSON batch report and stderr diagnostics. JSONL, JSON, CSV, TSV and plain-number inputs are supported by the repository launcher. IDs remain strings, and ordered duplicate/invalid rows require terminal outputs. A malformed file is an input failure, not a completed batch.

The current working tree implements `--budget-seconds` as a **total run budget**, overriding `SIGNALPOST_BUDGET_SECONDS`, which overrides config. The default total is **1,800 seconds**. An explicit total sets the completion reserve to `min(300 seconds, 20% of total)` and the soft deadline to total minus that reserve. With no explicit total, the configured defaults remain 1,800 hard / 1,350 soft / 300 completion-reserve seconds. These are project settings, not published organizer limits. Non-finite or non-positive explicit totals are rejected. Runtime/deadline behavior and final-source acceptance still require recorded verification; this interface is not present on baseline `725eb63`.

Current foundation order is implemented as identity-only official breadth, followed by structured financial acquisition for eligible companies, then optional official details, external discovery and OCR. This is an execution-order statement, not a guarantee of live completion or coverage.

Retain the output/state pair and adjacent publication marker for refresh; use separate paths plus `--previous-state` for new observations and the original command plus `--resume` for an interruption. See the [existing run guide](../../submission/README.md) for advanced inputs. These operations may acquire live data; no such acquisition was performed by this documentation task.

## Dependencies, models and licenses

Inspected files: [pyproject.toml](../../signalpost-starter-kit/pyproject.toml), [uv.lock](../../signalpost-starter-kit/uv.lock), [notices](../../THIRD_PARTY_NOTICES.md), [historical inventory](../data-licenses.md), [source rights](../source-rights.md), [source policy](../../config/source_policy.yaml), [setup](../../setup.sh), [launcher](../../run.sh) and the local OCR implementation. Baseline lock SHA-256: `dda32ec8bc0fa9684f06f6c80b0b4211f0245b193563e3674dd38308df318a46`. Parent must recheck this if dependencies change.

The versions below are read from the actual lock. The production virtual environment's RapidOCR assets were previously inspected; license statements below reflect repository/upstream notices and are **not a blanket legal audit**.

| Direct production dependency | Locked version | Existing license declaration |
| --- | --- | --- |
| beautifulsoup4 | 4.15.0 | MIT |
| extruct | 0.18.0 | BSD License classifier; no more specific identifier asserted here |
| fastapi | 0.142.2 | MIT |
| lxml | 6.1.2 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| pypdf | 6.19.0 | BSD-3-Clause |
| pypdfium2 | 4.30.0 | Apache-2.0 OR BSD-3-Clause, plus `LicenseRef-PdfiumThirdParty`; retain upstream PDFium component notices |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0; existing notices include bundled PP-OCR assets |
| pillow | 12.3.0 | MIT-CMU |
| tldextract | 5.3.2 | BSD-3-Clause |
| trafilatura | 2.2.0 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |

OCR-related transitive pins are **onnxruntime 1.31.0** (existing MIT declaration), **opencv-python 5.0.0.93** (Apache-2.0), **numpy 2.5.2** (BSD plus bundled component notices), **shapely 2.2.0** (BSD-3-Clause) and **pyclipper 1.4.0** (MIT). Setup's downloaded uv 0.8.0 is declared MIT OR Apache-2.0. These abbreviated labels do not replace the upstream license and notice files or constitute a complete transitive inventory.

**LLMs: none required. OCR models: local RapidOCR bundled defaults.** The production virtual environment was previously inspected: RapidOCR `1.4.4` (Apache-2.0) bundles `ch_PP-OCRv4_det_infer.onnx` SHA-256 `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9`, `ch_PP-OCRv4_rec_infer.onnx` SHA-256 `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b`, and `ch_ppocr_mobile_v2.0_cls_infer.onnx` SHA-256 `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c`. `annual_accounts.py` constructs `RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)` and calls it with `use_cls=False`, so the classifier asset is bundled but disabled. Existing notices identify PP-OCR assets as Apache-2.0. pypdfium2 metadata declares `Apache-2.0 OR BSD-3-Clause` and `LicenseRef-PdfiumThirdParty`; retain upstream notices. These findings do not replace a complete component-by-component license audit or the clean-machine setup check.

The historical inventory's lock hash (`8d9382ca…`) differs from the inspected lock and omits the OCR rows above. It remains historical evidence, not a complete current installed inventory. Regenerate/review a production inventory and retain installed third-party license/component notices before redistributing a built bundle. Optional `crawler` and `sentiment` dependencies in the lock are not enabled by the primary setup. No competitor source was incorporated by this documentation task. The repository declares **no project-code license**; these documents create no grant or new legal terms.

## APIs, source rights and security

- **BRREG:** exact-entity, roles, subunits, group records, accounts and official annual-account copy paths on `data.brreg.no`. The structured registry policy declares NLOD 2.0 and requires Brønnøysundregistrene attribution and retrieval date. Official PDF factual extraction does not establish a blanket right to republish filings. Retain source URL/hash, locator/page, short permitted evidence, period and scope.
- **NAV:** `pam-stilling-feed.nav.no` public-token/feed/detail API, governed by [NAV data-use terms](https://arbeidsplassen.nav.no/vilkar-api). Metadata analysis and current-ad/update/removal obligations are recorded in the rights register. Vacancy data is **not MIT-licensed**. The runtime public token needs protection; no personal API key is required. The scan is partial and cannot prove absence of jobs.
- **Wikidata:** exact `https://query.wikidata.org/sparql` candidate discovery, with structured-data CC0 and Wikimedia API/User-Agent rules. P2333/P856 results are candidates, not accepted ownership proof. The older report rejecting the experimental adapter is historical; the later bounded adapter is present. HTTP refusal remains blocked; no challenge bypass is authorized.
- **Company sites:** bounded public factual extraction with exact-company identity checks, source-specific terms and ordinary website robots checks. Terms are not globally adjudicated. Explicit rights blocks take precedence; robots permission alone does not license content. No social-platform scraper, paid search/news API, external ATS connector or browser-rendering service is enabled.
- **Organizer snapshot:** source URL, as-of date, license and retention terms must be supplied. BRREG licensing does not automatically license an independently supplied frozen dataset.

The gateway applies DNS/public-IP SSRF checks, redirect destination revalidation, source host/path restrictions, response bounds, pacing and request accounting. Ordinary website robots errors fail closed; explicit disallows are binding. The narrowly documented structured-API outage/access profiles must not be extended to ordinary sites. These are implemented controls, not proof of a complete deployment security audit.

Keep credentials server-side, out of logs and public outputs. Treat HTTP/PDF recordings, OCR caches, complete private envelopes, NAV tokens and SQLite checkpoints as **private captures**, never public fixtures. Release only sanitized metadata/short rights-permitted evidence after inspection. Hashing a raw response does not make the response publishable. A deterministic site exporter and human-profile renderer are implemented and have focused tests; the final export has not yet been generated or reviewed for release.

## Costs and coverage disclosure

**No paid API or LLM is required.** API billing is assumed to be **$0** for 100, 1,000 or 1,100 inputs under the configured public sources and local inference, provided those services remain available without charges. This is a configuration-based assumption, **not measured billing**. CPU/OCR, RAM, disk, installation downloads, network traffic and hosting consume resources and may cost money; no final-source per-batch resource or infrastructure-cost measurement was made here. No full-scale live completion time is inferred from a configured deadline.

Supplied artifacts for baseline `725eb6375feb0529da4cbe4f73bff05bd6e693f2` report a matched 100-input run with 98 finance-covered, 23 FTE-covered, zero verified websites, 3 jobs, and runtime 1,128.650 seconds. A previous 100-input holdout reports finance 99, FTE 29, websites 0, jobs 3, runtime 1,134.574 seconds. A 10-input smoke reports finance 10, FTE 8, websites 0, jobs 0, runtime 401.748 seconds. Artifacts reside privately at `/home/azureuser/projects/signalpost-crashsafe-acceptance-725eb63` on pancakes; sanitized local summary: `/tmp/signalpost-acceptance-public-725eb63/RESULTS.md`. The matched run reported full envelopes, no duplicates and exact replay. These claims cite supplied artifact provenance and were not independently rerun here; no new public report or improvement measurement exists. The repository's [27 October matched treatment](PHASE_BUDGET_RESULTS_2026-10-27.md) is a separate historical run. The [28 October runs](RELIABILITY_FINANCE_RESULTS_2026-10-28.md) aborted without final output; optional coverage is unknown. Clean-machine setup, final CI, fresh 100/1,000 checks and final export review remain pending. See [LIMITATIONS.md](../../LIMITATIONS.md).

## C4: honest handoff checklist

This package update records supplied benchmark artifacts and prior installed-environment inspection, but performed no live calls, tests, clean-machine setup or new measurements. Unchecked items are required evidence or owner details, **not passes**.

- [x] Inspect existing setup/run entry points, direct dependency constraints and locked versions without changing dependencies or source.
- [x] Inspect existing license/source-rights declarations; disclose stale inventory and limits of the available installed-model/license evidence.
- [x] Prepare limitations and an unsent email with Signalpost, the correct repository and explicit placeholders.
- [x] Implement `--budget-seconds` / `SIGNALPOST_BUDGET_SECONDS` total-budget precedence, invalid-total rejection, 1,800-second default and final reserve calculation inside the total; runtime acceptance remains pending.
- [ ] Freeze final source/commit and record exact CI/test results. Tests from older SHAs do not satisfy this item.
- [ ] From a clean machine/checkout without warm tools, dependency caches, credentials or research captures, run `./setup.sh` and rerun setup for idempotence; record OS/CPU/RAM/Python, lock hash, commands, elapsed time and exit codes. Verify `run.sh` performs no installation and missing/stale setup fails clearly.
- [x] Record previously inspected RapidOCR weight names/hashes and license notices and pypdfium2/PDFium metadata; retain upstream notices and complete clean-machine dependency inventory review.
- [ ] Record a fresh authorized final-source 100-company smoke result, exact cohort/hash/config/cutoff, wall time, requests, terminal cardinality/order, failures and field-company coverage. Preserve unsuccessful attempts; do not substitute historical results or unknowns with zeros.
- [ ] Run the agreed **1,000-company scale check**; record whether synthetic/offline/replay/live, exact input/config, CPU/RAM/disk/network, elapsed time and output/publication integrity. A synthetic or duplicate-expanded scale run does not establish 1,000-company live coverage. No such result exists in this pass.
- [ ] Validate duplicate/invalid inputs, source errors, budget exhaustion, reserve/finalization, checkpoint/resume, refresh, growing-batch behavior and evaluator/parser compatibility using the final implementation.
- [ ] Validate any final-source replay claim against successful complete capture and fresh serialization; partial historical captures do not establish byte-identical full replay.
- [ ] Generate and review the final exporter output and report; inspect public artifacts for tokens, credentials, personal contacts, raw bodies, PDFs, caches and private checkpoints.
- [x] Record supplied artifact provenance for matched baseline, prior holdout and smoke in this package; [ ] publish a new sanitized report and report any measured before/after coverage without claiming accuracy or an official score.
- [ ] Fill final commit/report/contact/JBOX placeholders, verify repository/reviewer access and intended recipient, and reconcile the task deadline with any organizer instructions.
- [ ] Owner review the email. **Sending/submitting is outside this implementation task.**
