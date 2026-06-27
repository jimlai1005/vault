"""Real-data go/no-go driver.

Loads cached fill shards -> reconstructs per-trader daily return panel -> runs
the walk-forward OOS backtest with the point-in-time selection step -> writes
reports/oos-verdict.md with an explicit GO / NO-GO.

Run after scripts/pull_archive.py has populated data/cache/fills/.
    python scripts/run_backtest.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.backtest import walk_forward  # noqa: E402
from hlvault.config import Settings  # noqa: E402
from hlvault.pipeline import select_at  # noqa: E402
from hlvault.prices import get_daily_returns  # noqa: E402
from hlvault.reconstruct import (  # noqa: E402
    daily_pnl_panel,
    load_fill_shards,
    returns_panel,
)
from hlvault.report import verdict, write_report  # noqa: E402

CACHE = "data/cache/fills"
PRICE_CACHE = Path("data/cache/prices.parquet")


def _prices(start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    if PRICE_CACHE.exists():
        df = pd.read_parquet(PRICE_CACHE)
        return df["btc"].dropna(), df["eth"].dropna()
    s = int(start.timestamp() * 1000)
    e = int(end.timestamp() * 1000)
    btc = get_daily_returns("BTC", s, e)
    eth = get_daily_returns("ETH", s, e)
    df = pd.DataFrame({"btc": btc, "eth": eth})
    PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRICE_CACHE)
    return btc, eth


def main() -> None:
    cfg = Settings()
    fills = load_fill_shards(CACHE)
    if fills.empty:
        raise SystemExit("no fills cached yet — run pull_archive.py first")
    print(f"loaded {len(fills):,} fills, {fills['user'].nunique()} traders")

    account_values = json.loads(Path("data/cache/account_values.json").read_text())
    pnl = daily_pnl_panel(fills)
    panel = returns_panel(pnl, account_values)
    panel = panel.dropna(how="all", axis=1)
    print(f"return panel: {panel.shape[0]} days x {panel.shape[1]} traders "
          f"({panel.index.min().date()} -> {panel.index.max().date()})")

    btc, eth = _prices(panel.index.min(), panel.index.max())

    def select(as_of, past):
        return select_at(
            past, btc, eth,
            top_n=cfg.top_n,
            min_alpha_tstat=cfg.min_alpha_tstat,
            min_history_months=cfg.min_history_months,
            n_trials=panel.shape[1],
        )

    res = walk_forward(
        panel, select,
        rebalance_days=cfg.rebalance_horizon_days,
        horizon_days=cfg.rebalance_horizon_days,
    )
    print(f"OOS days: {len(res.oos_returns)}, rebalances: {len(res.rebalance_dates)}")

    btc_oos = btc.reindex(res.oos_returns.index).fillna(0.0)
    v = verdict(res.oos_returns, btc_oos)
    final_w = select(panel.index.max(), panel)

    Path("reports").mkdir(exist_ok=True)
    write_report("reports/_raw-verdict.md", v, pd.DataFrame(), final_w)
    res.oos_returns.to_frame("ret").to_parquet("reports/oos_returns.parquet")
    final_w.to_frame("weight").to_parquet("reports/final_weights.parquet")

    print("\n==== VERDICT ====")
    print(f"decision     : {v.decision}")
    print(f"OOS t-stat   : {v.oos_tstat:.2f}")
    print(f"OOS Sharpe   : {v.oos_sharpe:.2f}  (BTC {v.btc_sharpe:.2f})")
    print(f"OOS max DD   : {v.oos_mdd:.1%}")
    print(f"note         : {v.note}")
    print(f"selected     : {len(final_w)} traders -> reports/oos-verdict.md")


if __name__ == "__main__":
    main()
