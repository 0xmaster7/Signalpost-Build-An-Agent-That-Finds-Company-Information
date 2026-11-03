import json
import socket

import pytest

from signalpost import network, run


@pytest.mark.parametrize("dns_failure", [False, True])
def test_recorded_pipeline_replays_identical_complete_envelopes(tmp_path, monkeypatch, dns_failure):
    original_gateway = network.NetworkGateway
    calls = []
    organisation = "923609016"

    class Transport:
        async def request(self, url, headers, timeout):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return 200, {}, b"User-agent: *\nAllow: /\n", url
            if "/api/publicToken" in url:
                return 200, {}, b"eyJfixture.public.token", url
            if "pam-stilling-feed.nav.no" in url:
                body = {"items": []}
            elif "query.wikidata.org" in url:
                body = {"results": {"bindings": []}}
            elif "/regnskapsregisteret/regnskap/" in url:
                body = []
            elif "/roller" in url:
                body = {"rollegrupper": []}
            elif "/underenheter?" in url:
                body = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
            else:
                body = {"organisasjonsnummer": organisation, "navn": "Deterministic Fixture AS",
                    "organisasjonsform": {"kode": "AS"}}
            return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url

    def gateway(**kwargs):
        result = original_gateway(transport=Transport(), **kwargs)

        async def no_wait(*args, **options):
            return None

        result._pace = no_wait
        return result

    monkeypatch.setattr(run, "NetworkGateway", gateway)
    def resolve(*args, **kwargs):
        if dns_failure:
            raise network.NetworkPolicyError("unresolved")
        return ("8.8.8.8",)

    monkeypatch.setattr(network, "validate_public_host", resolve)
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"organisation_number": organisation}) + "\n")
    capture = tmp_path / "private-capture"

    def arguments(name):
        return ["--input", str(source), "--output", str(tmp_path / (name + ".jsonl")),
            "--state-output", str(tmp_path / (name + ".state")),
            "--checkpoint", str(tmp_path / (name + ".sqlite")),
            "--live-brreg", "--live-websites", "--no-keyless-websites"]

    assert run.main(arguments("live") + ["--record-http", str(capture)]) == 0
    assert bool(calls) is not dns_failure

    def forbidden(*args, **kwargs):
        raise AssertionError("hermetic replay attempted network access")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(Transport, "request", forbidden)
    assert run.main(arguments("replay") + ["--replay-http", str(capture)]) == 0
    assert (tmp_path / "live.jsonl").read_bytes() == (tmp_path / "replay.jsonl").read_bytes()
    assert (tmp_path / "live.state").read_bytes() == (tmp_path / "replay.state").read_bytes()
