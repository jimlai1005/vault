#!/usr/bin/env python3
"""
Momentum-VT v1 Task 0 data foundation layer.
Builds k-line universe, PIT universe schedule, funding history, and HL fidelity report.

Usage:
  python k_data_layer.py --klines      # Fetch Binance USDT-perp day-lines 2020-2026
  python k_data_layer.py --universe    # Build PIT universe schedule
  python k_data_layer.py --funding     # Fetch Binance funding rate history
  python k_data_layer.py --fidelity    # HL vs Binance cross-validation (BTC/ETH/SOL/HYPE Jun 2026)
  python k_data_layer.py --all         # All tasks in sequence
"""

import os
import sys
import time
import json
import argparse
import warnings
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd
import requests

# Add scripts dir to path to import scalp_lib
sys.path.insert(0, str(Path(__file__).parent))

from scalp_lib import (
    binance_perp_symbols, binance_klines, binance_rows_to_df,
    INFO_URL, BINANCE_SLEEP
)

warnings.filterwarnings('ignore', category=FutureWarning)

DATA_DIR = Path("data/k_framework")
KLINES_DIR = DATA_DIR / "klines"
FUNDING_DIR = DATA_DIR / "funding"
REPORTS_DIR = Path("reports")

# Create directories
for d in [KLINES_DIR, FUNDING_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
FIXED_UNIVERSE = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT"}  # HYPE on Binance
HYPE_LISTING_DATE = "2024-11-01"  # Binance listing date for HYPE


def ts_ms(date_str: str) -> int:
    """Convert YYYY-MM-DD to milliseconds since epoch (UTC)."""
    return int(pd.Timestamp(date_str, tz="UTC").timestamp() * 1000)


def ms_to_date(ms: int) -> str:
    """Convert milliseconds to YYYY-MM-DD."""
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")


def fetch_all_klines(start_date: str = "2020-01-01", end_date: str = "2026-07-02"):
    """
    Task 1: Fetch all Binance USDT perpetual day-lines.
    """
    print(f"\n{'='*60}")
    print(f"Task 1: Fetch all Binance USDT-perp day-lines {start_date} → {end_date}")
    print(f"{'='*60}")

    start_ms = ts_ms(start_date)
    end_ms = ts_ms(end_date)

    # Get all active USDT perpetuals
    print("Fetching exchange info...")
    resp = requests.get(f"{BINANCE_FAPI}/exchangeInfo", timeout=20)
    resp.raise_for_status()
    info = resp.json()

    all_symbols = {s["symbol"] for s in info["symbols"]
                   if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"}

    # Filter to USDT-based (exclude busd, etc)
    usdt_symbols = sorted([s for s in all_symbols if s.endswith("USDT")])

    print(f"Found {len(usdt_symbols)} USDT perpetuals")
    print(f"Sample symbols: {sorted(usdt_symbols)[:10]}")

    failed = []
    success_count = 0

    for i, symbol in enumerate(usdt_symbols):
        if i % 50 == 0:
            print(f"Progress: {i}/{len(usdt_symbols)}")

        try:
            # Fetch in 2 pages (1500 * 2 = 3000 bars, enough for ~8 years of daily)
            rows = []
            cur = start_ms
            while cur < end_ms:
                batch = binance_klines(symbol, "1d", cur, end_ms, limit=1500, retries=3)
                time.sleep(BINANCE_SLEEP)
                if not batch:
                    break
                rows.extend(batch)
                cur = int(batch[-1][0]) + 24 * 3600 * 1000  # next day
                if len(batch) < 1500:
                    break

            if not rows:
                print(f"  {symbol}: no data")
                failed.append(symbol)
                continue

            df = binance_rows_to_df(rows)

            # Save compressed
            path = KLINES_DIR / f"{symbol}_1d.csv.gz"
            df.to_csv(path, index=False, compression="gzip")
            success_count += 1

            if i % 20 == 0:
                print(f"  {symbol}: {len(df)} bars → {path.name}")

        except Exception as e:
            print(f"  {symbol}: ERROR {e}")
            failed.append(symbol)

    print(f"\n✓ Fetched {success_count}/{len(usdt_symbols)} symbols")
    if failed:
        print(f"✗ Failed ({len(failed)}): {failed[:20]}")

    return success_count, failed


def build_pit_universe(start_date: str = "2020-07-01", end_date: str = "2026-07-02",
                       kline_dir: Path = KLINES_DIR):
    """
    Task 2: Build PIT universe schedule.
    Each quarter: compute trailing 90d volume, filter >= $100M and >= 180d old, keep top 8.
    No forward-looking: only use data before quarter start date.
    """
    print(f"\n{'='*60}")
    print(f"Task 2: Build PIT Universe schedule (quarterly)")
    print(f"{'='*60}")

    # Quarter boundaries from 2020-Q3 to 2026-Q1
    quarters = []
    year, q = 2020, 3
    while (year, q) <= (2026, 1):
        # Quarter starts: Q1=01-01, Q2=04-01, Q3=07-01, Q4=10-01
        month = (q - 1) * 3 + 1
        quarter_date = f"{year}-{month:02d}-01"
        quarters.append((quarter_date, year, q))
        q += 1
        if q > 4:
            q = 1
            year += 1

    print(f"Processing {len(quarters)} quarters: {quarters[0][0]} → {quarters[-1][0]}")

    # Load all klines
    kline_files = sorted(kline_dir.glob("*_1d.csv.gz"))
    print(f"Loaded {len(kline_files)} kline files")

    universe_schedule = {}

    for quarter_date, year, q in quarters:
        print(f"\n  {year}-Q{q} ({quarter_date}):")

        # Quarter start date (no forward-looking: only use data BEFORE this date)
        quarter_ts = pd.Timestamp(quarter_date, tz="UTC")
        lookback_end = quarter_ts - timedelta(days=1)  # Last day before quarter start
        lookback_start = lookback_end - timedelta(days=90)

        # Compute trailing 90d volume for each symbol
        volumes = {}
        listing_dates = {}  # Track when each symbol listed

        for kline_file in kline_files:
            symbol = kline_file.stem.split("_")[0]
            try:
                df = pd.read_csv(kline_file, usecols=["t", "v"])
                df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)

                # Find listing date (first bar)
                if len(df) > 0:
                    listing_date = df["t"].min()
                    listing_dates[symbol] = listing_date

                    # Filter to lookback window
                    mask = (df["t"] >= lookback_start) & (df["t"] <= lookback_end)
                    window = df[mask]

                    if len(window) > 0:
                        # Compute 90d volume (convert volume to nominal in quote currency)
                        # Note: Binance USDT perp volume is in USDT already
                        vol_usdt = window["v"].sum()
                        volumes[symbol] = vol_usdt
            except Exception as e:
                pass

        # Filter: >= $100M volume AND >= 180 days old
        min_volume = 100e6  # $100M
        min_listing_days = 180

        filtered = {}
        for symbol, vol in volumes.items():
            if vol >= min_volume:
                days_old = (lookback_end - listing_dates[symbol]).days
                if days_old >= min_listing_days:
                    filtered[symbol] = vol

        # Sort and take top 8
        top8 = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:8]
        top8_symbols = [s for s, v in top8]

        universe_schedule[quarter_date] = top8_symbols

        print(f"    Candidates: {len(filtered)}")
        print(f"    Top 8: {top8_symbols}")
        for s, v in top8:
            print(f"      {s}: ${v/1e6:.1f}M")

    # Save JSON
    schedule_file = DATA_DIR / "universe_schedule.json"
    with open(schedule_file, "w") as f:
        json.dump(universe_schedule, f, indent=2)
    print(f"\n✓ Saved {schedule_file}")

    # Save human-readable markdown
    md_file = REPORTS_DIR / "k-universe-schedule.md"
    with open(md_file, "w") as f:
        f.write("# Momentum-VT v1: PIT Universe Schedule\n\n")
        f.write("Each quarter: Binance USDT-perp symbols with trailing 90d volume >= $100M\n")
        f.write("and ≥180 days since listing (computed with data BEFORE quarter start).\n\n")
        f.write("| Quarter | Universe (Top 8) |\n")
        f.write("|---|---|\n")
        for quarter_date in sorted(universe_schedule.keys()):
            symbols_str = ", ".join(universe_schedule[quarter_date])
            f.write(f"| {quarter_date} | {symbols_str} |\n")
    print(f"✓ Saved {md_file}")

    return universe_schedule


def fetch_funding_history(kline_dir: Path = KLINES_DIR,
                          universe_schedule: Optional[Dict] = None):
    """
    Task 3: Fetch Binance fundingRate history.
    Covers: fixed-4 (BTC/ETH/SOL/HYPE) + all symbols that ever entered PIT top-8.
    """
    print(f"\n{'='*60}")
    print(f"Task 3: Fetch Binance fundingRate history")
    print(f"{'='*60}")

    # Symbols to fetch
    to_fetch = set(FIXED_UNIVERSE)

    if universe_schedule is None:
        # Load from file if not provided
        schedule_file = DATA_DIR / "universe_schedule.json"
        if schedule_file.exists():
            with open(schedule_file) as f:
                universe_schedule = json.load(f)

    if universe_schedule:
        for symbols_list in universe_schedule.values():
            to_fetch.update(symbols_list)

    to_fetch = sorted(to_fetch)
    print(f"Fetching funding for {len(to_fetch)} symbols: {to_fetch}")

    failed = []
    success_count = 0

    for i, symbol in enumerate(to_fetch):
        if i % 20 == 0:
            print(f"Progress: {i}/{len(to_fetch)}")

        try:
            # Binance fundingRate API: /fapi/v1/fundingRate
            # 1000 per request, paginated
            rows = []
            startTime = None

            while True:
                params = {"symbol": symbol, "limit": 1000}
                if startTime:
                    params["startTime"] = startTime

                r = requests.get(f"{BINANCE_FAPI}/fundingRate", params=params, timeout=20)
                r.raise_for_status()
                batch = r.json()
                time.sleep(BINANCE_SLEEP)

                if not batch:
                    break

                rows.extend(batch)
                startTime = int(batch[-1]["fundingTime"]) + 1

                if len(batch) < 1000:
                    break

            if not rows:
                print(f"  {symbol}: no data")
                failed.append(symbol)
                continue

            # Convert to DataFrame
            df = pd.DataFrame(rows)
            df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
            df["fundingRate"] = df["fundingRate"].astype(float)
            df = df[["fundingTime", "fundingRate"]].sort_values("fundingTime").reset_index(drop=True)

            # Save
            path = FUNDING_DIR / f"{symbol}_funding.csv.gz"
            df.to_csv(path, index=False, compression="gzip")
            success_count += 1

            if i % 10 == 0:
                print(f"  {symbol}: {len(df)} bars → {path.name}")

        except Exception as e:
            print(f"  {symbol}: ERROR {e}")
            failed.append(symbol)

    print(f"\n✓ Fetched funding for {success_count}/{len(to_fetch)} symbols")
    if failed:
        print(f"✗ Failed ({len(failed)}): {failed}")

    return success_count, failed


def compute_hl_fidelity():
    """
    Task 4: HL vs Binance proxy fidelity for BTC/ETH/SOL/HYPE over June 2026.
    Compare: day-line close correlation, volatility ratio, funding correlation.
    """
    print(f"\n{'='*60}")
    print(f"Task 4: HL vs Binance Fidelity (BTC/ETH/SOL/HYPE, Jun 2026)")
    print(f"{'='*60}")

    coins = ["BTC", "ETH", "SOL", "HYPE"]

    # 30 days of June 2026
    start_date = "2026-06-01"
    end_date = "2026-06-30"
    start_ms = ts_ms(start_date)
    end_ms = ts_ms(end_date)

    results = {}

    for coin in coins:
        print(f"\n  Processing {coin}:")

        try:
            # Binance klines
            symbol = f"{coin}USDT"
            rows_bn = binance_klines(symbol, "1d", start_ms, end_ms, limit=1500)
            time.sleep(BINANCE_SLEEP)

            if not rows_bn:
                print(f"    {symbol}: no Binance data")
                continue

            df_bn = binance_rows_to_df(rows_bn)

            # HL candles
            from scalp_lib import get_candles, candles_to_df
            rows_hl = get_candles(coin, "1d", start_ms, end_ms)
            time.sleep(0.5)

            if not rows_hl:
                print(f"    {coin}: no HL data")
                continue

            df_hl = candles_to_df(rows_hl)

            # Align by date
            df_bn["date"] = df_bn["ts"].dt.date
            df_hl["date"] = df_hl["ts"].dt.date

            merged = pd.merge(df_bn[["date", "c", "v"]].rename(columns={"c": "c_bn", "v": "v_bn"}),
                             df_hl[["date", "c", "v"]].rename(columns={"c": "c_hl", "v": "v_hl"}),
                             on="date", how="inner")

            if len(merged) < 5:
                print(f"    Insufficient overlap")
                continue

            # Compute correlations and vol ratio
            merged["ret_bn"] = merged["c_bn"].pct_change()
            merged["ret_hl"] = merged["c_hl"].pct_change()

            ret_corr = merged[["ret_bn", "ret_hl"]].corr().iloc[0, 1]
            vol_bn = merged["ret_bn"].std() * np.sqrt(252)
            vol_hl = merged["ret_hl"].std() * np.sqrt(252)
            vol_ratio = vol_hl / vol_bn if vol_bn > 0 else 0

            results[coin] = {
                "days": len(merged),
                "return_correlation": float(ret_corr),
                "binance_vol_annual": float(vol_bn),
                "hl_vol_annual": float(vol_hl),
                "vol_ratio_hl_bn": float(vol_ratio),
            }

            print(f"    Days: {len(merged)}")
            print(f"    Return correlation: {ret_corr:.4f}")
            print(f"    Binance vol (annual): {vol_bn:.2%}")
            print(f"    HL vol (annual): {vol_hl:.2%}")
            print(f"    Vol ratio (HL/Binance): {vol_ratio:.4f}")

        except Exception as e:
            print(f"    ERROR: {e}")

    # Save report
    report_file = REPORTS_DIR / "k-proxy-fidelity.md"
    with open(report_file, "w") as f:
        f.write("# Momentum-VT v1: HL vs Binance Proxy Fidelity\n\n")
        f.write("Comparison over June 2026 (30-day window).\n\n")
        f.write("## Summary\n\n")
        f.write("| Coin | Days | Return Corr | Binance Vol (ann) | HL Vol (ann) | Vol Ratio (HL/Bn) |\n")
        f.write("|---|---|---|---|---|---|\n")

        for coin in coins:
            if coin not in results:
                f.write(f"| {coin} | N/A | — | — | — | — |\n")
            else:
                r = results[coin]
                f.write(f"| {coin} | {r['days']} | {r['return_correlation']:.4f} | "
                       f"{r['binance_vol_annual']:.2%} | {r['hl_vol_annual']:.2%} | "
                       f"{r['vol_ratio_hl_bn']:.4f} |\n")

        f.write("\n## Details\n\n")
        for coin in coins:
            if coin in results:
                r = results[coin]
                f.write(f"### {coin}\n")
                f.write(f"- Overlapping days: {r['days']}\n")
                f.write(f"- Daily return correlation: {r['return_correlation']:.4f}\n")
                f.write(f"- Binance annualized vol: {r['binance_vol_annual']:.2%}\n")
                f.write(f"- HL annualized vol: {r['hl_vol_annual']:.2%}\n")
                f.write(f"- Vol ratio (HL/Binance): {r['vol_ratio_hl_bn']:.4f}\n")
                f.write("\n")

    print(f"\n✓ Saved {report_file}")

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--klines", action="store_true", help="Fetch all Binance USDT-perp day-lines")
    parser.add_argument("--universe", action="store_true", help="Build PIT universe schedule")
    parser.add_argument("--funding", action="store_true", help="Fetch Binance funding history")
    parser.add_argument("--fidelity", action="store_true", help="HL vs Binance fidelity report")
    parser.add_argument("--all", action="store_true", help="Run all tasks")

    args = parser.parse_args()

    if not any([args.klines, args.universe, args.funding, args.fidelity, args.all]):
        parser.print_help()
        sys.exit(1)

    start_time = time.time()

    try:
        if args.klines or args.all:
            fetch_all_klines()

        if args.universe or args.all:
            universe_schedule = build_pit_universe()
        else:
            universe_schedule = None

        if args.funding or args.all:
            fetch_funding_history(universe_schedule=universe_schedule)

        if args.fidelity or args.all:
            compute_hl_fidelity()

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"✓ All tasks completed in {elapsed:.1f}s")
        print(f"{'='*60}")

    except KeyboardInterrupt:
        print("\n✗ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
