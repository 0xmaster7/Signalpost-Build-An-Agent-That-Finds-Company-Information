# Signalpost canonical starter environment

Use the [repository README](../README.md) and [submission/run/demo guide](../submission/README.md) for the current production commands. The audited plan and approved source contracts govern all execution.

Python 3.12 and uv 0.8.0 are tested. Install from this directory:

```sh
uv sync --frozen --extra m08-test
```

Run the canonical launcher `run_signalpost.py` for evaluator output, and `run_signalpost_web.py --data OUTPUT.jsonl` for the read-only local web application. Both support absolute paths from an unrelated current directory. Exact offline/live, previous-state, resume, cutoff and budget commands are in the submission guide. No research API credential or paid service is required.

The `scripts/` folder also retains historical experiments and the original supplied reference utilities. Those experiments are not promoted production connectors and do not grant source rights. Do not run old broad registry downloads, external search, restricted-platform, PDF, model or provider experiments as part of the current release setup. Current release evidence is under [docs/release](../docs/release).

The current deterministic replay checks 12 recorded scenarios and six material changes. It establishes regression behavior, not official qualification or real-world coverage. The canonical evaluator mapping remains provisional pending authoritative organizer field names.
