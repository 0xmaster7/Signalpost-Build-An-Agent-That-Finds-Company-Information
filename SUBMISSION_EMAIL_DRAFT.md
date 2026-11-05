# Submission email draft — NOT SENT

Owner review only. Do not send or submit this file automatically. Replace every bracketed placeholder, verify the intended recipient and reviewer access, and attach the actual final-source report before sending. The task deadline is **7 November 2026, 18:00 IST (12:30 UTC)**; an organizer extension has not been verified here.

To: [VERIFIED_SUBMISSION_RECIPIENT]
Subject: Signalpost — company information agent — [FINAL_COMMIT_SHA]

Agent name: Signalpost
Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information
Final commit: [FINAL_COMMIT_SHA]
Smoke/acceptance report: [FINAL_REPORT_URL_OR_PATH]
Contact: [AUTHORIZED_CONTACT_NAME] <[AUTHORIZED_CONTACT_EMAIL]>
JBOX site: [JBOX_SITE_URL]

Please review Signalpost at the exact commit above. Reviewer repository access and any public artifact must be verified before this draft is sent.

From the repository root, with CPython 3.12+ and outbound HTTPS available:

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

The requested JSONL file contains the ordered company profiles; stdout is a separate machine-readable batch report and stderr contains diagnostics. The intended contract is one terminal envelope per input row, including failures and duplicates. Official parser compatibility remains to be confirmed.

The total-budget interface is `--budget-seconds` / `SIGNALPOST_BUDGET_SECONDS`, with a conservative default of 1,800 seconds including finalization. [PARENT: CONFIRM INTEGRATION, PRECEDENCE, FINAL RESERVE AND VALIDATION; REMOVE THIS NOTE ONLY AFTER VERIFICATION.] Baseline configuration reserves 300 seconds; the reserve must fit inside the total rather than extend it.

No LLM, paid API or personal API key is required. Local OCR uses locked RapidOCR 1.4.4 and ONNX Runtime 1.31.0 with PDFium via pypdfium2 4.30.0. Existing notices identify the bundled PP-OCR assets as Apache-2.0; [PARENT: VERIFY INSTALLED MODEL ASSETS/HASHES/NOTICES]. Sources include BRREG records and official filing copies, NAV public vacancy metadata, bounded company websites and candidate-only Wikidata SPARQL. Source-specific rights, dependency declarations and model verification limits are recorded in `docs/release/SUBMISSION_PACKAGE_2026-11-05.md`, `docs/source-rights.md` and `THIRD_PARTY_NOTICES.md`. No new project-code license grant is made.

API billing is assumed to be $0 under the public-source/local-inference configuration; this is not measured billing. CPU/OCR, RAM, disk, network, installation and hosting have resource costs and are not priced here. [PARENT: INSERT ACTUAL FINAL-SOURCE RUNTIME/RESOURCE RESULTS OR STATE NOT MEASURED.] No paid service is necessary to reproduce the declared workflow.

Coverage is limited. The supplied working baseline is roughly 23–29 FTE-covered companies and zero verified websites; [PARENT: ATTACH EXACT COHORT, DENOMINATOR, SOURCE AND REPORT]. New coverage is unproven pending the final run. Prior aborted runs do not establish optional coverage. Clean-machine setup, fresh final-source 100-company acceptance and 1,000-company scale checks remain pending unless the report above explicitly records their outcomes. No score or qualification is claimed.

URL/DNS and redirect checks, host/path restrictions, bounded requests and robots/source policy govern acquisition. Raw captures, tokens and private checkpoints are excluded from the public artifact. No precomputed company corpus is proposed as scoring input. See `LIMITATIONS.md` for remaining rights, security, coverage and parser gaps.

[AUTHORIZED_CONTACT_NAME]

This is an **unsent draft**, not a record of submission.
