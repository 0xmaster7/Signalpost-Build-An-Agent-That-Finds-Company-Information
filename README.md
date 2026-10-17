# Signalpost

Signalpost researches Norwegian companies by organisation number and returns ordered, evidence-backed JSONL profiles. Its read-only dashboard lets users find saved companies, compare facts, verify propositions and inspect sources and history.

**Status:** the accepted UI and tested backend are preserved. Website, jobs, news and numeric-financial coverage remain weak. The [current acceptance report](docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md) records official requirements, provider decisions, a new three-company experiment and remaining blockers. The repository remains PRIVATE. No official score, qualification or submission is claimed.

## Install

Requires Git, **Python 3.12** (tested) and **uv 0.8.0**. Dependencies are pinned in [uv.lock](signalpost-starter-kit/uv.lock). No personal API key, model, database server or paid service is required.

~~~sh
git clone --branch codex/m12-final-sol-remediation https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information.git
cd Signalpost-Build-An-Agent-That-Finds-Company-Information
# Pin the exact package SHA from the final handoff.
cd signalpost-starter-kit
uv sync --frozen --extra m08-test
cd ..
~~~

Private clone access is required. GitHub's default branch is older; use the branch above and an immutable SHA. The [submission guide](submission/README.md) includes the tested uv bootstrap.

## One evaluator command

After installation, from the repository root:

~~~sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py --input companies.jsonl --output output.jsonl --state-output state.json --checkpoint checkpoint.sqlite --live-brreg --live-websites
~~~

This makes external requests and accepts unseen runtime IDs without a precomputed manifest. Local testing requires its own request authorization; completed test budgets are not ongoing allowances.

Input:

~~~json
{"organisation_number":"923609016"}
{"organisation_number":"976390512"}
~~~

JSONL, JSON, CSV, TSV and plain-number inputs are supported. IDs remain strings. Each row receives one terminal JSONL result in input order, including duplicates, invalid IDs and unavailable companies. Malformed files fail before acquisition with a nonzero exit code. **Profiles are in the output file:** stdout carries a separate machine-readable batch report; stderr carries diagnostics.

The [repository output contract](signalpost/adapter.py) contains input_ref, organisation_number, terminal_state, seven sections, claims, evidence, source_snapshots, refresh, synthesis, errors, operations, run and batch. States are available, not_available, blocked, not_applicable, ambiguous and failed. Missing values are never zero.

Builderr confirms these semantic requirements, but the runnable starter emits a different structure from both our output and its own example. **Official parser compatibility remains unverified.** Its parser, frozen-registry handoff and numeric resource limits need [clarification](docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md#organizer-clarification).

## Architecture and information

Input → ordered batch/checkpoints → BRREG identity/records → bounded website verification → extraction → publication validation → evaluator/state pair.

| Production layer | Responsibility |
|---|---|
| [run](signalpost/run.py), [operations](signalpost/operations.py) | Runtime input, budgets, concurrency, checkpoint/resume and terminal cardinality |
| [BRREG](signalpost/brreg.py) | Exact identity, registered activity/purpose, filings, official roles and workplaces |
| [gateway](signalpost/network.py) | Physical accounting, pacing, public-IP and redirect checks, robots and response bounds |
| [websites](signalpost/websites.py) | Candidate verification, permitted pages, linked profiles, structured jobs and dated activity |
| [models](signalpost/models.py), [adapter](signalpost/adapter.py) | Claim/evidence/snapshot integrity and deterministic publication |
| [history](signalpost/history.py), [synthesis](signalpost/synthesis.py) | Prior evidence, material changes and supported deterministic summaries |
| [web app](signalpost/web.py) | Server-rendered saved-data Find, Profile, Compare, Verify and Changes |

Seven sections cover identity/brand, accounts/history, leadership/workplaces, websites/owned profiles, hiring/activity, evidence/states, and refresh/changes. A present section does not mean every field is available.

Website publication requires direct company ownership or permitted page-representation proof. Mentions/search results do not establish ownership; group and page-only scope remain separate. Hiring needs an actual employer-bound posting; activity needs a supported subject and date. Registered activity is not dated news.

Financial figures require authoritative period, currency, scope and **unit/scale** proof. Saved live accounts lack scale proof, so those numbers remain withheld. Currency alone does not prove NOK versus NOK-thousands.

## Refresh and operation

For a new observation, use new output/state/checkpoint paths and add --previous-state state.json. Preserve the state/output pair and adjacent .publication.json marker. Failed sources preserve prior supported facts and expose failure. Identical snapshots produce no false changes. Growing/subset batches retain compatible history; checkpoint resume requires identical input and configuration.

To resume interruption, repeat the original command with --resume. Refresh and unfinished resume can make external requests.

Use --config for supplied resource limits. Project defaults are 1,800 s hard / 1,350 s soft / 300 s completion reserve, 12*N+1000 physical attempts and $0 paid cost. These are **not published organizer limits**.

Default evidence cutoff is run start. Later observations without an established effective date can be withheld, including workplaces. Use --evidence-cutoff only with the organizer's actual authorized timestamp; never invent a future cutoff. A supplied registry uses --registry-snapshot, --registry-snapshot-as-of and --registry-source-url with real provenance and rights.

## Offline demo and UI

The bundled fixture is fictional and includes duplicate input. It demonstrates execution, not live coverage.

~~~sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py --input signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl --registry-snapshot signalpost-starter-kit/tests/fixtures/m01/registry.jsonl --output /tmp/signalpost-output.jsonl --state-output /tmp/signalpost-state.json
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost_web.py --data /tmp/signalpost-output.jsonl --host 127.0.0.1 --port 8000
~~~

Open http://127.0.0.1:8000. Find an ID, inspect its profile and evidence, compare companies, verify a legal-name proposition and inspect Changes. Load actual CLI output for real research. The dashboard performs no live acquisition. [Accepted UI evidence](docs/ui-ux-acceptance-20261017/REPORT.md) covers desktop/mobile.

## Sources, rights, costs and limits

Official BRREG entity/accounts/roles/subunit APIs provide the foundation, with NLOD attribution and privacy exclusions. Websites use bounded transient factual extraction subject to site terms, robots and ownership proof.

No paid model/API, external search/news provider, ATS integration, platform scraper, PDF acquisition or browser-rendering service is enabled. [Free-provider decisions](docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md#free-provider-decisions) explain why the experimental Wikidata adapter was rejected and excluded.

API/model cost is **$0** under the frozen configuration for 100, 1,000 or 1,100 inputs. Runner VM, bandwidth and installation infrastructure are not priced here. Full-scale live runtime is unproven. Website reach, jobs/news and financial values remain major scoring gaps; offline scale throughput is not factual accuracy or competition recall.

See [source rights](docs/source-rights.md), [source policy](config/source_policy.yaml), [data licences](docs/data-licenses.md) and [third-party notices](THIRD_PARTY_NOTICES.md). No licence grant for this repository's own code is implied; that decision remains with the owner. No research credentials are required.

## Tests and submission evidence

~~~sh
cd signalpost-starter-kit
uv pip install --python .venv/bin/python pytest==9.1.1
PYTHONPATH=.. .venv/bin/python -m pytest -q
PYTHONPATH=.. .venv/bin/python scripts/validate_signalpost_functionality.py --output-dir /tmp/signalpost-acceptance
~~~

CI also runs identity/ownership, M06 scale/provenance, M07 refresh, M08 gold/synthesis, M09 source/failure/resume, cardinality, clean-directory launch and UI/XSS checks.

The self-contained [100-company smoke report](submission/HISTORICAL_100_COMPANY_SMOKE.md) identifies its historical source SHA and conditions. Unavailable raw VM files are not required to read it; it is not a fresh 100-company test of this source. [20-company replay](docs/release/MAXIMUM_VERIFIED_COVERAGE_2026-10-17.md) and the latest three-company experiment are separate evidence.

[Submission guide](submission/README.md) · [Artifacts](submission/ARTIFACTS.md) · [Unsent draft](submission/DRAFT_SUBMISSION.md) · [Current acceptance](docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md)

External handoff remains on hold for verified organizer access/public-artifact arrangements, parser/handoff clarification and owner contact details. Nothing has been submitted.
