"""Stage 3: reconstruct daily equity curve -> daily returns. Current and peak
equity derive from the SAME series (CLAUDE.md #1 — never mix sources).

equity_t = starting_equity + cum(realized_pnl) + cum(funding) - cum(fee)
           + unrealized_mtm(position_t, price_t)

The realized+fee+funding spine is `daily_equity_from_fills`. Unrealized MtM is
layered in via `add_unrealized` when an OHLCV price frame is supplied (kept
separate + independently tested)."""
from __future__ import annotations

import pandas as pd


def daily_equity_from_fills(
    fills: pd.DataFrame, starting_equity: float, funding: pd.Series | None = None
) -> pd.Series:
    f = fills.copy()
    f["day"] = f["time"].dt.normalize()
    daily = (
        f.groupby("day").agg(realized=("closedPnl", "sum"), fee=("fee", "sum")).sort_index()
    )
    pnl = daily["realized"] - daily["fee"]
    if funding is not None and not funding.empty:
        fund_daily = funding.groupby(funding.index.normalize()).sum()
        pnl = pnl.add(fund_daily, fill_value=0.0)
    equity = starting_equity + pnl.cumsum()
    return equity


def add_unrealized(
    equity: pd.Series,
    fills: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.Series:
    """Add per-day unrealized mark-to-market of open positions.

    `prices` is a DataFrame indexed by day with one close-price column per coin.
    Position at day d for a coin = cumulative signed_sz of fills up to d.
    Unrealized = sum over coins of position * (close_d - avg_entry) is hard to
    get without entry tracking; we use a simpler mark consistent with the spine:
    unrealized_d = sum_coin position_d * (close_d - close_prev_d) cumulated,
    i.e. daily MtM change on the held position. This avoids mixing a separate
    entry-price source (CLAUDE.md #1)."""
    if fills.empty or prices.empty:
        return equity
    f = fills.copy()
    f["day"] = f["time"].dt.normalize()
    days = equity.index
    mtm = pd.Series(0.0, index=days)
    for coin in f["coin"].unique():
        if coin not in prices.columns:
            continue
        pos = (
            f[f["coin"] == coin]
            .groupby("day")["signed_sz"]
            .sum()
            .reindex(days, fill_value=0.0)
            .cumsum()
        )
        close = prices[coin].reindex(days).ffill()
        dprice = close.diff().fillna(0.0)
        mtm = mtm.add(pos.shift(1).fillna(0.0) * dprice, fill_value=0.0)
    return equity.add(mtm.cumsum(), fill_value=0.0)


def daily_returns_from_fills(
    fills: pd.DataFrame, starting_equity: float, funding: pd.Series | None = None
) -> pd.Series:
    equity = daily_equity_from_fills(fills, starting_equity, funding)
    prev = equity.shift(1).fillna(starting_equity)
    return (equity / prev - 1.0).rename("ret")


def passes_sample_gate(returns: pd.Series, min_months: int) -> bool:
    if returns.empty:
        return False
    span_days = (returns.index.max() - returns.index.min()).days
    return span_days >= min_months * 30
