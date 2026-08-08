"""Sub-project N — 訂單流特徵層。spec §5。

兩層存取（實測：BTC 最大月 5,772 萬列，載入 3.2s、聚合 5.9s、事件查詢 0.45ms）：
  · 可預聚合的（delta / notional / n_trades / cvd）→ build_bars()，每 symbol-month
    算一次落 sidecar。
  · 不可預聚合的 D_sweep（依賴每事件各自的池價位 P）→ sweep_delta()，用
    searchsorted 對已排序的 transact_time 做 range query，現算。

全部計價一律 USDT notional（P1），符號約定見 n_data.signed_qty（P2）。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_data as nd  # noqa: E402

CACHE_N = pathlib.Path(cfg.CACHE_DIR_N)


def build_bars(df, bar_ms):
    """aggTrades DataFrame → 逐棒聚合表（t, delta, notional, n_trades, cvd）。

    delta / notional 一律 USDT notional（P1）；bar = transact_time // bar_ms（P3）；
    n_trades 由 last_trade_id - first_trade_id + 1 還原（aggTrades 行數 != 筆數）。
    cvd 自本表第一根棒起累加（P8）。
    """
    if len(df) == 0:
        return pd.DataFrame(columns=["t", "delta", "notional", "n_trades", "cvd"])
    px = df["price"].to_numpy(dtype=float)
    q = df["quantity"].to_numpy(dtype=float)
    sgn = 1.0 - 2.0 * df["is_buyer_maker"].to_numpy()      # True -> -1（P2）
    t = df["transact_time"].to_numpy(dtype=np.int64)
    g = pd.DataFrame({
        "t": (t // int(bar_ms)) * int(bar_ms),
        "delta": q * px * sgn,
        "notional": q * px,
        "n_trades": nd.trade_count(df),
    }).groupby("t", sort=True).sum().reset_index()
    g["cvd"] = g["delta"].cumsum()
    return g


def build_index(df, bar_ms):
    """棒邊界索引，供 sweep_delta 做 O(log n) range query。

    回傳 dict(bar_t -> (start, end))；要求 transact_time 已排序（實測 Binance
    的 dump 已排序，但不假設——不符即拋錯，不靜默排序）。
    """
    t = df["transact_time"].to_numpy(dtype=np.int64)
    if len(t) > 1 and not bool((np.diff(t) >= 0).all()):
        raise ValueError("transact_time 未排序；searchsorted 前提不成立")
    if len(t) == 0:
        return {}
    b0 = int(t[0]) // int(bar_ms)
    b1 = int(t[-1]) // int(bar_ms)
    edges = (np.arange(b0, b1 + 2, dtype=np.int64)) * int(bar_ms)
    pos = np.searchsorted(t, edges, side="left")
    return {int(edges[i]): (int(pos[i]), int(pos[i + 1]))
            for i in range(len(edges) - 1)}


def sweep_delta(df, index, bar_t, pool, direction):
    """單一事件的 (D_sweep, V_sweep)。spec §5.1。

    direction = -1（空方掃單，池為 pivot high）→ 只計 price >= pool（P4）
    direction = +1（多方掃單，池為 pivot low） → 只計 price <= pool
    棒內無成交 → (nan, nan)，呼叫端據此記 nodata（P7）。
    """
    rng = index.get(int(bar_t))
    if rng is None or rng[1] <= rng[0]:
        return float("nan"), float("nan")
    a, b = rng
    px = df["price"].to_numpy(dtype=float)[a:b]
    q = df["quantity"].to_numpy(dtype=float)[a:b]
    sgn = 1.0 - 2.0 * df["is_buyer_maker"].to_numpy()[a:b]
    m = (px >= float(pool)) if direction == -1 else (px <= float(pool))
    if not m.any():
        return 0.0, 0.0
    notional = q[m] * px[m]
    return float((notional * sgn[m]).sum()), float(notional.sum())


def bars_path(symbol, interval):
    return CACHE_N / f"bars_{symbol}_{interval}.parquet"


def load_bars_of(symbol, interval):
    """已落檔的逐棒訂單流表。"""
    return pd.read_parquet(bars_path(symbol, interval))
