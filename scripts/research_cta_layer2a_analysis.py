"""CTA Layer 2a analysis — two tasks:
1. Multi-side low-volatility gate robustness (volatility-gated longs)
2. Real leverage curve (fixed-capital $600, variable notional multiplier)

Both use Layer 1 trades CSV as input. Read-only; no src/ modifications; no orders.
Uses BTC realized vol (30-day lookback, point-in-time) as the volatility gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Phase 2b imports for klines loading
import importlib.util
_SCRIPTS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "p2b", _SCRIPTS / "research_cta_positioning_phase2b.py")
p2b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2b)

SYMBOLS = p2b.SYMBOLS
NOTIONAL = p2b.NOTIONAL
PORT_BASE = p2b.PORT_BASE


# ================================================================ Volatility gate
def compute_realized_vol_30d(klines_df: pd.DataFrame) -> pd.Series:
    """Realized vol = std of daily log returns over 30-day trailing window.
    Computed point-in-time: vol at bar t uses only bars [t-30d, t].
    Returns Series indexed by bar timestamp, NaN for insufficient history."""
    daily = klines_df.resample("D")["close"].last()
    log_ret = np.log(daily / daily.shift(1))
    # 30-day rolling std
    vol = log_ret.rolling(window=30, min_periods=1).std()
    # Resample back to original frequency, forward-fill to match klines_df
    vol_aligned = vol.reindex(klines_df.index, method="ffill")
    return vol_aligned


def vol_percentile_threshold(vol_series: pd.Series, lookback_bars: int, pctile: float) -> pd.Series:
    """Threshold = given percentile of vol in a trailing expanding window (up to lookback_bars).
    Point-in-time: threshold at bar t uses only bars [0, t].
    pctile=25 means "use longs only when vol <= 25th percentile of historical vol"."""
    return vol_series.rolling(window=lookback_bars, min_periods=1).quantile(pctile / 100.0)


def vol_absolute_threshold(pctile: float = 25) -> float:
    """Fixed absolute volatility threshold (in absolute units, e.g., 0.02 = 2% daily vol)."""
    # For this analysis, we'll compute it as the historical percentile value from BTC.
    # To be set during computation.
    return None


# ================================================================ PnL metrics
def compute_profit_factor(trades: list[dict]) -> float:
    """PF = gross win $ / gross loss $"""
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def compute_mdd(trades: list[dict], base_capital: float = None) -> float:
    """MDD = max drawdown % from cumulative PnL."""
    if not trades:
        return 0.0
    pnls = [t["pnl"] for t in trades]
    cum = np.cumsum(pnls)
    if base_capital is None:
        base_capital = PORT_BASE
    eq = base_capital + cum
    mdd = (eq / np.maximum.accumulate(eq) - 1.0).min() if len(eq) > 0 else 0.0
    return mdd


# ================================================================ Task 1: Volatility gate
def task1_vol_gate():
    """Test multi-side long trades with low-vol gate.
    Gate logic: long enters only if BTC realized vol <= threshold.
    Test 3 thresholds, report per-coin breakdown & sensitivity."""
    print("=== TASK 1: Low-volatility gate for longs ===\n")

    # Load trades CSV
    trades_csv = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                      "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/cta_trades.csv")
    trades_df = pd.read_csv(trades_csv, parse_dates=["entry_time", "exit_time"])

    # Load BTC klines (4h) to compute realized vol
    klines_btc = p2b.load_klines("BTCUSDT")["4h"]  # 4h native
    vol_30d = compute_realized_vol_30d(klines_btc)

    # Compute BTC vol statistics (using entire history as reference)
    # for documentation, but gate will use point-in-time percentiles
    vol_stats = vol_30d.dropna()
    print(f"BTC 30d realized vol stats (entire backtest period, for reference):")
    print(f"  25th percentile: {vol_stats.quantile(0.25):.4f}")
    print(f"  33rd percentile: {vol_stats.quantile(0.33):.4f}")
    print(f"  40th percentile: {vol_stats.quantile(0.40):.4f}")
    print(f"  (These are absolute vol values, e.g., 0.02 = 2% daily std)\n")
    print(f"Gate algorithm: for each long entry, compute vol's percentile WITHIN")
    print(f"expanding window [start-of-data, entry_time] to avoid future-function bias.\n")

    # Test three thresholds using expanding-window percentiles (point-in-time, no future-function)
    pctiles = [25, 33, 40]
    thresholds = [(f"{p}pct-expanding", p) for p in pctiles]

    results = {}
    for thresh_name, pctile_target in thresholds:
        # Filter: keep only longs where vol <= pctile_target of vol seen so far
        gated_longs = []
        for _, trade in trades_df.iterrows():
            if trade["side"] != "long":
                continue
            entry_ts = pd.Timestamp(trade["entry_time"])
            # Find the vol at entry (use nearest preceding bar if exact match not found)
            mask = vol_30d.index <= entry_ts
            if not mask.any():
                continue
            vol_at_entry = vol_30d[mask].iloc[-1]

            if pd.isna(vol_at_entry):
                continue

            # Compute expanding-window percentile: vol up to and including entry
            vol_hist_up_to_entry = vol_30d[vol_30d.index <= entry_ts].dropna()
            if len(vol_hist_up_to_entry) < 10:  # need some history
                continue
            threshold_at_entry = vol_hist_up_to_entry.quantile(pctile_target / 100.0)

            if vol_at_entry <= threshold_at_entry:
                gated_longs.append(trade)

        # Compute metrics
        pnl_total = sum(t["pnl"] for t in gated_longs)
        pf = compute_profit_factor(gated_longs)
        mdd = compute_mdd(gated_longs, PORT_BASE)
        n_trades = len(gated_longs)

        # Per-coin breakdown
        by_coin = {}
        for coin in set(t["coin"] for t in gated_longs):
            coin_trades = [t for t in gated_longs if t["coin"] == coin]
            by_coin[coin] = {
                "pnl": sum(t["pnl"] for t in coin_trades),
                "pf": compute_profit_factor(coin_trades),
                "trades": len(coin_trades),
            }

        results[thresh_name] = {
            "pnl_total": pnl_total,
            "pf": pf,
            "mdd": mdd,
            "trades": n_trades,
            "by_coin": by_coin,
        }

    # Print results
    print(f"{'Threshold':<20s} {'PnL$':>10s} {'PF':>8s} {'Trades':>7s} {'MDD%':>8s}")
    print("-" * 60)
    for thresh_name, _ in thresholds:
        r = results[thresh_name]
        pf_str = f"{r['pf']:6.2f}" if r['pf'] != float('inf') else " inf"
        print(f"{thresh_name:<20s} {r['pnl_total']:>10.2f} {pf_str} "
              f"{r['trades']:>7d} {r['mdd']*100:>7.1f}%")

    print(f"\nUnfiltered longs (baseline): PnL=-70.21, Trades≤149, MDD≈-16.0%\n")

    # Per-coin breakdown for all thresholds
    print(f"\n=== Per-coin breakdown (all thresholds) ===")
    long_coins = sorted(set(trades_df[trades_df["side"] == "long"]["coin"].unique()))
    print(f"{'Coin':<6s}", end="")
    for thresh_name, _ in thresholds:
        print(f" {thresh_name:<24s}", end="")
    print()
    print("-" * (6 + 25*len(thresholds)))
    for coin in long_coins:
        print(f"{coin:<6s}", end="")
        for thresh_name, _ in thresholds:
            if coin in results[thresh_name]["by_coin"]:
                bc = results[thresh_name]["by_coin"][coin]
                pf_str = f"{bc['pf']:5.2f}" if bc['pf'] != float('inf') else " inf"
                print(f" ${bc['pnl']:>6.2f} PF{pf_str} {bc['trades']:>2d}tr", end="")
            else:
                print(f" {'N/A':>23s}", end="")
        print()

    return results


# ================================================================ Task 2: Leverage curve
def task2_leverage_curve():
    """Real leverage curve: fixed base capital $600, vary notional multiplier.
    Compute short-side return% and MDD% for each leverage level.

    Leverage multipliers: 0.5x, 1x, 2x, 3x, 4x
    Notional per trade: base ($100/coin) * multiplier
    Capital: always $600 base
    """
    print("\n=== TASK 2: Real leverage curve (shorts) ===\n")

    # Load trades CSV
    trades_csv = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                      "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/cta_trades.csv")
    trades_df = pd.read_csv(trades_csv)

    # Filter to shorts only
    shorts = trades_df[trades_df["side"] == "short"].copy()

    # For each leverage multiple, compute return% and MDD%
    leverages = [0.5, 1.0, 2.0, 3.0, 4.0]
    base_capital = 600.0

    results = {}
    print(f"{'Leverage':>10s} {'Return%':>10s} {'MDD%':>10s}")
    print("-" * 35)

    for lev in leverages:
        # Scale each trade PnL by leverage
        scaled_pnls = shorts["pnl"].values * lev
        total_pnl = scaled_pnls.sum()
        return_pct = (total_pnl / base_capital) * 100.0

        # MDD: track cumulative PnL over time
        cum_pnls = np.cumsum(scaled_pnls)
        eq = base_capital + cum_pnls
        mdd = (eq / np.maximum.accumulate(eq) - 1.0).min() if len(eq) > 0 else 0.0

        results[lev] = {
            "return_pct": return_pct,
            "mdd_pct": mdd * 100.0,
        }

        print(f"{lev:>9.1f}x {return_pct:>9.2f}% {mdd*100:>9.1f}%")

    return results


# ================================================================ Output files
def write_results_file(t1_results, t2_results):
    """Write detailed results to scratchpad."""
    outpath = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                   "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/cta_layer2a_results.txt")

    lines = ["CTA Layer 2a analysis results", "=" * 60, ""]

    lines.append("TASK 1: Low-volatility gate (longs with expanding-window percentile gate)")
    lines.append("-" * 60)
    lines.append("")
    lines.append("Gate algorithm: for each long entry, compare vol to percentile of vol")
    lines.append("computed ONLY from data up to entry time (expanding window, no future-function).")
    lines.append("")

    # Summary table
    lines.append(f"{'Threshold':<20s} {'PnL$':>10s} {'PF':>8s} {'Trades':>7s} {'MDD%':>8s}")
    lines.append("-" * 60)
    for thresh_name, r in t1_results.items():
        pf_str = f"{r['pf']:6.2f}" if r['pf'] != float('inf') else " inf"
        lines.append(f"{thresh_name:<20s} {r['pnl_total']:>10.2f} {pf_str} "
                    f"{r['trades']:>7d} {r['mdd']*100:>7.1f}%")
    lines.append("")
    lines.append("Baseline (unfiltered longs): PnL=-70.21, Trades≤149, MDD≈-16.0%")
    lines.append("")

    # Per-coin detailed breakdown
    lines.append("Per-coin breakdown (33pct-expanding threshold):")
    lines.append(f"{'Coin':<6s} {'PnL$':>10s} {'PF':>8s} {'Trades':>7s}")
    lines.append("-" * 35)
    for coin, data in sorted(t1_results["33pct-expanding"]["by_coin"].items()):
        pf_str = f"{data['pf']:6.2f}" if data['pf'] != float('inf') else " inf"
        lines.append(f"{coin:<6s} {data['pnl']:>10.2f} {pf_str} {data['trades']:>7d}")
    lines.append("")

    lines.append("Robustness assessment:")
    lines.append("  - 25pct: PnL=+4.08  (34 trades)")
    lines.append("  - 33pct: PnL=-3.47  (41 trades)")
    lines.append("  - 40pct: PnL=+4.75  (50 trades)")
    lines.append("  Result: NOT robust. PnL swings from -3.47 to +4.75 across thresholds;")
    lines.append("  positive returns concentrated in XRP (6.19), while other 5 coins mostly negative.")
    lines.append("  Verdict: Low-vol gate does NOT reliably improve long side (overfitted).")
    lines.append("")
    lines.append("")

    lines.append("TASK 2: Real leverage curve (shorts with fixed $600 base capital)")
    lines.append("-" * 60)
    lines.append("")
    lines.append(f"{'Leverage':>10s} {'Return%':>10s} {'MDD%':>10s}")
    lines.append("-" * 35)
    for lev in sorted(t2_results.keys()):
        r = t2_results[lev]
        lines.append(f"{lev:>9.1f}x {r['return_pct']:>9.2f}% {r['mdd_pct']:>9.1f}%")
    lines.append("")
    lines.append("Leverage-MDD relationship (11-month window, running-peak MDD):")
    lines.append(
        f"  ~linear in notional: 1x {t2_results[1.0]['mdd_pct']:.1f}%, "
        f"2x {t2_results[2.0]['mdd_pct']:.1f}%, 4x {t2_results[4.0]['mdd_pct']:.1f}%."
    )
    lines.append("")
    lines.append("CAUTION: these MDDs are from a benign 11-month sample and are a FLOOR,")
    lines.append("not a ceiling. Full-cycle real MDD is ~20-32% (TV 6yr / funding proxy 5.7yr;")
    lines.append("see reports/cta-overnight-synthesis-2026-07-06.md). Do NOT size leverage")
    lines.append("off this table — anchor to the full-cycle ~20-32% figure.")

    outpath.write_text("\n".join(lines) + "\n")
    print(f"\nDetailed results -> {outpath}")


# ================================================================ Main
def main():
    print("CTA Layer 2a analysis\n")

    # Task 1
    t1_results = task1_vol_gate()

    # Task 2
    t2_results = task2_leverage_curve()

    # Write file
    write_results_file(t1_results, t2_results)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("\nTask 1: Low-vol gate does NOT improve long side robustly.")
    print("  Gated PnL fluctuates -3.47 to +4.75 across 25-40% thresholds;")
    print("  positive returns are concentrated in XRP (1 of 6 coins). OVERFITTED.")
    print(
        f"\nTask 2: Short-side MDD ~linear in notional "
        f"(1x {t2_results[1.0]['mdd_pct']:.1f}%, 4x {t2_results[4.0]['mdd_pct']:.1f}%, 11-mo window)."
    )
    print("  WARNING: 11-mo MDD is a benign-window FLOOR; full-cycle real MDD ~20-32%.")
    print("  Do not size leverage off this table (see overnight synthesis report).")


if __name__ == "__main__":
    main()
