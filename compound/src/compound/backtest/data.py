"""Load candle CSVs produced by scripts/fetch_history.py."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True)
class Bar:
    mts: int          # bar open time, ms epoch
    open: float       # daily rate decimals (all OHLC)
    close: float
    high: float
    low: float
    volume: float
    # 30d-period market (daily granularity, broadcast onto hourly bars).
    # None = no 30d trades that day -> long offers cannot fill.
    high30: Optional[float] = None
    vol30: Optional[float] = None     # daily p30 volume / 24, per-hour share


def load_bars(csv_path, start_iso=None, end_iso=None):
    """Read a candles CSV (timestamp_ms,date_iso,open,close,high,low,volume),
    ascending by time. Optional ISO-prefix date filters (inclusive start,
    exclusive end)."""
    bars: List[Bar] = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            date = row["date_iso"]
            if start_iso and date < start_iso:
                continue
            if end_iso and date >= end_iso:
                continue
            bars.append(
                Bar(
                    mts=int(row["timestamp_ms"]),
                    open=float(row["open"]),
                    close=float(row["close"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    volume=float(row["volume"]),
                )
            )
    bars.sort(key=lambda b: b.mts)
    if not bars:
        raise ValueError("no bars loaded from %s (filters %r..%r)" % (csv_path, start_iso, end_iso))
    return bars


def hourly_bars(start_iso=None, end_iso=None):
    return load_bars(DATA_DIR / "candles_1h_p2.csv", start_iso, end_iso)


def hourly_bars_dual(start_iso=None, end_iso=None):
    """Hourly 2d-period bars enriched with the 30d-period market for pricing
    and filling long offers.

    Look-ahead honesty: each hourly bar carries the PREVIOUS UTC day's p30
    candle. Broadcasting the same day's candle would let an offer placed at
    hour h fill against that day's full-day high — including trades that
    happen after h (review finding). Using yesterday's candle makes long
    fills strictly causal at the cost of one day of staleness (conservative:
    spikes reach the long book with a lag)."""
    from datetime import datetime, timedelta, timezone

    day30 = {}
    with open(DATA_DIR / "candles_1D_p30.csv", newline="") as f:
        for row in csv.DictReader(f):
            day30[row["date_iso"][:10]] = (
                float(row["high"]),
                float(row["volume"]) / 24.0,
            )
    out = []
    for b in hourly_bars(start_iso, end_iso):
        dt = datetime.fromtimestamp(b.mts / 1000, tz=timezone.utc)
        prev_day = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        h30, v30 = day30.get(prev_day, (None, None))
        out.append(Bar(mts=b.mts, open=b.open, close=b.close, high=b.high,
                       low=b.low, volume=b.volume, high30=h30, vol30=v30))
    return out


def daily_bars(start_iso=None, end_iso=None):
    return load_bars(DATA_DIR / "candles_1D_p2.csv", start_iso, end_iso)
