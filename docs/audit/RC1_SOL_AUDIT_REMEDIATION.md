# RC1 Sol-audit remediation record

Status: local remediation complete at the commit recorded by the completion report. Starting source: `4ed01bedc784702a1ef904dbc80b1152608a62ba`.

This record covers the six P1 findings and seven P2 findings from the independent RC1 audit. No independent audit pass is asserted here. No live cohort, external network request, provider, search, model, or paid API was used in this remediation.

## P1 findings

| Finding | Root cause | Remediation |
|---|---|---|
| A01 wrong-company website publication | A target identifier found anywhere on a page could be treated as ownership proof, including incidental footer and shared group-homepage mentions. | Website parsing separates footer blocks from affirmative identity blocks. Verification weighs legal entity identifiers, names, headings, structured identity, and conflicting/multiple entities. Ambiguous shared pages are withheld; target-specific pages can still pass with target-bound proof. Regression coverage includes target-in-footer, rival main identity, multi-entity homepages, and target-specific pages. |
| A02 cross-company provenance identity | Website evidence identifiers did not bind the subject company, and per-envelope validation could not detect conflicting identities across a batch. | Subject organisation is included in website evidence identity. Batch publication validation rejects cross-envelope evidence conflicts and snapshot ID conflicts while treating retrieval time as observation metadata for stable URL/content snapshots. |
| A03 financial source unit loss | Financial unit metadata could be lost or inferred from currency, making source values ambiguous in scale. | BRREG values retain explicit source unit; record-level unit may be inherited by a metric, conflicting units are rejected, and missing/unsupported units cannot publish canonically. No conversion is performed. FIND, COMPARE, VERIFY, evaluator adaptation, and smoke validation require compatible unit semantics. |
| A04 incomplete roles response | A malformed HTTP 200 collection could appear complete and authorize role-removal events. | Role group and role collection shape is validated; only a structurally complete collection can establish absence. Missing/null/wrongly typed role arrays and malformed groups remain incomplete. M07 refresh regression coverage checks that incomplete data cannot end a prior role. |
| A05 final publication boundary | Evaluator serialization trusted earlier checks and did not compare section claims or revalidate synthesis and financial semantics. | `to_evaluator` revalidates the publication graph, claim/section consistency, citation-supported synthesis, and available financial unit/value/currency/period/scope semantics immediately before serialization. |
| A06 malformed CSV row loss | Permissive CSV parsing allowed an unclosed quote to consume a following physical company row. | CSV/TSV parsing uses strict standard-library parsing while preserving valid quoted newlines. Malformed quoting now fails the input parse rather than silently reducing rows. |

## P2 findings

| Finding | Status | Evidence / behavior |
|---|---|---|
| A07 frozen-registry hash exception | FIXED | Exception requires the approved extraction method, official source class, registry snapshot identity, exact evidence/snapshot URL binding, and `NLOD-2.0` rights marker. Public-web method-label spoofing does not qualify. |
| A08 VERIFY numeric equivalence | FIXED | Numeric propositions compare via validated Decimal semantics; integral floats and integers compare equally. Non-finite/malformed values and dimension mismatches are rejected. |
| A09 old job counted current | FIXED | Unknown status is not treated as open. Expired postings are closed; only affirmative open/current evidence contributes to current hiring. |
| A10 output aliases input | FIXED | Preflight resolves and checks aliases among output, state, checkpoint, marker, and read-only inputs/configuration/registry/previous state. |
| A11 paired output/state publication | FIXED | A durable publication marker is first written as `publishing`, then both artifacts are atomically replaced, then the marker commits hashes for both. Consumers can reject an incomplete pair. Failure injection covers the gap between writes. |
| A12 ephemeral release evidence | FIXED WITH LIMITATION | A compact durable receipt stores historical source/cohort/config/artifact hashes, counts, and release-report identity; a packaging verifier checks required fields and hash formats. The original raw `/private/tmp` bundle has expired and is not recreated. Historical measurements are not rewritten. |
| A13 source-specific rights decision | FIXED NARROWLY | Runtime configuration supports bounded host decisions `allowed`, `blocked`, and `unknown_not_reviewed`; explicit blocks prevent website research and decisions are carried into audits/snapshots. No legal conclusion or terms crawler was added. |

## Historical RC1 evidence

The durable receipt is [M09_RC1_DURABLE_EVIDENCE.json](../release/M09_RC1_DURABLE_EVIDENCE.json). It preserves recorded hashes and historical measurements without copying a large raw bundle. The prior report is linked to [the financial-validator correction](../release/M09_FINANCIAL_VALIDATOR_CORRECTION.md), which documents that the historical validator did not enforce source-unit semantics. Accordingly, historical financial publication counts and website ownership outcomes are not evidence that the corrected invariants passed on the live cohort.

## Verification

Verification completed against this remediation:

- Complete suite: 380 tests passed.
- Deterministic M09 live-shape production path: 2 tests passed.
- M08 suite: 35 tests passed.
- Smoke-validator purpose/family and financial gate: 3 tests passed.
- Offline scale gate: 1,000, 1,200, and 10,000 rows passed; 10,000-row writer completed in 77.258 seconds at 1,054.6 MiB maximum RSS; 0 physical requests. Scheduler scenarios also completed with 1,000/100 terminal official items, as configured.
- Durable evidence packaging check: passed.
- `compileall` and `git diff --check`: passed.

The complete suite includes M07 refresh/removal semantics, M08 gold and UX/XSS, crash/resume, gateway/robots/budget, input-format, final-adapter mutations, and publication fault injection. Verification is deterministic and offline. No live retry or independent Sol audit is included.
