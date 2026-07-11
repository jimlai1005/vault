"""F2b Maker-Entry Fade Walk-Forward Backtest (sub-project H, round 2).

F2 fade signals (W, K grid) with maker-entry limit orders.
Two variants: (A) no vol filter, (B) with vol24h filter.
Config grid: W ∈ {15,30,60}, K ∈ {3,4,5} => 9 configs (same as F2).
Exit: target = 38.2% retracement; stop = 0.5*ATR14 beyond extreme;
time-stop = 60 bars. Walk-forward train 60d/test 30d.
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
from research_scalp_f2_fade import generate_f2_signals


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
    fee_taker_bps = fees_data["taker"] * 1e4  # Convert to bps
    fee_maker_bps = fees_data.get("maker", 0.00015) * 1e4  # Default 0.00015 if not present

    with open(DATA_DIR / "slippage.json") as f:
        slippage_data = json.load(f)

    return fee_maker_bps, fee_taker_bps, slippage_data


def generate_f2b_signals(df: pd.DataFrame, cfg: dict, apply_vol_filter: bool = False) -> tuple:
    """Generate F2b maker signals: F2 fade signals + maker limit order prices.

    cfg: {"W": int, "K": int}
    Returns: (sig, limit_px, target_px, stop_px) where:
    - sig: F2 fade signals (+1/-1/0)
    - limit_px: maker entry limit (c - 0.1*atr14 for long, c + 0.1*atr14 for short)
    - target_px: F2 target (38.2% retracement)
    - stop_px: F2 stop (0.5*atr14 beyond extreme)
    - apply_vol_filter: if True, apply vol24h > rolling_median(vol24h, 43200) filter
    """
    # Get F2 signals first
    sig, target_px, stop_px = generate_f2_signals(df, cfg)

    # Compute maker limit prices: 0.1*atr14 away from close
    atr = df["atr14"].values
    limit_px = np.full(len(df), np.nan)

    for i in range(len(df)):
        if sig[i] == 1:  # Long: limit = c - 0.1*atr
            limit_px[i] = df["c"].iloc[i] - 0.1 * atr[i]
        elif sig[i] == -1:  # Short: limit = c + 0.1*atr
            limit_px[i] = df["c"].iloc[i] + 0.1 * atr[i]

    # Apply vol24h filter if requested
    if apply_vol_filter:
        ret = df["c"].values / df["c"].shift(1).values
        ret = np.log(ret)
        # vol24h = std(ret over 1440 bars) * sqrt(1440)
        vol24h = pd.Series(ret).rolling(window=1440).std() * np.sqrt(1440)
        vol24h_median = vol24h.rolling(window=43200, min_periods=1).median()  # 30 days
        vol24h_values = vol24h.values

        # Only allow signal if vol24h > median
        for i in range(len(df)):
            if vol24h_values[i] <= vol24h_median.iloc[i]:
                sig[i] = 0  # Cancel signal

    return sig, limit_px, target_px, stop_px


def run_f2b(
    df: pd.DataFrame,
    cfg: dict,
    fee_maker_bps: float,
    fee_taker_bps: float,
    slip_bps: float,
    apply_vol_filter: bool = False,
) -> list:
    """Run F2b backtest for a single config."""
    sig, limit_px, target_px, stop_px = generate_f2b_signals(df, cfg, apply_vol_filter)
    trades = backtest_lib.simulate_maker(
        df,
        sig,
        limit_px,
        target_px,
        stop_px,
        fee_maker_bps=fee_maker_bps,
        fee_taker_bps=fee_taker_bps,
        slip_bps=slip_bps,
        entry_ttl=3,
        hold_bars=TIME_STOP,
        coin="",
    )
    return trades


def backtest_coin(
    coin: str,
    fee_maker_bps: float,
    fee_taker_bps: float,
    slip_bps: float,
    apply_vol_filter: bool = False,
    smoke: bool = False,
) -> tuple:
    """Backtest a single coin across all F2b configs.

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
        lambda df_slice, cfg: run_f2b(
            df_slice, cfg, fee_maker_bps, fee_taker_bps, slip_bps, apply_vol_filter
        ),
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
    parser = argparse.ArgumentParser(description="F2b Maker-Entry Fade Walk-Forward Backtest")
    parser.add_argument("--coins", default=None, help="Comma-separated coin list (default: all)")
    parser.add_argument("--smoke", action="store_true", help="Smoke test mode (2-day data)")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load config
    shortlist = load_shortlist()
    fee_maker_bps, fee_taker_bps, slippage_data = load_fees_slippage()

    if args.coins:
        coins_to_test = args.coins.split(",")
    else:
        coins_to_test = [item["coin"] for item in shortlist]

    print(f"Testing coins: {coins_to_test}")
    print(f"Smoke mode: {args.smoke}")
    print(f"Fee (maker bps): {fee_maker_bps:.2f}, (taker bps): {fee_taker_bps:.2f}")

    # Run backtest for both variants
    variants = [
        ("NoFilter", False),
        ("WithFilter", True),
    ]

    all_variant_results = {}

    for variant_name, apply_vol_filter in variants:
        print(f"\n=== Variant {variant_name} ===")

        all_oos_trades = []
        all_coin_metrics = []
        all_picks = []

        for coin in coins_to_test:
            print(f"  {coin}...", end=" ", flush=True)
            slip_bps = slippage_data.get(coin, 1.0)
            oos_trades, picks, _, coin_metrics = backtest_coin(
                coin,
                fee_maker_bps,
                fee_taker_bps,
                slip_bps,
                apply_vol_filter=apply_vol_filter,
                smoke=args.smoke,
            )
            if oos_trades:
                all_oos_trades.extend(oos_trades)
                all_coin_metrics.append(coin_metrics)
                all_picks.extend([(coin, p) for p in picks])
                print(f"{len(oos_trades)} OOS trades")
            else:
                print("no trades")

        # Compute pooled metrics
        pooled_metrics = backtest_lib.metrics(all_oos_trades)
        exit_reasons = compute_exit_reason_distribution(all_oos_trades)

        # Sensitivity test: fee/slip ×1.5
        print(f"  Sensitivity (fee/slip ×1.5)...", end=" ", flush=True)
        all_oos_trades_sens = []
        for coin in coins_to_test:
            slip_bps = slippage_data.get(coin, 1.0)
            oos_trades, _, _, _ = backtest_coin(
                coin,
                fee_maker_bps * 1.5,
                fee_taker_bps * 1.5,
                slip_bps * 1.5,
                apply_vol_filter=apply_vol_filter,
                smoke=args.smoke,
            )
            if oos_trades:
                all_oos_trades_sens.extend(oos_trades)

        sensitivity_metrics = backtest_lib.metrics(all_oos_trades_sens)
        print("done")

        # Check G1 gates
        g1_gates, mdd_pct = check_g1_gates(pooled_metrics, sensitivity_metrics, all_oos_trades)

        all_variant_results[variant_name] = {
            "pooled_metrics": pooled_metrics,
            "sensitivity_metrics": sensitivity_metrics,
            "all_coin_metrics": all_coin_metrics,
            "exit_reasons": exit_reasons,
            "g1_gates": g1_gates,
            "mdd_pct": mdd_pct,
            "all_oos_trades": all_oos_trades,
        }

    # Prepare combined report
    lines = [
        "# F2b Maker-Entry Fade Walk-Forward Results (Round 2)",
        "\n**Hypothesis:** F2 fade signals with maker-entry limit orders (cost structure).",
        "**Two variants:** (A) No vol filter, (B) With vol24h > rolling_median filter.",
        f"\n**Data window:** Pooled across coins",
        f"**Configs:** {len(CONFIGS)} (W ∈ {{15,30,60}}, K ∈ {{3,4,5}})",
        "",
    ]

    for variant_name in ["NoFilter", "WithFilter"]:
        if variant_name not in all_variant_results:
            continue

        result = all_variant_results[variant_name]
        pooled_metrics = result["pooled_metrics"]
        sensitivity_metrics = result["sensitivity_metrics"]
        exit_reasons = result["exit_reasons"]
        g1_gates = result["g1_gates"]
        mdd_pct = result["mdd_pct"]
        all_coin_metrics = result["all_coin_metrics"]

        lines.append(f"\n## Variant {variant_name}\n")
        lines.append(f"**OOS trades:** {pooled_metrics.get('n', 0)}\n")

        summary_data = [
            {"coin": f"{variant_name}-Pooled", **pooled_metrics},
            {"coin": f"{variant_name}-Sens ×1.5", **sensitivity_metrics},
        ]
        lines.append(format_metrics_table(summary_data, f"{variant_name} Pooled Metrics"))

        lines.append("\n### Exit Reason Distribution\n")
        lines.append(f"- **Target:** {exit_reasons['target']:.1f}%")
        lines.append(f"- **Stop:** {exit_reasons['stop']:.1f}%")
        lines.append(f"- **Time:** {exit_reasons['time']:.1f}%")
        if exit_reasons["stop"] > 50.0:
            lines.append("\n⚠️ **Divergence-Dominated:** Stop > 50% indicates weak signal fitness.")

        lines.append("\n### Per-Coin Metrics\n")
        lines.append(format_metrics_table(all_coin_metrics, f"{variant_name} By Coin"))

        lines.append(f"\n### G1 Gate Checklist ({variant_name})\n")
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
        lines.append(
            f"| MDD ≤ 15% | ≤ 15% | {mdd_pct:.1f}% | {'✓' if g1_gates['mdd_lte_15pct'] else '✗'} |"
        )
        lines.append(f"\n_Capital base for MDD: 6 coins × $1,000 max concurrent book_\n")
        lines.append(
            f"| t-stat ≥ 2.0 | ≥ 2.0 | {pooled_metrics.get('t_stat', 0.0):.2f} | {'✓' if g1_gates['t_stat_gte_2'] else '✗'} |"
        )
        lines.append(
            f"| Sens PF ≥ 1.15 | ≥ 1.15 | {sensitivity_metrics.get('pf', 0.0):.3f} | {'✓' if g1_gates['sens_pf_gte_1_15'] else '✗'} |"
        )

        all_pass = all(g1_gates.values())
        lines.append(f"\n**{variant_name} G1 Result:** {'PASS ✓' if all_pass else 'FAIL ✗'}\n")

    # Write report
    report_path = REPORTS_DIR / "scalp-f2b-maker-results.md"
    report_path.write_text("\n".join(lines))
    print(f"\nReport written to: {report_path}")

    # Write trades CSV (combine both variants)
    all_trades_combined = []
    for variant_name in ["NoFilter", "WithFilter"]:
        if variant_name in all_variant_results:
            for t in all_variant_results[variant_name]["all_oos_trades"]:
                all_trades_combined.append({
                    "variant": variant_name,
                    "coin": t.coin,
                    "side": t.side,
                    "entry_i": t.entry_i,
                    "exit_i": t.exit_i,
                    "entry_px": t.entry_px,
                    "exit_px": t.exit_px,
                    "gross_bps": t.gross_bps,
                    "net_bps": t.net_bps,
                    "exit_reason": t.exit_reason,
                })

    if all_trades_combined:
        trades_df = pd.DataFrame(all_trades_combined)
        trades_csv = DATA_DIR / "f2b_trades.csv"
        trades_df.to_csv(trades_csv, index=False)
        print(f"Trades written to: {trades_csv}")
    else:
        print("No trades to write.")

    print("\nDone.")


if __name__ == "__main__":
    main()
