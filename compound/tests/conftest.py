"""Global test fixtures.

Principle: tests must NEVER touch the real world. The autouse fixture below makes
any real socket connection fail the test, so a new test can't accidentally reach
Bitfinex even if a real .env with live keys sits in the working tree.
"""
import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(self, *args, **kwargs):
        raise RuntimeError(
            "Test attempted a real network connection — forbidden. Mock the transport."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch):
    """Ensure ambient credentials never leak into tests."""
    monkeypatch.delenv("BFX_API_KEY", raising=False)
    monkeypatch.delenv("BFX_API_SECRET", raising=False)


@pytest.fixture
def fake_config():
    from compound.config import Config

    return Config(api_key="test_key", api_secret="test_secret")
