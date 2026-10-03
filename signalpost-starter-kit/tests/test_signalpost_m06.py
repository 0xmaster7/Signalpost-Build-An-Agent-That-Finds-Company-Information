from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost.network import NetworkGateway
from signalpost.operations import Budget, Opportunity, OpportunityDeferred, OpportunityFailed, OpportunityScheduler, RunBudget
from signalpost.run import main
from test_signalpost_m01 import FakeTransport, valid_envelope


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_thousand_companies_fast_slow_hosts_no_starvation(self):
        scheduler = OpportunityScheduler(concurrency=8)
        work = [Opportunity(str(i), "official_foundation", f"company-{i}",
                            expected_company_family_gain=3, sequence=i) for i in range(1000)]
        active = 0
        peak = 0
        host_active: dict[str, int] = {}
        host_peak: dict[str, int] = {}
        lock = asyncio.Lock()
        async def worker(item: Opportunity) -> str:
            nonlocal active, peak
            host = "slow" if int(item.company.split("-")[1]) == 0 else "fast"
            async with lock:
                active += 1
                peak = max(peak, active)
                host_active[host] = host_active.get(host, 0) + 1
                host_peak[host] = max(host_peak.get(host, 0), host_active[host])
            await asyncio.sleep(0.003 if host == "slow" else 0)
            async with lock:
                active -= 1
                host_active[host] -= 1
            return item.company
        result = await scheduler.run(work, worker)
        self.assertEqual(len(result), 1000)
        self.assertEqual(scheduler.metrics["official_foundation"]["completed"], 1000)
        self.assertLessEqual(peak, 8)
        self.assertEqual(result["0"], "company-0")

    async def test_twelve_hundred_operational_actions_are_input_sized(self):
        scheduler = OpportunityScheduler(concurrency=8)
        work = [Opportunity(f"{i}", "official_foundation", f"org-{i}", sequence=i) for i in range(1200)]
        result = await scheduler.run(work, lambda item: asyncio.sleep(0, result=item.key))
        self.assertEqual(len(result), 1200)
        self.assertEqual(scheduler.metrics["official_foundation"]["completed"], 1200)

    async def test_pathological_company_is_terminalized_without_stopping_later_work(self):
        scheduler = OpportunityScheduler(concurrency=4)
        jobs = [Opportunity(str(i), "official_foundation", f"org-{i}", sequence=i) for i in range(100)]
        async def worker(item):
            if item.key == "0":
                raise OpportunityFailed("failed envelope")
            await asyncio.sleep(0)
            return item.key
        result = await scheduler.run(jobs, worker)
        self.assertEqual(len(result), 100)
        self.assertEqual(result["0"], "failed envelope")
        self.assertEqual(scheduler.metrics["official_foundation"]["failed"], 1)
        self.assertEqual(scheduler.metrics["official_foundation"]["completed"], 99)

    async def test_optional_pass_waits_for_official_pass_and_can_be_deferred(self):
        scheduler = OpportunityScheduler(concurrency=4)
        events: list[str] = []
        jobs = [Opportunity("o", "official_foundation", "x", sequence=0),
                Opportunity("w", "website_verify", "x", sequence=1)]
        allowed = False
        async def worker(item):
            events.append(item.pass_name)
            return item.key
        result = await scheduler.run(jobs, worker, permitted=lambda item: allowed or item.pass_name == "official_foundation")
        self.assertEqual(result, {"o": "o"})
        self.assertEqual(events, ["official_foundation"])
        self.assertEqual(scheduler.metrics["website_verify"]["deferred"], 1)

    async def test_deadline_defers_each_optional_pass_with_internal_reason(self):
        scheduler = OpportunityScheduler(concurrency=2)
        names = ("website_verify", "website_shallow", "jobs_activity", "search", "deep")
        work = [Opportunity(name, name, name) for name in names]
        result = await scheduler.run(work, lambda item: asyncio.sleep(0, result=item.key), permitted=lambda _: False)
        self.assertEqual(result, {})
        self.assertTrue(all(scheduler.metrics[name]["deferred"] == 1 for name in names))

    async def test_score_uses_audited_formula_and_order_is_stable(self):
        item = Opportunity("x", "official_foundation", "x", 2, 3, 0.25, 4, 5, sequence=9)
        self.assertAlmostEqual(item.score, 8 + 3 - 2 - 4 - 1)
        scheduler = OpportunityScheduler(concurrency=1)
        jobs = [Opportunity(str(i), "website_verify", str(i), sequence=i) for i in range(25)]
        result = await scheduler.run(jobs, lambda item: asyncio.sleep(0, result=item.key))
        self.assertEqual(list(result), [str(i) for i in range(25)])


class DeadlineAndBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_monotonic_rollback_does_not_extend_budget(self):
        now = [100.0]
        budget = Budget(RunBudget(hard_seconds=20, soft_seconds=10, completion_reserve_seconds=5,
                                  physical_request_limit=5), monotonic=lambda: now[0])
        now[0] = 106
        self.assertTrue(await budget.reserve_request(required=True))
        now[0] = 90  # A broken injected clock cannot make elapsed negative or reopen time.
        self.assertEqual(budget.elapsed, 6)
        # The high-water mark prevents even a faulty clock source from reopening the budget.
        now[0] = 116
        self.assertFalse(await budget.reserve_request(required=True))

    async def test_soft_stop_defers_optional_but_required_work_keeps_completion_reserve(self):
        now = [0.0]
        budget = Budget(RunBudget(hard_seconds=10, soft_seconds=4, completion_reserve_seconds=2,
                                  physical_request_limit=5), monotonic=lambda: now[0])
        now[0] = 5
        self.assertFalse(await budget.reserve_request())
        self.assertTrue(await budget.reserve_request(required=True))
        now[0] = 8
        self.assertFalse(await budget.reserve_request(required=True))

    async def test_per_company_and_host_accounting_are_atomic(self):
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
                                  physical_request_limit=11))
        reserved = await asyncio.gather(*(budget.reserve_request(company="c1", host="h1") for _ in range(50)))
        self.assertEqual(sum(reserved), 11)
        self.assertEqual(budget.company_request_count("c1"), 11)
        self.assertEqual(budget.host_request_count("h1"), 11)

    async def test_per_company_per_host_and_paid_cost_caps_are_atomic(self):
        from decimal import Decimal
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
            physical_request_limit=20, paid_cost_limit=Decimal("0.05"),
            per_company_physical_limit=2, per_host_physical_limit=3))
        results = await asyncio.gather(*(budget.reserve_request(Decimal("0.01"), company="c1", host="h1")
                                         for _ in range(20)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(budget.physical_requests, 2)
        self.assertEqual(budget.cost, Decimal("0.02"))
        # A different company reaches the host cap; rejected reservations do not consume cost.
        more = await asyncio.gather(*(budget.reserve_request(Decimal("0.01"), company=f"c{i}", host="h1")
                                      for i in range(10)))
        self.assertEqual(sum(more), 1)
        self.assertEqual(budget.host_request_count("h1"), 3)
        self.assertEqual(budget.cost, Decimal("0.03"))

    async def test_paid_cost_reservation_race_never_exceeds_cap(self):
        from decimal import Decimal
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
            physical_request_limit=100, paid_cost_limit=Decimal("0.05")))
        results = await asyncio.gather(*(budget.reserve_request(Decimal("0.01")) for _ in range(50)))
        self.assertEqual(sum(results), 5)
        self.assertEqual(budget.cost, Decimal("0.05"))

    async def test_logical_request_allowance_is_atomic(self):
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
                                  physical_request_limit=20, logical_request_limit=3))
        reserved = await asyncio.gather(*(budget.reserve_logical_request() for _ in range(50)))
        self.assertEqual(sum(reserved), 3)
        self.assertEqual(budget.logical_requests, 3)


class GatewayM06Tests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_inflight_fetch_coalesces_physical_work_and_keeps_logical_count(self):
        started = asyncio.Event()
        release = asyncio.Event()
        class SlowTransport:
            async def request(self, url, headers, timeout):
                started.set()
                await release.wait()
                return 200, {}, b"ok", url
        gateway = NetworkGateway(SlowTransport(), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            one = asyncio.create_task(gateway.fetch("https://8.8.8.8/same", use_robots=False))
            await started.wait()
            two = asyncio.create_task(gateway.fetch("https://8.8.8.8/same", use_robots=False))
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await one, await two)
        self.assertEqual(gateway.ledger.logical_requests, 2)
        self.assertEqual(gateway.ledger.physical_requests, 1)
        self.assertEqual(gateway.coalesced_requests, 1)

    async def test_global_and_per_host_concurrency_limits_are_enforced(self):
        active = 0
        global_peak = 0
        host_active: dict[str, int] = {}
        host_peak: dict[str, int] = {}
        lock = asyncio.Lock()
        class MeasuredTransport:
            async def request(self, url, headers, timeout):
                nonlocal active, global_peak
                from urllib.parse import urlsplit
                host = urlsplit(url).hostname or ""
                async with lock:
                    active += 1
                    global_peak = max(global_peak, active)
                    host_active[host] = host_active.get(host, 0) + 1
                    host_peak[host] = max(host_peak.get(host, 0), host_active[host])
                await asyncio.sleep(0.005)
                async with lock:
                    active -= 1
                    host_active[host] -= 1
                return 200, {}, b"ok", url
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
                                  physical_request_limit=20, global_http_concurrency=8, per_host_concurrency=2))
        gateway = NetworkGateway(MeasuredTransport(), budget=budget, retries=0)
        hosts = ("8.8.8.8", "1.1.1.1", "9.9.9.9", "8.8.4.4", "1.0.0.1")
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            await asyncio.gather(*(gateway.fetch(f"https://{hosts[i % len(hosts)]}/{i}", use_robots=False) for i in range(10)))
        self.assertEqual(global_peak, 8)
        self.assertTrue(all(value <= 2 for value in host_peak.values()))
        self.assertEqual(max(host_peak.values()), 2)
        self.assertEqual(gateway.ledger.physical_requests, 10)

    async def test_cold_cache_repeats_sequential_request_and_ledgers_each_physical_fetch(self):
        fake = FakeTransport([(200, {}, b"one", "https://8.8.8.8/a"),
                              (200, {}, b"two", "https://8.8.8.8/a")])
        gateway = NetworkGateway(fake, retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            first = await gateway.fetch("https://8.8.8.8/a", use_robots=False)
            second = await gateway.fetch("https://8.8.8.8/a", use_robots=False)
        self.assertEqual((first[2], second[2]), (b"one", b"two"))
        self.assertEqual(gateway.ledger.logical_requests, 2)
        self.assertEqual(gateway.ledger.physical_requests, 2)
        self.assertEqual(gateway.coalesced_requests, 0)

    async def test_official_subunit_query_is_counted_against_its_company(self):
        org = "923609016"
        fake = FakeTransport([(200, {}, b'{"_embedded":{"underenheter":[]}}',
                               f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}")])
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
                                  physical_request_limit=5))
        gateway = NetworkGateway(fake, retries=0, budget=budget)
        url = f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}"
        with patch("signalpost.network.validate_public_host", return_value=("195.43.63.68",)):
            await gateway.fetch(url, purpose="subunits", use_robots=False,
                allowed_hosts={"data.brreg.no"}, access_profile="brreg_structured_api")
        self.assertEqual(budget.company_request_count(org), 1)

    async def test_logical_budget_exhaustion_is_distinct_from_transport_and_disallow(self):
        budget = Budget(RunBudget(hard_seconds=30, soft_seconds=20, completion_reserve_seconds=2,
                                  physical_request_limit=5, logical_request_limit=0))
        fake = FakeTransport([])
        gateway = NetworkGateway(fake, budget=budget, retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            result = await gateway.fetch("https://8.8.8.8/a", use_robots=False)
        self.assertEqual(result[-1], "budget_exhausted")
        self.assertEqual(gateway.ledger.logical_requests, 1)
        self.assertEqual(gateway.ledger.physical_requests, 0)
        self.assertEqual(fake.urls, [])

    async def test_429_retry_after_halves_host_rate_and_preserves_attempt_ledger(self):
        fake = FakeTransport([(429, {"Retry-After": "0"}, b"", "https://8.8.8.8/a"),
                              (200, {}, b"ok", "https://8.8.8.8/a")])
        gateway = NetworkGateway(fake, retries=1)
        gateway.set_rate_limit("8.8.8.8", 4)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch("signalpost.network.asyncio.sleep", return_value=None):
            result = await gateway.fetch("https://8.8.8.8/a", use_robots=False)
        self.assertEqual(result[-1], "ok")
        self.assertAlmostEqual(gateway._rates["8.8.8.8"], 1 / 2)
        self.assertEqual(gateway._host_slots["8.8.8.8"].limit, 1)
        self.assertEqual(gateway.ledger.physical_requests, 2)

    async def test_cancelled_transport_attempt_is_ledgered(self):
        class HangingTransport:
            async def request(self, url, headers, timeout):
                await asyncio.Event().wait()
        gateway = NetworkGateway(HangingTransport(), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            task = asyncio.create_task(gateway.fetch("https://8.8.8.8/a", use_robots=False))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(gateway.ledger.physical_requests, 1)
        self.assertEqual(gateway.ledger.entries[0].outcome, "cancelled")


class CheckpointResumeTests(unittest.TestCase):
    def test_terminalized_checkpoint_resume_has_no_duplicate_facts(self):
        from signalpost.operations import CheckpointStore
        for terminal_count in (25, 50, 90):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.sqlite"
                store = CheckpointStore(path)
                for row in range(1, 101):
                    store.connection.execute("INSERT INTO shells VALUES (?,?,?,'pending')", (row, f"row:{row}", "923609016"))
                store.set_meta("input_fingerprint", "fixture")
                for row in range(1, terminal_count + 1):
                    store.put(valid_envelope(row))
                    store.set_shell_state(row, "terminalized")
                store.close()  # Crash boundary: process exits with this durable partial checkpoint.
                resumed = CheckpointStore(path)
                found = resumed.terminalized()
                self.assertEqual(len(found), terminal_count)
                for row, envelope in found.items():
                    self.assertEqual(envelope.row_number, row)
                    self.assertEqual([claim.claim_id for claim in envelope.claims], ["c1"])
                for row in range(terminal_count + 1, 101):
                    resumed.put(valid_envelope(row))
                    resumed.set_shell_state(row, "terminalized")
                complete = resumed.terminalized()
                self.assertEqual(len(complete), 100)
                self.assertTrue(all([claim.claim_id for claim in env.claims] == ["c1"] for env in complete.values()))
                self.assertEqual(resumed.get_meta("input_fingerprint"), "fixture")
                resumed.close()

    def test_clean_offline_resume_replays_same_cardinality_and_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, state, registry = (Path(directory) / name for name in ("input.txt", "output.jsonl", "state.sqlite", "registry.jsonl"))
            source.write_text("923609016\n923609016\n", encoding="utf-8")
            registry.write_text('{"orgnr":"923609016","name":"Fixture AS"}\n', encoding="utf-8")
            options = ["--input", str(source), "--format", "plain", "--output", str(output),
                       "--state-output", str(state), "--registry-snapshot", str(registry)]
            self.assertEqual(main(options), 0)
            first = output.read_text(encoding="utf-8")
            self.assertEqual(main(options + ["--resume"]), 0)
            second = output.read_text(encoding="utf-8")
            import json
            self.assertEqual([json.loads(line)["row_number"] for line in first.splitlines()], [1, 2])
            self.assertEqual([json.loads(line)["row_number"] for line in second.splitlines()], [1, 2])
            self.assertEqual([len(json.loads(line)["claims"]) for line in first.splitlines()],
                             [len(json.loads(line)["claims"]) for line in second.splitlines()])
            for before, after in zip(first.splitlines(), second.splitlines()):
                a, b = json.loads(before), json.loads(after)
                self.assertEqual([(c["claim_id"], c["value"]) for c in a["claims"]],
                                 [(c["claim_id"], c["value"]) for c in b["claims"]])
