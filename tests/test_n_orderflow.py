import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_orderflow as of

BAR = 3_600_000


def trades(rows):
    """rows: (time, price, qty, is_buyer_maker)。schema = Binance futures trades。"""
    a = pd.DataFrame(rows, columns=["time", "price", "qty", "is_buyer_maker"])
    a["id"] = np.arange(len(a))
    a["quote_qty"] = a["price"] * a["qty"]
    return a[["id", "price", "qty", "quote_qty", "time", "is_buyer_maker"]]


def test_bar_aggregation_delta_sign():
    """P2：is_buyer_maker=True -> 主動方是賣方 -> delta 為負。"""
    df = trades([(0, 10.0, 3.0, False),      # 主動買 30
                 (1, 10.0, 1.0, True)])      # 主動賣 10
    b = of.build_bars(df, BAR)
    assert len(b) == 1
    assert b["delta"].iloc[0] == pytest.approx(20.0)
    assert b["notional"].iloc[0] == pytest.approx(40.0)


def test_bar_aggregation_uses_notional_not_base():
    """P1：一律 USDT notional，不是 base 量。"""
    df = trades([(0, 100.0, 2.0, False)])
    assert of.build_bars(df, BAR)["notional"].iloc[0] == pytest.approx(200.0)


def test_bar_assignment_is_left_closed():
    """P3：bar = transact_time // BAR_MS，左閉右開。"""
    df = trades([(BAR - 1, 10.0, 1.0, False), (BAR, 10.0, 1.0, False)])
    b = of.build_bars(df, BAR)
    assert list(b["t"]) == [0, BAR]


def test_trade_count_is_row_count():
    """trades 是逐筆原始成交（不聚合），故筆數 = 列數。

    對比：aggTrades 的列數不是筆數，且其單一時戳會讓跨棒邊界的聚合被錯歸
    （spec §3.2.1 修訂 A1 的成因）——這正是本案改用 trades 的理由。
    """
    df = trades([(0, 10.0, 1.0, False), (1, 10.0, 2.0, True),
                 (2, 10.0, 3.0, False)])
    assert of.build_bars(df, BAR)["n_trades"].iloc[0] == 3


def test_cvd_is_cumulative_and_starts_at_first_bar():
    df = trades([(0, 10.0, 1.0, False), (BAR, 10.0, 3.0, True)])
    b = of.build_bars(df, BAR)
    assert list(b["cvd"]) == pytest.approx([10.0, -20.0])


def test_sweep_delta_counts_only_at_or_above_pool_for_bearish():
    """P4：空方掃單取 price >= P（含等號）。"""
    df = trades([(0, 9.0, 1.0, False),    # 池下，不算
                 (1, 10.0, 2.0, False),   # 等於池 -> 算（+20）
                 (2, 11.0, 1.0, True)])   # 池上主動賣 -> 算（-11）
    idx = of.build_index(df, BAR)
    d, v = of.sweep_delta(df, idx, bar_t=0, pool=10.0, direction=-1)
    assert d == pytest.approx(20.0 - 11.0)
    assert v == pytest.approx(20.0 + 11.0)


def test_sweep_delta_mirrors_for_bullish():
    df = trades([(0, 11.0, 1.0, False),   # 池上，不算
                 (1, 10.0, 2.0, True),    # 等於池 -> 算（-20）
                 (2, 9.0, 1.0, False)])   # 池下主動買 -> 算（+9）
    idx = of.build_index(df, BAR)
    d, v = of.sweep_delta(df, idx, bar_t=0, pool=10.0, direction=+1)
    assert d == pytest.approx(-20.0 + 9.0)


def test_sweep_delta_empty_bar_returns_nan():
    df = trades([(0, 10.0, 1.0, False)])
    idx = of.build_index(df, BAR)
    d, v = of.sweep_delta(df, idx, bar_t=5 * BAR, pool=10.0, direction=-1)
    assert np.isnan(d) and np.isnan(v)


def test_build_index_requires_sorted_time():
    df = trades([(BAR, 10.0, 1.0, False), (0, 10.0, 1.0, False)])
    with pytest.raises(ValueError):
        of.build_index(df, BAR)


@pytest.mark.parametrize("k", [3, 5, 8])
def test_no_lookahead_truncation(k):
    """截斷式斷言：只餵前 k 根棒的成交，第 k-1 根的聚合值必須不變。"""
    rows = [(i * BAR + 1, 10.0 + i, 1.0 + i, i % 2 == 0) for i in range(10)]
    full = of.build_bars(trades(rows), BAR)
    trunc = of.build_bars(trades(rows[:k]), BAR)
    for col in ("delta", "notional", "n_trades", "cvd"):
        assert trunc[col].iloc[-1] == pytest.approx(full[col].iloc[k - 1])
