# M09 live smoke: website claim ID collision

This is the final host-context 100-company cohort authorized for this continuation. It failed during final synthesis and is not a release pass. No later live cohort is authorized by the current request.

- Branch: `codex/m00-contract-audit`
- Smoke source SHA: `704f83e7279a55a251a6668fa3c9c3a426a5b669` (clean)
- Fixed input: `signalpost-starter-kit/tests/fixtures/m02/foundation-input.jsonl`
- Input SHA-256: `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`
- Configuration SHA-256: `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b35b20966310d1d`
- Failure: `ValueError: synthesis sentence contains unsupported or altered factual wording`
- Failure location: `signalpost/synthesis.py:117`, while finalizing `row:11`, organisation `987709324`
- Runtime: 360.535 seconds; configured hard limit 1,800 seconds and soft deadline 1,350 seconds were not reached
- Network accounting: 470 physical requests, 496 logical requests, below the 2,200 physical-request limit
- Request ledger SHA-256: `0ce81c4d42127a15206cf2859c7929dcbbb204ece9d7db98b25ec4d78364144a`
- Checkpoint: 100 baseline envelopes saved; atomic evaluator output and final public state were not published
- Preserved run bundle: `/private/tmp/signalpost-m09-rc1-smoke.failure-artifacts`
- Failure report: `/private/tmp/signalpost-m09-rc1-smoke.json`

The ledger recorded 400 official API requests (`entity`, `accounts`, `roles`, and `subunits`: 100 each), plus 70 website-policy requests (23 robots, 33 pages, 7 sitemaps, 7 feeds). Two robots requests also went to `data.brreg.no`, for 402 physical requests to that host in total. There were 12 robots transport errors, 8 robots 200 responses, and 3 robots redirects; the failures were recorded distinctly and did not stop the official structured API path. Website and BRREG HTTP outcomes are preserved in the ledger.

## Root cause

Two different `product_or_service_heading` facts extracted from the same page received the same claim ID. `_make_claim` used only organisation, field, and page identity. The synthesis generator emitted both values, while validation resolved the shared ID to only one claim and rejected the other sentence. The checkpoint identifies the collision on row 11: `Tjenester` and `BioBank AS` shared IDs for two headings.

## Local correction

Website fact claim IDs now include a deterministic digest of the canonical value. Canonical envelopes also reject repeated claim IDs, so a future producer collision fails at the envelope boundary. A minimal two-heading regression test verifies distinct IDs and successful synthesis, and separately verifies that duplicate IDs are rejected.

The partial run is retained as a failed historical attempt. It is not counted as terminal output, identity-quality evidence, a release benchmark, or a passed smoke. No new live cohort was started after this failure.
