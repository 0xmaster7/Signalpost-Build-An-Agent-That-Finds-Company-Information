#!/usr/bin/env python3
"""CWD-independent evaluator launcher for the repository Signalpost package."""
from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from signalpost.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
