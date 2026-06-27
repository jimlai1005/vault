"""BTC/ETH daily returns for the alpha/beta factor regression and the BTC
benchmark, from the public candleSnapshot endpoint."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pandas as pd

from .io.source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"


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
    body = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end_ms},
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
            if e.code >= 500:
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    return candles_to_returns(resilient_read(call))
