"""Exercise the installed wrappers with offline evaluator data and local PDF/OCR."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    locked = tomllib.loads((root / "signalpost-starter-kit/uv.lock").read_text())
    versions: dict[str, set[str]] = {}
    for package in locked["package"]:
        versions.setdefault(package["name"].replace("_", "-"), set()).add(package["version"])
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"].lower().replace("_", "-")
        assert distribution.version in versions.get(name, set()), (name, distribution.version)

    # A synthetic one-page PDF checks PDFium + the actual bundled local OCR models.
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    import io
    writer = PdfWriter()
    page = writer.add_blank_page(width=450, height=170)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
        DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 32 Tf 25 80 Td (SIGNALPOST 2025) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)

    with tempfile.TemporaryDirectory(prefix="command-check-", dir=root / ".signalpost-tools/tmp") as temp:
        work = Path(temp)
        denied = work / "denied-tools"
        denied.mkdir()
        calls = work / "unexpected-installer-calls"
        for name in ("uv", "uvx", "pip", "pip3", "curl", "wget", "tesseract"):
            executable = denied / name
            executable.write_text(f'#!/bin/sh\nprintf "%s\\n" "$0" >> "{calls}"\nexit 99\n')
            executable.chmod(0o755)
        env = {**os.environ, "PATH": str(denied) + os.pathsep + os.environ.get("PATH", ""),
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        ocr = subprocess.run([sys.executable, "-m", "signalpost.annual_accounts", "--ocr-worker"],
            input=buffer.getvalue(), cwd=root, env=env, capture_output=True, timeout=90, check=True)
        pages = json.loads(ocr.stdout)
        text = " ".join(word["text"] for page in pages for word in page["words"])
        assert "SIGNALPOST" in text.upper().replace(" ", ""), text

        fixture = root / "signalpost-starter-kit/tests/fixtures/m01"
        output = work / "profiles with spaces.jsonl"
        arguments = ["--input", str(fixture / "offline-batch.jsonl"),
            "--registry-snapshot", str(fixture / "registry.jsonl"), "--output", str(output),
            "--state-output", str(work / "state.json"), "--checkpoint", str(work / "checkpoint.sqlite")]
        completed = subprocess.run([str(root / "run.sh"), *arguments], cwd=work, env=env,
            capture_output=True, text=True, timeout=60)
        assert completed.returncode == 0, completed.stderr
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == 4 and all(row["terminal_state"] for row in rows)
        assert output.with_suffix(output.suffix + ".publication.json").exists()
        failure = subprocess.run([str(root / "run.sh"), "--input", str(work / "missing.jsonl"),
            "--output", str(work / "missing-output.jsonl")], cwd=work, env=env,
            capture_output=True, text=True, timeout=60)
        assert failure.returncode != 0
        assert not calls.exists(), "run.sh/OCR invoked an installer or Tesseract"
        print(json.dumps({"locked_distribution_versions": "verified", "offline_terminal_rows": len(rows),
            "unrelated_cwd": True, "failure_exit_code": failure.returncode,
            "local_pdf_ocr": text, "installation_during_run": False, "tesseract_used": False}))


if __name__ == "__main__":
    main()
