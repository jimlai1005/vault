"""Pure CTA signal functions — the SAME math as
scripts/research_cta_positioning_phase2b.py (raw_indicators / shifted_signals /
the entry condition in simulate), so the live signal reproduces the backtest's
signal for the same bar (a hard spec requirement).

Direction (do NOT invert — contrarian by design):
  SHORT = down-trend (EMA50 > EMA20) AND retail crowded-long (LSR percentile
          high, >= 100-p) AND fuel (OI rising).
  LONG  = up-trend AND retail crowded-short (LSR percentile low, <= p) AND fuel.
Point-in-time: callers pass CLOSED-bar frames; compute_signals reads the last
closed bar (equivalent to the backtest's shift(1)-then-act-next-bar, since the
live engine only ever sees closed bars)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema_trend(close: pd.Series, fast: int, slow: int, warmup_bars: int) -> pd.DataFrame:
    """EMA{fast}/EMA{slow} trend flags. trend_up = fast>slow, trend_dn =
    slow>fast, both False until `warmup_bars` of history exist (matches the
    backtest's TREND_WARMUP_BARS gate)."""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    valid = pd.Series(np.arange(len(close)) >= warmup_bars, index=close.index)
    return pd.DataFrame({
        "trend_up": (ema_f > ema_s) & valid,
        "trend_dn": (ema_s > ema_f) & valid,
    })


def _pct_rank_last(w: np.ndarray) -> float:
    """Percentile of the CURRENT (last) value within the trailing window —
    identical to the backtest's _pct_rank_last."""
    cur = w[-1]
    if np.isnan(cur):
        return np.nan
    w = w[~np.isnan(w)]
    return float((w <= cur).mean() * 100.0)


def crowd_percentile(long_pct: pd.Series, window_bars: int, warmup_bars: int) -> pd.Series:
    """Rolling trailing percentile of the long-account-% series (matches the
    backtest's rolling(CROWD_WINDOW*bpd, min_periods=CROWD_WARMUP*bpd) apply)."""
    return long_pct.rolling(window_bars, min_periods=warmup_bars).apply(
        _pct_rank_last, raw=True)


def is_crowd_long(pct_rank: float, pctile: float) -> bool:
    """Retail crowded LONG when the long-% percentile is in the top decile
    (>= 100 - pctile). NaN (warmup) -> False."""
    if pct_rank is None or (isinstance(pct_rank, float) and np.isnan(pct_rank)):
        return False
    return bool(pct_rank >= 100 - pctile)


def is_crowd_short(pct_rank: float, pctile: float) -> bool:
    """Retail crowded SHORT when the long-% percentile is in the bottom decile
    (<= pctile). NaN -> False."""
    if pct_rank is None or (isinstance(pct_rank, float) and np.isnan(pct_rank)):
        return False
    return bool(pct_rank <= pctile)


def fuel_ok(oi_level: pd.Series, lookback_bars: int) -> bool:
    """OI rose over the trailing lookback (last value > value lookback_bars
    ago). Matches the backtest's oi_level > oi_level.shift(lb_bars)."""
    if len(oi_level) <= lookback_bars:
        return False
    cur = oi_level.iloc[-1]
    prev = oi_level.iloc[-1 - lookback_bars]
    if np.isnan(cur) or np.isnan(prev):
        return False
    return bool(cur > prev)


def atr(bars: pd.DataFrame, period: int, warmup_bars: int) -> pd.Series:
    """ATR via Wilder EWM (alpha=1/period) on high/low/close — matches the
    backtest's atr_raw; NaN for the first `warmup_bars` bars."""
    prev_close = bars["close"].shift(1)
    tr = pd.concat([
        bars["high"] - bars["low"],
        (bars["high"] - prev_close).abs(),
        (bars["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out = tr.ewm(alpha=1 / period, adjust=False).mean()
    out.iloc[:warmup_bars] = np.nan
    return out


def compute_signals(bars: pd.DataFrame, *, ema_fast: int, ema_slow: int,
                    trend_warmup_bars: int, crowd_pctile: float,
                    crowd_window_bars: int, crowd_warmup_bars: int,
                    fuel_lookback_bars: int, atr_period: int) -> dict:
    """Reduce a per-coin closed-bar frame (columns: open/high/low/close/
    oi_level/long_pct) to the last-bar signal booleans + atr. All flags are
    evaluated on the final (most recent CLOSED) row."""
    trend = ema_trend(bars["close"], ema_fast, ema_slow, trend_warmup_bars)
    crowd = crowd_percentile(bars["long_pct"], crowd_window_bars, crowd_warmup_bars)
    atr_series = atr(bars, atr_period, trend_warmup_bars)
    last_pct = crowd.iloc[-1]
    atr_last = atr_series.iloc[-1]
    return {
        "trend_up": bool(trend["trend_up"].iloc[-1]),
        "trend_dn": bool(trend["trend_dn"].iloc[-1]),
        "crowd_long": is_crowd_long(last_pct, crowd_pctile),
        "crowd_short": is_crowd_short(last_pct, crowd_pctile),
        "fuel": fuel_ok(bars["oi_level"], fuel_lookback_bars),
        "atr": float(atr_last) if not np.isnan(atr_last) else float("nan"),
        "close": float(bars["close"].iloc[-1]),
        # observability only (live per-rebalance log); not a decision input —
        # decide() consumes the boolean crowd flags above
        "crowd_pct": float(last_pct) if not np.isnan(last_pct) else float("nan"),
    }


def decide(trend_up: bool, trend_dn: bool, crowd_long: bool, crowd_short: bool,
           fuel: bool, *, enable_long: bool, enable_short: bool) -> str:
    """Per-coin entry decision -> 'short' | 'long' | 'flat'. Side switches
    applied here (disabled side collapses to flat). SHORT wins ties only if it
    is uniquely satisfied — both cannot be satisfied at once (a bar cannot be
    both down-trend+crowd-long and up-trend+crowd-short)."""
    want_short = enable_short and trend_dn and crowd_long and fuel
    want_long = enable_long and trend_up and crowd_short and fuel
    if want_short:
        return "short"
    if want_long:
        return "long"
    return "flat"


def should_exit(direction: int, trend_up: bool, trend_dn: bool, fuel: bool,
                held_days: float, max_hold_days: float) -> "str | None":
    """Exit reason for an OPEN position (direction: 1 long, -1 short), or None
    to hold. Order matches the backtest: trend flip, then fuel fail, then max
    hold. The 2xATR hard stop is evaluated separately against the live price in
    risk.stop_hit (it needs the entry-relative stop level, not just flags)."""
    flip = (direction == 1 and not trend_up) or (direction == -1 and not trend_dn)
    if flip:
        return "flip"
    if not fuel:
        return "fuel"
    if held_days >= max_hold_days:
        return "maxhold"
    return None
