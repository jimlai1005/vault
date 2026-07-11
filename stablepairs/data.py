"""Data layer: fetch OHLCV via ccxt, cache to parquet.

Runs on YOUR machine (needs internet). ccxt unifies binance / okx / bybit /
hyperliquid, so switching venue is a one-line config change.
"""
import os
import time
import pandas as pd
import ccxt


def make_exchange(name: str):
    klass = getattr(ccxt, name)
    return klass({"enableRateLimit": True})


def fetch_ohlcv(symbol: str, timeframe: str, since_ms: int,
                exchange: str = "binance", limit: int = 1000) -> pd.DataFrame:
    """Paginated OHLCV pull from `since_ms` to now."""
    ex = make_exchange(exchange)
    ms_per = ex.parse_timeframe(timeframe) * 1000
    rows, cursor = [], since_ms
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
        if not batch:
            break
        rows += batch
        cursor = batch[-1][0] + ms_per
        if len(batch) < limit:
            break
        time.sleep(ex.rateLimit / 1000.0)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts")
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume"]]


def load_series(symbol: str, cfg) -> pd.DataFrame:
    """Cached loader: returns OHLCV DataFrame for `symbol`."""
    os.makedirs(cfg.cache_dir, exist_ok=True)
    safe = symbol.replace("/", "_")
    path = os.path.join(cfg.cache_dir, f"{cfg.exchange}_{safe}_{cfg.timeframe}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    since = int((pd.Timestamp.utcnow() - pd.Timedelta(days=cfg.lookback_days)).timestamp() * 1000)
    df = fetch_ohlcv(symbol, cfg.timeframe, since, cfg.exchange)
    df.to_parquet(path)
    return df
