"""Replay historical candles through the exact same `strategy.step` used
live, so backtest and live share one implementation (CLAUDE.md #5)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .strategy import GridConfig, init_state, step


@dataclass
class BacktestResult:
    events: pd.DataFrame
    equity_curve: pd.Series
    total_pnl: float
    num_fills: int
    num_tps: int
    num_stops: int
    max_drawdown: float
    sharpe: float


def run_backtest(candles: pd.DataFrame, cfg: GridConfig, anchor_price: float | None = None) -> BacktestResult:
    """`candles` must have columns t/h/l/c (t = timestamp, ascending)."""
    state = init_state(anchor_price if anchor_price is not None else float(candles["c"].iloc[0]))
    rows = []
    cum_pnl = 0.0
    for _, row in candles.iterrows():
        state, events = step(state, {"h": row["h"], "l": row["l"], "c": row["c"]}, cfg)
        for ev in events:
            cum_pnl += ev.pnl
            rows.append({
                "t": row["t"], "kind": ev.kind, "level": ev.level,
                "price": ev.price, "size": ev.size, "pnl": ev.pnl, "cum_pnl": cum_pnl,
            })

    events_df = pd.DataFrame(rows, columns=["t", "kind", "level", "price", "size", "pnl", "cum_pnl"])
    if events_df.empty:
        equity = pd.Series([0.0], index=[candles["t"].iloc[-1]])
    else:
        # multiple events can land in the same candle — keep the last cum_pnl per timestamp
        by_t = events_df.groupby("t")["cum_pnl"].last()
        equity = by_t.reindex(candles["t"]).ffill().fillna(0.0)

    running_max = equity.cummax()
    drawdown = (equity - running_max)
    max_dd = float(drawdown.min())

    daily_pnl = equity.diff().fillna(equity.iloc[0] if len(equity) else 0.0)
    sharpe = 0.0
    if daily_pnl.std(ddof=0) > 0:
        sharpe = float(daily_pnl.mean() / daily_pnl.std(ddof=0) * (365 ** 0.5))

    return BacktestResult(
        events=events_df,
        equity_curve=equity,
        total_pnl=float(cum_pnl),
        num_fills=int((events_df["kind"] == "fill").sum()) if not events_df.empty else 0,
        num_tps=int((events_df["kind"] == "tp").sum()) if not events_df.empty else 0,
        num_stops=int((events_df["kind"] == "stop").sum()) if not events_df.empty else 0,
        max_drawdown=max_dd,
        sharpe=sharpe,
    )
