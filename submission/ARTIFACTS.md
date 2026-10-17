# Submission artifact index

This index is part of the repository. Clone the exact package SHA from the owner handoff, not the default branch. No item below requires private Azure files to read or run the offline demonstration.

| Required item | Repository artifact | Status |
|---|---|---|
| Agent code and runnable command | `signalpost/`, `signalpost-starter-kit/run_signalpost.py`, [run guide](README.md#exact-evaluator-command) | Present; organizer supplies actual company batch, snapshot/cutoff and budget |
| Pinned clean installation | `signalpost-starter-kit/pyproject.toml`, `uv.lock`, [setup](README.md#fresh-setup-linuxmacos-python-312) | Python 3.12 tested; uv 0.8.0; no hidden runtime credentials |
| Input/output examples | [offline command](../README.md#install-and-run), `signalpost-starter-kit/tests/fixtures/m01/`, [actual starter/production outputs](../docs/final-evaluator-acceptance-20261017/) | Fictional offline fixtures; not precomputed official results |
| 100-company smoke result OR report | [historical index](HISTORICAL_100_COMPANY_SMOKE.md), [complete accepted report](../docs/release/M12_POST_REPAIR_LIVE_ACCEPTANCE_2026-10-10.md) | Present, self-contained report of older SHA; raw bundle unavailable, not a fresh final-SHA cohort |
| Refresh/resume and growing-batch behavior | [run guide](README.md#budget-cutoff-refresh-resume), [acceptance](../docs/final-evaluator-acceptance-20261017/REPORT.md), `scripts/validate_signalpost_functionality.py` and `scripts/validate_signalpost_growing_scale.py` under the starter directory | Offline repeatable process checks; preserve state/publication marker pair |
| Source rights, attribution, secrets/URL handling | [source rights](../docs/source-rights.md), [policy](../config/source_policy.yaml), [machine-readable manifest](../docs/release/source-rights-manifest.json) | No new sources; central gateway; no personal-account research credentials |
| Models, APIs, costs and limitations | [disclosures](README.md#sources-cost-and-known-limitations), [licence inventory](../docs/data-licenses.md), [notices](../THIRD_PARTY_NOTICES.md) | Models none; paid APIs none; declared third-party API/model cost $0 per official batch; infrastructure excluded |
| Code licence | [notices](../THIRD_PARTY_NOTICES.md) | Undeclared; owner decision required before any licence grant; no official requirement for a particular open-source licence found |
| UX demonstration | [launch instructions](../README.md#install-and-run), [accepted UI evidence](../docs/ui-ux-acceptance-20261017/REPORT.md) | Saved-data dashboard, desktop/mobile; optional live demo data stays on VM |
| Exact package hash and CI | `git rev-parse HEAD`, exact-SHA CI linked in final owner handoff | Do not mistake historical checkpoint hashes for final package SHA |
| Agent name/contact/submission text | [draft](DRAFT_SUBMISSION.md) | Agent name Signalpost; contact requires owner-provided details; unsent |

## Local reproduction (zero company-data requests)

After the declared installation, from any directory with an absolute checkout path:

```sh
/path/to/checkout/signalpost-starter-kit/.venv/bin/python /path/to/checkout/signalpost-starter-kit/run_signalpost.py --input /path/to/checkout/signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl --registry-snapshot /path/to/checkout/signalpost-starter-kit/tests/fixtures/m01/registry.jsonl --output /tmp/signalpost-dry-output.jsonl --state-output /tmp/signalpost-dry-state.json --checkpoint /tmp/signalpost-dry-checkpoint.sqlite
```

Use fresh output/checkpoint paths. This is one run command after installation, produces four ordered terminal JSONL rows, and uses fictional identities. Run `scripts/validate_signalpost_functionality.py --output-dir /tmp/signalpost-acceptance-new` with the same installed interpreter for independent process, malformed-input, source-failure, refresh/resume, batch-growth and HTTP checks. Controlled transport fixtures in that script make zero external requests. For the actual official run use the live command in the run guide with organizer-provided data/configuration; this dry run does not authorize running it now.

## Publication boundary

Only tracked Git files are included by a source archive (`git archive HEAD`); `.git`, ignored virtualenvs/tools, VM research bundles, tmux configuration and SSH keys are not part of that archive. Publishing GitHub also exposes reachable history and other branches, so the dry-run scan covers all locally fetched branch history, not just an archive. Pattern scans and manual artifact review found no credential/private-key payloads; this is a bounded check, not a guarantee about every deleted remote object. The repository includes public registry facts, public business role names and screenshots of such facts, plus clearly identified fictional fixtures. These are intentional research evidence, not private credentials. There is no automatic repository publication or submission action.

## Latest verification

See [final coverage/submission acceptance](../docs/release/FINAL_COVERAGE_SUBMISSION_2026-10-17.md) and its tracked receipts, 20-company funnel, new three-company result and physical ledger. No new provider was promoted. The historical 100-company report remains historical. Exact organizer parser/resource handoff and public-artifact/access acceptance remain unresolved.
