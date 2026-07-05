"""Resilience boundary: every REST call passes through `call()`, which forces
the call site to declare what the call IS (read/write, idempotent, critical)
so failure handling is structural, not remembered (engineering principle 5).

Failure taxonomy (principle 2):
- Transient (connection errors, timeouts, 5xx, 429): retried with backoff,
  but ONLY for reads and idempotent writes. A non-idempotent write that fails
  transiently may have landed — we raise immediately and the next reconcile
  tick re-derives desired state (self-healing by design, never blind retry).
- Semantic (4xx, Bitfinex ["error", code, msg] payloads): never retried.

Critical calls that fail log loudly before raising (principle 3).
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

import requests

log = logging.getLogger("compound.boundary")


class TransientError(Exception):
    pass


class SemanticError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CallSpec:
    name: str
    kind: str                # 'read' | 'write'
    idempotent: bool
    critical: bool = False

    def __post_init__(self):
        if self.kind not in ("read", "write"):
            raise ValueError("CallSpec.kind must be read|write: %r" % (self,))


MAX_RETRIES = 4
BACKOFF_5XX = 2.0      # seconds, doubles each retry
BACKOFF_429 = 60.0   # documented rate-limit block lasts 60s; retrying sooner extends it


def _classify(status, payload):
    """Return ('ok'|'transient'|'semantic', detail)."""
    if isinstance(payload, dict) and "error" in payload:
        # documented rate-limit body: {"error": "ERR_RATE_LIMIT"} (api ref §5)
        err = str(payload.get("error", ""))
        if "RATE_LIMIT" in err.upper():
            return "transient", "ratelimit body %s" % err
        return "semantic", "error body %r" % (payload,)
    if isinstance(payload, list) and payload[:1] == ["error"]:
        code = payload[1] if len(payload) > 1 else None
        msg = payload[2] if len(payload) > 2 else ""
        if status == 429 or code == 11010:      # ratelimit
            return "transient", "ratelimit code=%s %s" % (code, msg)
        return "semantic", "code=%s %s" % (code, msg)
    if status == 429:
        return "transient", "HTTP 429"
    if 500 <= status <= 599:
        return "transient", "HTTP %d" % status
    if 400 <= status <= 499:
        return "semantic", "HTTP %d: %r" % (status, payload)
    return "ok", None


def call(spec, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) -> (status, payload) under spec's policy.
    Returns payload on success; raises TransientError/SemanticError."""
    sleep = kwargs.pop("_sleep", time.sleep)   # injectable for tests
    retryable = spec.kind == "read" or spec.idempotent
    attempts = MAX_RETRIES + 1 if retryable else 1
    last_err = None

    for attempt in range(attempts):
        try:
            status, payload = fn(*args, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_err, backoff = "connection: %s" % exc, BACKOFF_5XX
        else:
            verdict, detail = _classify(status, payload)
            if verdict == "ok":
                return payload
            if verdict == "semantic":
                err = SemanticError("%s failed (semantic, no retry): %s"
                                    % (spec.name, detail))
                if spec.critical:
                    log.error("CRITICAL call failed: %s — %s", spec.name, detail)
                raise err
            last_err = detail
            backoff = BACKOFF_429 if "429" in detail or "ratelimit" in detail \
                else BACKOFF_5XX

        if attempt < attempts - 1:
            delay = backoff * (2 ** attempt) * (1.0 + 0.2 * random.random())
            log.warning("%s transient (%s), retry %d/%d in %.1fs",
                        spec.name, last_err, attempt + 1, attempts - 1, delay)
            sleep(delay)

    suffix = "" if retryable else " — non-idempotent write MAY HAVE LANDED; reconcile before retrying"
    err = TransientError("%s failed (transient): %s%s" % (spec.name, last_err, suffix))
    if spec.critical:
        log.error("CRITICAL call failed: %s — %s%s", spec.name, last_err, suffix)
    raise err
