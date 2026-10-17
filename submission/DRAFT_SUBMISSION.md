# Builderr submission draft — NOT SENT

Owner preparation only. Resolve `PACKAGE_SHA` with `git rev-parse HEAD` at the frozen package checkout and fill `CONTACT_NAME` / `CONTACT_EMAIL` with details you authorize sharing. Confirm reviewer access before sending. A rendered exact-SHA copy is supplied in the final handoff archive; this template stays self-contained in Git without claiming its own commit hash.

To: submit@builderr.ai
Subject: Signalpost — company research agent submission — PACKAGE_SHA

Agent: Signalpost
Contact: CONTACT_NAME <CONTACT_EMAIL>
Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information
Branch: codex/m12-final-sol-remediation
Exact frozen package commit: PACKAGE_SHA

The repository is currently private. Reviewer access must be arranged and verified; the URL alone does not grant access. The default branch is older: please use the exact frozen commit above.

Install: Git, Python 3.12 (tested), uv 0.8.0; from `signalpost-starter-kit`, run `uv sync --frozen --extra m08-test`. A no-sudo pinned uv bootstrap is documented in `submission/README.md`. No research API credentials, model key or paid service is required.

One run command from the checkout root (Builderr supplies `companies.jsonl` at runtime):

```sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py --input companies.jsonl --output output.jsonl --state-output state.json --checkpoint checkpoint.sqlite --live-brreg --live-websites
```

Supply the official frozen registry, source/date metadata, authorized cutoff and budget using the documented `--registry-snapshot`, `--registry-snapshot-as-of`, `--registry-source-url`, `--evidence-cutoff` and `--config` inputs. The command above is the declared live fallback, not an authorization to run a new test now. JSONL output is written to the requested file, one ordered terminal envelope per input row; stdout is a separate JSON batch report. State and its adjacent publication marker must be retained for refresh; repeat the original command with `--resume` for interrupted work, or use new outputs/checkpoint plus `--previous-state` for a refresh.

100-company smoke report: `submission/HISTORICAL_100_COMPANY_SMOKE.md` links to the complete repository-contained report. It records source `7d4fe04867cd746389c48a47f360afd7ac4b8fb1`, 100/100 ordered terminal outputs, 459 physical requests and 347.077 seconds. It is historical evidence, not a new final-SHA live run. Raw historical bundle bytes are unavailable. Fresh offline acceptance and growing-batch checks are separately documented; precomputed profiles are not proposed as official scoring input.

Models: none. APIs: official BRREG exact-entity/accounts/roles/subunits, plus bounded registry-listed or approved conservative candidate websites through the policy gateway. Paid APIs: none. Declared third-party API/model cost per official 1,000/1,100-company batch: $0; supplied VM/network infrastructure is excluded, and full-scale live runtime is not measured by the offline scale tests.

Rights/licences: BRREG attribution and NLOD 2.0 policy, site-specific website restrictions, dependency licence inventory and third-party notices are in `docs/source-rights.md`, `config/source_policy.yaml`, `docs/data-licenses.md` and `THIRD_PARTY_NOTICES.md`. No prohibited platform scraping, PDFs, external model/API credentials or paid integrations are enabled. The project's own code licence is undeclared; no new licence grant is implied by this draft. No cached live company corpus is required for execution; the bundled examples are identified fixtures and historical reports.

Known limitations: strong evidence-backed abstention with limited verified websites; no promotable numeric financials without scale/unit proof; sparse hiring and dated activity. No official score or qualification is claimed. The read-only Find/Compare/Verify/Changes dashboard works with saved output and has desktop/mobile owner acceptance; launch it with `run_signalpost_web.py --data output.jsonl --host 127.0.0.1 --port 8000` using the installed interpreter.

Parser/handoff clarification requested: Will Builderr run our declared command and consume its documented six-state claim/evidence envelope, or require the runnable starter's `--organisations/--bulk` flags and `state/modules/profile` output? Please provide the accepted parser/schema and the batch, frozen-registry metadata/rights, cutoff, resource-budget and prior-state handoff. The published prose, starter example and executable terminal format differ; no unpublished schema compatibility is claimed.

Package contents and reproducibility: `submission/ARTIFACTS.md`, `submission/README.md`, `submission/DRY_RUN.md`. Exact-SHA CI: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions (select the run whose head SHA is PACKAGE_SHA).

This draft has not been sent. The owner must authorize access/publication and external submission separately.

## Latest validation disclosure for owner review

The final package pins patched pypdf 6.19.0 and urllib3 2.8.0. Production Python and the accepted UI are preserved. A separately authorized three-company live experiment used 15/60 physical attempts, returned three envelopes and 264 source-supported registry claims, but added no website/jobs/news coverage. Wikidata discovery was refused by its robots policy; the experimental adapter is not in this submission. Do not describe this as a fresh 100-company smoke or improved external recall. Use the final handoff SHA/CI and [current report](../docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md). Repository access/public-artifact acceptance and parser/handoff clarification remain pending.
