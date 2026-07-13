"""B1-universe candidate data pull — thin wrapper around cta_proxy_pull_data.py.

Motivation: owner needs a ~6-coin live universe for the new B1 instance.
Existing proxy-research universe (data/cache/cta_proxy/) covers
BTC/ETH/SOL/DOGE/XRP (+HYPE, excluded from multi-year work). This script pulls
the SAME Binance USDT-M futures klines (4h/1d) + funding-rate history for 7
new candidates that already cleared the listing/liquidity hard screen:
BNBUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, BCHUSDT, LTCUSDT, DOTUSDT.

Does NOT modify scripts/cta_proxy_pull_data.py — imports and reuses its
pull_klines()/pull_funding()/probe_oi() functions verbatim (identical
pagination, retry, and dtype handling as the original 5/6-coin pull), only
substituting the SYMBOLS list. Writes parquet files in the exact same format
to the same data/cache/cta_proxy/ directory (so cta_proxy_lib.load_klines/
load_funding pick them up unmodified), plus a SEPARATE summary json
(`_pull_summary_b1_candidates.json`) so the original `_pull_summary.json` is
left untouched.

Binance public API only, no key, no .env access. Read-only pull -> parquet.

Usage: .venv/bin/python scripts/research_cta_b1_universe_pull.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "cta_proxy_pull_data", _SCRIPTS / "cta_proxy_pull_data.py")
ppd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppd)

CACHE_DIR = ppd.CACHE_DIR

CANDIDATES = ["BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "BCHUSDT",
              "LTCUSDT", "DOTUSDT"]


def main() -> None:
    summary = []
    for sym in CANDIDATES:
        print(f"\n=== {sym} ===")
        for interval, tag in (("4h", "4h"), ("1d", "1d")):
            df = ppd.pull_klines(sym, interval)
            path = CACHE_DIR / f"{sym}_{tag}.parquet"
            df.to_parquet(path)
            if len(df):
                t0 = pd.to_datetime(df["open_time"].iloc[0], unit="ms")
                t1 = pd.to_datetime(df["open_time"].iloc[-1], unit="ms")
                print(f"  klines {tag}: {len(df):5d} bars  [{t0:%Y-%m-%d} .. {t1:%Y-%m-%d}]  -> {path.name}")
            else:
                print(f"  klines {tag}: NO DATA")

        fdf = ppd.pull_funding(sym)
        fpath = CACHE_DIR / f"{sym}_funding.parquet"
        fdf.to_parquet(fpath)
        if len(fdf):
            t0 = pd.to_datetime(fdf["fundingTime"].iloc[0], unit="ms")
            t1 = pd.to_datetime(fdf["fundingTime"].iloc[-1], unit="ms")
            print(f"  funding : {len(fdf):5d} events [{t0:%Y-%m-%d} .. {t1:%Y-%m-%d}] -> {fpath.name}")
        else:
            print("  funding : NO DATA")

        oi_diag = ppd.probe_oi(sym)
        print(f"  OI (diagnostic, expect ~30d cap): {oi_diag}")

        k4h = pd.read_parquet(CACHE_DIR / f"{sym}_4h.parquet")
        summary.append({
            "symbol": sym,
            "klines_4h_bars": len(k4h),
            "klines_4h_start": str(pd.to_datetime(k4h["open_time"].iloc[0], unit="ms")) if len(k4h) else None,
            "klines_4h_end": str(pd.to_datetime(k4h["open_time"].iloc[-1], unit="ms")) if len(k4h) else None,
            "funding_events": len(fdf),
            "funding_start": str(pd.to_datetime(fdf["fundingTime"].iloc[0], unit="ms").date()) if len(fdf) else None,
            "oi_diag": oi_diag,
        })

    summary_path = CACHE_DIR / "_pull_summary_b1_candidates.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSummary -> {summary_path}")


if __name__ == "__main__":
    main()
