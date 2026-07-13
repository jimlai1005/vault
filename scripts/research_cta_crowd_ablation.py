"""Crowd-filter A/B ablation for the short-crowding CTA family (read-only research).

Scientific question: does the CROWD condition add value ON TOP OF trend+fuel?
  crowd-ON  short entry = trend_dn AND crowd_long AND fuel   (the live signal)
  crowd-OFF short entry = trend_dn            AND fuel       (crowd dropped)
  (long side mirrored: trend_up [AND crowd_short] AND fuel)

This is an ablation, not a new strategy. It REUSES the exact phase-2b engine
(scripts/research_cta_positioning_phase2b.py: load_klines / load_coinalyze /
bar_frame / raw_indicators / shifted_signals / simulate / daily_stats) so the
crowd-ON arm reproduces the published phase-2b numbers bar-for-bar. Crowd-OFF is
produced by forcing the crowd_long / crowd_short signal columns to True (crowd
gate always passes) — nothing else changes: same window, same stats_start, same
fuel gate, same exits (trend flip / fuel fail / 2xATR stop / 14d maxhold), same
fees. Crowd only ever gates ENTRY, so this isolates exactly the crowd filter.

Same-basis discipline (engineering principle #1): both arms are scored on the
IDENTICAL window and stats_start (30d crowding warmup after the common
coverage start), so crowd-OFF is not silently handed extra early bars.

Does NOT modify any file under src/hlvault/cta/ (live engine). Read-only: no
orders, no network unless the caches are missing (they are present -> offline).

Usage: .venv/bin/python scripts/research_cta_crowd_ablation.py
Writes a full table to scratchpad; prints the headline 4-cell A/B to stdout.
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

# Import the phase-2b engine as a module WITHOUT running its main().
_spec = importlib.util.spec_from_file_location(
    "p2b", _SCRIPTS / "research_cta_positioning_phase2b.py")
p2b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2b)

PORT_BASE = p2b.PORT_BASE            # $600 (6 coins x $100)
SYMBOLS = p2b.SYMBOLS                # {BTCUSDT: BTC, ...}

# Production-equivalent config = live cta/config.py: 4h, p10 (crowd_long>=90),
# fuel24. Robustness sweep adds the other pre-declared matrix cells.
PRIMARY = ("4h", 10, 24)
SWEEP = [(tf, p, fl) for tf in ("4h", "1d") for p in (10, 20) for fl in (24, 72)]


def _profit_factor(trades: list[dict]) -> float:
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _crowd_off(sig: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of a shifted-signal frame with the crowd gate disabled
    (crowd_long / crowd_short forced True on every bar). Trend, fuel, atr,
    prices untouched -> entry collapses to trend AND fuel."""
    out = sig.copy()
    out["crowd_long"] = True
    out["crowd_short"] = True
    return out


def run_cell(frames, tf, side, crowd_on, p, fuel_lb, stats_start):
    """One A/B cell: 6-coin portfolio, one side, crowd on/off, at (tf,p,fuel_lb).
    Returns dict of portfolio metrics scored from stats_start (same as phase2b)."""
    per_coin_daily = {}
    all_trades = []
    for sym, coin in SYMBOLS.items():
        sig = p2b.shifted_signals(frames[(coin, tf)], p, fuel_lb)
        if not crowd_on:
            sig = _crowd_off(sig)
        bar_pnl, trades = p2b.simulate(sig, side)
        per_coin_daily[coin] = bar_pnl.resample("1D").sum()
        for t in trades:
            t["coin"] = coin
        all_trades.extend(trades)
    daily = pd.concat(per_coin_daily.values(), axis=1).fillna(0).sum(axis=1)
    st = p2b.daily_stats(daily, stats_start, stats_start)  # split unused here
    tr = [t for t in all_trades if t["exit_time"] >= stats_start]
    return {
        "ret_pct": st["ret"] * 100.0,
        "pnl": st["pnl"],
        "pf": _profit_factor(tr),
        "trades": len(tr),
        "mdd_pct": st["mdd"] * 100.0,
        "win_pct": (np.mean([t["pnl"] > 0 for t in tr]) * 100.0) if tr else 0.0,
    }


def build_frames():
    """Load caches and compute raw indicators per (coin, tf); also return the
    common backtest window + stats_start (identical to phase2b's derivation)."""
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


def fmt_pf(pf: float) -> str:
    return " inf" if pf == float("inf") else f"{pf:5.2f}"


def main() -> None:
    frames, w0, w1, stats_start = build_frames()
    print(f"data window [{w0:%Y-%m-%d} .. {w1:%Y-%m-%d}]  "
          f"stats from {stats_start:%Y-%m-%d} (30d crowd warmup)  "
          f"source: cached Binance klines + Coinalyze OI/LSR (offline)")

    tf, p, fl = PRIMARY
    print(f"\n=== HEADLINE A/B  (production config {tf}-p{p}-fuel{fl}, "
          f"6-coin $100 portfolio, base ${PORT_BASE:.0f}) ===")
    hdr = f"{'cell':<22s}{'ret%':>8s}{'pnl$':>9s}{'PF':>7s}{'trades':>8s}{'MDD%':>8s}{'win%':>7s}"
    print(hdr)
    headline = {}
    for side in ("short", "long"):
        for crowd_on in (True, False):
            r = run_cell(frames, tf, side, crowd_on, p, fl, stats_start)
            tag = f"{side}/crowd-{'ON' if crowd_on else 'OFF'}"
            headline[tag] = r
            print(f"{tag:<22s}{r['ret_pct']:>7.2f}%{r['pnl']:>9.2f}{fmt_pf(r['pf']):>7s}"
                  f"{r['trades']:>8d}{r['mdd_pct']:>7.1f}%{r['win_pct']:>6.0f}%")

    # Full robustness sweep -> file
    lines = ["crowd-filter ablation — full sweep (all pre-declared matrix cells)",
             f"data window [{w0:%Y-%m-%d} .. {w1:%Y-%m-%d}]  stats from {stats_start:%Y-%m-%d}",
             "source: cached Binance klines (data/cache/cta) + Coinalyze OI/LSR "
             "(data/cache/coinalyze), 4h-native, ~335d. OFFLINE, no network.",
             "PF = gross win $ / gross loss $ (post-stats_start trades). "
             "'both arms same window+stats_start' (engineering principle #1).", "",
             f"{'config':<18s}{'side':<7s}{'crowd':<5s}"
             f"{'ret%':>8s}{'pnl$':>9s}{'PF':>7s}{'trades':>8s}{'MDD%':>8s}{'win%':>7s}"]
    for (tf, p, fl) in SWEEP:
        for side in ("short", "long"):
            for crowd_on in (True, False):
                r = run_cell(frames, tf, side, crowd_on, p, fl, stats_start)
                lines.append(
                    f"{tf+'-p'+str(p)+'-f'+str(fl):<18s}{side:<7s}"
                    f"{'ON' if crowd_on else 'OFF':<5s}"
                    f"{r['ret_pct']:>7.2f}%{r['pnl']:>9.2f}{fmt_pf(r['pf']):>7s}"
                    f"{r['trades']:>8d}{r['mdd_pct']:>7.1f}%{r['win_pct']:>6.0f}%")
        lines.append("")
    out = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
               "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/cta_crowd_ablation_full.txt")
    out.write_text("\n".join(lines) + "\n")
    print(f"\nfull sweep -> {out}")


if __name__ == "__main__":
    main()
