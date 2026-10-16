# Final release validation — 2026-10-17

**Disposition: engineering checks passed for the repaired implementation; competition submission remains HOLD.** This is a bounded final validation, not another full security audit, a new 100-company cohort, an independent population-precision study, or an official evaluator result.

## Candidate and repair

Initial remote/accepted candidate was `375b7ff4f1f1998a6e04b5a58e8a276c118dbd82`; its exact-SHA Actions run [38551519938](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/38551519938) was completed successfully. The VM initially had a clean older default branch and was switched to `codex/m12-final-sol-remediation` after fetching and checking the remote tip.

Final implementation: `4e5aacbb1d9793095e6c89eb06f56b496324c814`. The subsequent package commit changes documentation, evidence receipts and a bootstrap-directory ignore only. The exact final package SHA, remote match and CI result are recorded in the final handoff and the external `FINAL_RELEASE_RECEIPT.json`. The package does not attempt to embed its own commit hash. No force push, merge, PR or visibility change is part of this release.

A bounded set of three new adversarial variants plus a positive control reproduced two existing shared-page defects through `research_company`, publication-graph validation and `to_evaluator`: selecting the target from competing direct main entities, and accepting a same-name group page publisher whose identifier contradicted the site publisher. All three negative variants failed before the fix, including the reversed entity order. The root fix checks all direct company subjects and compares explicit publisher identifiers before any shared-page proof is accepted. A coherent group subsidiary page still publishes only its exact URL, never group-domain ownership.

Existing resource-bound, direct typed ownership, visible contradictory operator, exact query/path, off-host metadata, nested publisher, trading-name, redirect, customer-story and supported subsidiary controls passed. Final acceptance remains deterministic and scoped; no new architecture, provider, source right or material publication policy was introduced. Fixture verification is bounded evidence, not a universal website-precision guarantee.

## Actual application and clean environment

A separate checkout with no inherited virtual environment installed the locked dependencies, launched the CLI from `/tmp` with `PYTHONPATH` unset, and produced all four ordered offline fixture rows including the duplicate. The optional HTTP application launched from that clean directory and passed find/profile/evidence/compare/verify/history/XSS smoke. The fixture identities are synthetic and are not counted as live coverage.

A second isolated checkout at implementation `4e5aacb` installed with pinned uv 0.8.0 and passed the same clean-directory CLI/UI checks without installing pytest. The standalone uv 0.8.0 bootstrap was also verified; the optional Python `venv` bootstrap failed on this VM because ensurepip is absent, which is why the submission guide uses the tested standalone installer. Runtime dependency and environment requirements are explicit.

The actual canonical CLI then researched a single real company, PARS INVEST AS (`995854600`), from an unrelated directory using plain-text input and no `PYTHONPATH`. It produced one available, source-bound evaluator envelope in six physical requests. The four-company application baseline and real previous-state refresh are described below. Both live JSONL results launched in the real read-only HTTP UI; legal-name verification, compare, profile/evidence/source information, changes and escaping checks passed. The comparison did not invent missing financial metrics.

## Authorized live validation and coverage

The historical M12 authorization was a consumed one-time cohort. Before further company-data requests, the user approved four distinct companies and at most 80 physical requests against existing BRREG endpoints and registry-listed website/robots/bounded site resources. No new 100-company cohort was started.

The clean initial baseline at `375b7ff4` used 25 requests. Two Equinor page inspections through the gateway used three more requests. A real refresh of the same four companies with `--previous-state` used another 25, with an additional pre-reservation guard limiting the remaining aggregate allowance to 52. The standalone single-company CLI had a separate 20-request maximum and used six. Total: **59 physical requests / 80 approved**, four distinct companies, $0 paid API cost. There were no new providers, credentials, PDFs, restricted-platform scraping, paid services or robots bypasses. Package/dependency downloads are installation traffic, not company-data acquisition.

Both batch runs used `--no-keyless-websites` to keep acquisitions registry-listed, and the explicit audited cutoff `2026-10-17T23:59:00+05:30`. Source retrievals preceded that cutoff. Default run-start behavior is unchanged. The complete baseline/refresh each produced four ordered available envelopes and valid state/publication pairs. Current adapter serialization of retained canonical envelopes matches their evaluator JSON exactly. Claim/evidence/snapshot, batch publication and financial-withholding checks passed. The real refresh recognized the prior-state hash for all four companies, kept all 908 available claims and produced zero spurious changes. Material-change positive cases are separately verified by the recorded replay, not inferred from this unchanged live sample.

Observed real-company results:

- `923609016` EQUINOR ASA: exact official identity; six financial records, 15 role rows, 35 complete exact-parent workplaces. Website remained ambiguous (`conflicting_structured_company_identity`); no owned-site claim was published. Its fetched Organization record names Equinor ASA but lacks the exact company identifier needed by that proof route; this inspection did not establish another permitted sufficient ownership proof.
- `976390512` NORSK RIKSKRINGKASTING AS: exact official identity; six financial records, 23 role rows, 20 complete exact-parent workplaces. No registry website candidate in this response.
- `995854600` PARS INVEST AS: exact official identity; three financial records, four role rows, one complete exact-parent workplace. No registry website candidate. This also passed the single-company canonical CLI.
- `926627708` NORDVEST INSTALLASJON AS: exact official identity; three financial records, two role rows, one complete exact-parent workplace. No registry website candidate.

These are confirmed source-anchored observations, not independent human adjudication of every role or estimates for Norway's company population. No confirmed wrong-company association was found in this sample. Missing candidate sites are potentially obtainable only if approved discovery/evidence supports them; absence in the registry does not mean no website exists. Equinor ownership is unresolved, not a claim that its website is wrong.

Across the required envelope sections: identity/brand has exact legal identities for 4/4; accounts/history has 18 records and 126 metadata claims but zero numeric metrics; leadership/workplaces has 44 role rows represented by 355 claims and 57 workplaces represented by 361 claims; websites/owned profiles has zero published claims; hiring/activity has zero published claims and remains unattempted after no accepted site; claims/evidence/states has 908 available canonical claims with validated provenance; refresh/history has a recognized prior snapshot for 4/4, zero live changes, and positive/negative material-change replay coverage.

Financial values remain contractually withheld without unit/scale proof; currency is not scale. Current jobs/activity remain unsupported by approved reached sources, not confirmed absent. No financial unit was guessed. The workplace gain comes from an explicit authorized cutoff that permits already supported current observations, not from changing removal or freshness rules. Robots transport exceptions remain confined to the existing exact BRREG API policy; ordinary websites still fail closed.

## Deterministic gates and limits

- Complete initial-candidate suite: 432 tests, 194 subtests, one third-party deprecation warning.
- Repaired implementation suite: **433 tests, 198 subtests**, one identical third-party warning; zero failures. This exercised the exact source subsequently committed as `4e5aacb`.
- Repaired focused website/ownership/M03/M04/M05/M09-live-shape suite: **150 tests, 152 subtests**. Includes the latest shared-operator and legitimate trading-name cases through final serialization.
- M07 recorded replay: 12 profiles, six material changes, precision/recall 1.0, complete provenance, stable and idempotent event IDs.
- M08 independent gold: four fixture profiles; find/compare/verify 1.0, citation completeness 1.0, unsupported assertions zero. This is a query fixture benchmark, not external coverage evidence.
- M09 source-shaped integration, identity, financial withholding, synthesis evidence boundary, claim/snapshot validation, and XSS: covered in the full/focused suites; real HTTP smoke also passed on baseline and refreshed live outputs.
- Real process crash/resume: kills after durable checkpoints 25/50/90, each resumed to 100 ordered rows with semantic equality to an uninterrupted run; network disabled.
- Existing M06 scale/provenance script and verifier: 1,000/1,200 operational writes and 10,000-row offline run; stress modes A–D; no physical requests; synthetic identity precision explicitly not measured. Scheduler/network/scale code was unchanged by the ownership fix.
- Clean-CWD launcher: exact four-row cardinality, duplicate preservation, zero network; pinned clean installation and UI smoke passed at implementation SHA.
- Historical RC1/post-Sol receipt packaging verifier: PASS. All previously tracked `docs/release` files were hashed before documentation work and will be compared unchanged before freeze. Historical M12 raw bundle paths belong to another host and are absent here; no fresh raw-bundle integrity claim is made.
- `git diff --check`, production compilation, final exact-SHA GitHub CI and remote/clean-tree receipt are required freeze checks; their final results are in the final handoff/external receipt. Documentation-only edits do not justify re-running expensive scale tests.

Replay/gold/scale/crash scripts ran on clean `375b7ff4` before the narrow ownership fix; the ownership fix does not touch their code paths. Full/focused tests covered the repaired source. The final package's CI repeats the configured release gates on its exact SHA. Do not describe baseline script artifacts as if their metadata named the package SHA.

## Historical evidence, reproducibility and submission blockers

The accepted historical [M12 100-company smoke](M12_POST_REPAIR_LIVE_ACCEPTANCE_2026-10-10.md) remains unchanged: source `7d4fe04867cd746389c48a47f360afd7ac4b8fb1`, 100 outputs, 459 physical requests, 347.077 seconds, one verified website, zero numeric financial metrics/workplaces/jobs/activity under its cutoff and source access. Its output bytes are not on this VM, so recorded hashes are preserved rather than claimed freshly checked. Earlier failures and known historical artifact deviations remain disclosed in their original reports.

Current machine-readable measurements/hashes are [FINAL_VALIDATION_2026-10-17.json](FINAL_VALIDATION_2026-10-17.json). Current raw evaluator/state/checkpoint/report/ledger and deterministic gate artifacts are preserved outside the checkout at `/home/azureuser/projects/signalpost-release-evidence/final-20261017` on pancakes, with a complete manifest. They include factual personal-role names from approved official responses; no new raw website response bodies or PDFs are retained in the package. These VM-local files are not automatically accessible to organizers. The checked-in summary/receipts are portable evidence; raw artifacts can be reviewed by the owner before any external sharing.

The [submission/demo guide](../../submission/README.md) contains installation, exact launch/evaluator invocation, schema, previous-state/resume, cutoff/budget behavior, free-versus-paid disclosure, source/rights limitations, and owner actions. Repository access is PRIVATE; the authenticated collaborator listing contains only the owner, so Builderr access is NOT VERIFIED. No public hosting contract, exact official JSON Schema, frozen-registry contract or official evaluation feedback has been supplied. A source-code licence remains undeclared. None was invented or changed here.

**Submission remains HOLD.** Low supported external coverage and absent comparable held-out recall evidence remain proven limitations; CI does not establish official evaluator acceptance or qualification. The owner must resolve private access/licensing and organizer contract inputs, review the coverage limits, and separately approve any actual submission. No external communication or competition submission was performed.
