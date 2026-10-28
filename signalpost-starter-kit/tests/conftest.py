import ipaddress
import socket

import pytest


@pytest.fixture(autouse=True)
def isolated_research_environment(monkeypatch, tmp_path):
    """Unit tests use private caches and cannot accidentally contact public sources."""
    monkeypatch.setenv("SIGNALPOST_OCR_CACHE", str(tmp_path / "ocr-cache"))
    original_lookup = socket.getaddrinfo
    original_connect = socket.socket.connect

    def local_host(host):
        if host in {"localhost", "localhost.localdomain", None}:
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def lookup(host, *args, **kwargs):
        if not local_host(host):
            raise OSError("public DNS is forbidden in unit tests; supply a source fixture")
        return original_lookup(host, *args, **kwargs)

    def connect(connection, address):
        if isinstance(address, tuple) and not local_host(address[0]):
            raise OSError("public HTTP is forbidden in unit tests; supply a source fixture")
        return original_connect(connection, address)

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket.socket, "connect", connect)
