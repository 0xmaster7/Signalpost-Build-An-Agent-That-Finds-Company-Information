# Final capability integration — 2026-10-17

## Measured result

Six previously unseen Norwegian AS employers were selected before observing source outcomes: ROMERIKE BARNEHAGE - SOLHAUG AS (930827088), LAUVVERKET AS (920710514), PAUL AS (952780093), RISINGVEIEN MAT AS (993955299), KVISTE MASKIN AS (992936916), TRAFIKKDRIFT AS (924356715). Selection used a saved official universe, excluded previously reported organization numbers, required at least five registered employees, and took the six smallest seeded SHA256 values. This is a small employer cohort, not a representative population sample.

Both columns below use actual production live source retrieval on the same six companies. Before is exact fallback release `8076e1b627cf1bdac00f9a241fdf6c6bf1831af8`. Final claims were extracted during the final live execution, retained in terminal checkpoints, and published through the production `--resume` path after a serialization whitelist repair. Resume used zero physical HTTP requests. No saved-source replay or synthetic test is counted as live recall.

| Company-level category | Before live | Final live |
| --- | ---: | ---: |
| At least one numeric financial figure | 6/6 | 6/6 |
| Workforce FTE | 4/6 | 4/6 |
| Any registered business/workplace location | 6/6 | 6/6 |
| Exact-parent registered workplace location | 0/6 | **6/6** |
| Verified website | 0/6 | 0/6 |
| Public profile | 0/6 | 0/6 |
| Jobs | 0/6 | 0/6 |
| Dated activity | 0/6 | 0/6 |

**Financial claims: 14 → 71, a gain of 57; all six companies gained additional financial facts.** Seventeen distinct financial metrics were actually published in this live cohort. Revenue remains 3/6, operating result 5/6 and annual result 6/6. New coverage includes assets 5/6, current assets 6/6, receivables 6/6, pre-tax result 6/6, net financial items 6/6, fixed assets 5/6, financial costs 5/6, payroll 4/6, financial income 4/6, operating costs 3/6, tax expense 2/6, paid-in equity 2/6, total comprehensive result 2/6 and sales revenue 1/6.

**Registered workplace facts: 0 → 37**, including six workplace-location claims and one workplace postal-address claim. The remaining 30 are linked workplace organization numbers, parent organization numbers, names, industry codes and employee figures. These are registered facts, not independently observed operational offices. Total newly published financial/workplace claims: **94 = 57 + 37**. The seven address claims are a subset of the 37, not an additional count. Existing business/postal address country fields were enriched but are not counted as new claims. No additional FTE, verified-website, profile, job or activity claims were recovered. No wrong-company findings were found in the reviewed results; this small sample does not establish population precision.

The older eight-company document benchmark and historical 0/10 external benchmark have different cohorts. Their denominators are not substituted here. Broad registered-address coverage was already present; the earlier broad “0 locations” description was inaccurate. The genuine new location gain is the exact-parent workplace category.

## Implemented

1. **P0: 23 supported financial mappings**, independently implemented from the official JSON contract and observed statement labels. The existing single PDF fetch now supports income statements and balance sheets; no per-metric downloads. Every published financial row still requires exact legal-entity identity, filing/journal and actual reporting period, standalone scope, explicit document currency/scale, the correct year column, sufficiently confident OCR and equality with the JSON metric. Conflicts and ambiguous values are withheld independently. Query filters recognize the expanded fields and retain required financial dimensions.
2. **P1: default-live workplace cutoff repair.** Previously the exact-parent subunit rows were retrieved and validated but their undated claims were excluded because retrieval followed the default run-start cutoff. In default live mode they now publish as current registry observations, with their real retrieval evidence and no invented historical date. Explicit evaluator historical cutoffs retain strict exclusion of later observations. Parent/child checksums, parent equality, duplicate conflict checks and ENK address protections remain enforced. Registered-location labels and query aliases distinguish these records from operational-office assertions. Registered address projections preserve country fields; direct registry location fields are supported when supplied.
3. **P2: bounded discovery.** Added non-consumer registry email domains and homepages/email domains from exact-parent validated workplaces, preserving source pointers/hashes as candidate evidence. Mailboxes are not published. Added a second distinctive-name domain variant within a six-candidate cap and existing shared crawl budgets. Repaired role corroboration to use source-backed person names rather than role descriptions or organization-role holders. Email/workplace candidates receive conservative contact/identity checks, not registry-declared website ownership. Existing wrong-company, group-domain, robots, SSRF and rights gates remain.

No runtime dependencies, paid APIs, model credentials or source hosts were added. The public reference at `169cc6b35851cd0336fb9d70b5617253354f0473` has no repository licence; no source code was copied. Financial paths and techniques were implemented independently. The existing PDFium/RapidOCR production dependency lock is unchanged.

## Deliberately omitted and limits

- **NAV:** not integrated. Its published smoke artifact records 85 feed pages and zero confirmed companies in the 100-company sample. Broad feed scanning is not justified by this sprint's 100-attempt budget. Current token/access terms and feed availability were not independently re-requested; no reproducible live benefit is claimed.
- **Profiles/activity:** existing exact-verified-site profile and genuinely dated activity extraction remains. No additional public-source integration or general crawler was added. The final run had little website budget after the restarted financial/workplace acceptance; the 0/6 external results do not prove a discovery coverage gain. New candidate generation is tested, but broader external recall remains unverified.
- The parser supports 23 metric types; not every type was recovered live. Equity, total/short/long debt, retained earnings and cash were not published in this cohort, including continuation-page and wrapped-row cases that did not satisfy the current strict header/label gates. Missing or OCR-ambiguous values are not guessed. The existing bounded seven-page/90-second OCR policy remains.
- Workforce stayed 4/6, including one explicit zero. No headcount is relabelled as FTE. The two missing FTE results remain unavailable.
- No claim is made that this surpasses the competitor's population coverage, official Builderr score or unknown organizer runtime/resource limits.

## Representative live evidence

All financial examples are standalone **NOK**, period **2025-01-01 through 2025-12-31**, as established by the filing cover, explicit `Beløp i: NOK`, the 2025 column and matching official JSON. PDF page numbering includes the cover.

- **KVISTE MASKIN AS, 992936916:** assets **7,722,629**, fixed assets **5,736,159**, current assets **1,986,470**, receivables **538,564**, paid-in equity **100,000** on PDF page 3; payroll **4,428,169**, net financial items **−351,199**, pre-tax result **−2,639,292** on page 2. [Official filing](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/992936916/2025).
- **RISINGVEIEN MAT AS, 993955299:** sales revenue **125,934,156**, operating costs **125,954,963**, payroll **9,519,054**, page 2; assets **21,587,936**, current assets **18,962,670**, paid-in equity **3,101,400**, page 3. [Official filing](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/993955299/2025).
- **LAUVVERKET AS, 920710514:** operating costs **3,866,395**, payroll **1,409,541**, pre-tax result **42,113**, page 2; current assets **10,874,361**, receivables **2,437,842**, page 3. [Official filing](https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/920710514/2025).
- **ROMERIKE BARNEHAGE - SOLHAUG AS, 930827088:** workplace **979586701**, registered location **Brånåsveien 10, 2019 SKEDSMOKORSET**, parent explicitly **930827088**. [Official exact-parent collection](https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet=930827088&size=1000).
- **TRAFIKKDRIFT AS, 924356715:** workplace **924412402**, registered location **Liaveien 22, 1614 FREDRIKSTAD**; separately registered postal address **Gluppeåsen 12, 1614 FREDRIKSTAD**. [Official exact-parent collection](https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet=924356715&size=1000).

[Published claims and complete provenance](evidence/capability-integration-20261017/published-claims.jsonl) retain original PDF/JSON URLs, document hashes, page numbers, row/unit/year quotations, exact JSON pointers, scope and periods. [Summary](evidence/capability-integration-20261017/summary.json), selection, physical-request ledger and verification receipts accompany the output. No full PDFs, mailbox values or personal role records are committed. All 71 published financial values were compared against rendered statement rows; all six covers were reviewed. Original-baseline and final-retrieval statement renderings are checked for equality to bind that review to final live documents.

## Runtime, budget and publication recovery

- Before: **183.226 seconds**, **34 physical attempts**, six terminal outputs.
- Final live acquisition/extraction: **197.547 seconds**, **34 physical attempts**. After the narrow serialization repair, checkpoint publication via exact evaluator `--resume` took **1.601 seconds**, **zero HTTP attempts**, and emitted all **6/6** terminal outputs. Combined final processing/publication time: **199.148 seconds**. Repair/development wall time is not hidden inside that processing figure.
- Successful final document tasks took **47.5–71.1 seconds** each, including fetch and local OCR. Two production OCR workers remain the limit; an offline diagnostic briefly overlapped this run, so timings are observed values rather than a controlled performance comparison.
- Sprint total: **100/100 physical research attempts** = 34 before + **32 interrupted first post-change run** + 34 final. The interrupted run was stopped after discovering the workplace cutoff defect and contributes no coverage results. It remains fully counted. Failed robots/transport attempts are included. No counter reset or off-gateway company requests occurred; networking was sealed after the final run.
- All six PDFs were accessible in both completed live runs. No new external-source access was asserted merely from historical requests.
- The final live run initially failed at publication because the new candidate `json_pointer` key was not in the closed synthesis schema. All six completed graphs were already terminally checkpointed. A narrow whitelist repair and regression test fixed this, and the existing production resume path published those exact live claim graphs without refetching. The failure and recovery are explicitly retained; the interrupted and failed-publication stages are not presented as separate successful live benchmarks.

## Verification and handoff

Relevant final regressions: **165 tests + 47 subtests passed** across financial documents, BRREG, location/cutoff, candidate provenance, website gates, query dimensions, synthesis and refresh/history. Final captured-source refresh replay retained all **71 financial + 37 workplace + 4 FTE claims**, six terminal outputs, and **zero changes**. It denied actual HTTP; gateway counters in that replay represent mock transport calls. This is supplementary offline evidence only; exact-commit CI is verified after push. Dependencies are unchanged, so this sprint adds no new installation prerequisite. Exact evaluator compatibility, resume publication and cardinality were exercised from an unrelated working directory.

Fallback remains `8076e1b627cf1bdac00f9a241fdf6c6bf1831af8`. Repository visibility and submission are unchanged. Owner actions remain: confirm Builderr reviewer access and repository licensing, supply submission contact details, confirm organizer evaluator/resource/cutoff and any snapshot handoff requirements, then submit the final exact green SHA using the existing submission materials.
