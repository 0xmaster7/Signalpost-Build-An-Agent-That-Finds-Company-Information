#!/bin/sh
# No package manager, downloads or implicit setup in this execution path.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON="$ROOT/signalpost-starter-kit/.venv/bin/python"
STAMP="$ROOT/signalpost-starter-kit/.venv/.signalpost-ready.json"
missing() { printf 'Signalpost: environment missing or out of date. Run "%s/setup.sh" first.\n' "$ROOT" >&2; exit 2; }
[ -x "$PYTHON" ] && [ -f "$STAMP" ] || missing
if ! "$PYTHON" -I - "$ROOT" "$STAMP" <<'PY'
import hashlib, json, pathlib, sys
try:
    root = pathlib.Path(sys.argv[1])
    stamp = json.loads(pathlib.Path(sys.argv[2]).read_text())
    valid = all(stamp.get(name) == hashlib.sha256((root / "signalpost-starter-kit" / name).read_bytes()).hexdigest()
                for name in ("uv.lock", "pyproject.toml"))
except (OSError, ValueError):
    valid = False
sys.exit(0 if valid else 1)
PY
then
    missing
fi

# An explicit snapshot preserves the canonical CLI's offline mode. Add the live
# flags explicitly when combining a supplied snapshot with online research.
snapshot=false
for argument in "$@"; do
    case "$argument" in --registry-snapshot|--registry-snapshot=*) snapshot=true ;; esac
done
if [ "$snapshot" = true ]; then
    exec "$PYTHON" "$ROOT/signalpost-starter-kit/run_signalpost.py" "$@"
fi
exec "$PYTHON" "$ROOT/signalpost-starter-kit/run_signalpost.py" --live-brreg --live-websites "$@"
