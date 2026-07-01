"""Volatility-adaptive grid spacing — recalibrated periodically (e.g. daily),
not per-tick, to avoid the grid itself churning on its own noise."""
from __future__ import annotations

import pandas as pd


def atr_pct(candles: pd.DataFrame, lookback: int) -> float:
    """Average true range as a fraction of last close, over the last
    `lookback` rows of an OHLC frame with columns h/l/c."""
    h, l, c = candles["h"], candles["l"], candles["c"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    window = tr.tail(lookback)
    if window.empty or c.iloc[-1] <= 0:
        return 0.0
    return float(window.mean() / c.iloc[-1])


def adaptive_step_pct(atr_pct_1h: float, vol_k: float, min_step: float, max_step: float) -> float:
    return min(max(vol_k * atr_pct_1h, min_step), max_step)
