"""HTTP transport + v2 request signing. The ONLY module that touches the network.

Signing (api reference §1): signature = HMAC-SHA384 hex of
"/api/v2/{endpoint}{nonce}{rawBody}". The exact bytes that are signed MUST be
the bytes sent — we serialize once and pass that string as the request data.
Nonce: microseconds, strictly increasing (lock-guarded for thread safety).

No retries and no error classification here — that's boundary.py's job.
Returns (status_code, parsed_json_or_None).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time

import requests

PUB_BASE = "https://api-pub.bitfinex.com/v2/"
AUTH_BASE = "https://api.bitfinex.com/v2/"


class Transport:
    def __init__(self, api_key="", api_secret="", timeout=30.0):
        self._key = api_key
        self._secret = api_secret
        self._timeout = timeout
        self._session = requests.Session()
        self._nonce_lock = threading.Lock()
        self._last_nonce = 0

    def _next_nonce(self):
        with self._nonce_lock:
            n = int(time.time() * 1_000_000)
            if n <= self._last_nonce:
                n = self._last_nonce + 1
            self._last_nonce = n
            return str(n)

    @staticmethod
    def sign_payload(secret, endpoint, nonce, raw_body):
        """Kept separate and pure for testability."""
        msg = "/api/v2/" + endpoint + nonce + raw_body
        return hmac.new(secret.encode(), msg.encode(), hashlib.sha384).hexdigest()

    def public_get(self, endpoint, params=None):
        resp = self._session.get(
            PUB_BASE + endpoint, params=params, timeout=self._timeout
        )
        return resp.status_code, self._parse(resp)

    def auth_post(self, endpoint, body=None):
        if not self._key or not self._secret:
            raise RuntimeError("auth_post without credentials")
        raw = json.dumps(body if body is not None else {}, separators=(",", ":"))
        nonce = self._next_nonce()
        headers = {
            "Content-Type": "application/json",
            "bfx-nonce": nonce,
            "bfx-apikey": self._key,
            "bfx-signature": self.sign_payload(self._secret, endpoint, nonce, raw),
        }
        resp = self._session.post(
            AUTH_BASE + endpoint,
            data=raw.encode(),
            headers=headers,
            timeout=self._timeout,
        )
        return resp.status_code, self._parse(resp)

    @staticmethod
    def _parse(resp):
        try:
            return resp.json()
        except ValueError:
            return None
