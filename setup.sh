#!/bin/sh
# Project-local bootstrap. Pinned binary digests are from the upstream 0.8.0 release:
# https://github.com/astral-sh/uv/releases/tag/0.8.0
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TOOLS="$ROOT/.signalpost-tools"
UV="$TOOLS/bin/uv"
fail() { printf 'Signalpost setup: %s\n' "$*" >&2; exit 1; }

PYTHON=''
if [ -n "${SIGNALPOST_PYTHON:-}" ]; then
    candidates="$SIGNALPOST_PYTHON"
    if "$candidates" -I -c 'import sys; assert sys.implementation.name == "cpython" and sys.version_info >= (3, 12)' 2>/dev/null; then
        PYTHON=$("$candidates" -I -c 'import sys; print(sys.executable)')
    fi
else
    for candidate in python3.12 python3.13 python3.14 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -c 'import sys; assert sys.implementation.name == "cpython" and sys.version_info >= (3, 12)' 2>/dev/null; then
            PYTHON=$("$candidate" -I -c 'import sys; print(sys.executable)')
            break
        fi
    done
fi
[ -n "$PYTHON" ] || fail 'CPython 3.12+ is required (3.12 recommended). Install a compatible interpreter, or set SIGNALPOST_PYTHON to its executable path, then rerun ./setup.sh.'
[ -f "$ROOT/signalpost-starter-kit/uv.lock" ] || fail 'uv.lock is missing; run setup from a complete checkout.'

mkdir -p "$TOOLS/bin" "$TOOLS/tmp"
export TMPDIR="$TOOLS/tmp"
export UV_CACHE_DIR="$TOOLS/cache"
export UV_PROJECT_ENVIRONMENT="$ROOT/signalpost-starter-kit/.venv"
export UV_PYTHON_DOWNLOADS=never

if [ ! -x "$UV" ] || [ "$("$UV" --version 2>/dev/null | cut -d ' ' -f 1-2)" != 'uv 0.8.0' ]; then
    case "$(uname -s)/$(uname -m)" in
        Linux/x86_64) target=x86_64-unknown-linux-gnu; digest=a7d74ee5c5ff3069b9d88236a05f293cc4e2809bad872f3a88a384489ba3675e ;;
        Linux/aarch64|Linux/arm64) target=aarch64-unknown-linux-gnu; digest=61f136a187150624c10ec7025137fdf5391ef083a4cab0eba4fbdb2a928de16b ;;
        Darwin/x86_64) target=x86_64-apple-darwin; digest=828917cad79aae8327811c59fcc625ff3861bfe21d2cbb77c206737d41117ff2 ;;
        Darwin/arm64) target=aarch64-apple-darwin; digest=5a5ca58e3999d4f440632da87a56f7030eaaa3a13d3896561eec5fd51cb9ad45 ;;
        *) fail 'Automatic uv bootstrap supports Linux (glibc) and macOS on x86_64/arm64.' ;;
    esac
    command -v curl >/dev/null 2>&1 || fail 'curl is required to download the pinned project-local uv binary.'
    download=$(mktemp -d "$TOOLS/tmp/bootstrap.XXXXXX")
    trap 'rm -rf "$download"' EXIT HUP INT TERM
    printf 'Downloading project-local uv 0.8.0...\n'
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 20 --max-time 180 --retry 2 \
        "https://github.com/astral-sh/uv/releases/download/0.8.0/uv-$target.tar.gz" \
        --output "$download/uv.tar.gz" || fail 'uv download failed; check outbound HTTPS and rerun ./setup.sh.'
    "$PYTHON" -I - "$download/uv.tar.gz" "$UV" "$target" "$digest" <<'PY'
import hashlib, os, pathlib, shutil, sys, tarfile
archive, destination, target, expected = sys.argv[1:]
if hashlib.sha256(pathlib.Path(archive).read_bytes()).hexdigest() != expected:
    raise SystemExit("Signalpost setup: pinned uv archive checksum mismatch")
with tarfile.open(archive, "r:gz") as bundle:
    member = bundle.getmember("uv-" + target + "/uv")
    if not member.isfile() or member.size > 100 * 1024 * 1024:
        raise SystemExit("Signalpost setup: invalid uv archive member")
    with bundle.extractfile(member) as source, open(destination + ".tmp", "wb") as output:
        shutil.copyfileobj(source, output)
os.chmod(destination + ".tmp", 0o755)
os.replace(destination + ".tmp", destination)
PY
    rm -rf "$download"
    trap - EXIT HUP INT TERM
fi

printf 'Installing locked production dependencies with %s...\n' "$PYTHON"
cd "$ROOT/signalpost-starter-kit"
rm -f "$UV_PROJECT_ENVIRONMENT/.signalpost-ready.json"
"$UV" --no-config sync --frozen --no-dev --python "$PYTHON" || fail 'Locked dependency installation failed. Python 3.12 and a supported Linux/macOS platform are recommended; check the error above.'

if ! "$UV_PROJECT_ENVIRONMENT/bin/python" -I - "$ROOT" <<'PY'
import hashlib, importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for module in ("bs4", "extruct", "fastapi", "lxml", "pydantic", "pypdf", "pypdfium2",
               "rapidocr_onnxruntime", "onnxruntime", "numpy", "PIL", "tldextract", "trafilatura", "uvicorn"):
    importlib.import_module(module)
from rapidocr_onnxruntime import RapidOCR
RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
sys.path.insert(0, str(root))
import signalpost.run, signalpost.annual_accounts
stamp = {name: hashlib.sha256((root / "signalpost-starter-kit" / name).read_bytes()).hexdigest()
         for name in ("uv.lock", "pyproject.toml")}
pathlib.Path(sys.prefix, ".signalpost-ready.json").write_text(json.dumps(stamp) + "\n")
PY
then
    fail 'Installed dependency/PDF/OCR checks failed; review the error above and rerun ./setup.sh after correcting the prerequisite.'
fi
printf 'Signalpost is ready. Run: ./run.sh --input companies.jsonl --output output.jsonl\n'
