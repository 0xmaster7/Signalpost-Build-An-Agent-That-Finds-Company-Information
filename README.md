# Signalpost

Norwegian company research from an organisation number, returned as evidence-backed JSONL.
**Status:** revision 2 of 5 over submitted v1 `a9d0bc8` is being prepared. Fresh 1,000-company verification failed on disk exhaustion; automatic retained-folder refresh fails; private-parser acceptance is unconfirmed.

## Quick start
- CPython 3.12+ (3.12 recommended); Linux/glibc or macOS, x86_64/arm64.
- Git, curl and outbound HTTPS; no paid API key, Docker or Tesseract.
- Supply `companies.jsonl` with one organisation number per line.

```sh
git clone https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information.git
cd Signalpost-Build-An-Agent-That-Finds-Company-Information
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

Clone/enter the repo; setup installs locked dependencies locally and checks PDF/OCR.
`run.sh` installs nothing. Results: `output.jsonl`; stdout: batch report; stderr: diagnostics.
Measured runtimes: 10 companies about 17 s; 1,000 about 28 minutes on dated runtimes in [RESULTS.md](RESULTS.md), not a guarantee.

## Input and output
```jsonl
{"organisation_number":"923609016"}
{"organisation_number":"976390512"}
```

Trimmed projection (not a standalone valid envelope):
```json
{
  "organisation_number": "923609016",
  "state": "complete",
  "terminal_state": "available",
  "claims": [],
  "evidence": [],
  "changes": []
}
```

Actual rows include run, operations, seven sections, claims and source snapshots.
Unknown/incomplete research is never fabricated as zero. Legacy `state` differs from public `terminal_state`; see [contract check](docs/OUTPUT_CONTRACT_CHECK.md).

## Test it locally
Use a 10-row `companies.jsonl` for the smoke command; run from the repo root:
```sh
./run.sh --input companies.jsonl --output output.jsonl
(cd signalpost-starter-kit && ../.signalpost-tools/bin/uv sync --frozen --extra m08-test && ../.signalpost-tools/bin/uv pip install --python .venv/bin/python pytest==9.1.1 && PYTHONPATH=.. .venv/bin/python -m pytest -q)
PYTHONPATH=signalpost-starter-kit/src signalpost-starter-kit/.venv/bin/python -c 'import json; from norway_company_agent.batch import validate_envelopes; r=validate_envelopes([json.loads(x) for x in open("output.jsonl")],10); print(json.dumps(r,sort_keys=True)); assert r["passed"]'
./run.sh --input signalpost-starter-kit/tests/fixtures/m01/offline-batch.jsonl --registry-snapshot signalpost-starter-kit/tests/fixtures/m01/registry.jsonl --output /tmp/signalpost-demo.jsonl --state-output /tmp/signalpost-demo-state.json
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost_web.py --data /tmp/signalpost-demo.jsonl --host 127.0.0.1 --port 8000
```

Dashboard: http://127.0.0.1:8000 (saved data only). Offline fixtures are fictional.
The unchanged starter checks count/states, not the full private schema. Full suite: **1,358 tests + 252 subtests passed** against fresh-clone source using the prior pinned test venv; fresh test installation also verified separately. [Verification scope](RESULTS.md).

## Budget and settings
| Setting | Behavior |
| --- | --- |
| `SIGNALPOST_TIME_BUDGET_SECONDS` | Total seconds when CLI override absent |
| `--budget-seconds N` | Highest-precedence total-budget override |
| Default | 1.8 s/input including reserve; 1,800 s for 1,000 |
| `--output-first` | Live CLI default: complete JSONL before secondary state/recording |

Official allowance: **45 minutes and 2,000 requests per 100 companies (20/company)**.
Project defaults are shorter. Earlier gateway averages: **35/10 = 3.50**, **584/200 = 2.92** physical requests/input, including shared traffic. Failed run A has no final gateway total; its cap compliance is unverified.
Reserve: max(2 × measured preparation/flush estimate, 10% of budget). Blocked filesystem calls can overrun; no universal hard-deadline guarantee.

## Latest results
Counts: companies with supported finance / FTE / verified website / jobs claims, not scores.
| Inputs | Runtime commit | Seconds | Valid rows | Duplicate IDs | Starter | Finance / FTE / website / jobs |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 10 | `82703d3` source-equivalent | 16.87 | 10 | 0 | pass | 10 / 0 / 0 / 0 |
| 200 | `82703d3` source-equivalent | 332.41 | 200 | 0 | pass | 196 / 0 / 0 / 1 |
| 1,000 | `82703d3` FAILED | 598.86 | 1,000 snapshot | 0 | pass | 915 / 0 / 0 / 0 |

The 1,000-row snapshot is valid but **not a final output commitment**: exit 1, no state pair/aggregate. Historical `f0902cb` ran 1,000 in 1659.034 s; it lacked starter compatibility. [Results, commands and provenance](RESULTS.md).

## Known limitations
- Verified websites, jobs and explicit FTE remain sparse at scale; identity gates abstain.
- Complete primary output does not imply a committed state pair or usable refresh history.
- Retaining a folder does not auto-refresh; `--previous-state` and committed prior state are required.
- Local OCR/optional sources are time-limited; skipped research is not a zero finding.
- Private-parser acceptance, including null confidence, is unconfirmed.
- Scale measurements apply to their specific runtime and machine.

[Full limitations](LIMITATIONS.md) · [Output contract differences](docs/OUTPUT_CONTRACT_CHECK.md)

## Repo map
| Path | Purpose |
| --- | --- |
| `signalpost/` | Research, identity/evidence, adapter, history and dashboard |
| `signalpost-starter-kit/` | Starter docs, lockfile, tests and launchers |
| `docs/` | Design, provenance, audits and release reports |
| `submission/`, `site-data/` | Historical handoff and demonstration artifacts |

[Docs](docs/contract-matrix.md) · [Source rights](docs/source-rights.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Data licences](docs/data-licenses.md) · [README history, unchanged](docs/HISTORY.md)
