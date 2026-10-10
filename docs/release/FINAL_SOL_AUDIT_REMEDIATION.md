# Final Sol audit remediation

**Failed-audit checkpoint:** `53429111bd6062234231be51119ac7b145c30c02`  
**Implementation commit:** `2be9eb203729e86f7183b979011105fb54b451ae`  
**Branch:** `codex/m12-final-sol-remediation`  
**Live cohorts:** none run during this remediation

## Findings and fixes

### P1 — Website ownership

The Sol customer-reference fixture was added before the implementation change and failed through the production `research_company` path: the page could publish `verified_website_domain` for the mentioned target. The root issue was that identity evidence from a mention, page title, and incidental footer could be combined without sufficient subject scope.

Website ownership checks now classify exact legal-name and organisation-number mentions in local sentence/DOM blocks against customer, supplier, partner, case-study, article-subject, group-member, and service-provider contexts. Footer identity text cannot borrow unrelated ownership signals. Structured Organization identity must be subject scoped; where visible context is non-owner context, the Organization URL must bind to the page. Exact target-specific shared-domain pages remain eligible when independently bound, while the group homepage does not inherit a subsidiary's identity.

Regression coverage exercises customer/supplier/partner variants, different names and legal suffixes, incidental addresses, target numbers appearing only in customer context, nested article schema, unbound root Organization schema, target-owned structured sites, and target-specific shared-domain pages. The six-company M09 live-shape production path also passes after keeping title, heading, identity, and visible-text blocks separate during context classification.

### P1 — Synthesis publication boundary

The final adapter previously serialized arbitrary values in recognized nested synthesis sections after validating only the summary. It now rebuilds the summary deterministically from canonical claims and validates it, rejects a supplied summary that differs, and serializes only the versioned summary schema. Operational synthesis observations remain available internally but are not published as evaluator facts absent canonical bindings.

Mutation tests inject fabricated names, organisation numbers, dates, domains, counts, financial values, wrong types, and nested values under every recognized supplemental root. Final adapter output contains only `schema_version` and the validated canonical `summary`; edited or unknown summary data is rejected. Valid production synthesis continues to serialize.

M07 refresh coverage was also changed to derive from canonical sections, claims, and evidence references rather than mutable synthesis observations. Completeness evidence IDs are copied into section diagnostics and must resolve to actual evidence before they can authorize absence claims.

### P2 — Portable publication evidence

New paired-publication markers include a self-checking metadata digest. Archived bundle verification accepts an explicit bundle root only when the marker has an externally recorded SHA-256, safely rebases archived absolute paths, enforces bundle containment, checks marker and artifact names, rejects traversal and symlinks, and verifies output/state hashes. Active production markers retain their absolute-path behavior. Historical evidence and manifests were not modified.

The preserved post-repair M12 bundle was verified from its copied location using the manifest-recorded marker SHA-256 `f81111684c958819b61d3c2307ad5912fd72b9ac1b8ad9c425b0778ca5da1b6f`. The verified output hash is `401791971d5669156643af61428d0e8c918bf16e6cb7eaf348a1ba2730dcf31f`; the verified state hash is `98b1274c2bf8786d5a8f34021f6fd9c334dfb6ec66e8c2ed40b74e1cbe098b4e`. Relocation, tampering, missing artifacts, cross-run pairing, traversal, and symlink escape are covered by regression tests.

## Verification

- Baseline reproduction against unchanged source: three focused regressions failed as expected (customer-case ownership false positive, unbound recognized synthesis additions, and missing portable bundle-root verification support).
- Focused Sol/M09 production-path regressions: **38 passed, 32 subtests passed**.
- Complete test suite: **402 passed, 103 subtests passed**.
- M07 contract tests: **33 passed**.
- M07 refresh replay: 12 profiles; 6/6 material changes; precision 1.0, recall 1.0; complete provenance; idempotent event IDs; gate passed.
- M08 gold: four-company corpus; find/compare/verify accuracy 1.0; citation completeness 1.0; zero unsupported assertions; gate passed.
- M08 local HTTP UX/XSS smoke: launch, profile, changes, compare, evidence, verify, and XSS checks passed. This used local loopback and offline fixture output only.
- M09 six-company live-shape production integration: passed.
- Offline crash/resume: crash points 25, 50, and 90; all resumed to 100 ordered rows with semantic match to uninterrupted output; network disabled.
- M06 deterministic scale/provenance gate: passed its verifier; 1,000-row scheduler simulation, no network, synthetic identity claims absent.
- Clean-directory launcher with `PYTHONPATH` unset: four expected output rows; zero physical requests.
- `compileall` and `git diff --check`: passed.

Some standalone scripts record the current `HEAD` and dirty-tree state at execution; they were run before the implementation commit and therefore identify the failed-audit base plus a diff digest. Their deterministic results are recorded above. The final exact-SHA CI result is recorded in the accompanying checkpoint response, not inferred from these local runs.

## Release status and limits

No new live cohort was run. Preserved live evidence was read and hash-validated without rewriting historical reports or artifacts. The established limitations remain: no canonical financial numeric metrics where source unit/scale is unsupported, no published workplaces, one verified owned website among the prior 100-company cohort, no established current jobs/activity, no official Builderr score, and no confirmed Builderr access to the private repository. Competition submission remains **HOLD**; correctness rules were not loosened to raise coverage. No Builderr submission, paid provider, or M10 work was performed.

The requested remediation does not require a new architecture, source-rights decision, credential, or live test. Exact-SHA GitHub CI remains a required final gate.
