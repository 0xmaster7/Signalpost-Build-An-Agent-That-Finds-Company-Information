#!/usr/bin/env python3
"""Record the exact installed distribution/license metadata for the RC1 venv."""
from __future__ import annotations

import hashlib
import importlib.metadata
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "signalpost-starter-kit"


def main() -> int:
    lock_path = PROJECT / "uv.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    locked = {package["name"].casefold(): package["version"] for package in lock["package"]}
    distributions = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if not name or name.casefold() not in locked:
            continue
        license_value = dist.metadata.get("License-Expression") or dist.metadata.get("License")
        if not license_value:
            license_value = next((item.split("::", 1)[1].strip() for item in dist.metadata.get_all("Classifier", [])
                                  if item.startswith("License :: ")), "UNKNOWN_METADATA")
        distributions.append((name, dist.version, license_value, locked[name.casefold()]))
    distributions.sort(key=lambda item: item[0].casefold())
    missing = [(name, version) for name, version, _, expected in distributions if version != expected]
    if missing:
        raise SystemExit(f"installed version does not match uv.lock: {missing}")
    lock_sha = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    rows = "\n".join(f"| `{name}` | `{version}` | {license_name} |" for name, version, license_name, _ in distributions)
    docs = ROOT / "docs"
    (docs / "data-licenses.md").write_text(
        "# Data and software licences\n\n"
        "Generated from the clean RC1 environment's installed distribution metadata. "
        "The dependency versions are matched to `signalpost-starter-kit/uv.lock` "
        f"(SHA-256 `{lock_sha}`). {len(distributions)} locked distributions were installed.\n\n"
        "| Distribution | Locked version | Declared licence metadata |\n|---|---:|---|\n" + rows + "\n\n"
        "Optional `crawler` and `sentiment` dependency groups are pinned in the lock but were not installed or enabled for RC1; "
        "review their full upstream licence notices before enabling them. This inventory records package metadata, not a legal opinion.\n\n"
        "Data sources and acquisition/retention assumptions are in [`source-rights.md`](source-rights.md). "
        "The repository has no `LICENSE` file and declares no project-code licence; third-party data rights do not supply one.\n",
        encoding="utf-8")
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text(
        "# Third-party notices\n\n"
        "This release installs the distributions listed in [`docs/data-licenses.md`](docs/data-licenses.md), "
        "at the versions frozen in `signalpost-starter-kit/uv.lock`. Their reported licence metadata is reproduced there. "
        "The distributions are installed from PyPI and are not vendored into this repository. The installer retains each "
        "distribution's own licence/notice files in the environment. Read those files before redistributing a built bundle.\n\n"
        "Notable multi-option declarations in the active environment include `tld` (MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later), "
        "`packaging` (Apache-2.0 OR BSD-2-Clause), and `regex` (Apache-2.0 AND CNRI-Python). Optional crawler/model dependencies "
        "are disabled and not part of this active inventory.\n\n"
        "Signalpost's own code licence is undeclared in this repository.\n",
        encoding="utf-8")
    print(f"wrote licence inventory for {len(distributions)} locked installed distributions (uv.lock sha256 {lock_sha})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
