"""Telegram alerting for safety-critical events (CLAUDE.md #3 — never fail
silently). A notification failure must never raise into the caller — the
caller's safety action (flatten/halt) must proceed regardless of whether the
alert itself was deliverable."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from hlvault.io.source import TransientError, resilient_read

logger = logging.getLogger("notify.telegram")


def send_alert(bot_token: str, chat_id: str, message: str) -> bool:
    if not bot_token or not chat_id:
        logger.warning(f"Telegram not configured, alert dropped: {message}")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": message}).encode()

    def call():
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return True
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise TransientError(str(e))
            logger.error(f"Telegram send failed (semantic, not retried): {e}")
            return False
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    try:
        return bool(resilient_read(call, max_attempts=3, base_delay=1.0))
    except Exception as e:
        logger.error(f"Telegram send failed after retries: {e}")
        return False
