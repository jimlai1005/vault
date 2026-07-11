#!/usr/bin/env python3
"""Pull full 1m OHLCV history from Binance for scalp shortlist (sub-project H).

Reads shortlist.json, maps each coin to its Binance USDT-perp symbol,
fetches 1m bars from max(earliest, now - 730 days) to now, checks for gaps,
and saves to data/scalp/<COIN>_1m.csv.gz.
"""
import sys
import json
import argparse
from datetime import datetime, timedelta
import pandas as pd

sys.path.insert(0, 'scripts')
import scalp_lib as s


def load_shortlist(path: str = "data/scalp/shortlist.json") -> list:
    """Load shortlist.json: list of {coin, binance_symbol} dicts."""
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Pull Binance 1m history for scalp shortlist"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke test: only first coin, recent 2 days"
    )
    args = parser.parse_args()

    shortlist = load_shortlist()
    if args.smoke:
        shortlist = shortlist[:1]

    for item in shortlist:
        coin = item["coin"]
        binance_symbol = item["binance_symbol"]

        # Find earliest available bar timestamp
        earliest_ms = s.binance_earliest_1m(binance_symbol)
        if earliest_ms is None:
            print(f"{coin}: No data found on Binance")
            continue

        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)

        if args.smoke:
            # Smoke test: fetch last 2 days
            start_ms = now_ms - 2 * 24 * 60 * s.BAR_MS
            end_ms = now_ms
        else:
            # Full pull: from max(earliest, now - 730 days) to now
            floor_ms = int((
                pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=730)
            ).timestamp() * 1000)
            start_ms = max(earliest_ms, floor_ms)
            end_ms = now_ms

        # Pull 1m history
        df = s.pull_binance_1m(binance_symbol, start_ms, end_ms)

        if df.empty:
            print(f"{coin}: No data fetched for time range")
            continue

        # Check for gaps: consecutive bars should differ by exactly BAR_MS (60_000 ms)
        diffs = df["t"].diff().dropna()
        gaps = diffs[diffs > s.BAR_MS]
        gap_count = len(gaps)
        max_gap_ms = gaps.max() if len(gaps) > 0 else 0

        # Save to CSV
        path = s.save_df(df, f"{coin}_1m")

        # Summary line
        first_ts = df["ts"].iloc[0]
        last_ts = df["ts"].iloc[-1]
        bar_count = len(df)

        warn_suffix = " WARN: gap_count > 50" if gap_count > 50 else ""
        print(
            f"{coin}: {bar_count} bars, {first_ts}, {last_ts}, "
            f"gap_count={gap_count}{warn_suffix}"
        )


if __name__ == "__main__":
    main()
