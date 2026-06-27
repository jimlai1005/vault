"""Single resilience boundary. Every external read passes through here and
must classify failures: transient (retry w/ backoff) vs semantic (surface).
All reads here are idempotent (CLAUDE.md #2/#5 — no non-idempotent writes)."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class TransientError(Exception):
    """Connection reset/timeout/5xx — safe to retry (idempotent read)."""


class SemanticError(Exception):
    """Bad input/4xx — do NOT retry; surface."""


def resilient_read(
    fn: Callable[[], T], *, max_attempts: int = 5, base_delay: float = 0.5
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except SemanticError:
            raise
        except TransientError:
            if attempt == max_attempts:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")
