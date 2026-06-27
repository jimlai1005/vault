"""Official Hyperliquid info API client. Reads only; routed through resilient_read."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"


def _post(body: dict) -> object:
    def call():
        req = urllib.request.Request(
            INFO_URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    return resilient_read(call)


class HLApiFillSource:
    def get_fills(self, address: str, start=None, end=None) -> list[dict]:
        body: dict = {"type": "userFillsByTime", "user": address, "startTime": start or 0}
        if end is not None:
            body["endTime"] = end
        return _post(body)  # type: ignore[return-value]


def get_leaderboard() -> list[dict]:
    return _post({"type": "leaderboard"})  # type: ignore[return-value]
