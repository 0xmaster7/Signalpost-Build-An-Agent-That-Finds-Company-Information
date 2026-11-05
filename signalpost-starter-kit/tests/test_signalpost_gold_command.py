import json
from pathlib import Path
import subprocess
import sys


def test_gold_command_validates_canonical_supported_profiles(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "gold.json"
    process = subprocess.run([sys.executable,
        str(root / "signalpost-starter-kit/scripts/evaluate_signalpost_m08.py"),
        "--output", str(output)], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert report["evaluation_passed"] is True
    assert report["company_count"] == 4
    assert report["synthesis"]["unsupported_assertions"] == 0
    assert report["synthesis"]["provenance_completeness"] == 1
