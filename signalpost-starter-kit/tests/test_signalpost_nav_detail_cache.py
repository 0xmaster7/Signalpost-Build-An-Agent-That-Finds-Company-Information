import asyncio
import base64
import hashlib
import json
import shutil
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from signalpost import nav, network
from signalpost.models import Claim, PublicState
from signalpost.network import NetworkGateway
from signalpost.recording import ReplayError


ORG = "987974249"
OTHER = "111111111"
CHILD = "979586701"
NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def vacancy(number=1):
    return f"{number:08x}-1234-1234-1234-123456789abc"


def detail(number=1, employer=ORG):
    return {"uuid": vacancy(number), "status": "ACTIVE", "sistEndret": (NOW - timedelta(hours=1)).isoformat(),
        "ad_content": {"employer": {"orgnr": employer, "homepage": "https://example.no/"},
            "title": "Engineer", "published": (NOW - timedelta(days=2)).isoformat(),
            "expires": (NOW + timedelta(days=10)).isoformat()}}


def summary(number=1, **changes):
    entry = {"uuid": vacancy(number), "status": "ACTIVE", "businessName": "Trading alias",
        "sistEndret": (NOW - timedelta(hours=1)).isoformat()}
    entry.update(changes)
    return {"id": "detail-" + str(number), "_feed_entry": entry}


def targets(*claims):
    return {ORG: SimpleNamespace(claims=list(claims))}


class Gateway:
    def __init__(self, items=None, details=None, observed_at=NOW):
        self.items = [summary()] if items is None else items
        self.details = {"detail-1": detail()} if details is None else details
        self.observed_at = observed_at
        self.calls = []

    def set_rate_limit(self, host, seconds):
        assert host == "pam-stilling-feed.nav.no" and seconds == 4.0

    async def fetch(self, url, **kwargs):
        self.calls.append(kwargs["purpose"])
        if kwargs["purpose"] == "nav_public_access":
            return 200, {}, b"eyJabc.def.ghi", url, "ok"
        if kwargs["purpose"] == "nav_feed":
            payload = {"items": self.items}
        else:
            payload = self.details[url.rsplit("/", 1)[-1]]
            if isinstance(payload, Exception):
                raise payload
        return 200, {}, json.dumps(payload).encode(), url, "ok"


def research(gateway, cutoff=NOW, target=None, **options):
    return asyncio.run(nav.research_jobs(target or targets(), gateway, cutoff, allow_current=True, **options))


@pytest.fixture(autouse=True)
def private_nav_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNALPOST_NAV_CACHE", str(tmp_path / "nav-cache"))
    return tmp_path / "nav-cache"


def rewrite(path, mutation):
    wrapped = json.loads(path.read_bytes())
    mutation(wrapped["record"])
    wrapped["sha256"] = hashlib.sha256(nav._cache_bytes(wrapped["record"])).hexdigest()
    path.write_bytes(nav._cache_bytes(wrapped))


def test_resume_adds_only_unresolved_details_and_preserves_evidence(private_nav_cache):
    items = [summary(number) for number in (1, 2, 3)]
    details = {"detail-" + str(number): detail(number) for number in (1, 2, 3)}
    first, first_audit, _ = research(Gateway(items, details), max_details=1)
    assert first_audit["cache_writes"] == 1 and first_audit["unresolved_entries"] == 2
    assert first_audit["reason"] == "detail_cap" and not first_audit["negative_coverage"]
    second_gateway = Gateway(items, details, NOW + timedelta(minutes=5))
    second, second_audit, _ = research(second_gateway, NOW + timedelta(minutes=5), max_details=1)
    assert second_gateway.calls.count("nav_job") == 1
    assert second_audit["cache_hits"] == 1 and second_audit["cache_writes"] == 1
    assert second_audit["unresolved_entries"] == 1 and not second_audit["complete"]
    assert second[ORG].evidence[0] == first[ORG].evidence[0]
    assert second[ORG].snapshots[0] == first[ORG].snapshots[0]
    final_gateway = Gateway(items, details, NOW + timedelta(minutes=10))
    final, final_audit, _ = research(final_gateway, NOW + timedelta(minutes=10), max_details=1)
    assert len(final[ORG].claims) == 15 and final_audit["complete"]
    assert final_audit["cache_hits"] == 2 and final_gateway.calls.count("nav_job") == 1
    assert stat.S_IMODE(private_nav_cache.stat().st_mode) == 0o700
    for path in private_nav_cache.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        stored = json.loads(path.read_bytes())["record"]
        assert hashlib.sha256(base64.b64decode(stored["body"])).hexdigest() == stored["content_sha256"]
        assert stored["source_url"] == stored["request_url"]
        assert "Authorization" not in path.read_text() and "eyJabc" not in path.read_text()


@pytest.mark.parametrize("change", ["detail_id", "last_modified", "content", "uuid", "missing_modified"])
def test_feed_identity_changes_never_reuse_old_details(change):
    research(Gateway())
    item = summary()
    fresh = detail()
    if change == "detail_id":
        item["id"] = "replacement-id"
    elif change == "last_modified":
        item["_feed_entry"]["sistEndret"] = NOW.isoformat()
        fresh["sistEndret"] = NOW.isoformat()
    elif change == "content":
        item["_feed_entry"]["businessName"] = "Changed alias"
    elif change == "uuid":
        item["_feed_entry"]["uuid"] = vacancy(2)
        fresh["uuid"] = vacancy(2)
    else:
        del item["_feed_entry"]["sistEndret"]
    fresh["ad_content"]["employer"]["orgnr"] = OTHER
    gateway = Gateway([item], {item["id"]: fresh})
    results, audit, _ = research(gateway)
    assert not results and audit["cache_hits"] == 0 and gateway.calls.count("nav_job") == 1
    assert not audit["negative_coverage"]


@pytest.mark.parametrize("field,value", [("version", 999), ("retrieved_at", "2026-11-06T12:00:00+00:00"),
    ("retrieved_at", "2026-11-05T12:00:00"), ("source_url", "https://evil.example/"),
    ("request_url", nav.ORIGIN + "/api/v1/feedentry/another"), ("content_sha256", "0" * 64),
    ("body", "corrupt")])
def test_damaged_or_future_cache_records_remain_unknown_without_fresh_detail(private_nav_cache, field, value):
    research(Gateway())
    path = next(private_nav_cache.glob("*.json"))
    rewrite(path, lambda record: record.update({field: value}))
    gateway = Gateway(details={"detail-1": OSError("private failure")})
    results, audit, _ = research(gateway)
    assert not results and audit["cache_errors"] == 1 and audit["detail_failures"] == 1
    assert audit["unresolved_entries"] == 1 and not audit["complete"] and not audit["negative_coverage"]


@pytest.mark.parametrize("change", ["uuid", "modified", "employer", "incomplete", "status"])
def test_raw_detail_identity_is_revalidated_with_fresh_parser(private_nav_cache, change):
    research(Gateway())
    path = next(private_nav_cache.glob("*.json"))
    payload = detail()
    if change == "uuid":
        payload["uuid"] = vacancy(2)
    elif change == "modified":
        payload["sistEndret"] = NOW.isoformat()
    elif change == "employer":
        payload["ad_content"]["employer"]["orgnr"] = None
    elif change == "incomplete":
        del payload["ad_content"]["expires"]
    else:
        payload["status"] = "INACTIVE"
    body = json.dumps(payload).encode()
    rewrite(path, lambda record: record.update(body=base64.b64encode(body).decode(),
        content_sha256=hashlib.sha256(body).hexdigest()))
    results, audit, _ = research(Gateway(details={"detail-1": OSError()}))
    assert not results and audit["cache_hits"] == 0 and audit["cache_errors"] == 1
    assert audit["unresolved_entries"] == 1 and not audit["negative_coverage"]


@pytest.mark.parametrize("change", ["employer", "title", "published", "expires", "modified"])
def test_incomplete_detail_is_not_cached_or_counted_as_resolved(private_nav_cache, change):
    payload = detail()
    if change == "employer":
        payload["ad_content"]["employer"]["orgnr"] = None
    elif change == "modified":
        del payload["sistEndret"]
    else:
        del payload["ad_content"][change]
    results, audit, _ = research(Gateway(details={"detail-1": payload}))
    assert not results and audit["unresolved_entries"] == 1 and not audit["complete"]
    assert audit["cache_writes"] == 0 and not list(private_nav_cache.iterdir())
    assert not audit["negative_coverage"]


def test_incomplete_embedded_feed_detail_stays_unresolved():
    item = summary()
    item["_feed_entry"]["ad_content"] = detail()["ad_content"]
    del item["_feed_entry"]["ad_content"]["published"]
    gateway = Gateway([item], details={"detail-1": OSError("detail unavailable")})
    results, audit, _ = research(gateway)
    assert not results and audit["unresolved_entries"] == 1
    assert audit["detail_failures"] == 1 and not audit["complete"]
    assert not audit["negative_coverage"]


def test_expiry_is_evaluated_at_new_run_without_retiming_old_evidence():
    first, _, _ = research(Gateway())
    gateway = Gateway(details={}, observed_at=NOW + timedelta(days=11))
    results, audit, homepages = research(gateway, NOW + timedelta(days=11))
    assert first[ORG].evidence[0].retrieved_at == NOW
    assert not results and not homepages and audit["cache_hits"] == 1
    assert gateway.calls == ["nav_public_access", "nav_feed"] and not audit["negative_coverage"]


def test_historical_run_cannot_reuse_future_retrieval():
    research(Gateway())
    gateway = Gateway(details={"detail-1": OSError()})
    results, audit, _ = research(gateway, NOW - timedelta(minutes=1))
    assert not results and audit["cache_hits"] == 0 and audit["unresolved_entries"] == 1
    assert not audit["negative_coverage"]


def test_inactive_feed_event_never_resurrects_cached_job():
    research(Gateway())
    gateway = Gateway([summary(status="INACTIVE")], details={})
    results, audit, _ = research(gateway)
    assert not results and audit["cache_hits"] == 0 and audit["details"] == 0
    assert not audit["negative_coverage"]


@pytest.mark.parametrize("state,scope", [(PublicState.AVAILABLE, "workplace"),
    (PublicState.NOT_AVAILABLE, "workplace"), (PublicState.AVAILABLE, "legal_entity")])
def test_cached_workplace_details_still_require_current_official_relation(state, scope):
    relation = Claim(claim_id="relation", organisation_number=ORG, section="leadership_workplaces",
        field_family="workplace", subject_id=CHILD, field="workplace.overordnetEnhet", value=ORG,
        state=PublicState.AVAILABLE, scope="workplace", verification_rule_id="brreg_json_pointer_v1",
        verification_score="1", evidence_ids=["relation-proof"], source_snapshot_ids=["relation-source"])
    research(Gateway(details={"detail-1": detail(employer=CHILD)}), target=targets(relation))
    current = relation.model_copy(update={"state": state, "scope": scope})
    results, audit, _ = research(Gateway(details={}), target=targets(current))
    assert audit["cache_hits"] == 1
    if state == PublicState.AVAILABLE and scope == "workplace":
        assert "relation-proof" in results[ORG].claims[0].evidence_ids
        assert "relation-source" in results[ORG].claims[0].source_snapshot_ids
    else:
        assert not results


@pytest.mark.parametrize("credential", [{"authorization": "Bearer SECRET"}, {"access_token": "SECRET"},
    {"description": "eyJprivate.secret.signature"}])
def test_credentials_are_never_written_to_detail_cache(private_nav_cache, credential):
    payload = detail()
    payload["ad_content"].update(credential)
    _, audit, _ = research(Gateway(details={"detail-1": payload}))
    assert audit["cache_writes"] == 0 and not list(private_nav_cache.iterdir())


@pytest.mark.parametrize("damage", ["directory_mode", "file_mode", "file_symlink", "root_symlink", "hash", "json"])
def test_private_cache_fails_safely_and_fresh_detail_can_recover(private_nav_cache, tmp_path, damage):
    research(Gateway())
    path = next(private_nav_cache.glob("*.json"))
    if damage == "directory_mode":
        private_nav_cache.chmod(0o755)
    elif damage == "file_mode":
        path.chmod(0o644)
    elif damage == "file_symlink":
        outside = tmp_path / "outside"
        path.replace(outside)
        path.symlink_to(outside)
    elif damage == "root_symlink":
        outside = tmp_path / "outside"
        private_nav_cache.replace(outside)
        private_nav_cache.symlink_to(outside, target_is_directory=True)
    elif damage == "hash":
        wrapped = json.loads(path.read_bytes())
        wrapped["record"]["version"] = 999
        path.write_text(json.dumps(wrapped))
    else:
        path.write_text("[]")
    results, audit, _ = research(Gateway())
    assert results[ORG].claims and audit["cache_hits"] == 0 and audit["cache_errors"] >= 1
    assert audit["details"] == 1 and not audit["negative_coverage"]


def test_explicit_cache_path_overrides_environment(private_nav_cache, tmp_path):
    explicit = tmp_path / "explicit"
    _, audit, _ = research(Gateway(), cache_dir=explicit)
    assert audit["cache_writes"] == 1 and not private_nav_cache.exists()
    assert len(list(explicit.glob("*.json"))) == 1


def test_relative_cache_paths_are_rooted_under_project_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(nav, "__file__", str(tmp_path / "signalpost" / "nav.py"))
    research(Gateway(), cache_dir="nav-details")
    assert len(list((tmp_path / "cache" / "nav-details").glob("*.json"))) == 1


def test_cache_disabled_with_explicit_empty_configuration(monkeypatch):
    monkeypatch.setenv("SIGNALPOST_NAV_CACHE", "")
    _, audit, _ = research(Gateway())
    assert audit["cache_hits"] == audit["cache_misses"] == audit["cache_writes"] == audit["cache_errors"] == 0


def test_default_cache_is_private_and_project_local(tmp_path, monkeypatch):
    monkeypatch.delenv("SIGNALPOST_NAV_CACHE")
    monkeypatch.setattr(nav, "__file__", str(tmp_path / "signalpost" / "nav.py"))
    _, audit, _ = research(Gateway())
    cache = tmp_path / ".signalpost-cache" / "nav"
    assert audit["cache_writes"] == 1 and audit["cache_errors"] == 0
    assert stat.S_IMODE(cache.stat().st_mode) == 0o700
    assert len(list(cache.glob("*.json"))) == 1


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


class SyntheticTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def request(self, url, headers, timeout):
        self.calls.append(url)
        return 200, {}, next(self.responses), url


async def allowed_robots(*args, **kwargs):
    return "allowed", None


def recording_gateway(tmp_path, monkeypatch, responses):
    monkeypatch.setattr(network, "datetime", FixedClock)
    gateway = NetworkGateway(transport=SyntheticTransport(responses), retries=0,
        record_http=str(tmp_path / "capture"))
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))
    monkeypatch.setattr(gateway, "set_rate_limit", lambda host, seconds: None)
    monkeypatch.setattr(gateway, "robots_decision", allowed_robots)
    return gateway


def replay_gateway(tmp_path, monkeypatch):
    gateway = NetworkGateway(replay_http=str(tmp_path / "capture"), retries=0)
    monkeypatch.setattr(gateway, "set_rate_limit", lambda host, seconds: None)
    monkeypatch.setattr(gateway, "robots_decision", allowed_robots)
    return gateway


@pytest.mark.parametrize("warm", [False, True])
def test_strict_replay_uses_recorded_cache_decisions_and_raw_inputs(tmp_path, monkeypatch, private_nav_cache, warm):
    if warm:
        research(Gateway())
    responses = [b"eyJabc.def.ghi", json.dumps({"items": [summary()]}).encode()]
    if not warm:
        responses.append(json.dumps(detail()).encode())
    gateway = recording_gateway(tmp_path, monkeypatch, responses)
    expected, expected_audit, expected_homepages = research(gateway)
    assert expected_audit["cache_hits"] == int(warm)
    gateway.http_recording.seal()
    shutil.rmtree(private_nav_cache)
    if not warm:
        research(Gateway(details={"detail-1": detail(employer=OTHER)}))
    else:
        monkeypatch.setenv("SIGNALPOST_NAV_CACHE", str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(nav._NavDetailCache, "__init__", lambda *args: pytest.fail("replay touched mutable cache"))
    offline = replay_gateway(tmp_path, monkeypatch)
    actual, actual_audit, actual_homepages = research(offline)
    assert actual == expected and actual_homepages == expected_homepages
    for key, value in expected_audit.items():
        if not key.endswith("elapsed_seconds"):
            assert actual_audit[key] == value
    offline.http_recording.assert_complete()
    assert offline.http_recording.hits == (2 if warm else 3)
    assert actual[ORG].evidence[0].retrieved_at == NOW
    assert not (tmp_path / "does-not-exist").exists()


@pytest.mark.parametrize("damage", ["missing_control", "bad_raw_input"])
def test_missing_or_damaged_replay_cache_input_fails_closed(tmp_path, monkeypatch, damage):
    research(Gateway())
    gateway = recording_gateway(tmp_path, monkeypatch,
        [b"eyJabc.def.ghi", json.dumps({"items": [summary()]}).encode()])
    research(gateway)
    execution = gateway.http_recording._execution()
    key = "nav_detail_cache:lookup:" + vacancy()
    if damage == "missing_control":
        del execution["controls"][key]
    else:
        execution["controls"][key]["record"]["body"] = "damaged"
    gateway.http_recording._write("execution.json", execution)
    gateway.http_recording.seal()
    offline = replay_gateway(tmp_path, monkeypatch)
    results, audit, _ = research(offline)
    assert not results and audit["unresolved_entries"] == 1 and audit["details"] == 0
    assert offline.http_recording.failures > 0
    with pytest.raises(ReplayError):
        offline.http_recording.assert_complete()


def test_replay_without_capture_cannot_fall_back_to_live_gateway():
    gateway = Gateway()
    gateway.replay_mode = True
    with pytest.raises(ReplayError, match="live fallback forbidden"):
        research(gateway)
    assert not gateway.calls
