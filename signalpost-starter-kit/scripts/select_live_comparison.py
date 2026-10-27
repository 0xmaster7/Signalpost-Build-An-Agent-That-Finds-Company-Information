"""Freeze a random employer sample before observing either implementation's output."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import heapq
import io
import json
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path


FIXED = {"930827088", "920710514", "952780093", "993955299", "992936916", "924356715"}
SOURCE = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-fixed-cohort", action="store_true")
    parser.add_argument("--exclude-input", type=Path, action="append", default=[])
    args = parser.parse_args()
    fixed = set() if args.no_fixed_cohort else FIXED
    excluded = set()
    for filename in args.exclude_input:
        for line in filename.read_text().splitlines():
            if line.strip():
                value = json.loads(line)
                excluded.add(str(value["organisation_number"]))
    if fixed & excluded:
        raise SystemExit("Fixed cohort cannot also be excluded")
    random_count = 100 - len(fixed)
    destination = args.output_dir
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "selection.json").exists() or (destination / "companies.jsonl").exists():
        raise SystemExit("Selection already frozen; do not rerandomize after source outcomes")
    seed = secrets.token_hex(32)
    digest = hashlib.sha256()
    with args.registry.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    best = []
    fixed_rows = {}
    population = 0
    source_rows = 0
    seen = set()
    csv.field_size_limit(10_000_000)
    with args.registry.open("rb") as raw:
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        binary = gzip.GzipFile(fileobj=raw) if compressed else raw
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"organisasjonsnummer", "navn", "organisasjonsform.kode", "antallAnsatte", "konkurs", "underAvvikling"}
            if not required <= set(reader.fieldnames or []):
                raise SystemExit("Unexpected official CSV columns: " + repr(reader.fieldnames))
            for record in reader:
                source_rows += 1
                org = str(record["organisasjonsnummer"]).strip()
                if len(org) != 9 or not org.isdigit() or org in seen:
                    continue
                seen.add(org)
                employees = record.get("antallAnsatte", "").strip()
                employees = int(employees) if employees.isdigit() else None
                inactive = any(str(record.get(key, "")).strip().casefold() in {"ja", "true", "1"}
                    for key in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning")) or bool(record.get("slettedato"))
                eligible = record["organisasjonsform.kode"] == "AS" and employees is not None and employees >= 1 and not inactive
                public = {"organisation_number": org, "name": record["navn"], "legal_form": record["organisasjonsform.kode"],
                    "registered_employees": employees, "eligible_in_selection_frame": eligible, "fixed_six_company_cohort": org in fixed}
                if org in fixed:
                    fixed_rows[org] = public
                if not eligible:
                    continue
                population += 1
                if org in fixed or org in excluded:
                    continue
                rank = int(hashlib.sha256((seed + ":" + org).encode()).hexdigest(), 16)
                entry = (-rank, org, public)
                if len(best) < random_count:
                    heapq.heappush(best, entry)
                elif entry > best[0]:
                    heapq.heapreplace(best, entry)
    if len(best) != random_count or set(fixed_rows) != fixed:
        raise SystemExit("Insufficient random population or fixed cohort missing from registry")
    selected = [row for _, _, row in sorted(best, key=lambda entry: -entry[0])] + [fixed_rows[org] for org in sorted(fixed)]
    random.Random(int(seed, 16)).shuffle(selected)
    payload = "".join(json.dumps({"organisation_number": row["organisation_number"]}) + "\n" for row in selected)
    manifest = {"selected_at_utc": datetime.now(timezone.utc).isoformat(), "seed": seed,
        "method": f"{random_count} smallest independent seeded SHA256 ranks without replacement, plus {len(fixed)} fixed companies; all 100 shuffled",
        "population": "Active AS with at least one registered employee; no latest-filing-year or website/financial outcome filter",
        "source_url": SOURCE, "source_file_sha256": digest.hexdigest(), "source_bytes": args.registry.stat().st_size,
        "source_rows": source_rows, "eligible_population": population, "sample_size": 100,
        "random_additions": random_count, "fixed_companies": sorted(fixed),
        "excluded_organisation_numbers": sorted(excluded),
        "input_sha256": hashlib.sha256(payload.encode()).hexdigest(), "rows": selected}
    (destination / "companies.jsonl").write_text(payload, encoding="utf-8")
    (destination / "selection.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
