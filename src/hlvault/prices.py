"""BTC/ETH daily returns for the alpha/beta factor regression and the BTC
benchmark, plus raw OHLC candles for callers that need more than
close-to-close returns (e.g. multi-asset momentum signals) — all from the
public candleSnapshot endpoint, through the shared resilience boundary."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pandas as pd

from .io.source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"


def _fetch_candles_raw(coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    body = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
    }

    def call():
        req = urllib.request.Request(
            INFO_URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:   # 429 = rate limit -> retry (CLAUDE.md #2)
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    return resilient_read(call, max_attempts=6, base_delay=2.0)


def candles_to_returns(candles: list[dict]) -> pd.Series:
    """Daily close-to-close returns, indexed by normalized day."""
    if not candles:
        return pd.Series(dtype=float)
    df = pd.DataFrame(candles)
    df["day"] = pd.to_datetime(df["t"].astype("int64"), unit="ms").dt.normalize()
    df["close"] = pd.to_numeric(df["c"])
    df = df.sort_values("day").set_index("day")
    return df["close"].pct_change().dropna().rename("ret")


def get_daily_returns(coin: str, start_ms: int, end_ms: int) -> pd.Series:
    candles = _fetch_candles_raw(coin, "1d", start_ms, end_ms)
    return candles_to_returns(candles)


def get_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Raw OHLC frame (columns: day, o, h, l, c), ascending by day."""
    candles = _fetch_candles_raw(coin, interval, start_ms, end_ms)
    if not candles:
        return pd.DataFrame(columns=["day", "o", "h", "l", "c"])
    df = pd.DataFrame(candles)
    df["day"] = pd.to_datetime(df["t"].astype("int64"), unit="ms").dt.normalize()
    for col in ("o", "h", "l", "c"):
        df[col] = pd.to_numeric(df[col])
    return df.sort_values("day")[["day", "o", "h", "l", "c"]].reset_index(drop=True)
