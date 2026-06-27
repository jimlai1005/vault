"""Stage 8: walk-forward OOS. At each rebalance date T the SelectionFn sees
ONLY data with index <= T (structural no-lookahead). The held portfolio's
realized returns over (T, T+h] are concatenated into the OOS track."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import pandas as pd

SelectionFn = Callable[[pd.Timestamp, pd.DataFrame], pd.Series]


@dataclass
class BacktestResult:
    oos_returns: pd.Series
    rebalance_dates: List[pd.Timestamp]


def walk_forward(
    panel: pd.DataFrame,
    select: SelectionFn,
    rebalance_days: int,
    horizon_days: int,
) -> BacktestResult:
    dates = panel.index
    start, end = dates.min(), dates.max()
    rebal = pd.date_range(
        start + pd.Timedelta(days=rebalance_days),
        end - pd.Timedelta(days=horizon_days),
        freq=f"{rebalance_days}D",
    )
    segments, used = [], []
    for t in rebal:
        past = panel[panel.index <= t]  # <-- the only data select sees
        weights = select(t, past)
        future = panel[
            (panel.index > t) & (panel.index <= t + pd.Timedelta(days=horizon_days))
        ]
        cols = [c for c in weights.index if c in future.columns]
        if not cols or future.empty:
            continue
        seg = (future[cols] * weights[cols]).sum(axis=1)
        segments.append(seg)
        used.append(t)
    oos = (
        pd.concat(segments).sort_index()
        if segments
        else pd.Series(dtype=float)
    )
    # collapse any overlapping horizon dates by averaging (defensive)
    if not oos.empty:
        oos = oos.groupby(oos.index).mean()
    return BacktestResult(oos_returns=oos, rebalance_dates=used)
