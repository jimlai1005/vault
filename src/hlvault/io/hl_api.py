"""Official Hyperliquid info API client. Reads only; routed through resilient_read."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


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
    """Public-API fill source. Each call returns <=2000 fills; full history is
    obtained by paginating `start` forward. NOTE: for high-frequency traders
    this is rate-limit-impractical for 6-12mo of history — the S3 archive
    (requester-pays, needs AWS creds) is the production source. See spec."""

    PAGE = 2000

    def get_fills(self, address: str, start=None, end=None) -> list[dict]:
        body: dict = {"type": "userFillsByTime", "user": address, "startTime": start or 0}
        if end is not None:
            body["endTime"] = end
        return _post(body)  # type: ignore[return-value]

    def get_fills_paginated(self, address: str, start: int, end=None,
                            max_pages: int = 50) -> list[dict]:
        """Paginate forward until a short page or max_pages (rate-limit guard)."""
        out: list[dict] = []
        cursor = start
        for _ in range(max_pages):
            page = self.get_fills(address, start=cursor, end=end)
            if not page:
                break
            out.extend(page)
            if len(page) < self.PAGE:
                break
            cursor = page[-1]["time"] + 1
        return out


def get_leaderboard() -> list[dict]:
    """Fetch the public leaderboard (large JSON). Returns leaderboardRows."""

    def call():
        req = urllib.request.Request(LEADERBOARD_URL)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return json.loads(r.read()).get("leaderboardRows", [])
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    return resilient_read(call)
