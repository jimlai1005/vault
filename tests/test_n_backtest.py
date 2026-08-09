# tests/test_n_backtest.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_backtest as bt
import n_config as cfg

BAR = 3_600_000


def mk(rows):
    a = np.array(rows, dtype=float)
    return dict(t=np.arange(len(rows), dtype=np.int64) * BAR,
                o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3])


def ev(**kw):
    """預設：空方掃單（做空），掃單棒 j=1，針尖 110，pool 100。"""
    base = dict(event_id="e1", symbol="X", interval="1h", j=1,
                t_j=BAR, as_of=2 * BAR - 1, direction=-1, pool=100.0,
                sweep_high=110.0, sweep_low=95.0, close_j=98.0)
    base.update(kw)
    return base


POOLS_LOW = pd.DataFrame({"idx": [0], "kind": ["low"], "price": [80.0],
                          "t": [0], "confirm_t": [BAR - 1], "swept_at": [99]})


def test_sl_is_outside_wick_tip_by_frozen_buffer():
    """spec §6.2：做空 SL = 針尖 x (1 + 0.0011)。"""
    assert bt.stop_price(110.0, -1) == pytest.approx(110.0 * (1 + cfg.SL_BUFFER))
    assert bt.stop_price(90.0, +1) == pytest.approx(90.0 * (1 - cfg.SL_BUFFER))


def test_entry_is_next_bar_open():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 60, 62)]
              + [(62, 63, 61, 62)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["fill"] == pytest.approx(97.0)
    assert r["entry_leg"] == "taker"


def test_tp_is_nearest_unswept_opposite_pool():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 79, 82)]
              + [(82, 83, 81, 82)] * 30)
    pools = pd.DataFrame({"idx": [0, 0], "kind": ["low", "low"],
                          "price": [80.0, 60.0], "t": [0, 0],
                          "confirm_t": [BAR - 1, BAR - 1], "swept_at": [99, 99]})
    r = bt.simulate_event(bars, ev(), pools)
    assert r["exit_reason"] == "tp"
    assert r["exit_px"] == pytest.approx(80.0)      # 取較近的 80，非 60


def test_no_target_when_no_pool_beyond_entry():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 96, 97)]
              + [(97, 98, 96, 97)] * 30)
    pools = pd.DataFrame({"idx": [0], "kind": ["low"], "price": [99.0],
                          "t": [0], "confirm_t": [BAR - 1], "swept_at": [99]})
    r = bt.simulate_event(bars, ev(), pools)   # 池 99 高於 fill 97 -> 做空無效
    assert r["exit_reason"] == "no_target"
    assert r["R_net"] == 0.0


def test_risk_too_small_terminal():
    """fill 貼著 SL（<0.22%）-> risk_too_small，R=0，計入分母。"""
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98),
               (110.0, 111, 109, 110)] + [(110, 111, 109, 110)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "risk_too_small"
    assert r["R_net"] == 0.0


def test_invalidated_by_gap_when_open_beyond_sl():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (120, 121, 119, 120)]
              + [(120, 121, 119, 120)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "invalidated_by_gap"
    assert r["R_net"] == 0.0


def test_sl_priority_within_bar_is_pessimistic():
    """同棒同時觸及 SL 與 TP -> 記 SL（P12）。"""
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 111, 79, 90)]
              + [(90, 91, 89, 90)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "sl"


def test_time_stop_after_max_hold():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98)]
              + [(97, 98, 96, 97)] * (cfg.MAX_HOLD_BARS + 5))
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "time_stop"


def test_nodata_when_orderflow_missing():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 79, 82)]
              + [(82, 83, 81, 82)] * 30)
    r = bt.simulate_event(bars, ev(d_sweep=float("nan")), POOLS_LOW,
                          require_orderflow=True)
    assert r["exit_reason"] == "nodata"
    assert r["R_net"] == 0.0


def test_r_net_anchor_matches_m():
    """沿用 m_backtest.r_net_single，錨例不得變（spec §6.6）。

    推導（entry=100, sl=98, exit=103, dir=+1, 兩腿皆 taker）：
      risk  = |100 − 98| = 2
      fee   = TAKER + SLIP = 0.00045 + 0.0001 = 0.00055（進出各一次）
      gross = (103 − 100) / 2 = 1.5
      cost  = (0.00055×100 + 0.00055×103) / 2 = 0.055825
      r_net = 1.5 − 0.055825 = 1.444175
    """
    assert bt.r_net(100, 98, 103, 1) == pytest.approx(1.444175, abs=1e-9)


def test_r_net_cross_checks_against_m_maker_anchor():
    """交叉檢查：同一組價位改用 maker 進場，應得 M spec §5.3 記載的 1.464175。

    兩者差值恰為 maker/taker 的 fee_in 差：(0.00055 − 0.00015) × 100 / 2 = 0.02。
    這條確保 N 的成本記帳與 M 同源，沒有各算各的。
    """
    from m_backtest import r_net_single
    maker = r_net_single(100, 98, 103, 1, "maker")
    assert maker == pytest.approx(1.464175, abs=1e-9)
    assert maker - bt.r_net(100, 98, 103, 1) == pytest.approx(0.02, abs=1e-9)


def test_bullish_mirror_end_to_end():
    """多方掃單：針尖在下，SL 在針尖下方，TP 取上方最近未掃池。"""
    bars = mk([(100, 101, 99, 100), (95, 105, 90, 102), (103, 121, 102, 120)]
              + [(120, 121, 119, 120)] * 30)
    pools_hi = pd.DataFrame({"idx": [0], "kind": ["high"], "price": [120.0],
                             "t": [0], "confirm_t": [BAR - 1], "swept_at": [99]})
    r = bt.simulate_event(bars, ev(direction=1, pool=100.0, sweep_low=90.0,
                                   sweep_high=105.0, close_j=102.0), pools_hi)
    assert r["fill"] == pytest.approx(103.0)
    assert r["exit_reason"] == "tp"
    assert r["exit_px"] == pytest.approx(120.0)
    assert r["R_net"] > 0
