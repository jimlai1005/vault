"""The point-in-time selection step used inside the walk-forward backtest.

Given ONLY past returns (data <= as_of), it: applies the sample-length gate,
decomposes each trader vs BTC/ETH and drops pure-beta, scores survivors by
risk-adjusted alpha + persistence (deflated Sharpe, win-rate stability), picks
top-N, and assigns HRP weights. Returns a weight Series over the chosen traders.
Pure function of its inputs -> safe to call repeatedly across rebalance dates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .factors import alpha_beta
from .metrics import deflated_sharpe, rolling_winrate_stability
from .weights import hrp_weights

MIN_OBS = 60  # need a reasonable sample before regressing/ranking


def portfolio_betas(
    past: pd.DataFrame, weights: pd.Series, btc: pd.Series, eth: pd.Series
) -> tuple[float, float]:
    """Weighted net BTC/ETH beta of a portfolio, from each holding's in-sample
    factor fit. Used to hedge the market-neutral construction OOS."""
    b_btc = b_eth = 0.0
    for user, w in weights.items():
        r = past[user].dropna()
        if len(r) < MIN_OBS:
            continue
        try:
            fit = alpha_beta(r, btc.reindex(r.index), eth.reindex(r.index))
        except Exception:  # noqa: BLE001
            continue
        b_btc += w * fit.beta_btc
        b_eth += w * fit.beta_eth
    return float(b_btc), float(b_eth)


def select_at(
    past: pd.DataFrame,
    btc: pd.Series,
    eth: pd.Series,
    top_n: int,
    min_alpha_tstat: float = 2.0,
    min_history_months: int = 9,
    n_trials: int = 300,
) -> pd.Series:
    rows = []
    min_days = min_history_months * 30
    for user in past.columns:
        r = past[user].dropna()
        if len(r) < MIN_OBS:
            continue
        if (r.index.max() - r.index.min()).days < min_days:
            continue
        try:
            fit = alpha_beta(r, btc.reindex(r.index), eth.reindex(r.index))
        except Exception:  # noqa: BLE001 — degenerate regression, skip trader
            continue
        if not np.isfinite(fit.alpha_tstat) or fit.alpha_tstat < min_alpha_tstat:
            continue
        rows.append(
            {
                "user": user,
                "alpha_tstat": fit.alpha_tstat,
                "dsr": deflated_sharpe(r, n_trials=n_trials),
                "winrate_stability": rolling_winrate_stability(r),
            }
        )
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows).set_index("user")

    def z(col: str) -> pd.Series:
        s = df[col]
        sd = s.std(ddof=0)
        return (s - s.mean()) / sd if sd > 0 else s * 0

    df["score"] = z("alpha_tstat") + z("dsr") - z("winrate_stability")
    chosen = df.sort_values("score", ascending=False).head(top_n).index.tolist()
    if len(chosen) == 1:
        return pd.Series([1.0], index=chosen)
    return hrp_weights(past[chosen].dropna(how="all").fillna(0.0))
