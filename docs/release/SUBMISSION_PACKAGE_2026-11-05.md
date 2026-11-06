# Submission package — updated 6 November 2026

**Acceptance FAILED; not submission-ready.** [Final report](FINAL_RESULTS_2026-11-06.md) and [sanitized receipts](evidence/final-676d6e5/) record live smoke, matched100, fresh100 and the failed live scale1000. Research stayed frozen at `676d6e513b70c0e3cbf8e884602ad7e5674d5df9`; later commits only repair validation or add docs/public exports. Exact package SHA is the commit containing this file (obtain with `git rev-parse HEAD`); never substitute an older green SHA. Contact **[CONTACT_NAME / CONTACT_EMAIL]**, JBOX **[JBOX_SITE_URL]** remain owner fields. Deadline: **7 November2026 18:00IST (12:30UTC)**; no organizer extension inferred.

Agent: **Signalpost**. Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information. Email remains an [unsent draft](../../SUBMISSION_EMAIL_DRAFT.md). No submission or email occurred. The public repository remains public with main as default; sanitized public exports are included.

## C1: install, run and budget contract

The existing root wrappers are the primary entry points:

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

`setup.sh` selects CPython 3.12+ (3.12 recommended), downloads project-local uv **0.8.0** with a platform-specific pinned SHA-256, and runs `uv --no-config sync --frozen --no-dev`. It installs no optional crawler/sentiment extra, uses no sudo, does not install Python or change shell profiles, and checks PDF/OCR imports and initialization. Supported bootstrap targets are Linux glibc and macOS on x86_64/arm64. `curl` and outbound HTTPS are installation prerequisites. `SIGNALPOST_PYTHON` selects an interpreter. Tools/cache/environment stay in the checkout.

`run.sh` validates the setup stamp against `pyproject.toml` and `uv.lock` and performs no installation. Without an explicit registry snapshot it supplies `--live-brreg --live-websites`. With `--registry-snapshot`, the caller must explicitly request any live paths. Relative input/output paths resolve from the caller's directory. Profiles go to `output.jsonl`; stdout carries a distinct JSON batch report and stderr diagnostics. JSONL, JSON, CSV, TSV and plain-number inputs are supported by the repository launcher. IDs remain strings, and ordered duplicate/invalid rows require terminal outputs. A malformed file is an input failure, not a completed batch.

The current working tree implements `--budget-seconds` as a **total run budget**, overriding `SIGNALPOST_BUDGET_SECONDS`, which overrides config. The default total is **1,800 seconds**. An explicit total sets the completion reserve to `min(300 seconds, 20% of total)` and the soft deadline to total minus that reserve. With no explicit total, the configured defaults remain 1,800 hard / 1,350 soft / 300 completion-reserve seconds. These are project settings, not published organizer limits. Non-finite or non-positive explicit totals are rejected. The live1000 run exceeded this budget and did not finalize: this setting is not a reliable hard-wall guarantee. This interface is absent from baseline `725eb63`.

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

Keep credentials server-side, out of logs and public outputs. Treat HTTP/PDF recordings, OCR caches, complete private envelopes, NAV tokens and SQLite checkpoints as **private captures**, never public fixtures. Release only sanitized metadata/short rights-permitted evidence after inspection. Hashing a raw response does not make the response publishable. A deterministic site exporter and human-profile renderer are implemented and have focused tests; the final100-company public export was generated, reference/hash checked and scanned for common secret patterns. Whole-file privacy/legal certification is not implied; see site-data/README.md.

## Costs and measured coverage

No paid API or LLM is required. Public-source/local-inference API billing is assumed **$0**, not measured billing. VM/OCR CPU, RAM, disk, installation, network and hosting costs are not priced. The failed35-minute scale attempt is not evidence of successful official-batch cost.

Matched/fresh finalized100/100 each and replayed exactly. Finance98/93, FTE18/19, verified websites0/1, jobs3/2, runtime1595.038/1584.378 seconds. Scale preserved1000 partial rows but was terminated at2100.355 seconds with no final state pair, aggregate or full counters. No coverage was measured on scale. FTE/web/fresh-finance/20-minute/scale-completion gates failed. Matched FTE regressed23→18; no improvement claimed. Full disjoint phase/timing receipts and baseline comparison are in the [final report](FINAL_RESULTS_2026-11-06.md).

## Evidence and remaining gates

- Implemented and unit-tested breadth ordering, explicit budget precedence, persistent phase statuses, partial flush, finance independence, strict identity and deterministic supported summaries. **Live scale shows finalization/breadth incompleteness despite these mechanisms.**
- Frozen-source local suite:1089 tests/252 subtests. Later CI surfaced validation-only fixture/harness assumptions; exact package CI must be checked independently.
- Clean implementation-commit installation passed first/repeated setup, pinned versions, actual OCR/noTesseract and run-without-installation. Exact package fresh-clone verification is separately recorded when completed; no historical test is substituted.
- Smoke10, matched100, fresh100 and their byte-identical offline replays passed execution/replay gates; quality gates did not all pass.
- Scale1000 live attempt completed measurement with **failed** gates. No retry, replay or tuning against fresh/scale occurred.
- Public site-data has100fullfiles/index and1,922,922-byte compactbundle. Full files are required for summaries/evidence: bundle omits15164facts/all100summaries. Rich profile survives privacy filtering inonly8files.
- Official parser, organizer numeric limits, independent all-field precision, full transitive license audit and JBOX deployment remain unproven.
- Owner contact/recipient/JBOX fields remain unset. [Email](../../SUBMISSION_EMAIL_DRAFT.md) is unsent; **do not submit this failed candidate as accepted**. Further remediation needs a separately authorized cycle.
