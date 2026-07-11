#!/usr/bin/env python3
"""
Scalping universe scanner (Task 3): filter coins by volume, depth, spread, fidelity.
Outputs: reports/scalp-universe-scan.md, data/scalp/shortlist.json, data/scalp/slippage.json
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
import argparse
from typing import Optional, Dict, List, Tuple

import pandas as pd
import numpy as np

sys.path.insert(0, 'scripts')
import scalp_lib as sl


def load_fees() -> Dict:
    """Load fees from data/scalp/fees.json."""
    with open(sl.DATA_DIR + '/fees.json') as f:
        return json.load(f)


def scan_spreads(candidates: List[str], num_rounds: int) -> Dict[str, List[float]]:
    """
    Sample spreads over num_rounds iterations, sleep(30) between rounds.
    Returns: {coin: [spread_bps_samples]}
    """
    samples = {c: [] for c in candidates}
    for round_i in range(num_rounds):
        for coin in candidates:
            try:
                spread = sl.l2_spread_bps(coin)
                if spread is not None:
                    samples[coin].append(spread)
                    print(f"  [{round_i+1}/{num_rounds}] {coin}: {spread:.2f} bps")
            except Exception as e:
                print(f"  [{round_i+1}/{num_rounds}] {coin}: ERROR {e}")
        if round_i < num_rounds - 1:
            time.sleep(30)
    return samples


def compute_range_stats(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute range_med_bps (median of single-bar range) and p90_range5_bps (P90 of rolling 5-bar range).
    """
    if df.empty:
        return None, None

    # Single-bar range in bps
    df_work = df.copy()
    df_work['range_bps'] = (df_work['h'] - df_work['l']) / df_work['c'] * 1e4
    range_med = df_work['range_bps'].median()

    # Rolling 5-bar range
    df_work['range5_bps'] = (df_work['h'].rolling(5).max() - df_work['l'].rolling(5).min()) / df_work['c'].rolling(5).mean() * 1e4
    p90_range5 = df_work['range5_bps'].quantile(0.9)

    return range_med, p90_range5


def compute_fidelity(hl_df: pd.DataFrame, binance_df: pd.DataFrame) -> Optional[float]:
    """
    Compare HL vs Binance single-bar range median on overlapping time window.
    fidelity = HL_median / Binance_median. Pass if in [0.7, 1.3]
    """
    if hl_df.empty or binance_df.empty:
        return None

    # Find overlapping timestamps
    hl_ts = set(hl_df['t'].values)
    binance_ts = set(binance_df['t'].values)
    overlap_ts = sorted(hl_ts & binance_ts)

    if len(overlap_ts) < 10:  # Need minimum overlap
        return None

    hl_overlap = hl_df[hl_df['t'].isin(overlap_ts)].sort_values('t')
    binance_overlap = binance_df[binance_df['t'].isin(overlap_ts)].sort_values('t')

    # Single-bar range in bps
    hl_overlap_work = hl_overlap.copy()
    hl_overlap_work['range_bps'] = (hl_overlap_work['h'] - hl_overlap_work['l']) / hl_overlap_work['c'] * 1e4
    hl_med = hl_overlap_work['range_bps'].median()

    binance_overlap_work = binance_overlap.copy()
    binance_overlap_work['range_bps'] = (binance_overlap_work['h'] - binance_overlap_work['l']) / binance_overlap_work['c'] * 1e4
    binance_med = binance_overlap_work['range_bps'].median()

    if binance_med < 1e-9:  # Avoid division by zero
        return None

    return hl_med / binance_med


def main():
    parser = argparse.ArgumentParser(description='Scalping universe scanner')
    parser.add_argument('--quick', action='store_true', help='Quick mode: 20 spread rounds instead of 240')
    args = parser.parse_args()

    spread_rounds = 20 if args.quick else 240
    print(f"Running scan with {spread_rounds} spread rounds...")

    # Load fees
    fees = load_fees()
    taker_bps = fees['taker'] * 1e4
    print(f"Using taker fee: {taker_bps:.2f} bps\n")

    # Step 1: Filter universe by volume
    print("Step 1: Fetching universe...")
    universe_df = sl.universe_ctxs()
    min_volume = 20e6
    candidates_df = universe_df[universe_df['dayNtlVlm'] >= min_volume].copy()
    candidates = candidates_df['name'].tolist()
    print(f"  Candidates (dayNtlVlm >= {min_volume/1e6:.0f}M): {len(candidates)} coins")
    print(f"  {', '.join(candidates[:10])}{'...' if len(candidates) > 10 else ''}\n")

    # Step 2: Map to Binance and compute depth
    print("Step 2: Mapping to Binance and computing depth...")
    now_ms = int(pd.Timestamp.now(tz='UTC').timestamp() * 1000)
    binance_symbols = sl.binance_perp_symbols()
    print(f"  Found {len(binance_symbols)} active Binance PERP symbols")

    mapped = {}  # coin -> {binance_symbol, depth_days}
    skipped = []
    for coin in candidates:
        sym = sl.binance_symbol(coin, binance_symbols)
        if sym is None:
            skipped.append(coin)
        else:
            earliest_ms = sl.binance_earliest_1m(sym)
            if earliest_ms is None:
                skipped.append(coin)
            else:
                depth_days = (now_ms - earliest_ms) / (24 * 3600 * 1000)
                mapped[coin] = {'binance_symbol': sym, 'depth_days': depth_days}
                print(f"  {coin:12s} -> {sym:15s} ({depth_days:6.0f} days)")

    if skipped:
        print(f"  Skipped (no Binance mapping): {', '.join(skipped)}")

    candidates = list(mapped.keys())
    print(f"  After Binance mapping: {len(candidates)} coins\n")

    # Step 3: Spread sampling
    print(f"Step 3: Sampling spreads ({spread_rounds} rounds, ~{spread_rounds*30/60:.0f} min)...")
    spread_samples = scan_spreads(candidates, spread_rounds)
    print()

    # Step 4 & 4b: Binance history + range stats + fidelity
    print("Step 4/4b: Fetching Binance history & computing range/fidelity...")
    rows = []
    slippage_map = {}
    shortlist_coins = []

    thirty_days_ago = now_ms - 30 * 24 * 3600 * 1000
    three_days_ago = now_ms - 3 * 24 * 3600 * 1000

    for coin in candidates:
        print(f"  {coin}...", end=' ', flush=True)
        try:
            binance_sym = mapped[coin]['binance_symbol']

            # Range stats on 30-day Binance history
            binance_df = sl.pull_binance_1m(binance_sym, thirty_days_ago, now_ms)
            if binance_df.empty:
                print("(empty binance)")
                continue

            range_med, p90_range5 = compute_range_stats(binance_df)

            # Fidelity on 3-day overlap
            hl_df = sl.pull_1m_history(coin, three_days_ago, now_ms)
            fidelity = compute_fidelity(hl_df, binance_df)

            # Spread median from samples
            spread_samples_list = spread_samples[coin]
            spread_med = np.median(spread_samples_list) if spread_samples_list else None

            # Impact spread
            coin_ctx = universe_df[universe_df['name'] == coin].iloc[0]
            impact_bid = coin_ctx['impact_bid']
            impact_ask = coin_ctx['impact_ask']
            mid_px = coin_ctx['midPx']

            if impact_bid is None or impact_ask is None or mid_px is None or mid_px == 0:
                impact_spread = 0
            else:
                impact_spread = (impact_ask - impact_bid) / mid_px * 1e4 if mid_px else 0

            # Cost computation
            slip_bps = max(spread_med / 2 if spread_med else 0,
                           impact_spread / 2) + 0.5
            rt_cost_bps = 2 * taker_bps + 2 * slip_bps
            ratio = p90_range5 / rt_cost_bps if rt_cost_bps > 0 else 0

            slippage_map[coin] = slip_bps

            # Check shortlist criteria
            passes_shortlist = (
                ratio >= 3 and
                spread_med <= 5 and
                mapped[coin]['depth_days'] >= 180 and
                fidelity is not None and 0.7 <= fidelity <= 1.3
            )

            if passes_shortlist:
                shortlist_coins.append((coin, ratio))

            row = {
                'coin': coin,
                'binance_symbol': binance_sym,
                'dayNtlVlm': coin_ctx['dayNtlVlm'],
                'depth_days': mapped[coin]['depth_days'],
                'spread_med_bps': spread_med,
                'impact_spread_bps': impact_spread,
                'range_med_bps': range_med,
                'p90_range5_bps': p90_range5,
                'rt_cost_bps': rt_cost_bps,
                'ratio': ratio,
                'fidelity': fidelity,
                'shortlist': passes_shortlist
            }
            rows.append(row)
            print(f"OK (ratio={ratio:.2f}, fidelity={fidelity:.2f})")

        except Exception as e:
            print(f"ERROR: {e}")
            continue

    # Finalize shortlist (top 8 by ratio)
    shortlist_coins.sort(key=lambda x: x[1], reverse=True)
    shortlist_coins = shortlist_coins[:8]
    shortlist_set = {c for c, _ in shortlist_coins}

    # Mark shortlist in rows
    for row in rows:
        row['shortlist'] = row['coin'] in shortlist_set

    print(f"\nShortlist ({len(shortlist_coins)} coins): {[c for c, _ in shortlist_coins]}\n")

    # Step 5: Output files
    print("Step 5: Writing outputs...")

    # shortlist.json
    shortlist_data = [
        {'coin': c, 'binance_symbol': mapped[c]['binance_symbol']}
        for c, _ in shortlist_coins
    ]
    with open(sl.DATA_DIR + '/shortlist.json', 'w') as f:
        json.dump(shortlist_data, f, indent=2)
    print(f"  Wrote {sl.DATA_DIR}/shortlist.json")

    # slippage.json
    with open(sl.DATA_DIR + '/slippage.json', 'w') as f:
        json.dump(slippage_map, f, indent=2)
    print(f"  Wrote {sl.DATA_DIR}/slippage.json")

    # Report markdown
    report_path = 'reports/scalp-universe-scan.md'
    df_report = pd.DataFrame(rows)

    with open(report_path, 'w') as f:
        f.write("# Scalping Universe Scan Results\n\n")
        f.write(f"**Scan Date:** {datetime.utcnow().isoformat()}Z\n")
        f.write(f"**Spread Rounds:** {spread_rounds} (mode: {'quick' if args.quick else 'full'})\n")
        f.write(f"**Taker Fee:** {taker_bps:.2f} bps\n\n")

        f.write("## Candidates Table\n\n")
        f.write("| coin | binance_symbol | dayNtlVlm | depth_days | spread_med_bps | impact_spread_bps | range_med_bps | p90_range5_bps | rt_cost_bps | ratio | fidelity | shortlist |\n")
        f.write("|------|---|---|---|---|---|---|---|---|---|---|---|\n")

        for _, row in df_report.iterrows():
            vnlm = f"{row['dayNtlVlm']:.2e}" if pd.notna(row['dayNtlVlm']) else "N/A"
            depth = f"{row['depth_days']:.0f}" if pd.notna(row['depth_days']) else "N/A"
            spread_med = f"{row['spread_med_bps']:.2f}" if pd.notna(row['spread_med_bps']) else "N/A"
            impact_sp = f"{row['impact_spread_bps']:.2f}" if pd.notna(row['impact_spread_bps']) else "N/A"
            range_med = f"{row['range_med_bps']:.2f}" if pd.notna(row['range_med_bps']) else "N/A"
            p90_range5 = f"{row['p90_range5_bps']:.2f}" if pd.notna(row['p90_range5_bps']) else "N/A"
            rt_cost = f"{row['rt_cost_bps']:.2f}" if pd.notna(row['rt_cost_bps']) else "N/A"
            ratio = f"{row['ratio']:.2f}" if pd.notna(row['ratio']) else "N/A"
            fidelity = f"{row['fidelity']:.2f}" if pd.notna(row['fidelity']) else "N/A"

            f.write(f"| {row['coin']} | {row['binance_symbol']} | {vnlm} | {depth} | "
                   f"{spread_med} | {impact_sp} | {range_med} | "
                   f"{p90_range5} | {rt_cost} | {ratio} | {fidelity} | {'✓' if row['shortlist'] else '-'} |\n")

        f.write("\n## G0 Gate Result\n\n")
        passes = (len(shortlist_coins) >= 4)
        f.write(f"**Shortlist:** {len(shortlist_coins)} coins\n")
        f.write(f"**Threshold:** ≥ 4 coins\n")
        f.write(f"**G0 Result:** {'PASS ✓' if passes else 'FAIL ✗'}\n")

    print(f"  Wrote {report_path}")
    print(f"\nG0 Gate: {len(shortlist_coins)} coins shortlisted → {'PASS' if passes else 'FAIL'}")


if __name__ == '__main__':
    main()
