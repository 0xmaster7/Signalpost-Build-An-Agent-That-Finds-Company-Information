# Final official document coverage recovery — 2026-10-17

## Result and measurement

The production evaluator launcher retrieved official BRREG JSON and annual-account PDFs and automatically published **25 new document-backed numeric facts across 7 of 8 companies**. No manually entered company facts, paid APIs, model credentials or Tesseract are used.

| Metric | Before, same 8 companies | Final live run |
| --- | ---: | ---: |
| Companies with numeric revenue | 0/8 | 6/8 |
| Companies with operating result | 0/8 | 6/8 |
| Companies with annual result | 0/8 | 6/8 |
| Companies with explicit workforce FTE | 0/8 | 7/8 |
| Document-backed numeric claims | 0 | 25 |
| Unsupported/incorrectly attributed claims found in source review | — | 0/25 |
| Terminal envelopes | 8/8 | 8/8 |

The before column is a **network-disabled replay of the exact previous release `3c204eecfabf0b5f16e83250b3aa3b682889954a` against captured live source responses**, not a second live benchmark. Six companies come from previous live work; two fresh holdouts were selected deterministically from the official universe before examining their outcomes. Selection receipt and exact cohort are included. The earlier historical 0/10 cohort has a different denominator; no claim is made that this is an official Builderr score or a representative population estimate.

## Examples and source evidence

All periods below are **2025-01-01 through 2025-12-31**, established by the actual filing cover. All financial values are standalone legal-entity amounts in **NOK**, established by `Beløp i: NOK`, the 2025 column and matching JSON amounts. Page numbers count PDF pages, including the cover.

- **FOLK OG FE AS, 987974249:** revenue **5,135,536**, operating result **−22,366**, annual result **−12,695**, page 2; **10.00 FTE**, page 5 (`Antall årsverk i regnskapsåret`). Journal **2026488063**. [Official PDF](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/987974249/2025). All four requested facts are automatically published. Final PDF SHA256 `165b8165127dcd61a98e924567d37a128bdf82fff1f05667b20e5db4e79afd3b`.
- **AURA, 918652493:** revenue **3,089,741**, operating result **335,294**, annual result **260,481**, page 2; **7 FTE**, page 5. [Official PDF](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/918652493/2025).
- **HOVDEN, 959312869:** revenue **12,356,957**, operating result **−390,854**, annual result **−301,747**, page 2; **10.40 FTE**, page 5. [Official PDF](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/959312869/2025).
- **BRØDRENE KOLSTAD AS, 974350033 (fresh holdout):** revenue **3,916**, operating result **−77,284**, annual result **3,093,445**, page 2; explicit **0 FTE**, page 5. Its parent-company cover explicitly says consolidated accounts are not attached. [Official PDF](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/974350033/2025).
- Explicit **0 FTE** is also published for **997356624** and fresh holdout **915716121**, both page 5. This is workforce FTE, not headcount or open-job coverage.

[Machine-readable evidence](evidence/document-recovery-20261017/live-summary.json) includes every published figure, original URL, page, quotation, hash, period, scope and units. [Document-only production claims](evidence/document-recovery-20261017/document-claims.jsonl) also preserve cover evidence, BRREG JSON pointer evidence, source snapshots and stable claim identities. Raw PDFs and personal role records are not committed.

## Withheld results and limits

- **TINE, 947942638:** PDF timeout followed by transport failure; no financial or FTE recovery claimed. The company still receives a terminal envelope.
- NBN FLORØ's two result figures did not pass strict OCR row/amount checks (operating result was read as `2 666305`; annual result contains a low-confidence colon-like OCR character); KRAABOEL INVEST's zero revenue glyph had OCR confidence 0.564, below 0.90. Those claims remain withheld while independently supported facts on the same page are published.
- Only the latest uniquely identified eligible standalone filing is attempted. Missing units, ambiguous years, uncertain OCR numbers, mismatched identity/journal/period, group pages and conflicting candidates are withheld. No financial scale is inferred from JSON currency alone.
- At most seven prioritized pages are inspected. Statements outside that bound, other layouts and large group reports may be missed. This sprint does not improve website, NAV or dated-activity coverage.

## Runtime, access and request accounting

Final live run: **178.425 seconds**, 8/8 envelopes, **43 physical HTTP attempts**, including failed robots requests and PDF fallback. Seven PDF downloads succeeded. Per-company document processing was approximately **28–52 seconds** for successful reports, including download and local OCR; TINE failure took about 20 seconds. Parent process peak RSS was 89,688 KiB; this is **not** aggregate OCR-worker memory.

Sprint cumulative physical company-research attempts: **93/100** = 7 development + 43 first acceptance + 43 final retest. Every physical send, including failures, was reserved by an external SQLite guard as well as counted by the gateway. Networking was sealed after the final run. Dependency downloads are installation traffic, not company-research requests. Offline regressions/replays use no live HTTP.

The source path is exact `GET https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{orgnr}/{year}`, with no query parameters or credentials. Gateway robots/disallow, SSRF, redirect binding, byte, time and physical-budget controls apply. Two local killable OCR subprocesses maximum; 90-second OCR cap; 25 MiB PDF cap; seven-page cap; BLAS/OMP thread count one; hash-keyed run cache. Requests are spaced 2.1 seconds during the document phase; that is a conservative implementation setting, **not an asserted provider rate-limit guarantee**.

Foundation results are checkpointed before document work. Deadline-aware scheduling and exception handling preserve one terminal envelope per input. Actual organizer CPU/RAM/deadline limits were not supplied, so large-cohort throughput within unknown limits remains unverified. No assertion is made that the default deadline can OCR every company in a 1,000-company batch.

## Implementation and verification

- Original `signalpost/annual_accounts.py`, production scheduling in `run.py`, raw filing metadata handoff in `brreg.py`, PDF page provenance in models/history, exact official-copy policy in `network.py`, source-policy/rights updates and locked PDFium/RapidOCR/Pillow dependencies. Existing JSON financial-unit checks remain enforced.
- Competitor commit `169cc6b35851cd0336fb9d70b5617253354f0473` had no repository licence. No competitor code was copied. Runtime dependency/model licence notices are recorded in `THIRD_PARTY_NOTICES.md`.
- Full regression run before the final two narrow OCR/scope adjustments: **492 tests + 237 subtests passed**. Final targeted annual-document/runner/refresh regression run: **71 tests + 5 subtests passed**. Exact-commit GitHub Actions is checked separately after push.
- Completely fresh `uv sync --frozen --extra m08-test` environment installed the lockfile and successfully OCRed the saved official FOLK OG FE PDF without Tesseract. No optional OCR import broke ordinary package imports.
- The exact `signalpost-starter-kit/run_signalpost.py` launcher was exercised from an unrelated working directory through the guarded production network path. Final captured-byte baseline/refresh replay retained all **25** document claims across **8/8** envelopes with **zero changes**. Actual HTTP was denied; the gateway counters in those replay logs count mock transport calls, not live requests. The uncaptured TINE PDF is explicitly an offline replay failure.
- Source review compared rendered official covers, year columns, unit headers, financial rows and FTE notes against all 25 published claims. Zero unsupported or wrongly attributed claims were found in this small reviewed sample; this is not independent population validation.

## Submission handoff

Preserve fallback `3c204eecfabf0b5f16e83250b3aa3b682889954a`. Submit only the final exact commit after its CI completes successfully. Repository visibility and Builderr submission are unchanged.

The owner still needs to supply the submission contact details, confirm organizer evaluator/resource/cutoff and any frozen-snapshot handoff requirements, provide authorized reviewer repository access (or explicitly approve publication), and submit the final SHA using the existing submission materials. No official score is claimed.
