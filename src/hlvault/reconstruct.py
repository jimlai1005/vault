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
    pnl_panel: pd.DataFrame,
    account_values: dict[str, float],
    max_abs_daily_return: float = 3.0,
) -> pd.DataFrame:
    """Reconstruct daily returns per trader.

    Without a deposit/withdrawal ledger we estimate the starting equity E0 and
    propagate PnL forward: equity_t = E0 + cum_pnl_t. We anchor E0 to the
    current account value (E0 = av - total_pnl), but a trader who WITHDREW
    profits has av < total_pnl, which would make E0 negative and wrongly drop a
    *winner*. So we floor E0 at the minimum capital consistent with surviving
    their worst drawdown (-min(cum_pnl)). This keeps profitable-withdrawers in
    the sample at the cost of possibly overstating their returns — an explicit,
    documented approximation (returns are research signal, not accounting).

    Only traders with a known positive account value are kept; current and peak
    equity come from the SAME reconstructed series (CLAUDE.md #1)."""
    cols = {}
    for user in pnl_panel.columns:
        av = account_values.get(user.lower()) or account_values.get(user)
        if not av or av <= 0:
            continue
        pnl = pnl_panel[user]
        cum = pnl.cumsum()
        total = float(cum.iloc[-1])
        dd = float(cum.min())
        # 10% headroom so reconstructed equity never approaches 0 at the trough
        drawdown_floor = (-dd) * 1.1 if dd < 0 else 0.0
        eps = max(av, 1.0) * 1e-6
        e0_anchor = av - total
        if e0_anchor > 0:                      # snapshot consistent with PnL path
            e0 = max(e0_anchor, drawdown_floor) + eps
        elif drawdown_floor > 0:               # withdrew, but a real drawdown bounds capital
            e0 = drawdown_floor + eps
        else:                                  # always-up + tiny snapshot: unreconstructable
            continue
        equity_prev = (e0 + cum.shift(1)).fillna(e0)  # equity at start of each day
        ret = (pnl / equity_prev).astype(float)
        # Reconstruction-quality gate: a daily move beyond +/-max_abs_daily_return
        # means the reconstructed capital base is unreliable (or the trader runs
        # leverage too extreme to mirror in a vault). Drop, don't silently clip.
        if ret.abs().max() > max_abs_daily_return:
            continue
        cols[user] = ret
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
