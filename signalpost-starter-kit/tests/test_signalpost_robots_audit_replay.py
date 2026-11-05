import asyncio
from dataclasses import asdict

from signalpost import network


def test_concurrent_robots_observations_are_origin_scoped_and_replayable(tmp_path, monkeypatch):
    class Transport:
        async def request(self, url, headers, timeout):
            await asyncio.sleep(0)
            if "broken.example" in url:
                raise ConnectionRefusedError("private connection detail")
            return 404, {}, b"not found", url

    monkeypatch.setattr(network, "validate_public_host", lambda *args, **kwargs: ("8.8.8.8",))
    capture = tmp_path / "capture"
    live = network.NetworkGateway(transport=Transport(), record_http=str(capture))

    async def no_wait(*args, **kwargs):
        return None

    live._pace = no_wait

    async def run(gateway):
        return await asyncio.gather(
            gateway.robots_decision("https://broken.example/company", "Audit test"),
            gateway.robots_decision("https://empty.example/company", "Audit test"))

    assert asyncio.run(run(live)) == [("unreachable", None), ("allowed", None)]
    broken = live.robots_observations("https://broken.example/")
    empty = live.robots_observations("https://empty.example/")
    assert len(broken) == 2 and len(empty) == 1
    assert all(entry.error_type == "ConnectionRefusedError" for entry in broken)
    assert all("broken.example" in entry.url for entry in broken)
    assert empty[0].status == 404
    live.http_recording.seal()

    def forbidden(*args, **kwargs):
        raise AssertionError("replay attempted transport")

    monkeypatch.setattr(Transport, "request", forbidden)
    replay = network.NetworkGateway(transport=Transport(), replay_http=str(capture))
    assert asyncio.run(run(replay)) == [("unreachable", None), ("allowed", None)]
    assert [asdict(entry) for entry in replay.robots_observations("https://broken.example/")] == [
        asdict(entry) for entry in broken]
    assert [asdict(entry) for entry in replay.robots_observations("https://empty.example/")] == [
        asdict(entry) for entry in empty]
    replay.http_recording.assert_complete()
