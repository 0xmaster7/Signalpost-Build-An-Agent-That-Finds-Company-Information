# Main consolidation and two-command workflow — 2026-10-18

## Release selection and history

- Previous GitHub default: `codex/m00-contract-audit`, `b89a0a6590dc359f4ec4549c26edf6ce1b46623f`.
- Latest completed source: `codex/m12-final-sol-remediation`, `72e8c055f4919bcc04770442fe3fc5ab22bfc003`, with [successful exact-SHA CI](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/39057803645).
- No `main` existed at inspection. All four older remote branch tips were ancestors of the selected release, with no unique commits missing from it. No working-tree changes, stash entries, unpushed release commits, or active coding processes were found before this task.
- Consolidation creates `main` at the completed release plus the narrowly scoped wrapper/documentation/test commit. No squash, reset, force push, experimental branch merge or branch deletion is needed. Both release and main retain the full existing history. The final exact commit and CI links are provided in the handoff.

## Installation and execution

```sh
./setup.sh
./run.sh --input companies.jsonl --output output.jsonl
```

Setup prefers CPython 3.12, accepts compatible CPython 3.12+, and uses a checksum-pinned upstream uv 0.8.0 binary. Its tools, cache, temporary files and virtual environment stay in the checkout. It uses the existing frozen production lock, checks imports and bundled OCR model initialization, and writes a lock/project fingerprint only after success. It does not install Python or system packages, change shell configuration, use sudo, or require Tesseract/credentials/paid services.

Execution verifies that setup completed for the current lock/project metadata, then directly execs the existing evaluator with safely forwarded arguments and preserved streams/exit code. Default execution enables `--live-brreg --live-websites`, including the existing official PDF and local OCR path. There is no package manager, download or implicit setup in run.sh. An explicit registry snapshot preserves canonical offline semantics; callers can explicitly combine it with the existing live flags. Relative user paths retain their current-working-directory meaning.

All research code, validation, financial/workforce extraction, UI, evaluator, dependency lock and source policies are unchanged from the selected release. Only root wrappers, their focused tests/CI checks, primary instructions and third-party bootstrap attribution are added/updated.

## Completed local verification

- Fresh clone from the public GitHub release branch without credential helpers, overlaid with the exact wrapper changes: first setup succeeded using CPython 3.12.3 and project-local uv 0.8.0.
- Repeated setup succeeded. All installed production distribution versions matched the existing lock. Existing globally available uv 0.13.1 was not used as the pinned installer.
- Clean-environment synthetic PDF rendered through PDFium and was read as `SIGNALPOST2025` by bundled RapidOCR. No Tesseract call or system installation occurred.
- A previously downloaded official PDF was processed in the new environment with zero HTTP requests, reproducing FOLK OG FE's known revenue, operating result, annual result and FTE. This was a saved-source installation regression, not new live coverage.
- Actual wrapper execution from an unrelated directory with spaces in output paths produced all four fixture terminal envelopes and a paired publication marker. Missing input returned nonzero. Installer/Tesseract executables were blocked throughout the workflow verification; none were invoked.
- Wrapper unit checks cover default live flags, literal argument forwarding, stdout/stderr and exit-code preservation, explicit snapshots, missing/stale environments and no installer entrypoint.
- Relevant existing/new tests: **77 passed, 26 subtests passed**. Full exact-commit GitHub Actions remains the final release gate.
- Missing/invalid Python selection fails with an explicit prerequisite message. No new live company benchmark was launched.

## Public release checks and remaining limits

The bounded tracked-tree credential-pattern/path scan found no private keys, recognized credential strings or tracked private runtime directories. New wrappers contain no credentials; tools/environments/caches stay ignored. This reuses recent trusted release evidence and does not claim a new exhaustive audit of every historical blob.

Existing source/data attribution and PDF/OCR notices are preserved. uv's upstream MIT/Apache-2.0 attribution is added; its downloaded executable is not vendored. The owner has not declared a licence for Signalpost's own code; this task does not invent that grant. Official organizer parser/resource/cutoff details and actual submission remain owner handoff items. No repository visibility change, organizer email or Builderr submission is performed.
