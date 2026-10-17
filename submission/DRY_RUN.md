# Final submission dry run — 17 October 2026

**Engineering package: GO. External sending/publication: HOLD for owner decisions.** No UI/backend change, new acquisition, paid service, repository access/visibility change or competition submission is included. The accepted code is `64f69071b241614a1826c342ef65020db7a125d4`; this package changes documentation and evidence only. The owner handoff records the exact final package SHA, clean remote/worktree and exact-SHA CI. `git rev-parse HEAD` is the self-contained way to identify a cloned package.

## Current official contract and actual starter

Re-fetched the [challenge](https://builderr.ai/challenges/signalpost), [brief](https://builderr.ai/starter-briefs/signalpost.md), [evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md), [source policy](https://builderr.ai/starter-briefs/signalpost-sources.md), [rules](https://builderr.ai/guidelines) and [runnable archive](https://builderr.ai/signalpost-starter-kit.tar.gz). The brief, contract, policy and starter archive hashes match the previously inspected official versions. Current hash receipts are in [dry-run-evidence.json](dry-run-evidence.json); existing byte-identical vendor captures remain untouched.

Confirmed required submission artifacts: repository/code, exact commit, reproducible install and one run command, 100-company smoke result **or run report**, models/APIs/licences, expected cost and contact. No precomputed official profiles or entrant-selected official company manifest is required. Builderr supplies the company batch, frozen identity snapshot, cutoff, network/resource policy and output format. Return one terminal envelope per supplied company, preserve evidence/history, keep unavailable data distinct and do not invent zeros. Scoring is 50/30/12/8, qualification at 65 on an official run; no local qualification claim is made. The page currently lists Oct 21 closure and Oct 18 revision cutoff; neither replaces the owner's earlier deadline.

The current downloadable starter's executable `scripts/run_competition_batch.py` and `batch.py` are byte-identical to the repository copies. Independently ran that actual downloaded script from `/tmp` using a controlled fictional two-company JSON wrapper/native gzip CSV and offline `registry,accounting_obligation` modules: exit 0, two ordered outputs, zero requests, all five built-in checks passed. Production accepted the same supplied inputs and emitted two ordered `available` envelopes. The starter executable uses `state/modules/profile` and `complete`; production uses `terminal_state/sections/claims/evidence/...` and the prose contract's six states. These are not interchangeable serializers. No public source establishes which private parser will be used; no speculative alias or adapter change is justified.

**Exact outstanding question (prepared, not sent):** Will Builderr run our declared `run_signalpost.py --input ... --output ... --state-output ...` command and accept its documented six-state evidence envelope, or require the executable starter's flags and `state/modules/profile` wire format? Please supply the accepted parser/schema and batch, frozen-snapshot metadata/rights, cutoff, budget and prior-state handoff. Official parser compatibility remains UNVERIFIED; operational JSON/cardinality compatibility is proven locally.

## Executed acceptance

All acquisition scenarios here are controlled/offline; the real-company request count added is **zero**.

| Check | Actual outcome |
|---|---|
| Clean authenticated clone at accepted code SHA; new venv; pinned bootstrap/install | PASS, 50 distributions. Initial forced-uncached download timed out on a PyPI wheel; declared frozen install succeeded on retry with normal cache/120-second network timeout. No lockfile or dependency change. |
| Exact documented offline run from unfamiliar empty directory, `PYTHONPATH` unset | PASS, exit 0, four ordered envelopes including duplicate, unique input refs, strict JSON, stdout JSON batch report, zero stderr, zero requests |
| JSON array/wrapper, CSV, plain text; malformed JSONL, invalid/unknown company | PASS, ordering/cardinality preserved; invalid rows get terminal failure/errors rather than disappear |
| HTTP refusal, source absence, timeout, partial source | PASS under controlled transport: `blocked`, `not_available`, `failed`, `available`; unsupported claims withheld, no real outbound requests |
| Refresh, repeat idempotency, retained earlier evidence, checkpoint resume | PASS; controlled changed name produces one supported event, identical repeat produces none; documented command resumes with exit 0 |
| Growing batch 1,000 → 1,100; subset 2; repeat 1,100 | PASS, exact counts, one controlled change on growth, retained 1,100-company state for subset, no false repeated changes; frozen fixtures, not measured live scale |
| Actual HTTP saved-data workflows | PASS in independent process checks: Find/profile/evidence, supported/contradicted Verify, comparison, changes and mixed invalid-input dashboard |
| Historical 100-company report | Present and self-contained in Git; old SHA/report, raw bytes unavailable, no false final-SHA replay claim |
| Public-content review | All 223 original tracked files and 442 reachable history blobs reviewed with bounded pattern scan; no secret matches or tracked key/env/checkpoint files. New docs reviewed separately before commit. No archive includes `.git`, `.venv`, VM data or SSH configuration. |

The machine-readable evidence records these runs at the clean accepted code SHA; final package CI and exact-source clean-clone checks are reported in the final owner handoff. No production files changed, so the preceding 460-test/209-subtest result remains relevant; exact-package CI reruns its required full suite/gates. No expensive live tests are rerun for documentation edits.

## Self-contained artifacts and accuracy corrections

[ARTIFACTS.md](ARTIFACTS.md) maps every required item to a repository path. [HISTORICAL_100_COMPANY_SMOKE.md](HISTORICAL_100_COMPANY_SMOKE.md) explicitly identifies the accepted report and its unavailable raw bundle. A report is the permitted artifact: old absolute paths are historical identifiers, not install/runtime dependencies. Bundled offline fixtures and replay/process scripts work without any private VM research data. Original release reports and vendor captures are preserved unchanged.

Corrected stale implementation-checkpoint and 59-request descriptions in the current guide; actual authorized live usage is 78/80. Completed the installed licence inventory (50 distributions), declared $0 third-party API/model cost per official batch with infrastructure excluded, and made the older GitHub default branch explicit. The project code licence remains undeclared; the owner must approve any new licence grant. No code, UI, dependency, source policy or rights rule was changed.

Coverage limitations remain disclosed: verified websites are sparse; financial record metadata is not numeric metrics; hiring and dated activity lack approved supporting coverage in the saved sample. Historical workplace withholding reflects its cutoff. This dry run does not prove competitive recall, full-scale live runtime or an official score.

## Remaining owner actions

1. Authorize and verify a reviewer access route to the exact package. The repository is PRIVATE; only the owner appears in its collaborator listing. Public visibility is not changed automatically and private organizer access is not proven. The older default branch must not be mistaken for the final commit.
2. Supply the contact name/email authorized for results, and acknowledge the undeclared project-code licence or choose a licence if desired. Third-party/data rights are already disclosed; no particular open-source licence is invented as an official condition.
3. Authorize sending the specific parser/handoff clarification, or accept the disclosed compatibility uncertainty when deciding whether to submit. No confirmed parser mismatch is inferred from an unpublished interface.
4. Review the rendered draft and exact final SHA/CI, then separately authorize the external submission. Nothing has been sent; no version/revision slot was consumed.

The source archive is a convenience; the authoritative submission is the exact Git commit. It can be reproduced with `git archive --format=tar.gz --prefix=signalpost/ --output=/tmp/signalpost-package.tar.gz HEAD`. The final owner handoff archive additionally contains the exact-SHA rendered draft, logs and archive checksum; these supplementary receipts are not required to install or read the repository-contained run reports.
