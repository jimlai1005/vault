#!/usr/bin/env python3
"""
G0 cost feasibility analysis for HL stablecoin CROSS pairs (synthetic spreads).
Strategy: Long one stable pair, short another stable pair (two-leg trade on cross spread).
Example: Long USDT0/USDC, short USDe/USDC → trade the synthetic spread log(USDT0) - log(USDe).

Targets:
  - @166=USDT0/USDC, @150=USDe/USDC, @230=USDH/USDC
  - Combinations: 166-150, 166-230, 150-230

Cost model:
  RT_cross = (2*1.4 + spread_A) + (2*1.4 + spread_B)
  where spread_A, spread_B are taker spreads in bps for each leg.

G0 threshold: median amplitude >= 3x round-trip cost.

Outputs: stablepairs/reports/g0_cross_pairs.md
"""
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import sys
import os

# Add vault root to path
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

# Real-world spreads measured from g0_hl_stables.md (2026-07-11)
SPREADS_BPS = {
    "@166": 2.5,
    "@150": 0.1,
    "@230": 0.5,
}

# Cross pair combinations and their round-trip costs
CROSS_COMBINATIONS = [
    ("USDT0", "USDe", "@166", "@150"),  # 166-150
    ("USDT0", "USDH", "@166", "@230"),  # 166-230
    ("USDe", "USDH", "@150", "@230"),   # 150-230
]

ENTRY_ZS = [1.0, 1.5, 2.0]
LOOKBACK_BARS = 720  # For rolling mean/std (720 * 1h = 30 days)
EXIT_Z_THRESHOLD = 0.2  # Threshold at which we consider trade closed
TAKER_FEES_BPS_SIDE = 1.4  # Per side

# Time window: 300 days ago to now (same as g0_hl_stables.py)
DAYS_BACK = 300

# ============================================================================
# Fetch 1h history (reuse from g0_hl_stables.py logic)
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
# Compute synthetic spread and z-scores
# ============================================================================
def compute_synthetic_spread_z_roll(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    """
    Compute synthetic cross spread: log(close_A) - log(close_B).
    Then compute z_roll based on 720h rolling mean/std.

    Returns DataFrame with aligned timestamps, synthetic close, and z_roll.
    """
    # Merge on timestamp
    df_a_copy = df_a[["t", "c"]].copy()
    df_a_copy.rename(columns={"c": "c_a"}, inplace=True)

    df_b_copy = df_b[["t", "c"]].copy()
    df_b_copy.rename(columns={"c": "c_b"}, inplace=True)

    df = pd.merge(df_a_copy, df_b_copy, on="t", how="inner")
    df = df.sort_values("t").reset_index(drop=True)

    # Synthetic spread: log(c_a) - log(c_b)
    df["synthetic_spread"] = np.log(df["c_a"]) - np.log(df["c_b"])

    # Rolling z-score
    rolling_mean = df["synthetic_spread"].rolling(LOOKBACK_BARS, min_periods=1).mean()
    rolling_std = df["synthetic_spread"].rolling(LOOKBACK_BARS, min_periods=1).std()

    # Avoid division by zero
    rolling_std = rolling_std.replace(0, np.nan)
    df["z_roll"] = (df["synthetic_spread"] - rolling_mean) / rolling_std

    return df

# ============================================================================
# Event detection on synthetic spread
# ============================================================================
def find_amplitude_events(df: pd.DataFrame, entry_z_thresh: float) -> list:
    """
    Find crossover events where |z_roll| transitions from < entry_z to >= entry_z.
    For each event, track the synthetic spread from entry to first |z| <= EXIT_Z_THRESHOLD.

    Returns list of dicts with event details.
    """
    events = []
    z = df["z_roll"].values
    spread = df["synthetic_spread"].values
    t = df["t"].values

    # Filter out NaN z-scores
    valid_idx = ~np.isnan(z)
    z_valid = z[valid_idx]
    spread_valid = spread[valid_idx]
    t_valid = t[valid_idx]
    idx_valid = np.where(valid_idx)[0]

    if len(z_valid) < 2:
        return events

    in_trade = False
    entry_z_val = None
    entry_spread = None
    entry_t = None

    for i in range(1, len(z_valid)):
        abs_z_prev = abs(z_valid[i - 1])
        abs_z_curr = abs(z_valid[i])

        # Look for crossover: previous bar < threshold, current bar >= threshold
        if not in_trade and abs_z_prev < entry_z_thresh and abs_z_curr >= entry_z_thresh:
            in_trade = True
            entry_z_val = z_valid[i]
            entry_spread = spread_valid[i]
            entry_t = t_valid[i]

        # If in trade, look for exit: |z| <= EXIT_Z_THRESHOLD
        if in_trade and abs(z_valid[i]) <= EXIT_Z_THRESHOLD:
            exit_spread = spread_valid[i]
            exit_t = t_valid[i]

            # Amplitude in basis points: |delta_spread| * 1e4
            # (spread is in log space, so exp(spread) - 1 ≈ spread for small values)
            # But we want |Δ spread| in basis points of the PRICE ratio
            delta_spread = exit_spread - entry_spread
            amp_bps = abs(delta_spread) * 1e4

            hold_hours = (exit_t - entry_t) / (60 * 60 * 1000)
            direction = "pos" if entry_z_val > 0 else "neg"

            events.append({
                "entry_spread": entry_spread,
                "exit_spread": exit_spread,
                "delta_spread": delta_spread,
                "amp_bps": amp_bps,
                "hold_hours": hold_hours,
                "direction": direction,
            })

            in_trade = False
            entry_z_val = None
            entry_spread = None
            entry_t = None

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

    amps = [e["amp_bps"] for e in events]
    holds = [e["hold_hours"] for e in events]

    return {
        "count": len(events),
        "median_amp_bps": float(np.median(amps)),
        "mean_amp_bps": float(np.mean(amps)),
        "median_hold_hours": float(np.median(holds)),
    }

# ============================================================================
# Main analysis
# ============================================================================
def main():
    # Fetch all three pairs once
    print("\n" + "="*70)
    print("Fetching 1h candle history for all three pairs...")
    print("="*70)

    dfs = {}
    for coin_name, pair_info in PAIRS.items():
        coin = pair_info["coin"]
        df = fetch_1h_history(coin)
        if df.empty:
            print(f"SKIP {coin_name}: no candles")
        dfs[coin_name] = df

    # Analyze each cross combination
    results = []
    for pair_a_name, pair_b_name, coin_a_idx, coin_b_idx in CROSS_COMBINATIONS:
        print(f"\n{'='*70}")
        print(f"Analyzing cross pair: {pair_a_name} vs {pair_b_name}")
        print(f"Synthetic spread: log({pair_a_name}) - log({pair_b_name})")
        print(f"{'='*70}")

        df_a = dfs[pair_a_name]
        df_b = dfs[pair_b_name]

        if df_a.empty or df_b.empty:
            print(f"SKIP: one or both pairs have no data")
            continue

        # Compute synthetic spread and z-scores
        df_cross = compute_synthetic_spread_z_roll(df_a, df_b)

        if df_cross.empty:
            print(f"SKIP: no common timestamps")
            continue

        bars_count = len(df_cross)
        days_span = (df_cross["t"].max() - df_cross["t"].min()) / (24 * 60 * 60 * 1000)

        print(f"  Aligned bars: {bars_count}, span: {days_span:.1f} days")

        # Get spreads for both legs
        spread_a_bps = SPREADS_BPS[coin_a_idx]
        spread_b_bps = SPREADS_BPS[coin_b_idx]

        # Compute cross round-trip cost
        rt_cross = (2 * TAKER_FEES_BPS_SIDE + spread_a_bps) + (2 * TAKER_FEES_BPS_SIDE + spread_b_bps)
        g0_threshold = 3 * rt_cross

        print(f"  {pair_a_name} spread: {spread_a_bps:.1f} bps")
        print(f"  {pair_b_name} spread: {spread_b_bps:.1f} bps")
        print(f"  RT_cross = ({2*TAKER_FEES_BPS_SIDE} + {spread_a_bps}) + ({2*TAKER_FEES_BPS_SIDE} + {spread_b_bps}) = {rt_cross:.1f} bps")
        print(f"  G0 threshold (3×RT): {g0_threshold:.1f} bps")

        # Process events for each entry threshold
        events_data = {}
        g0_pass_list = []

        for entry_z in ENTRY_ZS:
            events = find_amplitude_events(df_cross, entry_z)
            stats = aggregate_stats(events)
            events_data[entry_z] = stats

            passes = stats["count"] > 0 and stats["median_amp_bps"] >= g0_threshold
            if passes:
                g0_pass_list.append(entry_z)

            print(f"  entry_z={entry_z}: {stats['count']} events, "
                  f"median_amp={stats['median_amp_bps']:.1f} bps, "
                  f"median_hold={stats['median_hold_hours']:.1f}h, "
                  f"{'✅ PASS' if passes else '❌ FAIL'}")

        results.append({
            "pair_a": pair_a_name,
            "pair_b": pair_b_name,
            "coin_a_idx": coin_a_idx,
            "coin_b_idx": coin_b_idx,
            "bars": bars_count,
            "days": days_span,
            "spread_a_bps": spread_a_bps,
            "spread_b_bps": spread_b_bps,
            "rt_cross_bps": rt_cross,
            "g0_threshold_bps": g0_threshold,
            "events_data": events_data,
            "g0_pass_list": g0_pass_list,
        })

    return results

# ============================================================================
# Report generation
# ============================================================================
def generate_report(results: list) -> str:
    """Generate markdown report with tables and G0 verdict."""
    report = """# G0 Cost Feasibility: HL Stablecoin CROSS Pairs

## Summary
Analysis of synthetic cross spreads (long one stable pair, short another) on HL.
- Pairs: USDT0/USDC (@166), USDe/USDC (@150), USDH/USDC (@230)
- Strategy: Synthetic spread = log(close_A) - log(close_B), mean reversion
- Fee structure: Taker 1.4 bps/side per leg (double-leg trade)
- G0 threshold: median amplitude >= 3× round-trip cost

## Cross Pair Analysis

"""

    # Summary table
    report += "| Combination | Bars | Days | Spread A (bps) | Spread B (bps) | RT_cross (bps) | 3×RT (bps) |\n"
    report += "|---|---|---|---|---|---|---|\n"

    for r in results:
        combo = f"{r['pair_a']}-{r['pair_b']}"
        report += f"| {combo} | {r['bars']} | {r['days']:.1f} | {r['spread_a_bps']:.1f} | {r['spread_b_bps']:.1f} | {r['rt_cross_bps']:.1f} | {r['g0_threshold_bps']:.1f} |\n"

    report += "\n## Event Statistics & G0 Judgment\n\n"

    for r in results:
        combo = f"{r['pair_a']}-{r['pair_b']}"
        report += f"### {combo}\n\n"
        report += f"**Data:** {r['bars']} bars, {r['days']:.1f} days | "
        report += f"**Cost:** RT_cross={r['rt_cross_bps']:.1f} bps, 3×RT={r['g0_threshold_bps']:.1f} bps\n\n"

        report += "| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | Passes G0 | Status |\n"
        report += "|---|---|---|---|---|---|---|\n"

        for entry_z in ENTRY_ZS:
            stat = r["events_data"][entry_z]
            passes = entry_z in r["g0_pass_list"]
            status = "✅ PASS" if passes else "❌ FAIL"

            report += (f"| {entry_z} | {stat['count']} | {stat['median_amp_bps']:.1f} | "
                      f"{stat['mean_amp_bps']:.1f} | {stat['median_hold_hours']:.1f} | "
                      f"{'✅' if passes else '❌'} | {status} |\n")

        report += "\n"

    # Final verdict
    report += "## G0 Verdict\n\n"

    any_pass = False
    pass_details = []

    for r in results:
        combo = f"{r['pair_a']}-{r['pair_b']}"
        if r["g0_pass_list"]:
            any_pass = True
            for entry_z in r["g0_pass_list"]:
                stat = r["events_data"][entry_z]
                pass_details.append(
                    f"- {combo} @ entry_z={entry_z}: median amp = {stat['median_amp_bps']:.1f} bps >= {r['g0_threshold_bps']:.1f} bps threshold"
                )

    if any_pass:
        report += f"✅ **G0 PASS**: One or more cross combinations exceed 3× round-trip cost threshold.\n\n"
        for detail in pass_details:
            report += detail + "\n"
    else:
        report += "❌ **G0 FAIL**: No cross combinations meet median amplitude >= 3× round-trip cost threshold.\n"

    return report

# ============================================================================
# Main entry
# ============================================================================
if __name__ == "__main__":
    print("\n" + "="*70)
    print("G0 Feasibility: HL Stablecoin CROSS Pairs")
    print("="*70)

    results = main()

    report = generate_report(results)

    # Write report
    report_path = "/Users/jim/projects/vault/stablepairs/reports/g0_cross_pairs.md"
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
