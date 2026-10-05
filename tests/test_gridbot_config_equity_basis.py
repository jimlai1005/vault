"""EQUITY_SPOT_BASIS env parsing — gridbot circuit-breaker equity basis switch."""
import importlib

from hlvault.gridbot import config as cfg


def test_default_is_all():
    assert cfg.EQUITY_SPOT_BASIS == "all"


def test_env_usdc_is_accepted(monkeypatch):
    monkeypatch.setenv("EQUITY_SPOT_BASIS", " USDC  # comment")
    importlib.reload(cfg)
    try:
        assert cfg.EQUITY_SPOT_BASIS == "usdc"
    finally:
        monkeypatch.delenv("EQUITY_SPOT_BASIS")
        importlib.reload(cfg)


def test_env_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("EQUITY_SPOT_BASIS", "everything")
    try:
        import pytest
        with pytest.raises(ValueError, match="EQUITY_SPOT_BASIS"):
            importlib.reload(cfg)
    finally:
        monkeypatch.delenv("EQUITY_SPOT_BASIS")
        importlib.reload(cfg)
