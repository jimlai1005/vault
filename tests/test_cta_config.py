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


# ---- B1 vol-target sizing: SIGMA_* defaults + import-time validity guard ---

def test_sigma_target_default_is_none_b1_off(monkeypatch):
    # Backward compatibility (wallet A / cta2): no env key -> B1 disabled.
    cfg = _reload_config(monkeypatch, None)
    assert cfg.SIGMA_TARGET is None
    assert cfg.SIGMA_SPAN_BARS == 180
    assert cfg.SIGMA_CLIP_LO == 0.25
    assert cfg.SIGMA_CLIP_HI == 1.0


def test_sigma_target_empty_string_means_off(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta3"
    env.write_text("SIGMA_TARGET=\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.SIGMA_TARGET is None


def test_sigma_target_valid_value_enables(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta3"
    env.write_text("SIGMA_TARGET=0.60\nSIGMA_SPAN_BARS=90\nSIGMA_CLIP_LO=0.5\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.SIGMA_TARGET == 0.60
    assert cfg.SIGMA_SPAN_BARS == 90
    assert cfg.SIGMA_CLIP_LO == 0.5
    assert cfg.SIGMA_CLIP_HI == 1.0   # never env-configurable (cap-only invariant)


@pytest.mark.parametrize("val", ["0", "-0.5"])
def test_sigma_target_nonpositive_raises_at_import(monkeypatch, tmp_path, val):
    # A set-but-nonsensical SIGMA_TARGET must refuse to start, not be
    # silently repaired downstream.
    env = tmp_path / ".env.cta3"
    env.write_text(f"SIGMA_TARGET={val}\n")
    with pytest.raises(RuntimeError, match="SIGMA_TARGET"):
        _reload_config(monkeypatch, str(env))


@pytest.mark.parametrize("clip_lo", ["0", "-0.1", "1.5"])
def test_sigma_clip_lo_out_of_range_raises_when_b1_on(monkeypatch, tmp_path, clip_lo):
    env = tmp_path / ".env.cta3"
    env.write_text(f"SIGMA_TARGET=0.60\nSIGMA_CLIP_LO={clip_lo}\n")
    with pytest.raises(RuntimeError, match="SIGMA_CLIP_LO"):
        _reload_config(monkeypatch, str(env))


def test_sigma_guard_does_not_fire_when_sigma_target_unset(monkeypatch, tmp_path):
    # Negative assertion: with SIGMA_TARGET unset the guard must NOT trigger,
    # even in the presence of an out-of-range SIGMA_CLIP_LO -- the unset path
    # must stay bit-identical to pre-B1 behavior (no new failure mode for the
    # two existing live instances, whose env files never set any SIGMA_* key).
    env = tmp_path / ".env.cta3"
    env.write_text("SIGMA_CLIP_LO=0\n")   # invalid, but B1 is off
    cfg = _reload_config(monkeypatch, str(env))   # must not raise
    assert cfg.SIGMA_TARGET is None
    assert cfg.SIGMA_CLIP_LO == 0.0
