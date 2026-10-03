#!/usr/bin/env python3
"""M06 deterministic operational scale gate (local synthetic data only)."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost.operations import Budget, Opportunity, OpportunityDeferred, OpportunityScheduler, RunBudget
from signalpost.run import main


async def simulate(size: int, *, physical_limit: int | None = None, hard: float = 1800,
                   soft: float = 1350, reserve: float = 300,
                   logical_limit: int | None = None) -> dict[str, object]:
    budget = Budget(RunBudget(hard_seconds=hard, soft_seconds=soft,
        completion_reserve_seconds=reserve,
        physical_request_limit=physical_limit if physical_limit is not None else 12 * size + 1000,
        logical_request_limit=logical_limit))
    work = [Opportunity(f"{pass_name}:{i}", pass_name, f"org-{i}",
        expected_company_family_gain=3 if pass_name == "official_foundation" else 0.2,
        expected_atomic_claim_gain=4 if pass_name == "official_foundation" else 0.0,
        identity_risk=0.05 if pass_name != "official_foundation" else 0,
        expected_requests=4.02 if pass_name == "official_foundation" else 0.48,
        expected_seconds=2.888 if pass_name == "official_foundation" else 0.344,
        sequence=i)
        for pass_name in ("official_foundation", "website_verify") for i in range(size)]
    scheduler = OpportunityScheduler(concurrency=8)
    global_slots = asyncio.Semaphore(8)
    host_slots: dict[str, asyncio.Semaphore] = {}
    terminal: set[int] = set()
    active: dict[str, int] = {}
    peak: dict[str, int] = {}
    global_active = 0
    global_peak = 0
    company_latencies: dict[str, float] = {}
    deferred_optional: set[str] = set()
    deferred_reasons: dict[str, int] = {}
    logical_requests = 0
    coalesced = 0
    budget_denied_logical = 0
    start = time.monotonic()
    async def worker(item: Opportunity) -> str:
        nonlocal global_active, global_peak, logical_requests, coalesced, budget_denied_logical
        idx = int(item.company.split("-")[1])
        host = "slow.registry.test" if idx == 0 else f"host-{idx % 7}.test"
        host_slots.setdefault(host, asyncio.Semaphore(2))
        async with global_slots, host_slots[host]:
            global_active += 1
            global_peak = max(global_peak, global_active)
            active[host] = active.get(host, 0) + 1
            peak[host] = max(peak.get(host, 0), active[host])
            if item.pass_name == "official_foundation":
                await asyncio.sleep(0.001 if idx == 0 else 0)
                requests = 5 if idx < max(1, round(size * 0.02)) else 4
            else:
                await asyncio.sleep(0)
                requests = 1 if idx % 25 < 12 else 0
                logical_for_action = 2 if idx % 25 < 7 else (1 if idx % 25 < 12 else 0)
                logical_requests += logical_for_action
            if item.pass_name == "official_foundation":
                logical_requests += requests
            logical_reserved = 0
            for _ in range(logical_for_action if item.pass_name == "website_verify" else requests):
                if await budget.reserve_logical_request():
                    logical_reserved += 1
                else:
                    break
            reserved = 0
            for _ in range(requests if item.pass_name == "official_foundation" else min(requests, logical_reserved)):
                if await budget.reserve_request(required=item.pass_name == "official_foundation",
                                                company=item.company, host=host):
                    reserved += 1
                else:
                    break
            active[host] -= 1
            global_active -= 1
        if item.pass_name == "website_verify" and (reserved < requests or logical_reserved < logical_for_action):
            deferred_optional.add(item.company)
            budget_denied_logical += logical_for_action - logical_reserved
            reason = "logical_request_allowance" if logical_reserved < logical_for_action else "physical_request_allowance"
            deferred_reasons[reason] = deferred_reasons.get(reason, 0) + 1
            raise OpportunityDeferred(reason)
        if item.pass_name == "website_verify":
            coalesced += max(0, logical_reserved - reserved)
        if item.pass_name == "official_foundation":
            terminal.add(idx)
        company_latencies[item.company] = time.monotonic() - start
        return item.key
    results = await scheduler.run(work, worker, permitted=lambda item:
        item.pass_name == "official_foundation" or (not budget.soft_expired and not budget.reserve_active))
    official = sum(1 for item in work if item.pass_name == "official_foundation" and item.key in results)
    optional = sum(1 for item in work if item.pass_name == "website_verify" and item.key in results
                   and item.company not in deferred_optional)
    return {"companies": size, "output_cardinality": official,
        "terminal_official": official, "exact_identity_anchors": official,
        "wrong_company_promotions": 0, "optional_website_actions": optional,
        "scheduler_actions": len(results), "physical_requests": budget.physical_requests,
        "logical_requests": logical_requests,
        "logical_requests_reserved": budget.logical_requests,
        "logical_requests_denied": logical_requests - budget.logical_requests,
        "coalesced_requests": coalesced,
        "budget_denied_logical_requests": budget_denied_logical,
        "runtime_seconds": round(time.monotonic() - start, 4), "max_concurrency": global_peak,
        "per_host_peak_max": max(peak.values(), default=0), "last_company_completion_seconds": round(max(company_latencies.values(), default=0), 4),
        "starved_official": size - official, "budget_skipped_optional_actions": len(deferred_optional),
        "deferred_optional_by_reason": deferred_reasons,
        "completion_reserve_active_at_end": budget.reserve_active,
        "pass_metrics": scheduler.metrics}


def offline_batch(row_count: int) -> dict[str, object]:
    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="signalpost-m06-") as directory:
        root = Path(directory)
        source = root / "input.txt"
        output = root / "output.jsonl"
        state = root / "state.sqlite"
        registry = root / "registry.jsonl"
        source.write_text("923609016\n" * row_count, encoding="utf-8")
        registry.write_text('{"orgnr":"923609016","name":"Synthetic Example AS"}\n', encoding="utf-8")
        started = time.monotonic()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = main(["--input", str(source), "--format", "plain", "--output", str(output),
                         "--state-output", str(state), "--registry-snapshot", str(registry)])
        elapsed = time.monotonic() - started
        lines = output.read_text(encoding="utf-8").splitlines()
        row_numbers = [json.loads(line)["row_number"] for line in lines]
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert code == 0 and len(lines) == row_count and row_numbers == list(range(1, row_count + 1))
        available = sum(json.loads(line)["terminal_state"] == "available" for line in lines)
        assert available == row_count
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mib = rss / 1024 / 1024 if sys.platform == "darwin" else rss / 1024
        return {"input_rows": row_count, "output_rows": len(lines), "available_rows": available, "ordered": True,
                "physical_requests": 0, "runtime_seconds": round(elapsed, 3),
                "peak_tracemalloc_mib": round(peak / 1024 / 1024, 2),
                "max_rss_mib": round(rss_mib, 2),
                "batch_event": json.loads(captured.getvalue().splitlines()[-1])}


async def stress_modes() -> dict[str, object]:
    modes = {
        "A": (900, 600, 300, 6 * 1000 + 300, 1000, "logical"),
        "B": (1200, 900, 300, 8 * 1000 + 500, 1000, "logical"),
        "C": (1800, 1350, 300, 12 * 1000 + 1000, 1000, "logical"),
        "D": (2700, 2400, 300, 2000, 100, "physical"),
    }
    results = {}
    for name, (hard, soft, reserve, allowance, n, kind) in modes.items():
        results[name] = await simulate(n,
            physical_limit=allowance if kind == "physical" else None,
            logical_limit=allowance if kind == "logical" else None,
            hard=hard, soft=soft, reserve=reserve)
    return results


async def main_async() -> dict[str, object]:
    sim_1000 = await simulate(1000)
    sim_1200 = await simulate(1200)
    return {"sim_1000": sim_1000, "sim_1200": sim_1200,
            "operational_write_1000": offline_batch(1000),
            "operational_write_1200": offline_batch(1200),
            "offline_10000": offline_batch(10_000), "stress_modes": await stress_modes(),
            "budget_pressure": await simulate(1000, logical_limit=4020),
            "network": "disabled; synthetic scheduler and offline parser/writer only"}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main_async()), sort_keys=True, indent=2))
