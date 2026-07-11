"""F2 Overshoot-Fade Walk-Forward Backtest (sub-project H).

Fade dump (long) / fade pump (short) signals on overshoot beyond rolling extremes.
Config grid: W ∈ {15,30,60}, K ∈ {3,4,5} => 9 configs.
Exit: target = 38.2% retracement of extreme move; stop = 0.5*ATR14 beyond extreme;
time-stop = 60 bars. Walk-forward train 60d/test 30d.

Reports exit_reason distribution (target/stop/time %) and flags divergence if stop > 50%.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import scalp_backtest_lib as backtest_lib


HOLD_BARS = 60
TIME_STOP = 60
DATA_DIR = Path("data/scalp")
REPORTS_DIR = Path("reports")
CONFIGS = [
    {"W": w, "K": k}
    for w in (15, 30, 60)
    for k in (3, 4, 5)
]


def load_shortlist() -> list:
    """Load shortlist.json (coins to backtest)."""
    path = DATA_DIR / "shortlist.json"
    with open(path) as f:
        return json.load(f)


def load_fees_slippage() -> tuple:
    """Load fees.json and slippage.json; return (fee_bps, slippage_dict)."""
    with open(DATA_DIR / "fees.json") as f:
        fees_data = json.load(f)
    fee_bps = fees_data["taker"] * 1e4  # Convert to bps

    with open(DATA_DIR / "slippage.json") as f:
        slippage_data = json.load(f)

    return fee_bps, slippage_data


def generate_f2_signals(df: pd.DataFrame, cfg: dict) -> tuple:
    """Generate F2 fade signals and return (sig, target_px, stop_px).

    cfg: {"W": int, "K": int} — dict form, matching CONFIGS entries that
    walk_forward passes through to run_fn unchanged.
    fade dump (long): ext_z <= -K & vol_z >= 3 & wick_lo >= 0.3
    target = extreme + 0.382*(window_start_c - extreme)
    stop = extreme - 0.5*atr14
    fade pump (short): opposite
    """
    W, K = cfg["W"], cfg["K"]
    n = len(df)

    # Cumulative log return over W bars
    cum = np.log(df["c"].values / np.roll(df["c"].values, W))
    cum[:W] = np.nan

    # Z-score of cumulative return
    ext_z = cum / (df["sigma"].values * np.sqrt(W))

    # Wick position: (close - low) / (high - low)
    wick_lo = (df["c"].values - df["l"].values) / (
        df["h"].values - df["l"].values + 1e-12
    )

    vol_z = df["vol_z"].values
    atr = df["atr14"].values

    sig = np.zeros(n, dtype=int)
    target_px = np.full(n, np.nan)
    stop_px = np.full(n, np.nan)

    for i in range(W, n):
        # Fade dump (long): bottom fishing
        if ext_z[i] <= -K and vol_z[i] >= 3 and wick_lo[i] >= 0.3:
            # Rolling window [i-W+1, i]
            window_low = df["l"].iloc[i - W + 1 : i + 1].min()
            window_start_c = df["c"].iloc[i - W + 1]
            target_px[i] = window_low + 0.382 * (window_start_c - window_low)
            stop_px[i] = window_low - 0.5 * atr[i]
            sig[i] = 1

        # Fade pump (short): top fishing (opposite)
        elif ext_z[i] >= K and vol_z[i] >= 3 and (1 - wick_lo[i]) >= 0.3:
            # Rolling window [i-W+1, i]
            window_high = df["h"].iloc[i - W + 1 : i + 1].max()
            window_start_c = df["c"].iloc[i - W + 1]
            target_px[i] = window_high - 0.382 * (window_high - window_start_c)
            stop_px[i] = window_high + 0.5 * atr[i]
            sig[i] = -1

    return sig, target_px, stop_px


def run_f2(df: pd.DataFrame, cfg: dict, fee_bps: float, slip_bps: float) -> list:
    """Run F2 backtest for a single config."""
    sig, target_px, stop_px = generate_f2_signals(df, cfg)
    trades = backtest_lib.simulate(
        df,
        sig,
        hold_bars=TIME_STOP,
        stop_atr_mult=0.5,  # Not used; stop_px provided
        fee_bps=fee_bps,
        slip_bps=slip_bps,
        coin="",
        target_px=target_px,
        stop_px=stop_px,
    )
    return trades


def backtest_coin(
    coin: str, fee_bps: float, slip_bps: float, smoke: bool = False
) -> tuple:
    """Backtest a single coin across all F2 configs.

    Returns: (oos_trades, picks, pooled_metrics, by_coin_metrics)
    """
    path = DATA_DIR / f"{coin}_1m.csv.gz"
    if not path.exists():
        print(f"  {coin}: data file not found, skipping")
        return [], [], {}, {}

    df = pd.read_csv(path)
    df["t"] = df["t"].astype("int64")
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["c"] = df["c"].astype(float)
    df["o"] = df["o"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["v"] = df["v"].astype(float)

    # Prep: add indicators
    df = backtest_lib.prep(df)

    # Smoke test: use only first 2 days
    if smoke:
        df = df.head(2880)  # ~2 days of 1m bars

    if len(df) < 7000:  # Less than ~5 days, not enough for walk_forward
        print(f"  {coin}: insufficient data ({len(df)} bars), skipping")
        return [], [], {}, {}

    # Walk-forward backtest
    oos_trades, picks = backtest_lib.walk_forward(
        df,
        CONFIGS,
        lambda df_slice, cfg: run_f2(df_slice, cfg, fee_bps, slip_bps),
        train_days=60,
        test_days=30,
    )

    if oos_trades:
        for t in oos_trades:
            t.coin = coin

    pooled_metrics = backtest_lib.metrics(oos_trades, df)
    by_coin_metrics = {"coin": coin, **pooled_metrics, "picks": picks}

    return oos_trades, picks, pooled_metrics, by_coin_metrics


def compute_exit_reason_distribution(trades: list) -> dict:
    """Count exit reasons (target/stop/time) and return as percentages."""
    if not trades:
        return {"target": 0.0, "stop": 0.0, "time": 0.0, "count": 0}

    reasons = [t.exit_reason for t in trades]
    total = len(reasons)
    return {
        "target": round(sum(1 for r in reasons if r == "target") / total * 100, 1),
        "stop": round(sum(1 for r in reasons if r == "stop") / total * 100, 1),
        "time": round(sum(1 for r in reasons if r == "time") / total * 100, 1),
        "count": total,
    }


def format_metrics_table(metrics_list: list, title: str) -> str:
    """Format a list of metrics dicts as markdown table."""
    lines = [f"\n### {title}\n"]
    lines.append("| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |")
    lines.append("|------|------|--------|-------|---------|-------|---------|----------|")

    for m in metrics_list:
        coin = m.get("coin", "POOLED")
        n = m.get("n", 0)
        if n == 0:
            continue
        pf = m.get("pf", 0.0)
        win = m.get("win", 0.0)
        avg = m.get("avg_net_bps", 0.0)
        mdd = m.get("mdd_bps", 0.0)
        t_stat = m.get("t_stat", 0.0)
        months = m.get("months_pos", "0/0")
        lines.append(
            f"| {coin} | {n} | {pf:.3f} | {win:.1%} | {avg:.2f} | {mdd:.1f} | {t_stat:.2f} | {months} |"
        )

    return "\n".join(lines)


def check_g1_gates(pooled_metrics: dict, sensitivity_metrics: dict, trades: list = None) -> tuple:
    """Check G1 gate conditions. Returns (gates dict, mdd_pct)."""
    n = pooled_metrics.get("n", 0)
    pf = pooled_metrics.get("pf", 0.0)
    win = pooled_metrics.get("win", 0.0)
    t_stat = pooled_metrics.get("t_stat", 0.0)
    months_str = pooled_metrics.get("months_pos", "0/0")
    months_pos = int(months_str.split("/")[0]) if "/" in months_str else 0
    months_total = int(months_str.split("/")[1]) if "/" in months_str else 1
    months_pct = months_pos / max(1, months_total)

    # Compute MDD pct from trades
    mdd_pct = 0.0
    if trades and len(trades) > 0:
        net_bps_arr = np.array([t.net_bps for t in trades])
        equity_usd = np.cumsum(net_bps_arr / 1e4 * 1000.0)

        # Compute MDD: max(peak - trough)
        if len(equity_usd) > 0:
            running_peak = np.maximum.accumulate(equity_usd)
            drawdown_usd = running_peak - equity_usd
            mdd_usd = np.max(drawdown_usd) if len(drawdown_usd) > 0 else 0.0
            # Capital base = 6 coins × $1,000 max concurrent book
            mdd_pct = (mdd_usd / 6000.0) * 100.0

    # Sensitivity: fee/slip ×1.5
    sens_pf = sensitivity_metrics.get("pf", 0.0)

    gates = {
        "pf_gte_1_3": pf >= 1.3,
        "n_gte_300": n >= 300,
        "months_gte_60pct": months_pct >= 0.6,
        "mdd_lte_15pct": mdd_pct <= 15.0,
        "t_stat_gte_2": t_stat >= 2.0,
        "sens_pf_gte_1_15": sens_pf >= 1.15,
    }

    return gates, mdd_pct


def main():
    parser = argparse.ArgumentParser(description="F2 Fade Walk-Forward Backtest")
    parser.add_argument("--coins", default=None, help="Comma-separated coin list (default: all)")
    parser.add_argument("--smoke", action="store_true", help="Smoke test mode (2-day data)")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load config
    shortlist = load_shortlist()
    fee_bps, slippage_data = load_fees_slippage()

    if args.coins:
        coins_to_test = args.coins.split(",")
    else:
        coins_to_test = [item["coin"] for item in shortlist]

    print(f"Testing coins: {coins_to_test}")
    print(f"Smoke mode: {args.smoke}")
    print(f"Fee (taker bps): {fee_bps:.2f}")

    # Run backtest per coin
    all_oos_trades = []
    all_coin_metrics = []
    all_picks = []

    for coin in coins_to_test:
        print(f"Backtesting {coin}...")
        slip_bps = slippage_data.get(coin, 1.0)
        oos_trades, picks, _, coin_metrics = backtest_coin(
            coin, fee_bps, slip_bps, smoke=args.smoke
        )
        if oos_trades:
            all_oos_trades.extend(oos_trades)
            all_coin_metrics.append(coin_metrics)
            all_picks.extend([(coin, p) for p in picks])
        print(f"  {coin}: {len(oos_trades)} OOS trades")

    # Compute pooled metrics
    pooled_metrics = backtest_lib.metrics(all_oos_trades)
    exit_reasons = compute_exit_reason_distribution(all_oos_trades)

    # Sensitivity test: fee/slip ×1.5
    print("Running sensitivity test (fee/slip ×1.5)...")
    all_oos_trades_sens = []
    for coin in coins_to_test:
        slip_bps = slippage_data.get(coin, 1.0)
        oos_trades, _, _, _ = backtest_coin(
            coin, fee_bps * 1.5, slip_bps * 1.5, smoke=args.smoke
        )
        if oos_trades:
            all_oos_trades_sens.extend(oos_trades)

    sensitivity_metrics = backtest_lib.metrics(all_oos_trades_sens)

    # Check G1 gates (compute MDD pct from trades)
    g1_gates, mdd_pct = check_g1_gates(pooled_metrics, sensitivity_metrics, all_oos_trades)

    # Prepare report
    lines = [
        "# F2 Overshoot-Fade Walk-Forward Results",
        f"\n**Data window:** Pooled across {len(all_coin_metrics)} coins",
        f"**Configs:** {len(CONFIGS)} (W ∈ {{15,30,60}}, K ∈ {{3,4,5}})",
        f"**OOS trades:** {pooled_metrics.get('n', 0)}",
        "",
        "## Summary Metrics (Pooled OOS)",
        "",
    ]

    summary_data = [
        {"coin": "POOLED", **pooled_metrics},
        {"coin": "POOLED (sens ×1.5)", **sensitivity_metrics},
    ]
    lines.append(format_metrics_table(summary_data, "Pooled Metrics"))

    lines.append("\n### Exit Reason Distribution\n")
    lines.append(f"- **Target:** {exit_reasons['target']:.1f}%")
    lines.append(f"- **Stop:** {exit_reasons['stop']:.1f}%")
    lines.append(f"- **Time:** {exit_reasons['time']:.1f}%")
    if exit_reasons["stop"] > 50.0:
        lines.append("\n⚠️ **Divergence-Dominated:** Stop > 50% indicates weak signal fitness.")

    lines.append("\n## Per-Coin Metrics\n")
    lines.append(format_metrics_table(all_coin_metrics, "By Coin (Pooled OOS)"))

    lines.append("\n## G1 Gate Checklist\n")
    lines.append("| Criterion | Threshold | Actual | Status |")
    lines.append("|-----------|-----------|--------|--------|")
    lines.append(
        f"| PF ≥ 1.3 | ≥ 1.30 | {pooled_metrics.get('pf', 0.0):.3f} | {'✓' if g1_gates['pf_gte_1_3'] else '✗'} |"
    )
    lines.append(
        f"| n ≥ 300 | ≥ 300 | {pooled_metrics.get('n', 0)} | {'✓' if g1_gates['n_gte_300'] else '✗'} |"
    )
    pct_months = (int(pooled_metrics.get("months_pos", "0/0").split("/")[0]) /
                  max(1, int(pooled_metrics.get("months_pos", "0/1").split("/")[1]))) * 100
    lines.append(
        f"| Months+ ≥ 60% | ≥ 60% | {pct_months:.1f}% | {'✓' if g1_gates['months_gte_60pct'] else '✗'} |"
    )
    # MDD pct computed from trades; include original mdd_bps for reference
    mdd_bps = pooled_metrics.get("mdd_bps", 0.0)
    lines.append(
        f"| MDD ≤ 15% | ≤ 15% | {mdd_pct:.1f}% | {'✓' if g1_gates['mdd_lte_15pct'] else '✗'} |"
    )
    lines.append(f"\n_Capital base for MDD: 6 coins × $1,000 max concurrent book_")
    lines.append(f"_MDD% = {mdd_pct:.1f}%, MDD bps (raw) = {mdd_bps:.1f}_\n")
    lines.append(
        f"| t-stat ≥ 2.0 | ≥ 2.0 | {pooled_metrics.get('t_stat', 0.0):.2f} | {'✓' if g1_gates['t_stat_gte_2'] else '✗'} |"
    )
    lines.append(
        f"| Sens PF ≥ 1.15 | ≥ 1.15 | {sensitivity_metrics.get('pf', 0.0):.3f} | {'✓' if g1_gates['sens_pf_gte_1_15'] else '✗'} |"
    )

    all_pass = all(g1_gates.values())
    lines.append(f"\n**Overall G1 Result:** {'PASS ✓' if all_pass else 'FAIL ✗'}\n")

    # Write report
    report_path = REPORTS_DIR / "scalp-f2-fade-results.md"
    report_path.write_text("\n".join(lines))
    print(f"\nReport written to: {report_path}")

    # Write trades CSV
    if all_oos_trades:
        trades_data = [
            {
                "coin": t.coin,
                "side": t.side,
                "entry_i": t.entry_i,
                "exit_i": t.exit_i,
                "entry_px": t.entry_px,
                "exit_px": t.exit_px,
                "gross_bps": t.gross_bps,
                "net_bps": t.net_bps,
                "exit_reason": t.exit_reason,
            }
            for t in all_oos_trades
        ]
        trades_df = pd.DataFrame(trades_data)
        trades_csv = DATA_DIR / "f2_trades.csv"
        trades_df.to_csv(trades_csv, index=False)
        print(f"Trades written to: {trades_csv}")
    else:
        print("No trades to write.")

    print("\nDone.")


if __name__ == "__main__":
    main()
