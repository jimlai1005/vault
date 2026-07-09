from __future__ import annotations

import importlib
from pathlib import Path

import dotenv
import pytest


def _reload_config(monkeypatch, env_path: str | None):
    """Reload hlvault.cta.config with CTA_ENV_FILE set (or unset)."""
    import hlvault.cta.config as cfg
    if env_path is None:
        monkeypatch.delenv("CTA_ENV_FILE", raising=False)
    else:
        monkeypatch.setenv("CTA_ENV_FILE", env_path)
    return importlib.reload(cfg)


@pytest.fixture(autouse=True)
def _restore_default_config():
    yield
    import hlvault.cta.config as cfg
    import os
    os.environ.pop("CTA_ENV_FILE", None)
    importlib.reload(cfg)  # leave wallet-A config loaded for the rest of the suite


# ---- backward compatibility (wallet A) --------------------------------
def test_default_env_file_is_env_cta(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg._ENV_PATH.name == ".env.cta"

def test_instance_label_default_cta(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.INSTANCE_LABEL == "cta"

def test_state_file_default_unchanged(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.STATE_FILE.name == "cta_state.json"
    assert cfg.STATE_FILE.parent.name == "cache"

def test_cache_dir_default_unchanged(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.CACHE_DIR.name == "cta_live"

def test_coin_universe_default_unchanged(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.COIN_UNIVERSE == ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP"]

def test_beta_disabled_by_default(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.BETA_TARGET_FRACTION == 0.0


# ---- instance B derivation --------------------------------------------
def test_instance_label_and_state_file_for_cta2(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta2"
    env.write_text("COIN_UNIVERSE=ETH,SOL,HYPE,DOGE,XRP\nBETA_TARGET_FRACTION=0.25\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.INSTANCE_LABEL == "cta2"
    assert cfg.STATE_FILE.name == "cta2_state.json"
    assert cfg.CACHE_DIR.name == "cta2_live"
    assert cfg.BETA_TARGET_FRACTION == 0.25
    assert "BTC" not in cfg.COIN_UNIVERSE

def test_absolute_env_path_label(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta2"
    env.write_text("BETA_TARGET_FRACTION=0.25\nCOIN_UNIVERSE=ETH,SOL\n")
    cfg = _reload_config(monkeypatch, str(env.resolve()))
    assert cfg.INSTANCE_LABEL == "cta2"


# ---- one-coin-one-owner forcing function ------------------------------
def test_beta_coin_in_universe_raises(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta2"
    env.write_text("BETA_TARGET_FRACTION=0.25\nBETA_COIN=BTC\nCOIN_UNIVERSE=BTC,ETH,SOL\n")
    with pytest.raises(RuntimeError, match="one-coin-one-owner|COIN_UNIVERSE"):
        _reload_config(monkeypatch, str(env))

def test_beta_coin_in_universe_ok_when_beta_off(monkeypatch, tmp_path):
    # fraction 0 => guard does not fire even if BETA_COIN is in the universe
    env = tmp_path / ".env.cta"  # wallet-A-shaped: BTC in universe, beta off
    env.write_text("BETA_TARGET_FRACTION=0\nCOIN_UNIVERSE=BTC,ETH\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.BETA_TARGET_FRACTION == 0.0


# ---- INSTANCE_LABEL must never silently default (review finding, Low) -----
def test_env_file_without_suffix_raises(monkeypatch, tmp_path):
    # A CTA_ENV_FILE with no suffix (e.g. no trailing ".cta"/".cta2") must not
    # silently become INSTANCE_LABEL "cta" -- that would collide with wallet
    # A's cta_state.json. Must fail loudly instead.
    env = tmp_path / "ctafile_without_a_suffix"
    env.write_text("WALLET_ADDRESS=0xabc\n")
    with pytest.raises(RuntimeError, match="INSTANCE_LABEL|suffix"):
        _reload_config(monkeypatch, str(env))


# ---- COINALYZE_API_KEY instance override (review finding, Medium) ---------
# These tests must NEVER read the real .env.research file's content (it holds
# a real API key -- CLAUDE.md red line). dotenv.dotenv_values is monkeypatched
# so any read of the research path returns a fabricated dict instead of
# touching the real file; reads of the tmp_path instance file still go
# through the real parser (it holds only test-fixture text we wrote).
def _patch_research_fallback(monkeypatch, fake_key: str):
    import hlvault.cta.config as cfg_mod
    real_dotenv_values = dotenv.dotenv_values
    research_path = cfg_mod._ROOT / ".env.research"

    def _fake(path, *a, **k):
        if Path(path) == research_path:
            return {"COINALYZE_API_KEY": fake_key}
        return real_dotenv_values(path, *a, **k)

    monkeypatch.setattr(dotenv, "dotenv_values", _fake)


def test_coinalyze_key_prefers_instance_env_override(monkeypatch, tmp_path):
    _patch_research_fallback(monkeypatch, "research-fallback-key")
    env = tmp_path / ".env.cta2"
    env.write_text("COIN_UNIVERSE=ETH,SOL\nCOINALYZE_API_KEY=instance-key-abc\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.COINALYZE_API_KEY == "instance-key-abc"


def test_coinalyze_key_falls_back_to_research_when_absent(monkeypatch, tmp_path):
    _patch_research_fallback(monkeypatch, "research-fallback-key")
    env = tmp_path / ".env.cta2"
    env.write_text("COIN_UNIVERSE=ETH,SOL\n")  # no COINALYZE_API_KEY override
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.COINALYZE_API_KEY == "research-fallback-key"
