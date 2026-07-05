"""bfx layer tests. All transport calls are faked — conftest blocks real sockets."""
import hashlib
import hmac
import logging

import pytest
import requests

from compound.bfx import boundary, models
from compound.bfx.boundary import CallSpec, SemanticError, TransientError
from compound.bfx.private import PrivateClient
from compound.bfx.public import PublicClient
from compound.bfx.transport import Transport

# --- live-verified sample payloads (docs/bitfinex-api-reference.md, 2026-07-04) ---

TICKER_RAW = [0.0003715232876712329, 0.00030136986301369865, 120, 28731506.92411286,
              0.000149, 2, 5996848.05921206, -0.00010701, -0.4164, 0.00014999,
              263018868.71194285, 0.00037104, 0.00007945, None, None,
              61314210.79990626, 1469734163000]


def test_ticker_parsing():
    t = models.FundingTicker.from_array(TICKER_RAW)
    assert t.frr == pytest.approx(0.0003715232876712329)
    assert t.bid_period == 120
    assert t.ask == pytest.approx(0.000149)
    assert t.last == pytest.approx(0.00014999)
    assert t.frr_amount_available == pytest.approx(61314210.79990626)


def test_book_side_convention():
    ask = models.BookEntry.from_array([0.00015, 2, 2, 5962953.88])
    bid = models.BookEntry.from_array([0.00030136986301369865, 120, 1, -3449958.41])
    assert ask.is_ask and not bid.is_ask


def test_funding_stat_unit_trap():
    # frr field is FRR/365; frr_daily must undo it.
    s = models.FundingStat.from_array(
        [1751587200000, None, None, 0.0003715 / 365, 30.0, None, None,
         3e8, 2.4e8, None, None, 1e6])
    assert s.frr_daily == pytest.approx(0.0003715, rel=1e-6)
    assert s.utilization == pytest.approx(0.8)


def test_signature_composition():
    secret = "s3cr3t"
    sig = Transport.sign_payload(secret, "auth/r/wallets", "1700000000000000", "{}")
    expected = hmac.new(
        secret.encode(),
        b"/api/v2/auth/r/wallets1700000000000000{}",
        hashlib.sha384,
    ).hexdigest()
    assert sig == expected


def test_nonce_strictly_increasing_under_threads():
    tr = Transport(api_key="k", api_secret="s")
    import threading
    out = []
    lock = threading.Lock()

    def grab():
        for _ in range(200):
            n = tr._next_nonce()
            with lock:
                out.append(int(n))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(out) == len(set(out)) == 1600


# --- boundary behavior ---

READ = CallSpec("t.read", kind="read", idempotent=True)
WRITE_NONIDEM = CallSpec("t.place", kind="write", idempotent=False, critical=True)


def flaky(fails, then):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] <= fails:
            raise requests.ConnectionError("reset")
        return then
    fn.calls = calls
    return fn


def test_read_retries_transient_then_succeeds():
    fn = flaky(2, (200, ["ok"]))
    assert boundary.call(READ, fn, _sleep=lambda s: None) == ["ok"]
    assert fn.calls["n"] == 3


def test_nonidempotent_write_never_retries_transient():
    fn = flaky(5, (200, ["ok"]))
    with pytest.raises(TransientError, match="MAY HAVE LANDED"):
        boundary.call(WRITE_NONIDEM, fn, _sleep=lambda s: None)
    assert fn.calls["n"] == 1


def test_semantic_error_never_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return 500, ["error", 10020, "amount: invalid"]
    with pytest.raises(SemanticError, match="10020"):
        boundary.call(READ, fn, _sleep=lambda s: None)
    assert calls["n"] == 1


def test_429_backs_off_longer_than_5xx():
    delays = []

    def sleeper(s):
        delays.append(s)

    def ratelimited():
        return 429, None
    with pytest.raises(TransientError):
        boundary.call(READ, ratelimited, _sleep=sleeper)
    assert delays and min(delays) >= boundary.BACKOFF_429


def test_critical_failure_logs_error(caplog):
    def fn():
        return 400, ["error", 10100, "apikey: invalid"]
    with caplog.at_level(logging.ERROR, logger="compound.boundary"):
        with pytest.raises(SemanticError):
            boundary.call(WRITE_NONIDEM, fn, _sleep=lambda s: None)
    assert any("CRITICAL" in r.message for r in caplog.records)


# --- private client ---

class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def auth_post(self, endpoint, body=None):
        self.sent.append((endpoint, body))
        return self.responses.pop(0)

    def public_get(self, endpoint, params=None):
        self.sent.append((endpoint, params))
        return self.responses.pop(0)


OFFER_ARR = [123456, "fUSD", 1751600000000, 1751600000000, 300.0, 300.0, "LIMIT",
             None, None, 0, "ACTIVE", None, None, None, 0.0003, 2, 0, 0, None, 0]


def test_submit_offer_body_and_parse():
    notif = [1751600000000, "fon-req", None, None, OFFER_ARR, None, "SUCCESS", "ok"]
    ft = FakeTransport([(200, notif)])
    off = PrivateClient(ft).submit_offer("fUSD", amount=300.0, rate=0.0003, period=2)
    endpoint, body = ft.sent[0]
    assert endpoint == "auth/w/funding/offer/submit"
    assert body["symbol"] == "fUSD"
    assert body["type"] == "LIMIT"
    assert isinstance(body["amount"], str) and float(body["amount"]) == 300.0
    assert isinstance(body["rate"], str) and float(body["rate"]) == 0.0003
    assert body["period"] == 2 and isinstance(body["period"], int)
    assert "flags" not in body
    assert off.id == 123456 and off.rate == pytest.approx(0.0003)


def test_submit_offer_status_error_is_semantic():
    notif = [1751600000000, "fon-req", None, None, None, None, "ERROR",
             "Invalid offer: incorrect amount, minimum is 150.0 dollar or equivalent in USD"]
    ft = FakeTransport([(200, notif)])
    with pytest.raises(SemanticError, match="rejected"):
        PrivateClient(ft).submit_offer("fUSD", amount=300.0, rate=0.0003, period=2)


def test_submit_offer_sanity_guards():
    ft = FakeTransport([])
    c = PrivateClient(ft)
    with pytest.raises(ValueError):
        c.submit_offer("fUSD", amount=-5, rate=0.0003, period=2)
    with pytest.raises(ValueError):
        c.submit_offer("fUSD", amount=300, rate=0.0003, period=1)
    with pytest.raises(ValueError):
        c.submit_offer("fUSD", amount=300, rate=0.5, period=2)   # 18250% APR typo
    with pytest.raises(ValueError):
        c.submit_offer("tBTCUSD", amount=300, rate=0.0003, period=2)
    assert ft.sent == []


def test_cancel_offer_gone_is_ok():
    ft = FakeTransport([(500, ["error", 10001, "Offer not found."])])
    assert PrivateClient(ft).cancel_offer(999) is None


def test_cancel_offer_other_semantic_raises():
    ft = FakeTransport([(500, ["error", 10100, "apikey: digest invalid"])])
    with pytest.raises(SemanticError):
        PrivateClient(ft).cancel_offer(999)


def test_ledgers_use_bare_currency():
    ft = FakeTransport([(200, [])])
    PrivateClient(ft).get_interest_ledgers("fUSD")
    endpoint, body = ft.sent[0]
    assert endpoint == "auth/r/ledgers/USD/hist"
    assert body["category"] == 28


def test_public_ticker_roundtrip():
    ft = FakeTransport([(200, TICKER_RAW)])
    t = PublicClient(ft).get_ticker("fUSD")
    assert t.frr == pytest.approx(0.0003715, rel=1e-3)
    assert ft.sent[0][0] == "ticker/fUSD"
