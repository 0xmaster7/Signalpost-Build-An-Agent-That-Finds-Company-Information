#!/usr/bin/env python3
"""Fail closed when the synthetic M06 gate makes factual or untraceable claims."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
metadata = report.get("benchmark_metadata", {})
if not re.fullmatch(r"[0-9a-f]{40}", str(metadata.get("git_sha", ""))):
    raise SystemExit("benchmark lacks exact git SHA")
if not isinstance(metadata.get("working_tree_dirty"), bool):
    raise SystemExit("benchmark lacks dirty/clean state")
if not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("working_tree_diff_sha256", ""))):
    raise SystemExit("benchmark lacks a hash of the measured working-tree source")
if not metadata.get("cohort_id") or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("cohort_sha256", ""))):
    raise SystemExit("benchmark lacks cohort identity/hash")


def visit(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        if value.get("measurement_kind") == "scheduler_simulation":
            if value.get("exact_identity_anchors") != 0:
                raise SystemExit(f"synthetic scenario reports factual exact identity at {path}")
            if "physical_requests" in value:
                raise SystemExit(f"scheduler reservations mislabeled physical requests at {path}")
            if not isinstance(value.get("modeled_physical_reservations"), int):
                raise SystemExit(f"scheduler simulation lacks reservation count at {path}")
        for key, child in value.items():
            visit(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            visit(child, f"{path}[{index}]")

visit(report)
print("M06 scale gate provenance and synthetic identity checks passed")
