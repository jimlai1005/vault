"""Stage 4: risk-adjusted + persistence metrics. Deflated Sharpe corrects the
multiple-testing selection bias from screening ~300 candidates."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

ANN = 252


def sharpe(r: pd.Series, rf: float = 0.0) -> float:
    ex = r - rf
    sd = ex.std(ddof=1)
    return float(ex.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def sortino(r: pd.Series, rf: float = 0.0) -> float:
    ex = r - rf
    downside = ex[ex < 0].std(ddof=1)
    return float(ex.mean() / downside * np.sqrt(ANN)) if downside > 0 else 0.0


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def rolling_winrate_stability(r: pd.Series, window: int = 21) -> float:
    wr = (r > 0).rolling(window).mean()
    sd = wr.std()
    return float(sd) if pd.notna(sd) else 0.0


def deflated_sharpe(r: pd.Series, n_trials: int, rf: float = 0.0) -> float:
    """Probability the true Sharpe > 0 after correcting for n_trials selection.
    Bailey & Lopez de Prado (2014), simplified."""
    sr = sharpe(r, rf) / np.sqrt(ANN)  # per-period SR
    n = len(r)
    if n < 3:
        return 0.0
    g = r.skew()
    k = r.kurt() + 3.0  # pandas kurt is excess; convert to raw
    sr_std = np.sqrt(max((1 - g * sr + (k - 1) / 4 * sr ** 2) / (n - 1), 1e-12))
    e_max = (np.sqrt(2 * np.log(max(n_trials, 1))) if n_trials > 1 else 0.0) * sr_std
    z = (sr - e_max) / sr_std if sr_std > 0 else 0.0
    return float(norm.cdf(z))
