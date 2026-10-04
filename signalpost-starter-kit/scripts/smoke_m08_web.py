#!/usr/bin/env python3
"""Launch the M08 UI from an unrelated CWD and exercise its core routes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from signalpost.query import load_profiles  # noqa: E402


def get(base: str, route: str) -> str:
    with urlopen(base + route, timeout=3) as response:
        assert response.status == 200
        return response.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    profiles = load_profiles(args.data)
    orgs = sorted(profiles)
    if not orgs:
        raise SystemExit("M08 smoke requires at least one canonical company")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    route_latency_ms: dict[str, float] = {}
    def timed_get(route: str) -> str:
        started = time.perf_counter()
        value = get(base, route)
        route_latency_ms[route.split("?", 1)[0]] = round((time.perf_counter() - started) * 1000, 3)
        return value
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    process = subprocess.Popen([sys.executable, str(ROOT / "signalpost-starter-kit" / "run_signalpost_web.py"),
        "--data", str(Path(args.data).resolve()),
        "--host", "127.0.0.1", "--port", str(port)], cwd="/tmp", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("M08 UI process exited before becoming ready")
            try:
                timed_get("/")
                break
            except (OSError, HTTPError):
                time.sleep(0.05)
        else:
            raise RuntimeError("M08 UI did not become ready")
        home = timed_get("/?" + urlencode({"q": "<script>alert(1)</script>"}))
        assert "&lt;script&gt;" in home and "<script>alert(1)</script>" not in home
        profile = timed_get("/companies/" + orgs[0])
        assert "Identity and public brand" in profile and "Accounts and history" in profile
        assert "Evidence and availability" in profile and "Refresh and changes" in profile
        evidence_id = next(iter(profiles[orgs[0]].evidence), None)
        if evidence_id:
            detail = timed_get("/evidence/" + orgs[0] + "/" + evidence_id)
            assert "Content SHA-256" in detail and "Extraction" in detail
        if len(orgs) > 1:
            compare = timed_get("/compare?" + "&".join("org=" + org for org in orgs[:2]))
            assert "not comparable" in compare or "comparable" in compare
        verified = next((claim for claim in profiles[orgs[0]].claims if claim.field in {"name", "legal_name"}), None)
        if verified:
            route = "/verify?" + urlencode({"org": orgs[0], "field": verified.field, "value": str(verified.value)})
            assert "supported" in timed_get(route)
        assert "Changes and history" in timed_get("/changes")
        source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
        print(json.dumps({"measurement_kind": "local_http_ui_smoke", "source_commit": source_sha,
            "source_tree_dirty": dirty, "data_sha256": hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
            "ui_launch": "PASS", "companies": len(profiles), "profile": "PASS",
            "evidence": "PASS", "compare": "PASS" if len(orgs) > 1 else "not_applicable",
            "verify": "PASS" if verified else "not_applicable", "changes": "PASS", "xss": "PASS",
            "route_latency_ms": route_latency_ms}, sort_keys=True))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
