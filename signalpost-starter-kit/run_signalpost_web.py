#!/usr/bin/env python3
"""CWD-independent local research UI launcher."""
from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from signalpost.web import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
