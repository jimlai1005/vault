import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-fail any real socket connection from any test (CLAUDE.md #4)."""

    def guard(*a, **k):
        raise RuntimeError("Network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
