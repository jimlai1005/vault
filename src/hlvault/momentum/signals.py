"""Time-series momentum signal (Moskowitz-Ooi-Pedersen style): trailing
risk-adjusted return over multiple lookbacks, averaged into one composite
score per asset. Pure functions — the same score computation drives both
the backtest (backtest.py) and the live engine (live.py), per CLAUDE.md #5."""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACKS_DAYS = (20, 60, 120)


def daily_log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def risk_adjusted_momentum(returns: pd.Series, lookback: int) -> pd.Series:
    """Trailing `lookback`-day cumulative return divided by trailing
    `lookback`-day realized vol — a rolling Sharpe-like score, so a merely
    volatile asset doesn't dominate just because it moved a lot."""
    cum = returns.rolling(lookback).sum()
    vol = returns.rolling(lookback).std(ddof=1) * (lookback ** 0.5)
    return (cum / vol.where(vol > 0)).rename(f"mom_{lookback}")


def composite_score(returns: pd.Series, lookbacks=LOOKBACKS_DAYS) -> pd.Series:
    scores = pd.concat([risk_adjusted_momentum(returns, l) for l in lookbacks], axis=1)
    return scores.mean(axis=1, skipna=False).rename("composite_score")


def score_to_position(score: float, entry_threshold: float = 0.5) -> float:
    """Map a single composite score to a target position in [-1, 1]: sign
    gives direction, magnitude ramps from 0 at |score|==entry_threshold to 1
    at |score|==2*entry_threshold (clipped beyond). Scores inside the
    threshold band map to zero to avoid churning on noise near zero."""
    if pd.isna(score) or entry_threshold <= 0:
        return 0.0
    magnitude = min(max(abs(score) - entry_threshold, 0.0) / entry_threshold, 1.0)
    if score > 0:
        return magnitude
    if score < 0:
        return -magnitude
    return 0.0


def position_signal(scores: pd.Series, entry_threshold: float = 0.5) -> pd.Series:
    """Vectorized form of score_to_position, used by the backtest."""
    return scores.apply(lambda s: score_to_position(s, entry_threshold)).rename("position_signal")
