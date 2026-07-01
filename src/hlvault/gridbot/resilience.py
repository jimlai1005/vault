"""Single IO resilience boundary for all exchange writes (CLAUDE.md #5).
Adapted from hl-copytrader/src/resilience.py — same classification rules:
transient vs semantic (#2), only idempotent/verified writes retry."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.6

VERIFIED_OK = {"status": "ok", "_resilience": "verified"}

_TRANSIENT_MARKERS = (
    "connection reset", "connection aborted", "connection broken",
    "remote end closed", "timed out", "timeout", "max retries",
    "temporarily unavailable", "bad gateway", "service unavailable",
    "502", "503", "504",
)


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def run(fn, *, what, idempotent, verify=None, attempts=None, base_delay=RETRY_BASE_DELAY):
    """idempotent=True (reduce-only / cancel) -> retry transient errors directly.
    idempotent=False + verify given -> on a transient error, verify() whether the
    write actually landed before deciding to retry (never blind-retry a possibly-
    landed non-idempotent write). Semantic errors always raise immediately."""
    can_retry = idempotent or (verify is not None)
    if attempts is None:
        attempts = RETRY_ATTEMPTS if can_retry else 1
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            if not _is_transient_error(e) or i == attempts or not can_retry:
                raise
            if not idempotent:
                try:
                    landed = verify()
                except Exception:
                    landed = True  # can't tell -> assume landed, never double-place
                if landed:
                    logger.warning(f"{what}: transient error but verified landed, not resending")
                    return VERIFIED_OK
            delay = base_delay * (2 ** (i - 1))
            logger.warning(f"{what}: transient error (attempt {i}/{attempts}), retrying in {delay:.1f}s: {e}")
            time.sleep(delay)
    raise RuntimeError("resilience.run exited loop unexpectedly")  # pragma: no cover


class ResilientExchange:
    """Wraps the SDK Exchange; Trader/live engine only ever holds this."""

    def __init__(self, exchange):
        self._ex = exchange

    def market_close(self, *a, **k):
        return run(lambda: self._ex.market_close(*a, **k), what="market_close", idempotent=True)

    def update_leverage(self, *a, **k):
        return run(lambda: self._ex.update_leverage(*a, **k), what="update_leverage", idempotent=True)

    def cancel(self, *a, **k):
        return run(lambda: self._ex.cancel(*a, **k), what="cancel", idempotent=True)

    def order(self, *a, reduce_only=False, _verify=None, **k):
        idem = bool(reduce_only)
        return run(lambda: self._ex.order(*a, reduce_only=reduce_only, **k),
                   what="order", idempotent=idem, verify=(None if idem else _verify))
