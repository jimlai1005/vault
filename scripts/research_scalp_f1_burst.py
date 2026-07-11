#!/usr/bin/env python3
"""F1 Burst Continuation walk-forward backtest (sub-project H).

Grid: Z∈{3,4,5}, V∈{2,3}, hold∈{5,15,30} → 18 configs.
Signal: sig[i] = sign(ret[i]) if (|ret[i]/sigma[i]| >= Z AND vol_z[i] >= V) else 0.
Flow: each coin -> prep -> walk_forward -> pooled OOS + sensitivity.
Output: reports/scalp-f1-burst-results.md, data/scalp/f1_trades.csv.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import scalp_lib
import scalp_backtest_lib


def generate_configs():
    """Generate 18 configs (Z, V, hold_bars, stop_mult=1.5)."""
    configs = []
    for z in [3, 4, 5]:
        for v in [2, 3]:
            for hold in [5, 15, 30]:
                configs.append({
                    "Z": z,
                    "V": v,
                    "hold_bars": hold,
                    "stop_mult": 1.5,
                })
    return configs


def generate_signal(df, z_threshold, vol_z_threshold):
    """Generate F1 signal: sign(ret) if (|ret/sigma| >= Z AND vol_z >= V) else 0."""
    sig = np.zeros(len(df))
    for i in range(len(df)):
        if pd.isna(df["sigma"].iloc[i]) or pd.isna(df["vol_z"].iloc[i]):
            sig[i] = 0
        elif pd.isna(df["ret"].iloc[i]):
            sig[i] = 0
        else:
            ret = df["ret"].iloc[i]
            sigma = df["sigma"].iloc[i]
            vol_z = df["vol_z"].iloc[i]

            if sigma > 0 and abs(ret / sigma) >= z_threshold and vol_z >= vol_z_threshold:
                sig[i] = 1.0 if ret > 0 else -1.0
    return sig


def run_f1(df_slice, config, coin, fee_bps, slip_bps):
    """Run one F1 config on a df slice. Returns list of Trade objects."""
    sig = generate_signal(df_slice, config["Z"], config["V"])
    trades = scalp_backtest_lib.simulate(
        df_slice,
        sig,
        hold_bars=config["hold_bars"],
        stop_atr_mult=config["stop_mult"],
        fee_bps=fee_bps,
        slip_bps=slip_bps,
        coin=coin,
    )
    return trades


def load_fees_and_slippage():
    """Load fees.json and slippage.json; return (taker_bps, slip_dict)."""
    fees_path = scalp_lib.DATA_DIR + "/fees.json"
    slip_path = scalp_lib.DATA_DIR + "/slippage.json"

    with open(fees_path) as f:
        fees = json.load(f)
    taker_bps = fees["taker"] * 1e4  # Convert to bps

    with open(slip_path) as f:
        slip_dict = json.load(f)

    return taker_bps, slip_dict


def compute_metrics_with_months(trades, df):
    """Compute metrics including monthly positive slice ratio."""
    m = scalp_backtest_lib.metrics(trades, df=df)
    # Fallback: if months_pos not in m, compute it manually from trades
    if "months_pos" not in m and trades:
        # Extract entry timestamps from trades if available
        # For pooled trades without df, we skip this detail
        pass
    return m


def format_report(
    pooled_m,
    coin_results,
    sens_base,
    sens_high,
    picks_by_coin,
    shortlist_coins,
    mdd_pct=0.0,
):
    """Format markdown report with pooled, by-coin, sensitivity, picks, G1 gates."""
    lines = [
        "# F1 Burst Continuation Walk-Forward Results",
        "",
        f"**Date:** {datetime.utcnow().isoformat()}",
        f"**Data window:** {shortlist_coins}",
        "",
        "## Pooled OOS Metrics (All Coins)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]

    if pooled_m["n"] > 0:
        lines.extend([
            f"| n | {pooled_m['n']} |",
            f"| PF | {pooled_m['pf']:.3f} |",
            f"| Win% | {pooled_m['win']:.3f} |",
            f"| Avg Net (bps) | {pooled_m['avg_net_bps']:.2f} |",
            f"| MDD (bps) | {pooled_m['mdd_bps']:.1f} |",
            f"| t-stat | {pooled_m['t_stat']:.2f} |",
            f"| Months+ | {pooled_m['months_pos']} |",
        ])
    else:
        lines.append("| n | 0 (no trades) |")

    lines.extend(["", "## By-Coin OOS Metrics", "", "| Coin | n | PF | Avg (bps) | MDD (bps) | Months+ |", "|------|---|--------|-----------|-----------|---------|"])

    for coin in sorted(coin_results.keys()):
        m = coin_results[coin]
        if m["n"] > 0:
            lines.append(
                f"| {coin} | {m['n']} | {m['pf']:.3f} | {m['avg_net_bps']:.2f} | {m['mdd_bps']:.1f} | {m['months_pos']} |"
            )
        else:
            lines.append(f"| {coin} | 0 | — | — | — | — |")

    lines.extend(["", "## Sensitivity Analysis (Fee & Slip ×1.5)", "", "| Scenario | PF | n |", "|----------|-----|---|"])
    lines.append(f"| Base (1×cost) | {sens_base['pf']:.3f} | {sens_base['n']} |")
    lines.append(f"| 1.5×cost | {sens_high['pf']:.3f} | {sens_high['n']} |")

    lines.extend(["", "## Config Selection by Walk-Forward Window", ""])
    for coin in sorted(picks_by_coin.keys()):
        picks = picks_by_coin[coin]
        if picks:
            lines.append(f"### {coin}")
            lines.append("")
            lines.append("| Window Start | Z | V | Hold (bars) |")
            lines.append("|--------------|---|---|-------------|")
            for start_date, cfg in picks:
                lines.append(f"| {start_date} | {cfg['Z']} | {cfg['V']} | {cfg['hold_bars']} |")
            lines.append("")
        else:
            lines.append(f"### {coin}")
            lines.append("_No valid windows (insufficient data)_")
            lines.append("")

    lines.extend(["", "## G1 Gate Checklist", ""])

    # G1 gate checks
    pf_pass = pooled_m["n"] > 0 and pooled_m["pf"] >= 1.3
    n_pass = pooled_m["n"] >= 300
    months_parts = pooled_m.get("months_pos", "0/0").split("/")
    months_pos = int(months_parts[0]) if len(months_parts) > 0 else 0
    months_total = int(months_parts[1]) if len(months_parts) > 1 else 1
    months_pass = months_pos >= 0.6 * months_total if months_total > 0 else False
    mdd_bps = pooled_m.get("mdd_bps", 0)
    # mdd_pct computed from trades (passed as parameter)
    mdd_pass = mdd_pct <= 15.0
    tstat_pass = pooled_m.get("t_stat", 0) >= 2.0
    sens_pass = sens_high.get("pf", 0) >= 1.15

    lines.extend([
        f"- PF ≥ 1.3 (base OOS): **{'PASS' if pf_pass else 'FAIL'}** ({pooled_m.get('pf', 0):.3f})",
        f"- n ≥ 300: **{'PASS' if n_pass else 'FAIL'}** ({pooled_m['n']})",
        f"- Months ≥60%: **{'PASS' if months_pass else 'FAIL'}** ({months_pos}/{months_total})",
        f"- MDD ≤15%: **{'PASS' if mdd_pass else 'FAIL'}** ({mdd_pct:.1f}%)",
        f"- t-stat ≥2.0: **{'PASS' if tstat_pass else 'FAIL'}** ({pooled_m.get('t_stat', 0):.2f})",
        f"- PF ≥1.15 @ 1.5×cost: **{'PASS' if sens_pass else 'FAIL'}** ({sens_high.get('pf', 0):.3f})",
        "",
        f"_Capital base for MDD: 6 coins × $1,000 max concurrent book_",
        f"_MDD% = {mdd_pct:.1f}%, MDD bps (raw) = {mdd_bps:.1f}_",
        "",
    ])

    all_pass = pf_pass and n_pass and months_pass and mdd_pass and tstat_pass and sens_pass
    lines.append(f"**Verdict: {'GO' if all_pass else 'NO-GO'}**")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="F1 burst-continuation walk-forward backtest")
    parser.add_argument("--coins", type=str, default=None, help="Comma-separated coin list")
    parser.add_argument("--smoke", action="store_true", help="Smoke test mode (same coin list, normal data)")
    args = parser.parse_args()

    # Load shortlist
    with open(f"{scalp_lib.DATA_DIR}/shortlist.json") as f:
        shortlist = json.load(f)

    if args.coins:
        coin_list = [c.strip() for c in args.coins.split(",")]
    else:
        coin_list = [c["coin"] for c in shortlist]

    print(f"Running F1 on coins: {coin_list}")

    # Load fees and slippage
    taker_bps, slip_dict = load_fees_and_slippage()

    # Generate configs
    configs = generate_configs()
    print(f"Generated {len(configs)} configs")

    # Container for OOS trades and per-coin metrics
    all_oos_trades = []
    coin_results = {}
    picks_by_coin = {}

    # Process each coin
    for coin in coin_list:
        data_file = f"{scalp_lib.DATA_DIR}/{coin}_1m.csv.gz"
        if not Path(data_file).exists():
            print(f"  {coin}: data file not found")
            coin_results[coin] = {"n": 0}
            picks_by_coin[coin] = []
            continue

        df = scalp_lib.load_df(f"{coin}_1m")
        slip_bps = slip_dict.get(coin, 1.0)  # Default 1 bps if missing

        # Convert ts to Timestamp
        df["ts"] = pd.to_datetime(df["ts"], utc=True)

        df = scalp_backtest_lib.prep(df)

        # Walk-forward
        def run_fn_coin(df_slice, cfg):
            return run_f1(df_slice, cfg, coin, taker_bps, slip_bps)

        oos_trades, picks = scalp_backtest_lib.walk_forward(
            df, configs, run_fn_coin, train_days=60, test_days=30
        )

        # Attach timestamps and coin to trades
        for t in oos_trades:
            t.coin = coin
            # Extract entry timestamp from df
            t.entry_ts = df["ts"].iloc[t.entry_i] if t.entry_i < len(df) else None
            t.exit_ts = df["ts"].iloc[t.exit_i] if t.exit_i < len(df) else None

        # Coin metrics (OOS only)
        coin_m = compute_metrics_with_months(oos_trades, df)
        coin_results[coin] = coin_m
        picks_by_coin[coin] = picks

        all_oos_trades.extend(oos_trades)

        print(f"  {coin}: {len(oos_trades)} OOS trades, PF={coin_m.get('pf', 'N/A')}")

    # Pooled OOS metrics
    pooled_m = scalp_backtest_lib.metrics(all_oos_trades, df=None)

    # Add months_pos if we have trades with timestamps
    if len(all_oos_trades) > 0:
        net_arr = np.array([t.net_bps for t in all_oos_trades])
        ts_arr = np.array([t.entry_ts for t in all_oos_trades])
        mon = pd.Series(net_arr, index=pd.to_datetime(ts_arr))
        # Convert index to naive datetime to avoid timezone warnings
        mon.index = mon.index.tz_localize(None)
        try:
            by_m = mon.groupby(pd.Series(mon.index).dt.to_period("M")).sum()
            pooled_m["months_pos"] = f"{int((by_m > 0).sum())}/{len(by_m)}"
        except Exception as e:
            pooled_m["months_pos"] = "N/A"
    else:
        pooled_m["months_pos"] = "0/0"

    # Sensitivity: re-run with 1.5× fees and slip
    print("Running sensitivity analysis (fee/slip ×1.5)...")
    sens_trades = []

    for coin in coin_list:
        data_file = f"{scalp_lib.DATA_DIR}/{coin}_1m.csv.gz"
        if not Path(data_file).exists():
            continue

        df = scalp_lib.load_df(f"{coin}_1m")
        slip_bps = slip_dict.get(coin, 1.0)

        # Convert ts to Timestamp
        df["ts"] = pd.to_datetime(df["ts"], utc=True)

        df = scalp_backtest_lib.prep(df)

        def run_fn_coin_sens(df_slice, cfg):
            return run_f1(df_slice, cfg, coin, taker_bps * 1.5, slip_bps * 1.5)

        oos_trades_sens, _ = scalp_backtest_lib.walk_forward(
            df, configs, run_fn_coin_sens, train_days=60, test_days=30
        )

        # Attach timestamps to sensitivity trades
        for t in oos_trades_sens:
            t.entry_ts = df["ts"].iloc[t.entry_i] if t.entry_i < len(df) else None

        sens_trades.extend(oos_trades_sens)

    sens_m = scalp_backtest_lib.metrics(sens_trades, df=None)

    # Add months_pos for sensitivity
    if len(sens_trades) > 0:
        net_arr = np.array([t.net_bps for t in sens_trades])
        ts_arr = np.array([t.entry_ts for t in sens_trades])
        mon = pd.Series(net_arr, index=pd.to_datetime(ts_arr))
        # Convert index to naive datetime to avoid timezone warnings
        mon.index = mon.index.tz_localize(None)
        try:
            by_m = mon.groupby(pd.Series(mon.index).dt.to_period("M")).sum()
            sens_m["months_pos"] = f"{int((by_m > 0).sum())}/{len(by_m)}"
        except Exception as e:
            sens_m["months_pos"] = "N/A"
    else:
        sens_m["months_pos"] = "0/0"

    # Output CSV
    csv_rows = []
    for t in all_oos_trades:
        csv_rows.append({
            "coin": t.coin,
            "side": t.side,
            "entry_ts": str(t.entry_ts) if hasattr(t, 'entry_ts') and t.entry_ts else "",
            "exit_ts": str(t.exit_ts) if hasattr(t, 'exit_ts') and t.exit_ts else "",
            "entry_px": t.entry_px,
            "exit_px": t.exit_px,
            "net_bps": t.net_bps,
            "exit_reason": t.exit_reason,
        })

    trades_df = pd.DataFrame(csv_rows)
    trades_df.to_csv(f"{scalp_lib.DATA_DIR}/f1_trades.csv", index=False)
    print(f"Saved {len(trades_df)} trades to data/scalp/f1_trades.csv")

    # Compute MDD% from trades
    mdd_pct = 0.0
    if len(all_oos_trades) > 0:
        net_bps_arr = np.array([t.net_bps for t in all_oos_trades])
        equity_usd = np.cumsum(net_bps_arr / 1e4 * 1000.0)
        if len(equity_usd) > 0:
            running_peak = np.maximum.accumulate(equity_usd)
            drawdown_usd = running_peak - equity_usd
            mdd_usd = np.max(drawdown_usd) if len(drawdown_usd) > 0 else 0.0
            # Capital base = 6 coins × $1,000 max concurrent book
            mdd_pct = (mdd_usd / 6000.0) * 100.0

    # Generate report
    shortlist_coins_str = ", ".join(coin_list)
    report = format_report(
        pooled_m,
        coin_results,
        pooled_m,
        sens_m,
        picks_by_coin,
        shortlist_coins_str,
        mdd_pct=mdd_pct,
    )

    report_path = "reports/scalp-f1-burst-results.md"
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)

    print(f"Saved report to {report_path}")
    print(f"\nPooled OOS: n={pooled_m['n']}, PF={pooled_m.get('pf', 'N/A')}")


if __name__ == "__main__":
    main()
