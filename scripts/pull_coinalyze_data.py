#!/usr/bin/env python3
"""
Coinalyze Data Pull — OI and Long/Short Ratio History
Pulls 2-year 4h data for BTC, ETH, SOL, HYPE, DOGE, XRP from Coinalyze.
Saves to parquet with schema inspection and gap reporting.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import os

try:
    import pandas as pd
    import pyarrow.parquet as pq
except ImportError:
    print("ERROR: pandas and pyarrow required. Install: pip install pandas pyarrow", file=sys.stderr)
    sys.exit(1)

# Configuration
VAULT_ROOT = Path(__file__).parent.parent
CACHE_DIR = VAULT_ROOT / "data" / "cache" / "coinalyze"
REPORTS_DIR = VAULT_ROOT / "reports"
TIMEOUT = 20
MAX_RETRIES = 3
RATE_LIMIT_SLEEP = 1.6  # 40 req/min = 1.5s; use 1.6s to be safe

TARGET_COINS = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP"]
# NOTE: original plan assumed 2yr history (2024-07-01), but this API key's plan
# only serves ~335 days of 4h OI/LSR history (verified empirically 2026-07-04:
# BTC/HYPE both return empty before ~2025-08-03, full data from ~2025-08-04).
# DATE_START is set a couple days before that empirically-verified boundary;
# the pre-boundary chunk legitimately returns empty and is skipped (see
# pull_oi_history / pull_lsr_history "No data" branch) rather than erroring.
DATE_START = datetime(2025, 8, 1)
DATE_END = datetime.now()
CHUNK_DAYS = 120  # Safe pagination window for 4h data (verified: 120d -> 721 rows, no truncation)

# Load API key
load_dotenv(VAULT_ROOT / ".env.research")
API_KEY = os.getenv("COINALYZE_API_KEY")
if not API_KEY:
    print("ERROR: COINALYZE_API_KEY not found in .env.research", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://api.coinalyze.net/v1"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def make_request(endpoint, params=None):
    """Make HTTP request with retry logic, rate limiting, and timeout."""
    import urllib.parse

    url = f"{BASE_URL}{endpoint}"
    if params:
        param_str = urllib.parse.urlencode(params)
        url = f"{url}?{param_str}"

    headers = {"api_key": API_KEY}

    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(RATE_LIMIT_SLEEP)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode('utf-8')), response.status, None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):  # Transient errors
                wait_time = 2 ** attempt
                print(f"  [Attempt {attempt + 1}] HTTP {e.code}, retrying in {wait_time}s...", file=sys.stderr)
                time.sleep(wait_time)
                if attempt < MAX_RETRIES - 1:
                    continue
            error_msg = f"HTTP {e.code}"
            return None, e.code, error_msg
        except urllib.error.URLError as e:
            wait_time = 2 ** attempt
            print(f"  [Attempt {attempt + 1}] URLError: {e.reason}, retrying in {wait_time}s...", file=sys.stderr)
            time.sleep(wait_time)
            if attempt < MAX_RETRIES - 1:
                continue
            return None, None, str(e.reason)
        except Exception as e:
            return None, None, str(e)

    return None, None, "Max retries exceeded"

def get_future_markets():
    """Fetch available future markets and find Binance (.A) symbols."""
    print("\n=== Fetching Future Markets ===")
    data, status, error = make_request("/future-markets")

    if error:
        print(f"ERROR: Failed to fetch markets: {error}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print(f"ERROR: Unexpected response format (expected list): {type(data)}", file=sys.stderr)
        sys.exit(1)

    markets = data
    symbols_map = {}  # coin -> symbol

    print(f"Total markets: {len(markets)}")

    for market in markets:
        symbol = market.get("symbol", "")
        base_asset = market.get("base_asset", "")

        # Find Binance (.A) USDT perps for target coins
        if not symbol.endswith("USDT_PERP.A"):
            continue

        # base_asset is already the coin name (e.g., "BTC")
        if base_asset in TARGET_COINS:
            symbols_map[base_asset] = symbol
            print(f"  ✓ {base_asset}: {symbol}")

    # Check for missing coins and fallback to other exchanges
    missing = set(TARGET_COINS) - set(symbols_map.keys())
    if missing:
        print(f"\n⚠ Missing on Binance: {missing}")
        print("  Looking for fallbacks...")

        for market in markets:
            symbol = market.get("symbol", "")
            base_asset = market.get("base_asset", "")

            if "_PERP" not in symbol or "USDT" not in symbol:
                continue

            if base_asset in missing and base_asset not in symbols_map:
                symbols_map[base_asset] = symbol
                exchange = market.get("exchange", "?")
                print(f"  ⚠ {base_asset}: {symbol} (exchange suffix: .{exchange})")

    return symbols_map

def pull_oi_history(symbol, coin):
    """Pull open interest history for a symbol."""
    print(f"  Pulling OI history for {coin} ({symbol})...")

    all_rows = []
    current = DATE_START

    while current < DATE_END:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), DATE_END)

        params = {
            "symbols": symbol,
            "interval": "4hour",
            "from": int(current.timestamp()),  # seconds, not ms
            "to": int(chunk_end.timestamp())
        }

        data, status, error = make_request("/open-interest-history", params)

        if error:
            print(f"      ERROR: {error}", file=sys.stderr)
            break

        if not isinstance(data, list) or not data:
            print(f"      No data for {current.date()} to {chunk_end.date()}")
            current = chunk_end
            continue

        # Response is a list with one item: {symbol, history}
        rows = data[0].get("history", [])
        if not rows:
            print(f"      No rows for {current.date()} to {chunk_end.date()}")
            current = chunk_end
            continue

        all_rows.extend(rows)
        print(f"      ✓ {len(rows)} rows for {current.date()} to {chunk_end.date()}")
        current = chunk_end

    return all_rows

def pull_lsr_history(symbol, coin):
    """Pull long/short ratio history for a symbol."""
    print(f"  Pulling LSR history for {coin} ({symbol})...")

    all_rows = []
    current = DATE_START

    while current < DATE_END:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), DATE_END)

        params = {
            "symbols": symbol,
            "interval": "4hour",
            "from": int(current.timestamp()),  # seconds, not ms
            "to": int(chunk_end.timestamp())
        }

        data, status, error = make_request("/long-short-ratio-history", params)

        if error:
            print(f"      ERROR: {error}", file=sys.stderr)
            break

        if not isinstance(data, list) or not data:
            print(f"      No data for {current.date()} to {chunk_end.date()}")
            current = chunk_end
            continue

        # Response is a list with one item: {symbol, history}
        rows = data[0].get("history", [])
        if not rows:
            print(f"      No rows for {current.date()} to {chunk_end.date()}")
            current = chunk_end
            continue

        all_rows.extend(rows)
        print(f"      ✓ {len(rows)} rows for {current.date()} to {chunk_end.date()}")
        current = chunk_end

    return all_rows

def save_to_parquet(coin, dataset_type, rows):
    """Save rows to parquet file. Handle both OI and LSR schemas."""
    if not rows:
        print(f"    SKIPPED (no data): {coin}_{dataset_type}")
        return None

    # Inspect the first row to understand schema
    sample = rows[0]
    print(f"    Sample fields: {list(sample.keys())}")

    # Build dataframe
    # OI history: t (unix seconds), o, h, l, c  (OI value in base asset units)
    # LSR history: t (unix seconds), r (long/short ratio), l (long %), s (short %)

    df = pd.DataFrame(rows)

    # Ensure timestamp column (either 't' or 'timestamp')
    if 't' in df.columns:
        df['t'] = pd.to_numeric(df['t'], errors='coerce')
    elif 'timestamp' in df.columns:
        df['t'] = pd.to_numeric(df['timestamp'], errors='coerce')
        df = df.drop('timestamp', axis=1)

    # Sort by timestamp
    df = df.sort_values('t').reset_index(drop=True)

    # Save
    filename = CACHE_DIR / f"{coin}_{dataset_type}_4h.parquet"
    df.to_parquet(filename)

    # NOTE: Coinalyze /open-interest-history and /long-short-ratio-history both
    # return `t` in whole SECONDS (verified empirically 2026-07-04), not
    # milliseconds as originally assumed. Dividing by 1000 here previously
    # produced bogus 1970-epoch dates.
    earliest_ts = df['t'].min()
    latest_ts = df['t'].max()
    earliest_iso = datetime.fromtimestamp(earliest_ts).isoformat() if earliest_ts > 0 else "N/A"
    latest_iso = datetime.fromtimestamp(latest_ts).isoformat() if latest_ts > 0 else "N/A"

    info = {
        "file": str(filename.relative_to(VAULT_ROOT)),
        "coin": coin,
        "dataset": dataset_type,
        "rows": len(df),
        "earliest": earliest_iso,
        "latest": latest_iso,
        "schema": df.dtypes.to_dict()
    }

    print(f"    ✓ Saved {len(df)} rows to {filename.name}")
    print(f"      Range: {earliest_iso} to {latest_iso}")

    return info

def main():
    """Main entry point."""
    print("\n" + "="*70)
    print("COINALYZE DATA PULL — OI + Long/Short Ratio (4h, 2yr)")
    print("="*70)

    # Step 1: Get markets and find symbols
    symbols_map = get_future_markets()

    if not symbols_map:
        print("ERROR: No valid symbols found", file=sys.stderr)
        sys.exit(1)

    # Step 2: Pull data for each coin
    summary = []

    for coin in TARGET_COINS:
        if coin not in symbols_map:
            print(f"\n✗ {coin}: NO SYMBOL FOUND")
            summary.append({
                "coin": coin,
                "oi_dataset": "oi_4h",
                "oi_rows": 0,
                "oi_earliest": "N/A",
                "oi_latest": "N/A",
                "lsr_dataset": "lsr_4h",
                "lsr_rows": 0,
                "lsr_earliest": "N/A",
                "lsr_latest": "N/A"
            })
            continue

        symbol = symbols_map[coin]
        print(f"\n{'='*70}")
        print(f"{coin} ({symbol})")
        print(f"{'='*70}")

        # Pull OI history
        oi_rows = pull_oi_history(symbol, coin)
        oi_info = save_to_parquet(coin, "oi", oi_rows)

        # Pull LSR history
        lsr_rows = pull_lsr_history(symbol, coin)
        lsr_info = save_to_parquet(coin, "lsr", lsr_rows)

        # Track for summary
        summary.append({
            "coin": coin,
            "oi_dataset": "oi_4h",
            "oi_rows": oi_info["rows"] if oi_info else 0,
            "oi_earliest": oi_info["earliest"] if oi_info else "N/A",
            "oi_latest": oi_info["latest"] if oi_info else "N/A",
            "oi_schema": oi_info["schema"] if oi_info else {},
            "lsr_dataset": "lsr_4h",
            "lsr_rows": lsr_info["rows"] if lsr_info else 0,
            "lsr_earliest": lsr_info["earliest"] if lsr_info else "N/A",
            "lsr_latest": lsr_info["latest"] if lsr_info else "N/A",
            "lsr_schema": lsr_info["schema"] if lsr_info else {}
        })

    # Step 3: Generate report
    generate_report(summary, symbols_map)

    print("\n" + "="*70)
    print("✓ PULL COMPLETE")
    print("="*70)

def generate_report(summary, symbols_map):
    """Generate markdown report."""
    report_path = REPORTS_DIR / "coinalyze-data-pull.md"

    with open(report_path, 'w') as f:
        f.write("# Coinalyze Data Pull Report\n\n")
        f.write(f"**Date:** {datetime.now().isoformat()}\n")
        f.write(f"**Requested range:** {DATE_START.isoformat()} to {DATE_END.isoformat()}\n")
        f.write(f"**Interval:** 4 hours\n\n")
        f.write(
            "> Note: original Phase 2b plan assumed 2 years of history "
            "(from 2024-07-01). Empirically this API key's plan only serves "
            "~335 days of 4h OI/long-short-ratio history — requests before "
            "~2025-08-03 return an empty list (verified against both BTC and "
            "HYPE). `DATE_START` was pulled forward to 2025-08-01; actual "
            "earliest/latest coverage per dataset is in the summary table "
            "below.\n\n"
        )

        # Symbols used
        f.write("## Symbols Used\n\n")
        for coin, symbol in sorted(symbols_map.items()):
            f.write(f"- {coin}: `{symbol}`\n")

        missing = set(TARGET_COINS) - set(symbols_map.keys())
        if missing:
            f.write(f"\n⚠ Missing coins (no Binance USDT perp available): {', '.join(sorted(missing))}\n")

        # Summary table
        f.write("\n## Data Summary\n\n")
        f.write("| Coin | OI Dataset | OI Rows | OI Earliest | OI Latest | LSR Dataset | LSR Rows | LSR Earliest | LSR Latest |\n")
        f.write("|------|-----------|---------|------------|----------|-------------|---------|-------------|------------|\n")

        for row in summary:
            coin = row["coin"]
            f.write(f"| {coin} ")
            f.write(f"| {row['oi_dataset']} ")
            f.write(f"| {row['oi_rows']:,} ")
            f.write(f"| {row['oi_earliest']} ")
            f.write(f"| {row['oi_latest']} ")
            f.write(f"| {row['lsr_dataset']} ")
            f.write(f"| {row['lsr_rows']:,} ")
            f.write(f"| {row['lsr_earliest']} ")
            f.write(f"| {row['lsr_latest']} |\n")

        # Schema documentation
        f.write("\n## Schema Details\n\n")

        f.write("### Open Interest History (OI)\n\n")
        f.write("Observed fields: `t` (unix **seconds**, not ms), `o` (open), `h` (high), `l` (low), `c` (close), OI value in base-asset units\n\n")

        for row in summary:
            if row.get("oi_schema"):
                f.write(f"**{row['coin']} OI Schema:**\n```\n")
                for field, dtype in row["oi_schema"].items():
                    f.write(f"  {field}: {dtype}\n")
                f.write("```\n\n")

        f.write("### Long/Short Ratio History (LSR)\n\n")
        f.write("Observed fields: `t` (unix **seconds**, not ms), `r` (long/short ratio), `l` (long %), `s` (short %)\n\n")

        for row in summary:
            if row.get("lsr_schema"):
                f.write(f"**{row['coin']} LSR Schema:**\n```\n")
                for field, dtype in row["lsr_schema"].items():
                    f.write(f"  {field}: {dtype}\n")
                f.write("```\n\n")

        # Data files
        f.write("## Output Files\n\n")
        for row in summary:
            coin = row["coin"]
            if row["oi_rows"] > 0:
                f.write(f"- `data/cache/coinalyze/{coin}_oi_4h.parquet` ({row['oi_rows']:,} rows)\n")
            if row["lsr_rows"] > 0:
                f.write(f"- `data/cache/coinalyze/{coin}_lsr_4h.parquet` ({row['lsr_rows']:,} rows)\n")

    print(f"\n✓ Report saved to {report_path.relative_to(VAULT_ROOT)}")

if __name__ == "__main__":
    main()
