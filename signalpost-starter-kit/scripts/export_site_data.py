#!/usr/bin/env python3
"""Export saved evaluator JSONL without contacting any sources."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost.site_export import BUNDLE_LIMIT_BYTES, SiteExportError, export_site_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Existing evaluator output JSONL")
    parser.add_argument("--output-dir", type=Path, default=Path("site-data"), help="New or empty destination")
    parser.add_argument("--bundle-limit-bytes", type=int, default=BUNDLE_LIMIT_BYTES)
    arguments = parser.parse_args()
    try:
        report = export_site_data(arguments.input, arguments.output_dir, bundle_limit_bytes=arguments.bundle_limit_bytes)
    except (SiteExportError, OSError) as error:
        print(f"site export failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
