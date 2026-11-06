# Submission email draft — NOT SENT / ACCEPTANCE FAILED

Bounded-run remediation uses `SIGNALPOST_TIME_BUDGET_SECONDS=1800` for1000inputs,15%finalization reserve. Replacement safety is **unproven until the authorized live1000 run and exact replay pass**. Contact/recipient and `[JBOX_SITE_URL]` remain owner placeholders. This draft must not be sent automatically.

Do not send automatically. The candidate is **not submission-ready**: live scale timed out and coverage gates failed. Owner must explicitly decide next steps. Replace owner/recipient/JBOX fields only with authorized details. Exact package SHA must be obtained from the checked-out commit; the measured implementation below is not presented as a successful final release.

To: [VERIFIED_SUBMISSION_RECIPIENT]
Subject: Signalpost — measured candidate, acceptance gates not met — [PACKAGE_COMMIT_SHA]

Agent: Signalpost
Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information
Exact package commit: [PACKAGE_COMMIT_SHA]
Measured implementation: 676d6e513b70c0e3cbf8e884602ad7e5674d5df9
Smoke/acceptance report: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/blob/main/docs/release/FINAL_RESULTS_2026-11-06.md
Contact: [AUTHORIZED_CONTACT_NAME] <[AUTHORIZED_CONTACT_EMAIL]>
JBOX: [JBOX_SITE_URL]

From a fresh clone with CPython3.12+, curl and outbound HTTPS:

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

Setup installs locked production dependencies. Run performs no installation and enables live BRREG, structured financials, PDF/local OCR, NAV and permitted website research. JSONL profiles go to the output file; stdout is a separate aggregate. `--budget-seconds` overrides `SIGNALPOST_BUDGET_SECONDS`, then config; default1800 seconds. Explicit totals reserve min(300s,20%) within the total. **Measured scale exceeded the internal deadline and did not finalize.**

Matched/fresh each finalized100/100 and replayed identical output/state bytes: finance98/93, FTE18/19, verified websites0/1, jobs3/2, runtime1595/1584 seconds, zero duplicate IDs. The1000-company operational run was externally terminated at2100 seconds:1000 partial rows survived, but no final state pair/aggregate or complete phase metrics. FTE, website, fresh-finance,20-minute and scale-completion gates failed. No official score, qualification, coverage improvement or full-field accuracy is claimed.

No LLM/paid API/personal key is required. Local models: RapidOCR1.4.4 bundled PP-OCR ONNX assets (existing Apache2 notices), ONNX Runtime1.31.0(MIT), pypdfium2 4.30.0 with PDFium third-party notices. Sources: BRREG, NAV, candidate-only Wikidata and rights-permitted company websites. Component hashes/rights/limits are documented in the package and notices; no new project-code license grant is made.

API billing is assumed $0, not measured billing. VM/OCR CPU, RAM, disk, network, install and hosting costs are not priced. Two-core/7.7GB Linux host; the scale attempt consumed35 minutes without clean completion, so successful official-batch cost is unproven.

Raw captures, credentials, PDFs and private checkpoints are not public. Public site-data is a saved demonstration, not precomputed evaluator input. Official parser/resources and a deployed JBOX site remain unverified.

[AUTHORIZED_CONTACT_NAME]

**Unsent draft.** Task deadline7November2026 18:00IST; no organizer extension is independently established.
