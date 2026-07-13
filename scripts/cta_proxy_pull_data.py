"""Layer-2b proxy data pull — Binance PUBLIC, FREE, no-key endpoints only.

Read-only research. Pulls, for each symbol:
  - USDT-M futures klines (4h, 1d), paginated from the symbol's actual listing
    date to now (fapi/v1/klines) — years of depth, this is NOT the binding
    constraint.
  - Funding-rate history, paginated from listing to now (fapi/v1/fundingRate)
    — this is the multi-year CROWD-PROXY source (funding rate has been
    published since each symbol's futures listing; no ~30d cap like the
    "data" statistics endpoints below).
  - Open-interest history (futures/data/openInterestHist), best-effort/
    diagnostic only — Binance hard-caps this endpoint's retrievable window
    to ~30 days regardless of startTime (confirmed empirically below and in
    reports/cta-data-feasibility.md / vault CLAUDE.md). This means OI cannot
    be the multi-year fuel proxy; the multi-year study instead reuses
    Phase-2a's already-validated volume-based fuel proxy (24h quote-volume
    sum vs prior 24h), computed straight from the klines we already have.

No API key used anywhere. No .env files touched. Does not modify
src/hlvault/cta/. Writes only to data/cache/cta_proxy/.

Usage: .venv/bin/python scripts/cta_proxy_pull_data.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

VAULT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = VAULT_ROOT / "data" / "cache" / "cta_proxy"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://fapi.binance.com"
TIMEOUT = 20
MAX_RETRIES = 4
SLEEP_BETWEEN_CALLS = 0.25          # be polite; Binance public weight limits are generous

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "HYPEUSDT"]
# Earliest plausible start per symbol (a few days before actual listing is fine;
# Binance simply returns data from the true listing date onward). BTC futures
# launched 2019-09-08; using 2019-01-01 (ms) as a safe universal floor.
EARLIEST_MS = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
NOW_MS = int(datetime.now(timezone.utc).timestamp() * 1000)


def _get(path: str, params: dict) -> list | dict:
    import urllib.parse
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cta-proxy-research/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = 2 ** attempt
                print(f"    HTTP {e.code}, retry in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                last_err = e
                continue
            raise
        except urllib.error.URLError as e:
            wait = 2 ** attempt
            print(f"    URLError {e.reason}, retry in {wait}s...", file=sys.stderr)
            time.sleep(wait)
            last_err = e
            continue
    raise RuntimeError(f"max retries exceeded for {url}: {last_err}")


def pull_klines(symbol: str, interval: str) -> pd.DataFrame:
    rows = []
    start = EARLIEST_MS
    while start < NOW_MS:
        data = _get("/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "startTime": start, "limit": 1500,
        })
        time.sleep(SLEEP_BETWEEN_CALLS)
        if not data:
            break
        rows.extend(data)
        last_open = data[-1][0]
        if last_open <= start:      # safety against infinite loop
            break
        start = last_open + 1
        if len(data) < 1500:
            break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "n_trades", "taker_base", "taker_quote", "ignore",
    ])
    df = df[["open_time", "open", "high", "low", "close", "quote_volume", "close_time"]].copy()
    for c in ("open", "high", "low", "close", "quote_volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    df["close_time"] = df["close_time"].astype("int64")
    df = df.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
    return df


def pull_funding(symbol: str) -> pd.DataFrame:
    rows = []
    start = EARLIEST_MS
    while start < NOW_MS:
        data = _get("/fapi/v1/fundingRate", {
            "symbol": symbol, "startTime": start, "limit": 1000,
        })
        time.sleep(SLEEP_BETWEEN_CALLS)
        if not data:
            break
        rows.extend(data)
        last_t = data[-1]["fundingTime"]
        if last_t <= start:
            break
        start = last_t + 1
        if len(data) < 1000:
            break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)[["fundingTime", "fundingRate"]].copy()
    df["fundingTime"] = df["fundingTime"].astype("int64")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.drop_duplicates(subset="fundingTime").sort_values("fundingTime").reset_index(drop=True)
    return df


def probe_oi(symbol: str) -> dict:
    """Diagnostic only — confirms/documents the ~30d hard cap. Not used by the
    multi-year study (fuel proxy there is volume-based, see module docstring)."""
    try:
        data = _get("/futures/data/openInterestHist", {
            "symbol": symbol, "period": "4h", "limit": 500,
        })
        time.sleep(SLEEP_BETWEEN_CALLS)
        if not data:
            return {"rows": 0}
        first_ts = data[0]["timestamp"] / 1000
        last_ts = data[-1]["timestamp"] / 1000
        return {
            "rows": len(data),
            "earliest": datetime.utcfromtimestamp(first_ts).strftime("%Y-%m-%d %H:%M"),
            "latest": datetime.utcfromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        return {"rows": 0, "error": str(e)}


def main() -> None:
    summary = []
    for sym in SYMBOLS:
        print(f"\n=== {sym} ===")
        for interval, tag in (("4h", "4h"), ("1d", "1d")):
            df = pull_klines(sym, interval)
            path = CACHE_DIR / f"{sym}_{tag}.parquet"
            df.to_parquet(path)
            if len(df):
                t0 = pd.to_datetime(df["open_time"].iloc[0], unit="ms")
                t1 = pd.to_datetime(df["open_time"].iloc[-1], unit="ms")
                print(f"  klines {tag}: {len(df):5d} bars  [{t0:%Y-%m-%d} .. {t1:%Y-%m-%d}]  -> {path.name}")
            else:
                print(f"  klines {tag}: NO DATA")

        fdf = pull_funding(sym)
        fpath = CACHE_DIR / f"{sym}_funding.parquet"
        fdf.to_parquet(fpath)
        if len(fdf):
            t0 = pd.to_datetime(fdf["fundingTime"].iloc[0], unit="ms")
            t1 = pd.to_datetime(fdf["fundingTime"].iloc[-1], unit="ms")
            print(f"  funding : {len(fdf):5d} events [{t0:%Y-%m-%d} .. {t1:%Y-%m-%d}] -> {fpath.name}")
        else:
            print("  funding : NO DATA")

        oi_diag = probe_oi(sym)
        print(f"  OI (diagnostic, expect ~30d cap): {oi_diag}")

        summary.append({
            "symbol": sym,
            "klines_4h_bars": len(pd.read_parquet(CACHE_DIR / f'{sym}_4h.parquet')),
            "funding_events": len(fdf),
            "funding_start": str(pd.to_datetime(fdf['fundingTime'].iloc[0], unit='ms').date()) if len(fdf) else None,
            "oi_diag": oi_diag,
        })

    summary_path = CACHE_DIR / "_pull_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSummary -> {summary_path}")


if __name__ == "__main__":
    main()
