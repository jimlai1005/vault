"""Build a per-trader daily return panel from cached fill shards.

Equity-curve reconstruction strategy (live run):
- Daily booked PnL per trader = sum(closedPnl - fee) for the day. This is the
  realized P&L a copy-trader actually captures by mirroring fills; it needs no
  per-alt OHLCV. (Unrealized MtM is available via equity.add_unrealized for
  major coins when wanted — see spec; omitted here to avoid pricing 100+ alts.)
- We KNOW each trader's current account value (leaderboard). With the full PnL
  path we reconstruct the equity curve backward:
      equity_t = account_value_now - (total_pnl - cum_pnl_t)
  so return_t = pnl_t / equity_{t-1}. Same series for current & peak
  (CLAUDE.md #1).
- Traders whose reconstructed equity goes <= 0 (deposits/withdrawals or a blown
  account the snapshot can't reconcile) are dropped — flagged, not silently
  fudged."""
from __future__ import annotations

import pandas as pd


def daily_pnl_panel(fills: pd.DataFrame) -> pd.DataFrame:
    """date x user -> booked PnL (closedPnl - fee), summed per day."""
    if fills.empty:
        return pd.DataFrame()
    f = fills.copy()
    f["day"] = pd.to_datetime(f["time"]).dt.normalize()
    f["pnl"] = f["closedPnl"] - f["fee"]
    panel = f.pivot_table(index="day", columns="user", values="pnl",
                          aggfunc="sum", fill_value=0.0)
    return panel.sort_index()


def returns_panel(
    pnl_panel: pd.DataFrame, account_values: dict[str, float]
) -> pd.DataFrame:
    """Reconstruct daily returns per trader by anchoring to current account
    value and propagating PnL backward. Drops traders with non-positive
    reconstructed equity anywhere in the path."""
    cols = {}
    for user in pnl_panel.columns:
        av = account_values.get(user.lower()) or account_values.get(user)
        if not av or av <= 0:
            continue
        pnl = pnl_panel[user]
        cum = pnl.cumsum()
        total = cum.iloc[-1]
        # equity at end of day t
        equity_t = av - (total - cum)
        # equity at start of day t = equity at end of previous day
        equity_prev = equity_t.shift(1)
        equity_prev.iloc[0] = av - total  # equity before the first day
        if (equity_prev <= 0).any() or (equity_t <= 0).any():
            continue
        cols[user] = (pnl / equity_prev).astype(float)
    if not cols:
        return pd.DataFrame(index=pnl_panel.index)
    return pd.DataFrame(cols).reindex(pnl_panel.index)


def load_fill_shards(cache_dir: str) -> pd.DataFrame:
    """Concatenate all per-day fill parquet shards."""
    from pathlib import Path

    parts = sorted(Path(cache_dir).glob("*.parquet"))
    if not parts:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
