"""Walk-forward-safe replay of the momentum signal over historical daily
closes: at day t, every score/vol input is computed from data with index <=
t only (pandas .rolling() looks backward by construction), and a day's PnL
uses YESTERDAY's target position against TODAY's return before rebalancing
to today's new target — the same causal ordering the live engine follows.
This replays the exact signals.py + risk.py functions used live (CLAUDE.md
#5: one implementation, not a re-derivation for the backtest)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .risk import risk_budget_per_coin, target_position_notional
from .signals import composite_score, daily_log_returns, position_signal

FEE_RATE = 0.0005


@dataclass
class MomentumBacktestResult:
    equity_curve: pd.Series
    daily_returns: pd.Series
    max_drawdown: float
    sharpe: float
    total_return: float


def run_backtest(
    closes: pd.DataFrame,
    capital: float,
    max_coin_allocation_pct: float,
    max_leverage: float,
    entry_threshold: float = 0.5,
    vol_lookback: int = 20,
) -> MomentumBacktestResult:
    if capital <= 0:
        # Fail at the actual mistake: a bad live-equity read feeding capital<=0
        # would otherwise surface as a NaN total_return (capital==0) or a
        # confusingly-sourced ValueError deep inside risk.allocate_capital
        # (capital<0) instead of naming the real problem here.
        raise ValueError(f"capital must be positive, got {capital}")
    coins = list(closes.columns)
    returns = pd.DataFrame({c: daily_log_returns(closes[c]) for c in coins}).reindex(closes.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(closes.index)
    signals = pd.DataFrame({c: position_signal(scores[c], entry_threshold) for c in coins}).reindex(closes.index)
    trailing_vol = returns.rolling(vol_lookback).std(ddof=1)

    equity = capital
    equity_curve = []
    prev_notional = {c: 0.0 for c in coins}

    for t in closes.index:
        vol_by_coin = {
            c: float(trailing_vol.loc[t, c]) for c in coins
            if pd.notna(trailing_vol.loc[t, c]) and trailing_vol.loc[t, c] > 0
        }
        if not vol_by_coin:
            equity_curve.append(equity)
            continue
        budgets = risk_budget_per_coin(vol_by_coin, equity, max_coin_allocation_pct)
        day_pnl = 0.0
        for c in vol_by_coin:
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            target = target_position_notional(sig, budgets.get(c, 0.0), max_leverage)
            ret = float(returns.loc[t, c]) if pd.notna(returns.loc[t, c]) else 0.0
            day_pnl += prev_notional[c] * ret
            day_pnl -= abs(target - prev_notional[c]) * FEE_RATE
            prev_notional[c] = target
        equity += day_pnl
        equity_curve.append(equity)

    eq = pd.Series(equity_curve, index=closes.index)
    daily_ret = eq.pct_change().dropna()
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min()) if len(eq) else 0.0
    sharpe = 0.0
    if len(daily_ret) and daily_ret.std(ddof=1) > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * (365 ** 0.5))
    total_return = float(eq.iloc[-1] / capital - 1.0) if len(eq) else 0.0

    return MomentumBacktestResult(
        equity_curve=eq, daily_returns=daily_ret, max_drawdown=max_dd,
        sharpe=sharpe, total_return=total_return,
    )
