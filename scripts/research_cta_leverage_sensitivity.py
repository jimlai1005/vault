"""Leverage sensitivity analysis for CTA Phase 2b.

Given fixed-notional sizing ($100 per coin × 6 coins = $600 base),
compute returns and MDD under leverage multipliers: ×0.5, ×1, ×2.

Since PnL is linear in notional and MDD is computed on equity curve,
we scale both:
  - $-PnL scales linearly
  - MDD% scales approximately linearly (same drawdown magnitude, proportional equity impact)
  - % return scales linearly (same notional PnL / higher/lower base)

Approach: Load daily PnL from full backtest, compute equity curves for each leverage,
then report return% and MDD% for each side separately.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parent / "src"))

_spec = importlib.util.spec_from_file_location(
    "p2b", _SCRIPTS / "research_cta_positioning_phase2b.py")
p2b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2b)

SYMBOLS = p2b.SYMBOLS
PORT_BASE = p2b.PORT_BASE
SCRATCHPAD = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                  "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad")


def build_frames():
    """Load all data and compute raw indicators."""
    frames, cov_starts, cov_ends = {}, [], []
    for sym, coin in SYMBOLS.items():
        kls = p2b.load_klines(sym)
        oi, long_pct = p2b.load_coinalyze(coin)
        for tf in p2b.TFS:
            bars = p2b.bar_frame(kls[tf], oi, long_pct, tf)
            frames[(coin, tf)] = p2b.raw_indicators(bars, tf)
        b4 = frames[(coin, "4h")]
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())
    window_start = max(cov_starts)
    window_end = min(cov_ends)
    stats_start = (window_start + pd.Timedelta(days=p2b.CROWD_WARMUP_DAYS)).ceil("D")
    return frames, window_start, window_end, stats_start


def extract_daily_pnl(frames, stats_start, side):
    """Extract daily PnL for a given side (short or long)."""
    tf, p, fl = "4h", 10, 24
    per_coin_daily = {}
    for sym, coin in SYMBOLS.items():
        sig = p2b.shifted_signals(frames[(coin, tf)], p, fl)
        bar_pnl, trades = p2b.simulate(sig, side)
        per_coin_daily[coin] = bar_pnl.resample("1D").sum()
    daily = pd.concat(per_coin_daily.values(), axis=1).fillna(0).sum(axis=1)
    return daily.loc[stats_start:]


def compute_equity_metrics(daily_pnl, base_capital, leverage):
    """Compute return% and MDD% under a given leverage.

    Args:
        daily_pnl: Series of daily PnL in dollars
        base_capital: Initial capital (before leverage)
        leverage: Multiplier (0.5, 1.0, 2.0)

    Returns:
        dict with 'ret_pct', 'mdd_pct'
    """
    scaled_pnl = daily_pnl * leverage
    scaled_base = base_capital * leverage
    equity = scaled_base + scaled_pnl.cumsum()

    total_ret = scaled_pnl.sum()
    ret_pct = (total_ret / scaled_base) * 100.0

    eq_dd = equity / equity.cummax() - 1.0
    mdd_pct = eq_dd.min() * 100.0

    return {
        "ret_pct": ret_pct,
        "mdd_pct": mdd_pct,
        "total_pnl": total_ret,
    }


def main():
    SCRATCHPAD.mkdir(parents=True, exist_ok=True)

    print("Loading data and building frames...")
    frames, w_start, w_end, stats_start = build_frames()

    lines = [
        "=== CTA Leverage Sensitivity Analysis (4h-p10-fuel24, crowd-ON) ===",
        f"Data window: {w_start:%Y-%m-%d} to {w_end:%Y-%m-%d}",
        f"Stats from: {stats_start:%Y-%m-%d}",
        f"Base capital: ${PORT_BASE}",
        "",
    ]

    for side in ("short", "long"):
        print(f"Computing daily PnL for {side}...")
        daily_pnl = extract_daily_pnl(frames, stats_start, side)

        lines.append(f"\n--- {side.upper()} SIDE ---")
        lines.append(f"{'Leverage':<12s}{'Capital':<15s}{'Return %':<12s}{'MDD %':<12s}{'Total PnL $':<15s}")
        lines.append("-" * 70)

        for leverage in (0.5, 1.0, 2.0):
            metrics = compute_equity_metrics(daily_pnl, PORT_BASE, leverage)
            capital = PORT_BASE * leverage
            lines.append(
                f"×{leverage:<10.1f}${capital:<14.0f}{metrics['ret_pct']:<11.2f}%"
                f"{metrics['mdd_pct']:<11.1f}%${metrics['total_pnl']:<14.2f}"
            )

    out_path = SCRATCHPAD / "leverage_sensitivity.txt"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Leverage analysis written to: {out_path}")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
