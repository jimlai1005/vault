"""M-G0 基準忠實度（spec §6.2）。四項斷言 a/b/c/d。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pytest

import m_config as cfg
import m_verify_baseline as mvb


def test_verify_baseline_reads_frozen_table_from_config(monkeypatch):
    """M-G0a 的 guard 必須真的綁在 m_config 上，不能是複製的常數。"""
    assert mvb.SL_LEVEL_OVER_XA is cfg.SL_LEVEL_OVER_XA


def test_all_assertions_pass():
    """M-G0 a/b/c/d 全過（main 回傳 0）。"""
    assert mvb.main() == 0


def test_mg0a_fails_when_frozen_table_is_tampered(monkeypatch):
    """改動凍結表必須讓 M-G0a 失敗——否則 regression guard 形同虛設。"""
    tampered = dict(cfg.SL_LEVEL_OVER_XA)
    tampered["bat"] = 1.0                      # 觀測值是 1.13
    monkeypatch.setattr(mvb, "SL_LEVEL_OVER_XA", tampered)
    assert mvb.main() != 0


@pytest.mark.parametrize("label,key", list(mvb.LABEL_TO_KEY.items()))
def test_fixture_labels_map_to_known_patterns(label, key):
    assert key in cfg.PATTERNS
