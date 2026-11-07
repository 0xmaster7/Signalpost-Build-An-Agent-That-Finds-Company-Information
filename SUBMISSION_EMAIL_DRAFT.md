# Revision 2 submission email draft — not sent

Revision 1 `a9d0bc8` is already on record. This draft proposes revision 2 of 5, not a first submission. Soham confirmed up to four revisions through 7 November 2026, 23:59 IST; each applies to later runs. This draft has not been sent.

To: [VERIFIED_SUBMISSION_RECIPIENT]
Subject: Signalpost — revision 2 of 5 — runtime 82703d3

Hello Soham,

Please use this revision for later runs of our existing Signalpost submission.

- Agent: Signalpost
- Repository: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information
- Frozen runtime: `82703d348e894ed68bf9873404a7900886440398`
- Documentation/package commit: use the exact final hash accompanying this draft
- Previous submission: `a9d0bc8` (version 1); this is proposed revision 2 of 5
- Measurement report: https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/blob/main/RESULTS.md
- Contact: [AUTHORIZED_CONTACT_NAME] <[AUTHORIZED_CONTACT_EMAIL]>
- JBOX: [JBOX_SITE_URL]

Fresh checkout, CPython 3.12+, curl and outbound HTTPS:

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

Setup installs pinned dependencies; run installs nothing. The project default is 1.8 seconds/input (1,800 seconds for 1,000), shorter than the confirmed official 45-minute / 2,000-request allowance per 100 companies. Output JSONL is primary; exit zero does not promise complete optional research or paired state.

Source-equivalent 10/200 runs returned 10/200 valid rows, zero duplicate claim IDs, and passed the unchanged starter validator in 16.87/332.41 seconds. Counts (finance/FTE/verified website/jobs): 10/0/0/0 and 196/0/0/1. The fresh exact-runtime default-budget 1,000-company run FAILED on disk exhaustion: exit1 at598.86seconds. Its surviving snapshot has1,000 valid rows, zero duplicates, starter-validator pass and counts915/0/0/0, but no final output commitment, state pair or aggregate. Total gateway requests are unavailable. No retry, coverage improvement or official score is claimed.

The organizer-style repeated command does not automatically load retained state: the second10-company run reports baseline_no_prior_state. Earlier evidence IDs reappear for unchanged sources, but original evidence records are not retained. Refresh needs an explicit --previous-state argument and a committed prior canonical state, so the requested no-extra-flags refresh flow is not satisfied.

The unchanged starter's legacy state vocabulary differs from the public example; private-parser acceptance, including null confidence/spans, remains unconfirmed. Complete primary output does not establish committed canonical state, preserved refresh evidence or sealed live replay. See docs/OUTPUT_CONTRACT_CHECK.md and LIMITATIONS.md.

No LLM, paid API or personal key is required. Local models/components: RapidOCR 1.4.4 bundled PP-OCR ONNX assets (existing Apache 2 notices), ONNX Runtime 1.31.0 (MIT), pypdfium2 4.30.0/PDFium notices. Sources: BRREG/NLOD 2, NAV-specific terms, candidate-only Wikidata/CC0 and permitted company pages. Source-rights and third-party notices apply; no new repository-code licence grant is made.

Expected public API charges: $0 per official batch under the documented configuration, an assumption rather than measured billing. Compute, disk, network and hosting are unpriced. Raw captures, tokens, PDFs and private checkpoints are not published.

Regards,
[AUTHORIZED_CONTACT_NAME]

This revision email remains a draft; revision 1 was already submitted.
