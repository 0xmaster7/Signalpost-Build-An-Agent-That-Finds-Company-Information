# Signalpost

**[Results — live evaluation and evidence](RESULTS.md)**

Signalpost researches Norwegian companies by organisation number and returns ordered, evidence-backed JSONL profiles. Its read-only dashboard lets users find saved companies, compare facts, verify propositions and inspect sources and history.

**Status:** the public `main` branch is the canonical release. The [latest measured release](docs/release/FINAL_CAPABILITY_INTEGRATION_2026-10-17.md) recovered 57 additional financial claims and registered workplace locations for 6/6 previously unseen companies. Website, jobs and news coverage remain limited. No official Builderr score or submission is claimed.

**Current review (26 October 2026):** [audit, reference comparison and fixes](docs/release/CURRENT_AUDIT_2026-10-26.md). Additional explicit FTE statement formats, corrected million-scale parsing and bounded OCR queue time are covered by offline regressions. The measured live results above have not been rerun; external coverage remains limited.

**Discovery update:** [independent NAV jobs and registry URL-only references](docs/release/PUBLIC_DISCOVERY_2026-10-26.md) no longer require website ownership to publish those specific facts. NAV coverage is a bounded partial scan, not proof of zero jobs. Batch Wikidata candidate discovery is implemented but currently blocked by the endpoint's robots policy; no access bypass or improved cohort coverage is claimed.

## Install and run: two commands

Clone this public repository and enter its directory, then run:

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

Prerequisites: **CPython 3.12+** (3.12 recommended), Linux with glibc or macOS on x86_64/arm64, and `curl` for the first setup. Setup downloads checksum-verified **uv 0.8.0**, creates `signalpost-starter-kit/.venv`, installs production dependencies from [uv.lock](signalpost-starter-kit/uv.lock), and checks the local PDF/OCR modules. Tools, caches and temporary installation files stay inside the checkout. Setup is safe to rerun; it does not install Python, modify shell profiles, use sudo or require Tesseract, Docker, API keys or paid services. Outbound HTTPS is needed for installation and live research. Set `SIGNALPOST_PYTHON=/path/to/python3.12` during setup if interpreter selection needs an override.

`run.sh` performs **no installation**. By default it enables the real production evaluator's **live BRREG, official annual-account PDF/local OCR, independent NAV jobs, and permitted website research** paths. NAV and batch candidate discovery share the existing gateway, budgets and completion reserve; current public feeds are not used to reconstruct an explicit historical cutoff. Arguments and exit codes are preserved; relative input/output paths resolve from your current directory. From another directory, use `/absolute/path/to/checkout/run.sh ...`.

The input contains company organisation numbers. The output is ordered JSONL with one terminal profile per input row; stdout is a separate machine-readable batch report and stderr contains diagnostics. State/checkpoint paths can be supplied with `--state-output` and `--checkpoint`. Current research limits and source/identity safeguards still apply.

An explicit `--registry-snapshot PATH` preserves the canonical CLI's offline mode unless you also supply `--live-brreg --live-websites`. For advanced direct Python, refresh, resume, configuration and dashboard commands, see the [submission guide](submission/README.md). The underlying production launcher remains `signalpost-starter-kit/run_signalpost.py`.

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
| [NAV](signalpost/nav.py), [batch discovery](signalpost/public_discovery.py) | Exact-employer jobs without websites; candidate-only batch discovery with access-policy gates |
| [models](signalpost/models.py), [adapter](signalpost/adapter.py) | Claim/evidence/snapshot integrity and deterministic publication |
| [history](signalpost/history.py), [synthesis](signalpost/synthesis.py) | Prior evidence, material changes and supported deterministic summaries |
| [web app](signalpost/web.py) | Server-rendered saved-data Find, Profile, Compare, Verify and Changes |

Seven sections cover identity/brand, accounts/history, leadership/workplaces, websites/owned profiles, hiring/activity, evidence/states, and refresh/changes. A present section does not mean every field is available.

Verified website/content publication requires direct company ownership or permitted page-representation proof. `registry_declared_website_url` and `shared_website` are separate registry references, never verified ownership or content. Mentions/search results do not establish ownership; group and page-only scope remain separate. Hiring needs an actual employer-bound posting; activity needs a supported subject and date. Registered activity is not dated news.

Financial figures require exact-entity period, currency, scope and **unit/scale** proof. Official annual-account PDF rows are reconciled with BRREG JSON; each supported value publishes independently, while ambiguous values remain withheld. Currency alone does not prove NOK versus NOK-thousands.

## Refresh and operation

For a new observation, use new output/state/checkpoint paths and add --previous-state state.json. Preserve the state/output pair and adjacent .publication.json marker. Failed sources preserve prior supported facts and expose failure. Identical snapshots produce no false changes. Growing/subset batches retain compatible history; checkpoint resume requires identical input and configuration.

To resume interruption, repeat the original command with --resume. Refresh and unfinished resume can make external requests.

Use --config for supplied resource limits. Project defaults are 1,800 s hard / 1,350 s soft / 300 s completion reserve, 12*N+1000 physical attempts and $0 paid cost. These are **not published organizer limits**.

Default evidence cutoff is run start. Current registered identity/workplace observations are supported in default live mode; an explicit historical cutoff strictly excludes later observations. Use --evidence-cutoff only with the organizer's actual authorized timestamp; never invent a future cutoff. A supplied registry uses --registry-snapshot, --registry-snapshot-as-of and --registry-source-url with real provenance and rights.

## Offline demo and UI

The bundled fixture is fictional and includes duplicate input. It demonstrates execution, not live coverage.

~~~sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py --input signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl --registry-snapshot signalpost-starter-kit/tests/fixtures/m01/registry.jsonl --output /tmp/signalpost-output.jsonl --state-output /tmp/signalpost-state.json
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost_web.py --data /tmp/signalpost-output.jsonl --host 127.0.0.1 --port 8000
~~~

Open http://127.0.0.1:8000. Find an ID, inspect its profile and evidence, compare companies, verify a legal-name proposition and inspect Changes. Load actual CLI output for real research. The dashboard performs no live acquisition. [Accepted UI evidence](docs/ui-ux-acceptance-20261017/REPORT.md) covers desktop/mobile.

## Sources, rights, costs and limits

Official BRREG entity/accounts/roles/subunit APIs provide the foundation, with NLOD attribution and privacy exclusions. Websites use bounded transient factual extraction subject to site terms, robots and ownership proof.

Official annual-account PDF acquisition and local OCR are enabled. No paid model/API, external search/news provider, ATS integration, platform scraper or browser-rendering service is enabled. [Free-provider decisions](docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md#free-provider-decisions) explain why the experimental Wikidata adapter was rejected and excluded.

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
