# Second Sol High RC1 verification remediation

Status: local remediation in progress; final commit and verification results are recorded in the completion report. Starting source: `8519e2d4620d87de0472d624dc2cc0957908bd0f` on `codex/m00-contract-audit`.

No live cohort, push, search, model, paid API, credential, Builderr submission, or M10 work is included. The five reported defects were reproduced against the starting code before applying fixes.

## Baseline reproductions and fixes

| Finding | Reproduced baseline behavior | Root fix and regression coverage |
|---|---|---|
| P1 website ownership | `research_company` accepted `https://rival.no/customer-stories/acme` as Acme AS using a customer-story title, customer mention, and footer address/org number. | Textual/name/address/role signals are rejected when the page context describes the subject as a customer or supplier. Target-specific structured Organization proof remains eligible, including shared domains. Production-path tests cover a rival customer-reference page, target-specific shared-domain acceptance, conflicting identities, and target mentions in footers. |
| P1 final synthesis boundary | `to_evaluator` serialized an arbitrary top-level `unsupported_financial_prose` synthesis field. | Synthesis is schema-versioned and checked recursively against closed known keys and exact summary/sentence shapes before evaluator serialization. Unknown keys are rejected at the top level and at nested locations. Regression mutations add arbitrary top-level, summary, website-audit, and nested audit prose. |
| P1 job status | `_page_footprints` converted `jobStatus=closed` plus a future `validThrough` to `open`. | Explicit closure and expired deadlines close a posting; explicit open cannot override an expired deadline; unknown explicit status stays unknown. Production-path tests cover closed/future, open/expired, unknown/future, malformed dates, and a currently confirmed posting. |
| P1 financial units | A metric `enhet=0` was treated as absent and inherited record-level `TNOK`. | Unit metadata now distinguishes absent, explicit null, malformed, unsupported, supported, and conflicting values. Only an absent metric key can inherit a valid record-level unit. Canonical and final publication reject incompatible currency/unit dimensions, including EUR/TNOK. Tests cover record and metric units, null/zero/empty/unknown values, conflicts, missing units, and legitimate zero/negative values. |
| P2 frozen hash exception | A fabricated public URL, `registry_snapshot:forged` ID, and matching labels activated the row/aggregate hash exception. | Exception requires the internal frozen-registry URN containing the full aggregate SHA-256, `registry_snapshot:<same SHA>`, matching snapshot hash, approved NLOD-2.0 rights, official source class, frozen JSONL extraction method, approved identity JSON pointer, and exact evidence/snapshot URL equality. Mutations cover forged URL, ID, license, method, source class, pointer, and hash mismatch. |

## BRREG financial-unit investigation

The official Enhetsregisteret OpenAPI documents entity-registry fields and identifies `valuta` in capital information; it does not document an `enhet` scale for the annual-account metrics used by this adapter. The official account API documentation exposes annual-account copies and interim balances as PDF. The older BRREG key-figures OpenAPI describes the JSON response only as an object; its record schema defines numeric financial values and a `valuta` code, but does not define an `enhet` field or numeric scale. It also describes that service as temporary and not maintained. See the [official Enhetsregisteret OpenAPI](https://github.com/brreg/openAPI/blob/master/specs/enhetsregisteret.yml), [BRREG account API specification](https://raw.githubusercontent.com/brreg/regnskapsregister-api/master/src/main/resources/specification/regnskapsregister.json), [account API documentation](https://data.brreg.no/regnskapsregisteret/regnskap/swagger-ui/swagger-ui/index.html?urls.primaryName=aarsregnskap), and [BRREG Regnskapsregisteret overview](https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/).

The source representation currently consumed by `signalpost/brreg.py` is not covered by an authoritative schema that establishes the assumed `enhet` metadata or the scale of unlabelled numeric values. A currency code establishes currency, not scale. Existing retained live artifacts do not include raw source bodies, so the 1,875 withheld candidate metrics cannot be safely reconstructed or relabelled. The active behavior remains fail-closed: publish a financial metric only when its value, period, scope, supported currency, and explicit compatible unit are all established. No scale normalization, currency inference, or recall restoration was made. Restoring those candidates requires an authoritative source contract for the exact consumed representation and is unresolved.

## Verification results

- Baseline reproductions: all five findings reproduced on the clean starting SHA before edits.
- Focused production-path suite: 129 passed across M03, M05, M08, and remediation tests; 69 subtests passed.
- Complete suite on the final code: **389 passed, 91 subtests passed**. The M09 live-shape integration is included (2 tests); both full publication runs pass.
- M07 replay: **PASS** — 12 rows, 12 baseline and 12 current envelopes, 6/6 expected changes, 0 FP/FN, complete provenance, stable event IDs.
- M08 gold: **PASS** — 4-company corpus; find/compare/verify accuracy 1.0, 0 unsupported assertions, citation completeness 1.0. The evaluator now validates each sentence in the intact versioned summary shape.
- M09 crash/resume: **PASS** — 25/50/90 durable-row interruption points, all resumed outputs had 100 ordered rows and matched uninterrupted semantics.
- M06 offline scale/provenance gate: **PASS** — ordered 1,000/1,200 operational writes; 10,000 rows in 59.754 seconds, 1,005.41 MiB peak RSS, 0 physical requests; M06 provenance and synthetic identity verifier passed. Scheduler simulation completed all 1,000 official work items and starved none; identity precision was not measured.
- Clean-directory launcher: **PASS** with `PYTHONPATH` unset, 4 output rows, 0 physical requests. M08 local UX/XSS smoke: **PASS** (launch, profile, evidence, compare, verify, changes, and XSS checks).
- `compileall`, `git diff --check`, publication/provenance mutation tests, adapter mutations, financial validation, gateway/robots/budget tests, wrong-company adversarial tests, and source-purpose/family validator tests passed.
- No live cohort or outbound network run was performed. Historical reports remain unchanged; the prior live-gate report records 1,875 candidate financial metrics withheld and 0 canonical financial publications. Since raw response bodies were not preserved and the source specification omits scale semantics, no recall restoration is supported by current evidence.
- The local test suite and deterministic gates are not GitHub CI. The user-reported green CI run `37659807168` is preserved as user-reported evidence; no independent GitHub result is claimed.

## Scope and release handling

Historical live reports are unchanged. No new live traffic was sent. No code or artifacts were pushed. M10 remains not started.
