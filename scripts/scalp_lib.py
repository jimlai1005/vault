"""Shared data utilities for sub-project H (scalping research).
Source: Hyperliquid /info REST (public, read-only). candleSnapshot ~5000 bars/req."""
import time
from typing import Optional
import pandas as pd
import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
SLEEP = 0.5          # pacing, well under info-endpoint rate limits
BAR_MS = 60_000
DATA_DIR = "data/scalp"

def info(payload: dict, retries: int = 5):
    """POST to Hyperliquid /info endpoint with retry on 429/5xx."""
    for i in range(retries):
        r = requests.post(INFO_URL, json=payload, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** i)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"info failed after {retries} tries: {payload.get('type')}")

def get_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch candleSnapshot bars for a coin in given time range."""
    return info({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": interval,
        "startTime": start_ms, "endTime": end_ms}})

def candles_to_df(rows: list) -> pd.DataFrame:
    """Convert raw candle list to DataFrame with UTC timestamps and dedupe."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64")
    df["n"] = df["n"].astype(int)
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df

def pull_1m_history(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paged pull, 5000-bar windows; jumps over empty windows (pre-listing gaps)."""
    rows, cur = [], start_ms
    while cur < end_ms:
        win_end = min(cur + 5000 * BAR_MS, end_ms)
        batch = get_candles(coin, "1m", cur, win_end)
        time.sleep(SLEEP)
        if not batch:
            cur = win_end
            continue
        rows.extend(batch)
        last_t = max(int(b["t"]) for b in batch)
        cur = max(last_t + BAR_MS, cur + BAR_MS)
    return candles_to_df(rows)

def find_earliest_1m(coin: str, floor: str = "2023-01-01") -> Optional[int]:
    """30-day window probe; then backward refine (do not assume server returns
    range-earliest first when >5000 bars in range)."""
    cur = int(pd.Timestamp(floor, tz="UTC").timestamp() * 1000)
    now = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    while cur < now:
        batch = get_candles(coin, "1m", cur, cur + 30 * 24 * 60 * BAR_MS)
        time.sleep(SLEEP)
        if batch:
            first_t = int(batch[0]["t"])
            while True:
                probe = get_candles(coin, "1m", cur, first_t - 1)
                time.sleep(SLEEP)
                if not probe:
                    return first_t
                first_t = int(probe[0]["t"])
        cur += 30 * 24 * 60 * BAR_MS
    return None

def universe_ctxs() -> pd.DataFrame:
    """One row per perp: name, dayNtlVlm, markPx, midPx, funding, openInterest, impact_bid, impact_ask."""
    meta, ctxs = info({"type": "metaAndAssetCtxs"})
    rows = []
    for m, c in zip(meta["universe"], ctxs):
        impact = c.get("impactPxs") or [None, None]
        rows.append({"name": m["name"], "szDecimals": m["szDecimals"],
                     "dayNtlVlm": float(c["dayNtlVlm"]), "markPx": float(c["markPx"]),
                     "midPx": float(c["midPx"]) if c.get("midPx") else None,
                     "funding": float(c["funding"]), "openInterest": float(c["openInterest"]),
                     "impact_bid": float(impact[0]) if impact[0] else None,
                     "impact_ask": float(impact[1]) if impact[1] else None})
    return pd.DataFrame(rows)

def l2_spread_bps(coin: str) -> Optional[float]:
    """Get L2 bid-ask spread in bps."""
    book = info({"type": "l2Book", "coin": coin})
    bids, asks = book["levels"][0], book["levels"][1]
    if not bids or not asks:
        return None
    bb, ba = float(bids[0]["px"]), float(asks[0]["px"])
    return (ba - bb) / ((ba + bb) / 2) * 1e4

def save_df(df: pd.DataFrame, name: str) -> str:
    """Save DataFrame to compressed CSV in DATA_DIR."""
    path = f"{DATA_DIR}/{name}.csv.gz"
    df.to_csv(path, index=False, compression="gzip")
    return path

def load_df(name: str) -> pd.DataFrame:
    """Load compressed CSV from DATA_DIR."""
    return pd.read_csv(f"{DATA_DIR}/{name}.csv.gz")


# Binance 1m proxy layer (Task 1b)

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
BINANCE_SLEEP = 0.25
# HL coin -> Binance USDT-perp symbol; None-able lookup via binance_symbol()
BINANCE_SYMBOL_OVERRIDES = {
    "kPEPE": "1000PEPEUSDT", "kBONK": "1000BONKUSDT", "kSHIB": "1000SHIBUSDT",
    "kFLOKI": "1000FLOKIUSDT", "kLUNC": "1000LUNCUSDT",
}

def binance_perp_symbols() -> set:
    """Fetch all active perpetual symbols from Binance FAPI."""
    info_ = requests.get(f"{BINANCE_FAPI}/exchangeInfo", timeout=20).json()
    return {s["symbol"] for s in info_["symbols"]
            if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"}

def binance_symbol(coin: str, available: set) -> Optional[str]:
    """Map HL coin to Binance USDT-perp symbol, or None if not available."""
    sym = BINANCE_SYMBOL_OVERRIDES.get(coin, f"{coin}USDT")
    return sym if sym in available else None

def binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                   limit: int = 1500, retries: int = 5) -> list:
    """Fetch klines from Binance FAPI with retry on 429/5xx."""
    for i in range(retries):
        r = requests.get(f"{BINANCE_FAPI}/klines", timeout=20, params={
            "symbol": symbol, "interval": interval,
            "startTime": start_ms, "endTime": end_ms, "limit": limit})
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** i)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"binance klines failed: {symbol}")

def binance_rows_to_df(rows: list) -> pd.DataFrame:
    """Map Binance klines to the SAME schema as candles_to_df: t,o,h,l,c,v,n,ts."""
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "T", "qv", "n",
                                     "tb", "tq", "ig"])[["t", "o", "h", "l", "c", "v", "n"]]
    if df.empty:
        return df
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64")
    df["n"] = df["n"].astype(int)
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df

def binance_earliest_1m(symbol: str) -> Optional[int]:
    """Probe for earliest 1m bar timestamp on Binance for given symbol."""
    rows = binance_klines(symbol, "1m", 1, int(pd.Timestamp.now(tz="UTC").timestamp() * 1000), limit=1)
    time.sleep(BINANCE_SLEEP)
    return int(rows[0][0]) if rows else None

def pull_binance_1m(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paged pull of 1m klines from Binance FAPI, 1500-bar windows."""
    rows, cur = [], start_ms
    while cur < end_ms:
        batch = binance_klines(symbol, "1m", cur, end_ms, limit=1500)
        time.sleep(BINANCE_SLEEP)
        if not batch:
            break
        rows.extend(batch)
        cur = int(batch[-1][0]) + BAR_MS
        if len(batch) < 1500 and cur >= end_ms - BAR_MS:
            break
    return binance_rows_to_df(rows)
