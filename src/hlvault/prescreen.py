"""Cheap first-pass screen on the leaderboard payload (which already carries
per-address allTime/month ROI, PnL, volume) to cut ~39.5k traders down to a
few hundred deep-pull candidates. Bounds S3 egress cost.

Filters out the obvious non-copyable accounts (vault-scale balances, near-zero
volume) and ranks by a cheap ROI/volume signal before the expensive deep pull."""
from __future__ import annotations


def _window(row: dict, name: str) -> dict:
    for win, perf in row.get("windowPerformances", []):
        if win == name:
            return perf
    return {}


def prescreen(
    rows: list[dict],
    keep: int,
    min_volume: float = 1_000_000.0,
    max_account_value: float = 50_000_000.0,
    min_alltime_roi: float = 0.0,
) -> list[str]:
    """Return up to `keep` candidate addresses for deep history pull.

    - drops vault-scale accounts (acctValue > max_account_value) — these are
      HLP/market-maker vaults, not copyable directional traders;
    - drops dust/low-volume accounts (allTime vlm < min_volume);
    - requires positive all-time ROI;
    - ranks survivors by allTime ROI (cheap proxy; real risk-adjusted ranking
      happens after deep history is reconstructed)."""
    cand = []
    for r in rows:
        try:
            acct = float(r.get("accountValue", 0))
        except (TypeError, ValueError):
            continue
        if acct > max_account_value:
            continue
        at = _window(r, "allTime")
        vlm = float(at.get("vlm", 0) or 0)
        roi = float(at.get("roi", 0) or 0)
        if vlm < min_volume or roi <= min_alltime_roi:
            continue
        cand.append((r["ethAddress"], roi))
    cand.sort(key=lambda x: x[1], reverse=True)
    return [a for a, _ in cand[:keep]]
