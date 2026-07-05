import json

import pytest

from compound import config


def test_load_env_and_overrides(tmp_path):
    env = tmp_path / ".env"
    env.write_text("BFX_API_KEY=abc\nBFX_API_SECRET='sec'\n# comment\n\n")
    overrides = tmp_path / "params.json"
    overrides.write_text(json.dumps({"tick_seconds": 60, "fee": 0.15}))
    cfg = config.load(env_path=env, overrides_path=overrides)
    assert cfg.api_key == "abc"
    assert cfg.api_secret == "sec"
    assert cfg.tick_seconds == 60


def test_secrets_never_from_json(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    overrides = tmp_path / "params.json"
    overrides.write_text(json.dumps({"api_key": "evil"}))
    cfg = config.load(env_path=env, overrides_path=overrides)
    assert cfg.api_key == ""


def test_unknown_key_rejected(tmp_path):
    overrides = tmp_path / "params.json"
    overrides.write_text(json.dumps({"typo_field": 1}))
    with pytest.raises(ValueError, match="typo_field"):
        config.load(env_path=tmp_path / ".env", overrides_path=overrides)


def test_missing_credentials_raise():
    cfg = config.Config()
    with pytest.raises(RuntimeError, match="BFX_API_KEY"):
        cfg.require_credentials()


def test_live_guardrails_default_on():
    cfg = config.Config()
    assert cfg.live_test_mode is True
    assert cfg.live_test_max_offer <= 300
    assert cfg.live_test_max_period == 2
