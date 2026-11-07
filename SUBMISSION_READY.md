# Submission status — 7 November 2026

**Revision 2 of 5 is being prepared for the existing submission.** Candidate runtime: `82703d348e894ed68bf9873404a7900886440398`. The already-submitted revision is `a9d0bc8`; this candidate is a later revision, not a first submission. Organizer Soham confirmed that up to four revisions may be made through 7 November, 23:59 IST, and that revisions apply to later runs. The submitted revision and revision allowance are organizer-confirmed; this document does not claim that revision 2 has already been sent.

## Official limits and compatibility

The official limits are 45 minutes and 2,000 requests per 100 companies (20 requests per company). The existing 10-company and 200-company compatibility runs are proven source-equivalent. The fresh exact-runtime 1,000-company snapshot also passes the unchanged starter validator, but the process failed before committing final output/state. This is not a clean scale-completion pass or proof of private-parser acceptance.

## Measurement state

**Run A FAILED:** exit1 at598.86seconds, disk exhaustion during periodic atomic output preparation. A valid 1,000-row snapshot survives (zero duplicate IDs; counts finance915/FTE0/verified websites0/jobs0), but its marker is partial, the canonical state pair and final aggregate are absent, and total gateway requests cannot be recovered. No retry was made. See [RESULTS.md](RESULTS.md).

**Organizer-style refresh FAILED:** repeating the default command while retaining the folder starts `baseline_no_prior_state`; it does not automatically reuse prior state. Earlier evidence IDs reappear, but none of the 1,174 earlier evidence records survive byte-for-byte. Explicit `--previous-state` plus a committed canonical prior state is required; the organizer's no-extra-flags flow does not provide it. No behavior fix was authorized.

Do not describe the revision as fully accepted, refresh-qualified, or a verified clean scale replacement. The original runtime remains unchanged; only documentation is revised. Official parser acceptance and exact final-commit CI are separate checks, not implied by row validity.

## Submission handling

The email text in [SUBMISSION_EMAIL_DRAFT.md](SUBMISSION_EMAIL_DRAFT.md) is a draft and remains unsent. Revision 1 (`a9d0bc8`) was already submitted; revision 2 remains in preparation.
