#!/usr/bin/env python3
"""
G0 cost feasibility analysis for HL stable coin pairs.
Targets: @166=USDT0/USDC, @150=USDe/USDC, @230=USDH/USDC
Strategy: mean reversion around peg, taker 1.4bps/side.
G0 threshold: median amplitude >= 3x round-trip cost.

Outputs: stablepairs/reports/g0_hl_stables.md with pair statistics & cost viability.
"""
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import sys
import os

# Add vault root to path so we can import scalp_lib
sys.path.insert(0, "/Users/jim/projects/vault/scripts")
from scalp_lib import get_candles, candles_to_df, l2_spread_bps, info

# ============================================================================
# Configuration
# ============================================================================
PAIRS = {
    "USDT0": {"coin": "@166", "index": 166, "tick_decimals": 6},
    "USDe":  {"coin": "@150", "index": 150, "tick_decimals": 6},
    "USDH":  {"coin": "@230", "index": 230, "tick_decimals": 6},
}

ENTRY_ZS = [1.0, 1.5, 2.0]
ENTRY_Z_NAMES = ["z_peg", "z_roll"]  # Two z definitions
LOOKBACK_BARS = 720  # For rolling mean/std (720 * 1h = 30 days)
EXIT_Z_THRESHOLD = 0.2  # Threshold at which we consider trade closed
TAKER_FEES_BPS_SIDE = 1.4  # Per side

# Stable pair taker fees: 1.4bps/side
TAKER_RT_BPS_ONLY_FEES = 2 * TAKER_FEES_BPS_SIDE  # 2.8 bps

# Number of L2 samples and interval between them
L2_SAMPLES = 5
L2_SAMPLE_INTERVAL_S = 3

# Time window: 300 days ago to now
DAYS_BACK = 300

# ============================================================================
# Fetch 1h candles
# ============================================================================
def fetch_1h_history(coin: str) -> pd.DataFrame:
    """Fetch ~5000 bars of 1h candles starting from 300 days ago."""
    now_ms = int(datetime.now(tz=None).timestamp() * 1000)
    start_ms = now_ms - DAYS_BACK * 24 * 60 * 60 * 1000

    print(f"Fetching {coin} 1h candles from {DAYS_BACK} days ago...")

    rows = []
    cur = start_ms
    interval_ms = 60 * 60 * 1000  # 1h in ms

    # Fetch in 5000-bar chunks
    while cur < now_ms:
        win_end = min(cur + 5000 * interval_ms, now_ms)
        try:
            batch = get_candles(coin, "1h", cur, win_end)
            if batch:
                rows.extend(batch)
            time.sleep(0.5)
        except Exception as e:
            print(f"  Warning: fetch error at {cur}: {e}")
            cur = win_end
            continue

        if batch:
            last_t = max(int(b["t"]) for b in batch)
            cur = max(last_t + interval_ms, cur + interval_ms)
        else:
            cur = win_end

    if not rows:
        print(f"  ERROR: No candles fetched for {coin}")
        return pd.DataFrame()

    df = candles_to_df(rows)
    bars_count = len(df)
    days_span = (df["t"].max() - df["t"].min()) / (24 * 60 * 60 * 1000)
    print(f"  Got {bars_count} bars spanning {days_span:.1f} days")

    return df

# ============================================================================
# Sample L2 Book for spread
# ============================================================================
def sample_l2_spreads(coin: str, num_samples: int = 5, interval_s: float = 3) -> float:
    """Take num_samples of L2 spreads at interval_s apart, return median in bps."""
    spreads = []
    for i in range(num_samples):
        try:
            spread = l2_spread_bps(coin)
            if spread is not None:
                spreads.append(spread)
        except Exception as e:
            print(f"  L2 sample {i+1} failed: {e}")

        if i < num_samples - 1:
            time.sleep(interval_s)

    if not spreads:
        print(f"  WARNING: No spreads sampled for {coin}")
        return 0.0

    med = np.median(spreads)
    print(f"  L2 spread samples: {spreads}, median={med:.2f} bps")
    return med

# ============================================================================
# Z-score calculations
# ============================================================================
def compute_z_scores(df: pd.DataFrame) -> tuple:
    """
    Compute two z-score definitions:
    - z_peg: anchor to peg at 1.0
    - z_roll: allow slow drift via 720h rolling mean

    Returns (df_with_z_peg, df_with_z_roll)
    """
    df = df.copy()
    df = df[df.index >= LOOKBACK_BARS]  # Need lookback window
    df = df.reset_index(drop=True)

    rolling_mean = df["c"].rolling(LOOKBACK_BARS, min_periods=1).mean()
    rolling_std = df["c"].rolling(LOOKBACK_BARS, min_periods=1).std()

    df["z_peg"] = (df["c"] - 1.0) / rolling_std
    df["z_roll"] = (df["c"] - rolling_mean) / rolling_std

    return df

# ============================================================================
# Event detection and amplitude calculation
# ============================================================================
def find_amplitude_events(df: pd.DataFrame, z_col: str, entry_z_thresh: float) -> list:
    """
    Find crossover events where |z| transitions from < entry_z to >= entry_z.
    For each event, track the price from entry close to first |z| <= EXIT_Z_THRESHOLD.

    Returns list of dicts: {
        'entry_bar': bar_idx,
        'entry_close': price at entry,
        'exit_bar': bar_idx when |z| <= 0.2,
        'exit_close': price at exit,
        'price_change_bps': |exit - entry| / entry * 1e4,
        'hold_hours': (exit_t - entry_t) / (60*60*1000),
        'direction': 'pos' if z >= entry_z_thresh else 'neg'
    }
    """
    events = []
    z = df[z_col].values
    close = df["c"].values
    t = df["t"].values

    in_trade = False
    entry_idx = None
    entry_z = None

    for i in range(1, len(z)):
        abs_z_prev = abs(z[i - 1])
        abs_z_curr = abs(z[i])

        # Look for crossover: previous bar < threshold, current bar >= threshold
        if not in_trade and abs_z_prev < entry_z_thresh and abs_z_curr >= entry_z_thresh:
            in_trade = True
            entry_idx = i
            entry_z = z[i]

        # If in trade, look for exit: |z| <= EXIT_Z_THRESHOLD
        if in_trade and abs(z[i]) <= EXIT_Z_THRESHOLD:
            entry_close = close[entry_idx]
            exit_close = close[i]
            price_change = abs(exit_close - entry_close)
            price_change_bps = price_change / entry_close * 1e4
            hold_hours = (t[i] - t[entry_idx]) / (60 * 60 * 1000)

            direction = "pos" if entry_z > 0 else "neg"

            events.append({
                "entry_bar": entry_idx,
                "entry_close": entry_close,
                "exit_bar": i,
                "exit_close": exit_close,
                "price_change_bps": price_change_bps,
                "hold_hours": hold_hours,
                "direction": direction,
            })

            in_trade = False
            entry_idx = None
            entry_z = None

    return events

# ============================================================================
# Stats aggregation
# ============================================================================
def aggregate_stats(events: list) -> dict:
    """Aggregate events into: count, median/mean amplitude, median hold hours."""
    if not events:
        return {
            "count": 0,
            "median_amp_bps": 0.0,
            "mean_amp_bps": 0.0,
            "median_hold_hours": 0.0,
        }

    amps = [e["price_change_bps"] for e in events]
    holds = [e["hold_hours"] for e in events]

    return {
        "count": len(events),
        "median_amp_bps": float(np.median(amps)),
        "mean_amp_bps": float(np.mean(amps)),
        "median_hold_hours": float(np.median(holds)),
    }

# ============================================================================
# Price statistics for each pair
# ============================================================================
def price_stats(df: pd.DataFrame) -> dict:
    """Return price statistics: std (bps), P5/P95 (bps), mean deviation from 1.0 (bps)."""
    c = df["c"].values

    std_bps = np.std(c) / np.mean(c) * 1e4
    p5 = np.percentile(c, 5)
    p95 = np.percentile(c, 95)
    p5_p95_bps = (p95 - p5) / np.mean(c) * 1e4

    mean_c = np.mean(c)
    mean_dev_from_1 = (mean_c - 1.0) / 1.0 * 1e4

    return {
        "std_bps": std_bps,
        "p5_p95_bps": p5_p95_bps,
        "mean_dev_from_1_bps": mean_dev_from_1,
    }

# ============================================================================
# Main analysis
# ============================================================================
def main():
    results = []

    for coin_name, pair_info in PAIRS.items():
        coin = pair_info["coin"]
        print(f"\n{'='*70}")
        print(f"Analyzing {coin_name} (index @{pair_info['index']})")
        print(f"{'='*70}")

        # Fetch 1h candles
        df = fetch_1h_history(coin)
        if df.empty:
            print(f"SKIP {coin_name}: no candles")
            results.append({
                "pair": coin_name,
                "index": pair_info["index"],
                "bars": 0,
                "days": 0,
                "spread_med_bps": 0.0,
                "price_std_bps": 0.0,
                "p5_p95_bps": 0.0,
                "mean_dev_from_1_bps": 0.0,
                "events_data": {},
            })
            continue

        bars_count = len(df)
        days_span = (df["t"].max() - df["t"].min()) / (24 * 60 * 60 * 1000)

        # Sample L2 spreads
        spread_med = sample_l2_spreads(coin, L2_SAMPLES, L2_SAMPLE_INTERVAL_S)

        # Price stats
        p_stats = price_stats(df)

        # Compute z-scores
        df_z = compute_z_scores(df)

        # Process events for each z definition and entry threshold
        events_data = {}
        for z_name in ENTRY_Z_NAMES:
            events_data[z_name] = {}
            for entry_z in ENTRY_ZS:
                events = find_amplitude_events(df_z, z_name, entry_z)
                stats = aggregate_stats(events)
                events_data[z_name][entry_z] = stats
                print(f"  {z_name} @ entry_z={entry_z}: {stats['count']} events, "
                      f"median_amp={stats['median_amp_bps']:.1f} bps, "
                      f"median_hold={stats['median_hold_hours']:.1f}h")

        results.append({
            "pair": coin_name,
            "index": pair_info["index"],
            "bars": bars_count,
            "days": days_span,
            "spread_med_bps": spread_med,
            "price_std_bps": p_stats["std_bps"],
            "p5_p95_bps": p_stats["p5_p95_bps"],
            "mean_dev_from_1_bps": p_stats["mean_dev_from_1_bps"],
            "events_data": events_data,
        })

    return results

# ============================================================================
# Report generation
# ============================================================================
def generate_report(results: list) -> str:
    """Generate markdown report with tables and G0 verdict."""
    report = """# G0 Cost Feasibility Analysis: HL Stable Pairs

## Summary
Analysis of three HL stable coin pairs for mean-reversion scalping strategy around peg.
- Pairs: USDT0/USDC (@166), USDe/USDC (@150), USDH/USDC (@230)
- Fee structure: Taker 1.4 bps/side
- G0 threshold: median amplitude >= 3× round-trip cost

## Candle Data & Spread Samples

| Pair | Index | Bars | Days | Spread (bps) | Std (bps) | P5-P95 (bps) | Mean Dev from 1 (bps) |
|------|-------|------|------|--------------|-----------|--------------|----------------------|
"""

    for r in results:
        report += f"| {r['pair']} | @{r['index']} | {r['bars']} | {r['days']:.1f} | {r['spread_med_bps']:.2f} | {r['price_std_bps']:.2f} | {r['p5_p95_bps']:.2f} | {r['mean_dev_from_1_bps']:.2f} |\n"

    report += "\n## Event Analysis & G0 Viability\n\n"

    # Cost table
    report += "### Cost Structure (bps)\n\n"
    report += "| Scenario | Cost |\n|----------|------|\n"
    report += f"| Taker RT (fees only) | {TAKER_RT_BPS_ONLY_FEES:.2f} |\n"

    for r in results:
        if r["spread_med_bps"] > 0:
            rt_taker = TAKER_RT_BPS_ONLY_FEES + r["spread_med_bps"]
            report += f"| {r['pair']} Taker RT (fees + spread) | {rt_taker:.2f} |\n"

    report += "\n### Amplitude Statistics & G0 Judgment\n\n"

    # Per-pair analysis
    for r in results:
        if r["bars"] == 0:
            report += f"**{r['pair']}**: Data unavailable\n\n"
            continue

        report += f"**{r['pair']}** (@{r['index']}, {r['bars']} bars, {r['days']:.1f} days)\n\n"

        # Z-peg table
        report += f"##### {r['pair']} - z_peg (anchored to 1.0)\n\n"
        report += "| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |\n"
        report += "|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|\n"

        rt_taker = TAKER_RT_BPS_ONLY_FEES + r["spread_med_bps"]
        g0_threshold = 3 * rt_taker

        g0_pass_list = []

        for entry_z in ENTRY_ZS:
            stat = r["events_data"]["z_peg"][entry_z]
            if stat["count"] > 0:
                median_amp = stat["median_amp_bps"]
                passes = median_amp >= g0_threshold
                if passes:
                    g0_pass_list.append(f"(z_peg, {entry_z})")
                status = "✅ PASS" if passes else "❌ FAIL"
            else:
                median_amp = 0.0
                passes = False
                status = "❌ No events"

            report += (f"| {entry_z} | {stat['count']} | {median_amp:.1f} | {stat['mean_amp_bps']:.1f} | "
                      f"{stat['median_hold_hours']:.1f} | {g0_threshold:.2f} | {'✅' if passes else '❌'} | {status} |\n")

        # Z-roll table
        report += f"\n##### {r['pair']} - z_roll (rolling mean basis)\n\n"
        report += "| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |\n"
        report += "|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|\n"

        for entry_z in ENTRY_ZS:
            stat = r["events_data"]["z_roll"][entry_z]
            if stat["count"] > 0:
                median_amp = stat["median_amp_bps"]
                passes = median_amp >= g0_threshold
                if passes:
                    g0_pass_list.append(f"(z_roll, {entry_z})")
                status = "✅ PASS" if passes else "❌ FAIL"
            else:
                median_amp = 0.0
                passes = False
                status = "❌ No events"

            report += (f"| {entry_z} | {stat['count']} | {median_amp:.1f} | {stat['mean_amp_bps']:.1f} | "
                      f"{stat['median_hold_hours']:.1f} | {g0_threshold:.2f} | {'✅' if passes else '❌'} | {status} |\n")

        report += "\n"

    # Final G0 verdict
    report += "\n## G0 Verdict\n\n"
    all_pass = []
    for r in results:
        if r["bars"] == 0:
            continue
        rt_taker = TAKER_RT_BPS_ONLY_FEES + r["spread_med_bps"]
        g0_threshold = 3 * rt_taker
        for z_name in ENTRY_Z_NAMES:
            for entry_z in ENTRY_ZS:
                stat = r["events_data"][z_name][entry_z]
                if stat["count"] > 0 and stat["median_amp_bps"] >= g0_threshold:
                    all_pass.append(f"({r['pair']}, {z_name}, entry_z={entry_z})")

    if all_pass:
        report += f"✅ **G0 PASS**: {', '.join(all_pass)}\n"
    else:
        report += "❌ **G0 FAIL**: No combinations meet median amplitude >= 3× round-trip cost threshold\n"

    return report

# ============================================================================
# Main entry
# ============================================================================
if __name__ == "__main__":
    print("\n" + "="*70)
    print("G0 Feasibility: HL Stable Pairs Mean Reversion")
    print("="*70)

    results = main()

    report = generate_report(results)

    # Write report
    report_path = "/Users/jim/projects/vault/stablepairs/reports/g0_hl_stables.md"
    with open(report_path, "w") as f:
        f.write(report)

    print(f"\n✅ Report written to: {report_path}")
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    # Extract and print G0 verdict line
    for line in report.split("\n"):
        if "G0" in line and ("PASS" in line or "FAIL" in line):
            print(line)
