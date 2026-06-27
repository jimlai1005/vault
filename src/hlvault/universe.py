"""Stage 1: candidate universe from leaderboard. NOTE: this is the *seed*
universe only. The backtest reconstructs the as-of universe to avoid
survivorship bias (see spec section Point-in-time)."""
from __future__ import annotations


def _month_pnl(row: dict) -> float:
    for win, perf in row.get("windowPerformances", []):
        if win == "month":
            return float(perf.get("pnl", 0))
    return 0.0


def top_addresses(leaderboard_rows: list[dict], n: int) -> list[str]:
    ranked = sorted(leaderboard_rows, key=_month_pnl, reverse=True)
    return [r["ethAddress"] for r in ranked[:n]]
