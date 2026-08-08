import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd
import pytest

import m_config as cfg
import m_backtest as bt

H = 3_600_000


def _bars(rows):
    """rows: list of (o, h, l, c)；t 從 0 起每根 1h。"""
    df = pd.DataFrame(rows, columns=["o", "h", "l", "c"])
    df.insert(0, "t", [i * H for i in range(len(rows))])
    df["v"] = 1.0
    df["qv"] = 1.0
    return df


def _ev(**kw):
    """最小事件。as_of = 收盤時間戳（bar0 的收盤 = H-1）→ bar1 起可交易。"""
    base = dict(event_id="E", symbol="X", interval="1h", pattern="gartley",
                direction=1, as_of=H - 1, prz_low=95.0, prz_high=100.0,
                sl=90.0, p_X=80.0, p_A=120.0, p_B=95.0, p_C=110.0)
    base.update(kw)
    return base


def test_prz_already_breached():
    # 確認棒（bar0）收盤 99 <= prz_high 100 → 不掛單
    bars = _bars([(101, 102, 98, 99)] + [(99, 100, 98, 99)] * 5)
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "prz_already_breached"
    assert r["R_net"] == 0.0
    assert r["term_t"] == H - 1                      # as_of 當日


def test_maker_fill_then_tp1():
    # bar0 收盤 105（>100 過守門）；bar1 low 觸及 100 → maker 成交；
    # bar2 high 到 tp1 → taker 出場
    ev = _ev()
    extreme = 120.0                                  # max(X,A,B,C)
    d = 100.0
    tp1 = d + cfg.TP_FACTORS[0] * (extreme - d)      # 100 + 0.382*20 = 107.64
    bars = _bars([(104, 106, 103, 105),
                  (103, 104, 99.5, 101),             # low 99.5 <= 100 → fill@100
                  (102, 108, 101, 106)])             # high 108 >= 107.64 → tp1
    r = bt.simulate_event(bars, ev)
    assert r["exit_reason"] == "tp1"
    assert r["fill"] == 100.0 and r["entry_leg"] == "maker"
    # spec §5.3：cost_abs = maker*fill + (taker+slip)*tp1
    cost = cfg.MAKER * 100.0 + (cfg.TAKER + cfg.SLIP) * tp1
    expect = (tp1 - 100.0) / 10.0 - cost / 10.0      # risk = |100-90| = 10
    assert abs(r["R_net"] - expect) < 1e-12
    assert r["term_t"] == bars["t"].iloc[2] + H - 1   # 終止 = 出場棒【收盤】時間


def test_gap_fill_is_taker_and_bar_participates_in_exit():
    # bar1 開盤 97 <= 100（跳空進 PRZ 但 > sl 90）→ taker 成交@97；
    # 同一根 low 89 <= 90 → 同棒 SL（悲觀，M10）
    bars = _bars([(104, 106, 103, 105),
                  (97, 98, 89, 95)])
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "sl"
    assert r["fill"] == 97.0 and r["entry_leg"] == "taker"
    # SL gap-through：開盤 97 > sl → 出在 sl=90
    cost = (cfg.TAKER + cfg.SLIP) * 97.0 + (cfg.TAKER + cfg.SLIP) * 90.0
    expect = (90.0 - 97.0) / 7.0 - cost / 7.0        # risk = |97-90| = 7
    assert abs(r["R_net"] - expect) < 1e-12


def test_invalidated_by_gap():
    # bar1 開盤 89 <= sl 90 → 作廢不進場
    bars = _bars([(104, 106, 103, 105), (89, 95, 88, 94)])
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "invalidated_by_gap"
    assert r["R_net"] == 0.0
    assert r["term_t"] == bars["t"].iloc[1] + H - 1   # 終止 = 跳空棒【收盤】時間


def test_no_fill_after_ttl():
    rows = [(104, 106, 103, 105)] + [(103, 104, 101, 102)] * (cfg.TTL_BARS + 3)
    bars = _bars(rows)
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "no_fill"
    assert r["R_net"] == 0.0
    # 終止日 = TTL 最後一根的收盤
    assert r["term_t"] == bars["t"].iloc[cfg.TTL_BARS] + H - 1


def test_time_stop_exits_at_close():
    rows = [(104, 106, 103, 105), (103, 104, 99.5, 101)]      # bar1 fill@100
    rows += [(101, 102, 100.5, 101.5)] * (cfg.MAX_HOLD_BARS + 5)
    bars = _bars(rows)
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "time_stop"
    j = 1 + cfg.MAX_HOLD_BARS - 1                    # fill 棒起算第 100 根
    assert r["exit_px"] == bars["c"].iloc[j]
    assert r["term_t"] == bars["t"].iloc[j] + H - 1


def test_censored_marks_to_market():
    rows = [(104, 106, 103, 105), (103, 104, 99.5, 101), (101, 103, 100.5, 102.5)]
    bars = _bars(rows)                               # 資料在持倉中結束
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "censored"
    assert r["exit_px"] == 102.5                     # 最後收盤 mark-to-market
    assert r["term_t"] == bars["t"].iloc[2] + H - 1


def test_bearish_mirror():
    # bearish：direction=-1，trigger = prz_low，SL 在上方
    ev = _ev(direction=-1, prz_low=100.0, prz_high=105.0, sl=110.0,
             p_X=120.0, p_A=80.0, p_B=105.0, p_C=90.0)
    extreme = 80.0                                   # min(X,A,B,C)
    d = 100.0
    tp1 = d - cfg.TP_FACTORS[0] * (d - extreme)      # 100 - 0.382*20 = 92.36
    bars = _bars([(97, 98, 95, 96),                  # 收盤 96 < trigger 100 → 過守門
                  (98, 100.5, 97, 99),               # high 100.5 >= 100 → fill@100
                  (99, 100, 92, 93)])                # low 92 <= 92.36 → tp1
    r = bt.simulate_event(bars, ev)
    assert r["exit_reason"] == "tp1"
    cost = cfg.MAKER * 100.0 + (cfg.TAKER + cfg.SLIP) * tp1
    expect = (100.0 - tp1) / 10.0 - cost / 10.0
    assert abs(r["R_net"] - expect) < 1e-12


def test_anchor_single_leg():
    """spec §5.3 數值錨例：entry=100, sl=98, exit=103 → R_net = 1.464175。"""
    r = bt.r_net_single(entry=100.0, sl=98.0, exit_px=103.0, direction=1,
                        entry_leg="maker")
    assert abs(r - 1.464175) < 1e-9


def test_stress_multiplier():
    """M-G7：fee×1.5、slip×1.5。"""
    r = bt.r_net_single(entry=100.0, sl=98.0, exit_px=103.0, direction=1,
                        entry_leg="maker", stress=cfg.STRESS_MULT)
    cost = 1.5 * (cfg.MAKER * 100.0 + (cfg.TAKER + cfg.SLIP) * 103.0)
    assert abs(r - ((103.0 - 100.0) / 2.0 - cost / 2.0)) < 1e-12
