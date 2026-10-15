import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_reconcile as rec

BAR = 3_600_000


def mk_trades(rows):
    """schema = Binance futures trades（id, price, qty, quote_qty, time, flag）。"""
    a = pd.DataFrame(rows, columns=["time", "price", "qty", "is_buyer_maker"])
    a["id"] = np.arange(len(a))
    a["quote_qty"] = a["price"] * a["qty"]
    return a[["id", "price", "qty", "quote_qty", "time", "is_buyer_maker"]]


def test_taker_buy_base_matches_when_consistent():
    """主動買量 = is_buyer_maker 為 False 的 quantity 總和（base 量，非 notional）。"""
    tr = mk_trades([(0, 10.0, 3.0, False), (1, 10.0, 5.0, True),
                    (BAR, 10.0, 2.0, False)])
    tbv = pd.DataFrame({"t": [0, BAR], "tbv": [3.0, 2.0]})
    out = rec.reconcile(tr, tbv, BAR)
    assert out["n_bars"] == 2
    assert out["max_rel_err"] == pytest.approx(0.0)
    assert out["pass"] is True


def test_detects_mismatch():
    tr = mk_trades([(0, 10.0, 3.0, False)])
    tbv = pd.DataFrame({"t": [0], "tbv": [4.0]})
    out = rec.reconcile(tr, tbv, BAR)
    assert out["pass"] is False
    assert out["max_rel_err"] > 0.1


def test_only_compares_overlapping_bars():
    """kline 有、aggTrades 沒有的棒不列入比較（避免月界假警報）。"""
    tr = mk_trades([(0, 10.0, 3.0, False)])
    tbv = pd.DataFrame({"t": [0, BAR, 2 * BAR], "tbv": [3.0, 9.9, 9.9]})
    out = rec.reconcile(tr, tbv, BAR)
    assert out["n_bars"] == 1 and out["pass"] is True


def test_zero_volume_bar_uses_absolute_tolerance():
    """兩邊皆為 0 的棒不得因除以 0 而判失敗。"""
    tr = mk_trades([(0, 10.0, 0.0, False)])
    tbv = pd.DataFrame({"t": [0], "tbv": [0.0]})
    assert rec.reconcile(tr, tbv, BAR)["pass"] is True
