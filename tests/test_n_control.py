import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_control as nc
import n_features as nf
import n_stats as ns


def test_control_arm_uses_identical_filter_function_object():
    """結構性公平保證：兩臂共用同一個函式物件，不是兩份平行實作。"""
    assert nc.FILTER_ENTRYPOINT is nf.arm_pass


def test_weights_renormalize_to_one_per_parent():
    """P15：每個母事件的存活對照，權重合計恰為 1。"""
    ct = pd.DataFrame({"parent_id": ["a", "a", "a", "b", "b"],
                       "R_net": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = nc.renormalize_weights(ct)
    s = out.groupby("parent_id")["weight"].sum()
    assert s.min() == pytest.approx(1.0) and s.max() == pytest.approx(1.0)


def test_weights_handle_single_survivor():
    ct = pd.DataFrame({"parent_id": ["a"], "R_net": [1.0]})
    assert nc.renormalize_weights(ct)["weight"].iloc[0] == pytest.approx(1.0)


def test_exposure_ratio_and_band():
    """P15：曝險比 = 對照加權曝險 / 事件臂事件數，出帶即作廢。"""
    assert ns.exposure_ratio(n_events=100, ctl_weight_sum=100.0) == pytest.approx(1.0)
    assert ns.exposure_ok(1.00) is True
    assert ns.exposure_ok(0.94) is False
    assert ns.exposure_ok(1.06) is False


def test_event_level_mean_is_exposure_invariant():
    """P16：對照臂複製一份（曝險加倍）不改變每事件 E[R]。"""
    ct = pd.DataFrame({"parent_id": ["a", "a"], "R_net": [1.0, 3.0]})
    ct = nc.renormalize_weights(ct)
    m1 = ns.weighted_event_mean(ct)
    ct2 = pd.concat([ct, ct], ignore_index=True)
    ct2 = nc.renormalize_weights(ct2)
    assert ns.weighted_event_mean(ct2) == pytest.approx(m1)


def test_cluster_bootstrap_is_deterministic():
    df = pd.DataFrame({"symbol": ["A"] * 5 + ["B"] * 5,
                       "R_net": list(range(10)), "weight": [1.0] * 10})
    a = ns.cluster_boot_lower95(df, df, "T1", B=200)
    b = ns.cluster_boot_lower95(df, df, "T1", B=200)
    assert a == pytest.approx(b)


def test_cluster_bootstrap_zero_diff_for_identical_arms():
    df = pd.DataFrame({"symbol": ["A"] * 5 + ["B"] * 5,
                       "R_net": list(range(10)), "weight": [1.0] * 10})
    assert ns.cluster_boot_lower95(df, df, "T2", B=200) == pytest.approx(0.0)


def test_control_delta_range_matches_spec():
    import n_config as cfg
    assert cfg.CONTROL_DELTA_MIN == cfg.MAX_HOLD_BARS + 1
    assert cfg.CONTROL_DELTA_MAX == 300
