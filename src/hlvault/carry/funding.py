"""Trailing funding signal. Shorts RECEIVE funding when the rate is
positive; the engine holds the carry while trailing funding stays positive
and unwinds when it turns negative (low turnover by design — the naive
daily-rotation variant lost to fees in research)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from hlvault.io.source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"
HOURS_PER_YEAR = 24 * 365


def _fetch_funding(coin: str, start_ms: int) -> list[dict]:
    body = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}

    def call():
        req = urllib.request.Request(INFO_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    return resilient_read(call, max_attempts=6, base_delay=1.0)


def trailing_funding_apr(coin: str, days: float) -> float:
    start = int(time.time() * 1000) - int(days * 86400 * 1000)
    rows = _fetch_funding(coin, start)
    if not rows:
        return 0.0
    rates = [float(r["fundingRate"]) for r in rows]
    return sum(rates) / len(rates) * HOURS_PER_YEAR


def funding_ok(apr: float, exit_apr: float) -> bool:
    return apr > exit_apr
