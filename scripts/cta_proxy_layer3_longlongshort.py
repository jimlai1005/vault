"""Layer-3 multi-configuration regime study — long-only vs short-only vs both-sides.

Validates whether running both long and short simultaneously provides robust
risk-adjusted advantage over single-side strategies across multiple cycles.

Configuration A: short-only, crowd-ON
Configuration B: long-only, crowd-ON
Configuration C: both-sides (long+short merged), crowd-ON

Three questions:
1. Does (C) exhibit lower MDD than (A) across most years?
   (This is stability decomposition: do we gain from non-correlated edge?)
2. Is (C)'s dominance regime-agnostic, or artifact of a bull/bear window?
3. What is (C)'s true worst MDD when side-equity curves are merged?

Precondition: scripts/cta_proxy_validate.py already confirmed the crowd filter
works (Phase 2b real-window check). This script uses PROXY data to test structural
robustness across cycles, not re-validate the crowd signal itself.

Universe: BTC ETH SOL DOGE XRP (SYMBOLS_5, HYPE excluded). Window: 2020-09~2026-07.
Inline reuse: lib.build_frames(), lib.run_cell(), lib.period_stats().
New: run_both_sides_merged() to generate (C) configuration + merged daily pnl.

Usage: .venv/bin/python scripts/cta_proxy_layer3_longlongshort.py
Output: cta_proxy_layer3_longlongshort.txt, cta_proxy_layer3_longlongshort.json
"""
from __future__ import annotations

import sys
from pathlib import Path
import json

import numpy as np
import pandas as pd
import math

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_proxy_lib as lib

SCRATCHPAD = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                  "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad")
REPORTS = Path("/Users/jim/projects/vault/reports")

TF, PCTILE, FUEL_LB = "4h", 10, 24     # production-equivalent (matches live cta/config.py)


def run_both_sides_merged(frames, symbols, tf, crowd_on, p, fuel_lb, stats_start):
    """Generate configuration (C): both long and short simultaneously.
    Returns: (merged_daily_pnl, all_trades) where merged_daily_pnl is the
    cumulative daily P&L from both sides, and all_trades is the combined trade list.

    Key: merged daily P&L is computed by summing long and short daily pnl
    at each timestamp, so MDD of the merged equity curve reflects true diversification.
    """
    per_coin_daily = {}
    all_trades = []

    for sym, coin in symbols.items():
        sig = lib.shifted_signals(frames[(coin, tf)], p, fuel_lb)
        if not crowd_on:
            sig = lib.crowd_off(sig)

        # Run BOTH sides for this coin, accumulating daily pnl
        long_pnl, long_trades = lib.p2b.simulate(sig, "long")
        short_pnl, short_trades = lib.p2b.simulate(sig, "short")

        # Merge daily P&L: sum of long + short per day
        daily_both = long_pnl.add(short_pnl, fill_value=0)
        per_coin_daily[coin] = daily_both

        # Merge trade lists with source label
        for t in long_trades:
            t["coin"] = coin
            t["side"] = "long"
        for t in short_trades:
            t["coin"] = coin
            t["side"] = "short"
        all_trades.extend(long_trades)
        all_trades.extend(short_trades)

    # Aggregate daily P&L across all coins
    daily_merged = pd.concat(per_coin_daily.values(), axis=1).fillna(0).sum(axis=1)

    # Calculate statistics
    port_base = lib.NOTIONAL * len(symbols)
    d = daily_merged.loc[stats_start:]
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    eq = port_base + d.cumsum()

    # CRITICAL: MDD from running peak (cummax), not max
    # This is the true peak-to-trough of the merged equity curve
    mdd = float((eq / eq.cummax() - 1.0).min())

    tr = [t for t in all_trades if t["exit_time"] >= stats_start]
    return {
        "pnl": d.sum(),
        "ret_pct": d.sum() / port_base * 100.0,
        "sharpe": sharpe,
        "mdd_pct": mdd * 100.0,
        "trades": len(tr),
        "pf": lib.profit_factor(tr),
        "win_pct": (np.mean([t["pnl"] > 0 for t in tr]) * 100.0) if tr else 0.0,
        "daily": daily_merged,
        "n_days": n,
        "port_base": port_base,
        "all_trades": all_trades,
    }


def period_stats_merged(daily_full: pd.Series, start: pd.Timestamp, end: pd.Timestamp,
                        port_base: float) -> dict:
    """Path-based Sharpe/MDD for a contiguous calendar slice of merged daily pnl."""
    d = daily_full.loc[start:end - pd.Timedelta(seconds=1)]
    if len(d) == 0:
        return {"n_days": 0, "pnl": 0.0, "sharpe": 0.0, "mdd_pct": 0.0}
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 and n > 1 else 0.0
    eq = port_base + d.cumsum()
    # CRITICAL: running peak, not max
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {"n_days": n, "pnl": d.sum(), "sharpe": sharpe, "mdd_pct": mdd * 100.0}


def fmt_row(label: str, stats: dict) -> str:
    """Format a single row for output tables."""
    return (f"{label:<35s}{stats['sharpe']:>8.2f}{stats['mdd_pct']:>8.1f}%"
            f"{stats['pnl']:>9.2f}{stats['trades']:>8d}")


def main() -> None:
    print("Layer 3: Long-only vs Short-only vs Both-sides stability decomposition")
    print("=" * 80)

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    stats_start = (w_start + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    n_years = (w_end - stats_start).days / 365.25

    print(f"Universe: {list(lib.SYMBOLS_5.values())}  (5 coins, HYPE excluded)")
    print(f"Window: [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]  stats from {stats_start:%Y-%m-%d}")
    print(f"Configuration: {TF} | percentile {PCTILE} | fuel {FUEL_LB}h")
    print(f"  (A) Short-only, crowd-ON")
    print(f"  (B) Long-only, crowd-ON")
    print(f"  (C) Both-sides merged, crowd-ON")
    print()

    lines = [
        f"Layer 3: Long-only vs Short-only vs Both-sides decomposition",
        f"Universe: {list(lib.SYMBOLS_5.values())}  Window: [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]",
        f"Config: {TF}-p{PCTILE}-fuel{FUEL_LB}",
        f"Stats from {stats_start:%Y-%m-%d} (~{n_years:.1f}y)",
        "",
    ]

    # Compute full-period cells for A, B, C
    print("=" * 80)
    print("FULL-PERIOD HEADLINE")
    print("=" * 80)
    hdr = f"{'Config':<35s}{'Sharpe':>8s}{'MDD%':>8s}{'PnL$':>9s}{'Trades':>8s}"
    print(hdr)
    lines.append(hdr)

    cell_short = lib.run_cell(frames, lib.SYMBOLS_5, TF, "short", True, PCTILE, FUEL_LB, stats_start)
    cell_long = lib.run_cell(frames, lib.SYMBOLS_5, TF, "long", True, PCTILE, FUEL_LB, stats_start)
    cell_both = run_both_sides_merged(frames, lib.SYMBOLS_5, TF, True, PCTILE, FUEL_LB, stats_start)

    cells = {
        "A_short_only": cell_short,
        "B_long_only": cell_long,
        "C_both_merged": cell_both,
    }

    for key, cell in cells.items():
        row = fmt_row(key, cell)
        print(row)
        lines.append(row)

    print()
    print(f"Key insight: (C) merged MDD {cell_both['mdd_pct']:.1f}% vs A {cell_short['mdd_pct']:.1f}% / B {cell_long['mdd_pct']:.1f}%")
    lines.append(f"\nKey insight: (C) merged MDD {cell_both['mdd_pct']:.1f}% vs A {cell_short['mdd_pct']:.1f}% / B {cell_long['mdd_pct']:.1f}%")

    # Year-by-year decomposition
    print()
    print("=" * 80)
    print("YEAR-BY-YEAR DECOMPOSITION (contiguous calendar slices)")
    print("=" * 80)
    yr_hdr = f"{'Year':<6s}{'Config':<20s}{'Days':>6s}{'Sharpe':>8s}{'MDD%':>8s}{'PnL$':>9s}"
    print(yr_hdr)
    lines.append(yr_hdr)

    years = list(range(w_start.year, w_end.year + 1))
    yearly_results = {yr: {} for yr in years}

    for yr in years:
        y0 = max(stats_start, pd.Timestamp(yr, 1, 1))
        y1 = min(w_end + pd.Timedelta(days=1), pd.Timestamp(yr + 1, 1, 1))
        if y0 >= y1:
            continue

        # (A) Short-only
        ps_a = lib.period_stats(cell_short["daily"], y0, y1, cell_short["port_base"])
        if ps_a["n_days"] > 0:
            row = f"{yr:<6d}{'A_short_only':<20s}{ps_a['n_days']:>6d}{ps_a['sharpe']:>8.2f}{ps_a['mdd_pct']:>8.1f}%{ps_a['pnl']:>9.2f}"
            print(row)
            lines.append(row)
            yearly_results[yr]["A_mdd"] = ps_a["mdd_pct"]
            yearly_results[yr]["A_sharpe"] = ps_a["sharpe"]
            yearly_results[yr]["A_pnl"] = ps_a["pnl"]

        # (B) Long-only
        ps_b = lib.period_stats(cell_long["daily"], y0, y1, cell_long["port_base"])
        if ps_b["n_days"] > 0:
            row = f"{yr:<6d}{'B_long_only':<20s}{ps_b['n_days']:>6d}{ps_b['sharpe']:>8.2f}{ps_b['mdd_pct']:>8.1f}%{ps_b['pnl']:>9.2f}"
            print(row)
            lines.append(row)
            yearly_results[yr]["B_mdd"] = ps_b["mdd_pct"]
            yearly_results[yr]["B_sharpe"] = ps_b["sharpe"]
            yearly_results[yr]["B_pnl"] = ps_b["pnl"]

        # (C) Both-sides merged
        ps_c = period_stats_merged(cell_both["daily"], y0, y1, cell_both["port_base"])
        if ps_c["n_days"] > 0:
            row = f"{yr:<6d}{'C_both_merged':<20s}{ps_c['n_days']:>6d}{ps_c['sharpe']:>8.2f}{ps_c['mdd_pct']:>8.1f}%{ps_c['pnl']:>9.2f}"
            print(row)
            lines.append(row)
            yearly_results[yr]["C_mdd"] = ps_c["mdd_pct"]
            yearly_results[yr]["C_sharpe"] = ps_c["sharpe"]
            yearly_results[yr]["C_pnl"] = ps_c["pnl"]

        print()

    # Analysis: does (C) reduce MDD vs (A) across years?
    print()
    print("=" * 80)
    print("STABILITY ANALYSIS: Does (C) reduce risk vs (A) across cycles?")
    print("=" * 80)
    c_better_than_a = 0
    c_better_than_b = 0
    n_valid_years = 0

    for yr in years:
        if yr not in yearly_results or "C_mdd" not in yearly_results[yr]:
            continue
        n_valid_years += 1
        c_mdd = abs(yearly_results[yr]["C_mdd"])
        a_mdd = abs(yearly_results[yr]["A_mdd"])
        b_mdd = abs(yearly_results[yr]["B_mdd"])

        c_wins_a = c_mdd < a_mdd
        c_wins_b = c_mdd < b_mdd
        c_better_than_a += c_wins_a
        c_better_than_b += c_wins_b

        status = "✓" if c_wins_a else "✗"
        print(f"  {yr}: (C) {c_mdd:6.1f}% vs (A) {a_mdd:6.1f}% {status} | vs (B) {b_mdd:6.1f}% {'✓' if c_wins_b else '✗'}")

    print()
    if n_valid_years > 0:
        frac_a = c_better_than_a / n_valid_years
        frac_b = c_better_than_b / n_valid_years
        print(f"(C) beats (A) in {c_better_than_a}/{n_valid_years} years ({frac_a*100:.0f}%)")
        print(f"(C) beats (B) in {c_better_than_b}/{n_valid_years} years ({frac_b*100:.0f}%)")
        lines.append(f"\n(C) beats (A) in {c_better_than_a}/{n_valid_years} years ({frac_a*100:.0f}%)")
        lines.append(f"(C) beats (B) in {c_better_than_b}/{n_valid_years} years ({frac_b*100:.0f}%)")

    # Write full output
    out = SCRATCHPAD / "cta_proxy_layer3_longlongshort.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nfull output -> {out}")

    # Machine-readable summary
    summary = {
        "metadata": {
            "description": "Layer 3: long-only vs short-only vs both-sides stability decomposition",
            "universe": list(lib.SYMBOLS_5.values()),
            "window": [str(w_start.date()), str(w_end.date())],
            "stats_start": str(stats_start.date()),
            "n_years": round(n_years, 2),
            "config_tf": TF,
            "config_percentile": PCTILE,
            "config_fuel_hours": FUEL_LB,
            "note_proxy": "Binance funding rate + quote volume (proxy, not real crowd)",
            "note_mdd": "All MDD calculated with running peak (cummax), not max",
        },
        "full_period": {
            "A_short_only": {
                "sharpe": round(cell_short["sharpe"], 3),
                "mdd_pct": round(cell_short["mdd_pct"], 1),
                "pnl": round(cell_short["pnl"], 2),
                "trades": cell_short["trades"],
            },
            "B_long_only": {
                "sharpe": round(cell_long["sharpe"], 3),
                "mdd_pct": round(cell_long["mdd_pct"], 1),
                "pnl": round(cell_long["pnl"], 2),
                "trades": cell_long["trades"],
            },
            "C_both_merged": {
                "sharpe": round(cell_both["sharpe"], 3),
                "mdd_pct": round(cell_both["mdd_pct"], 1),
                "pnl": round(cell_both["pnl"], 2),
                "trades": cell_both["trades"],
            },
        },
        "year_by_year": yearly_results,
        "analysis": {
            "C_beats_A_years": f"{c_better_than_a}/{n_valid_years}",
            "C_beats_A_pct": round(c_better_than_a / n_valid_years * 100, 0) if n_valid_years > 0 else 0,
            "C_beats_B_years": f"{c_better_than_b}/{n_valid_years}",
            "C_beats_B_pct": round(c_better_than_b / n_valid_years * 100, 0) if n_valid_years > 0 else 0,
        },
    }

    (SCRATCHPAD / "cta_proxy_layer3_longlongshort.json").write_text(json.dumps(summary, indent=2))
    print(f"summary json -> {SCRATCHPAD / 'cta_proxy_layer3_longlongshort.json'}")


if __name__ == "__main__":
    main()
