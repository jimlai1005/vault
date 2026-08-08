"""Sub-project N — N-G0 跨源對帳。spec §8。

aggTrades 重建的「主動買量」必須與 Binance kline 的 takerBuyVolume 逐棒相符。
這是動用 aggTrades 前的唯一保險：符號約定錯了、棒歸屬錯了、或解析錯位，
都會在這裡爆掉。不過即全案作廢（spec §8.1）。

注意：kline 的 takerBuyVolume 是【base 量】，不是 notional——此處刻意用
base 量比對，才能與 Binance 的定義對齊（與 §5 特徵用 notional 是兩回事）。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402

REL_TOL = 1e-9
ABS_TOL = 1e-6


def taker_buy_base_by_bar(trades, bar_ms):
    """trades → 每棒的主動買【base 量】。is_buyer_maker=False 才是主動買。"""
    m = ~trades["is_buyer_maker"].to_numpy()
    t = trades["time"].to_numpy(dtype=np.int64)
    return (pd.DataFrame({"t": (t[m] // int(bar_ms)) * int(bar_ms),
                          "tbv_agg": trades["qty"].to_numpy(dtype=float)[m]})
            .groupby("t", sort=True).sum().reset_index())


def reconcile(trades, kline_taker, bar_ms):
    """回傳 dict(n_bars, max_rel_err, worst_t, pass)。只比對兩邊都有的棒。"""
    a = taker_buy_base_by_bar(trades, bar_ms)
    b = kline_taker.rename(columns={"tbv": "tbv_kline"})[["t", "tbv_kline"]]
    j = a.merge(b, on="t", how="inner")
    if len(j) == 0:
        return {"n_bars": 0, "max_rel_err": float("nan"),
                "worst_t": None, "pass": False}
    x = j["tbv_agg"].to_numpy(dtype=float)
    y = j["tbv_kline"].to_numpy(dtype=float)
    denom = np.maximum(np.abs(y), ABS_TOL)
    rel = np.abs(x - y) / denom
    rel = np.where((np.abs(x) <= ABS_TOL) & (np.abs(y) <= ABS_TOL), 0.0, rel)
    k = int(np.argmax(rel))
    return {"n_bars": int(len(j)), "max_rel_err": float(rel[k]),
            "worst_t": int(j["t"].iloc[k]), "pass": bool(rel.max() <= REL_TOL)}
