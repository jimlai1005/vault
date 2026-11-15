"""R-J / R-K / R-L / R-M of docs/plans/gridbot-position-truth.md (second review round).

R-J (W1 + W4): the stop-loss exit is the single-coin version of the circuit-breaker flatten:
    _flatten_round([coin]) -> sleep(FLATTEN_SETTLE_SECONDS) -> _verify_flat([coin])
driven by the EXCHANGE's open orders and szi, never by state. W1 = an armed buy whose fill is only
learnt after the flat used to be settled into a lot and answered with a reduce-only TP on a flat
position (rejected, armed never cleared, coin wedged). W4 = a resting order state does not know
survived the stop and filled during the cooldown.
R-K (W3): one coin's failed sync must not stop the others; the consecutive-failure counter covers
the whole sync_coin and is persisted even when it raised.
R-L: every verified stop-loss exit sends a Telegram.
R-M: the halted reminder names the coins whose stop-loss exit never verified.
Plus the test-strengthening items of the plan (multi-cycle stop_pending, run_once end to end, resume
after a mid-exit exception, settle sleep sits between the sends and the read-back).

All I/O is a stateful fake venue; nothing touches the network and nothing really sleeps."""
import json

import pytest

from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod

import test_gridbot_flatten_truth as ft
from test_gridbot_flatten_truth import _no_flatten_settle_sleep  # noqa: F401  (autouse: never really sleep)

env = ft.env
UNIVERSE = ft.UNIVERSE


class Venue(ft.Venue):
    """ft.Venue plus: a mid for every coin, openOrders in the real shape (origSz), reduce-only on a
    flat position rejected like HL does, an ordered trace of sends / reads / sleeps, and a hook that
    makes open_orders fail for the coin currently being synced."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mids = {"BTC": 100.0, "ETH": 100.0, "HYPE": 100.0}
        self.current = None
        self.open_orders_fail_for = set()
        self.cancel_fails_for_oids = set()
        self.queries = []

    def all_mids(self):
        return dict(self.mids)

    @property
    def mid(self):
        return self.mids["HYPE"]

    @mid.setter
    def mid(self, v):
        self.mids["HYPE"] = v

    def user_state(self, address):
        self.calls.append(("read", "user_state"))
        return super().user_state(address)

    def open_orders(self, address):
        if self.current in self.open_orders_fail_for:
            raise ConnectionError("open_orders down")
        self.calls.append(("read", "open_orders"))
        return super().open_orders(address)

    def query_order_by_oid(self, address, oid):
        self.queries.append(oid)
        return super().query_order_by_oid(address, oid)

    def cancel(self, coin, oid):
        if oid in self.cancel_fails_for_oids:
            self.calls.append(("cancel", coin, oid))
            return ft.CANCEL_ERR            # order stays on the book
        return super().cancel(coin, oid)

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        if reduce_only and self.positions.get(coin, 0.0) == 0.0:
            self.calls.append(("order_rejected", coin, is_buy, size, px, reduce_only))
            return {"status": "ok", "response": {"type": "order", "data": {"statuses": [
                {"error": "Reduce only order would increase position."}]}}}
        resp = super().order(coin, is_buy, size, px, order_type, reduce_only)
        oid = self.next_oid - 1
        for o in self.orders:
            if o["oid"] == oid:
                o.update({"side": "B" if is_buy else "A", "limitPx": str(px), "sz": str(size), "origSz": str(size)})
        return resp


@pytest.fixture
def build(env, monkeypatch):
    """env + equity pinned at the peak (no breaker) + sync_coin tagged with the coin being synced."""
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 1000.0)

    def make(venue, **kw):
        e = env(venue, **kw)
        real = e.sync_coin

        def tagged(coin):
            venue.current = coin
            try:
                return real(coin)
            finally:
                venue.current = None
        monkeypatch.setattr(e, "sync_coin", tagged)
        return e
    return make


def _stop_setup(build, szi=0.5, lot_size=0.5, **kw):
    v = Venue({"HYPE": szi}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0       # lot at level -1: stop = 99 * 0.85 = 84.15 -> triggered
    e = build(v, lots={"HYPE": {"-1": ft._lot(lot_size)}}, **kw)
    return e, v


# ---- (a) R-J / W1: armed buy filled, its status query fails ---------------------------------------

def test_w1_armed_fill_unresolved_at_stop_is_closed_with_the_rest_and_books_cleared(build):
    v = Venue({"HYPE": 0.8}, orders=[{"coin": "HYPE", "oid": 55}, {"coin": "HYPE", "oid": 777}])
    v.mid = 80.0
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}}, armed={"HYPE": {"-2": 777}})
    c = e.state["coins"]["HYPE"]
    v.order_status[777] = ConnectionError("orderStatus timeout")   # the filled buy cannot be queried

    e.sync_coin("HYPE")

    assert v.positions["HYPE"] == 0.0                              # whole szi (incl. the 0.3 fill) closed
    assert v.calls_of("close") == [("close", "HYPE", 0.8)]
    assert c["armed"] == {} and c["open_lots"] == {}               # nothing left that could wedge the coin
    assert c["stop_pending"] is False and c["stopped_until_ms"] is not None
    assert v.queries == []                                         # no per-order settlement on this path
    assert v.calls_of("order") == [] and v.calls_of("order_rejected") == []   # no TP, no buy, ever
    v.mid = 120.0
    for _ in range(5):                                             # cooldown cycles stay quiet
        e.sync_coin("HYPE")
    assert v.calls_of("order") == [] and v.calls_of("order_rejected") == []
    assert c["stop_pending"] is False


# ---- (b) R-J / W4: an order state does not know -----------------------------------------------------

def test_w4_unknown_resting_buy_is_cancelled_by_the_stop(build):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}, {"coin": "HYPE", "oid": 999}])
    v.mid = 80.0
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert sorted(x[2] for x in v.calls_of("cancel")) == [55, 999]
    assert v.orders == [] and v.positions["HYPE"] == 0.0
    assert c["stop_pending"] is False and c["stopped_until_ms"] is not None


def test_w4_unknown_order_that_cannot_be_cancelled_keeps_the_stop_pending_until_it_is(build):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}, {"coin": "HYPE", "oid": 999}])
    v.mid = 80.0
    v.cancel_fails_for_oids = {999}
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    c = e.state["coins"]["HYPE"]
    e.sync_coin("HYPE")
    assert v.positions["HYPE"] == 0.0                              # the position itself is closed
    assert c["stop_pending"] is True and c["stopped_until_ms"] is None   # ...but 999 still rests: not done
    assert len(e.sent) == 1 and "HYPE" in e.sent[0] and "open_orders=1" in e.sent[0]
    e.sync_coin("HYPE")
    assert c["stop_pending"] is True and len(e.sent) == 1          # failure alert only once
    v.cancel_fails_for_oids = set()
    e.sync_coin("HYPE")
    assert c["stop_pending"] is False and c["stopped_until_ms"] is not None
    assert v.orders == []


# ---- (c) the stop touches only its own coin ----------------------------------------------------------

def test_stop_leaves_other_coins_and_non_universe_alone(build):
    v = Venue({"HYPE": 0.5, "BTC": 0.01, "ETH": 0.1, "SOL": 3.0},
              orders=[{"coin": "HYPE", "oid": 55}, {"coin": "BTC", "oid": 1}, {"coin": "ETH", "oid": 2},
                      {"coin": "SOL", "oid": 3}, {"coin": "@107", "oid": 4}])
    v.mid = 80.0
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.sync_coin("HYPE")
    assert [x[2] for x in v.calls_of("cancel")] == [55]
    assert v.calls_of("close") == [("close", "HYPE", 0.5)]
    assert v.positions == {"HYPE": 0.0, "BTC": 0.01, "ETH": 0.1, "SOL": 3.0}
    assert sorted(o["oid"] for o in v.orders) == [1, 2, 3, 4]


# ---- (d) R-L: success is always announced -------------------------------------------------------------

def test_l_clean_first_try_sends_exactly_one_success_alert(build):
    e, v = _stop_setup(build)
    e.sync_coin("HYPE")
    assert len(e.sent) == 1
    msg = e.sent[0]
    assert "HYPE" in msg and "verified" in msg.lower() and "szi" in msg and "1h" in msg   # coin, verified, cooldown
    assert "NOT VERIFIED" not in msg


def test_l_failure_then_success_sends_one_failure_and_one_success(build):
    e, v = _stop_setup(build)
    v.close_error = True
    e.sync_coin("HYPE")
    e.sync_coin("HYPE")
    assert len(e.sent) == 1 and "NOT VERIFIED" in e.sent[0]
    v.close_error = False
    e.sync_coin("HYPE")
    assert len(e.sent) == 2 and "NOT VERIFIED" not in e.sent[1] and "verified" in e.sent[1].lower()


def test_l_dry_run_stop_is_silent_sends_nothing_reads_nothing_and_does_not_sleep(build, monkeypatch):
    sleeps = []
    monkeypatch.setattr(live_mod.time, "sleep", lambda s: sleeps.append(s))
    e, v = _stop_setup(build, live=False)
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["open_lots"] == {} and c["armed"] == {} and c["stop_pending"] is False
    assert c["stopped_until_ms"] is not None
    assert v.calls == [] and v.user_state_calls == 0 and v.open_orders_calls == 0
    assert sleeps == [] and e.sent == []


# ---- (e) R-K: per-coin isolation and the consecutive-failure counter ----------------------------------

def _disk(coin):
    return json.loads(cfg.STATE_FILE.read_text())["coins"][coin]


def test_k_open_orders_failure_on_one_coin_does_not_stop_the_others_and_alerts_once_at_five(build):
    v = Venue()
    v.open_orders_fail_for = {"BTC"}
    e = build(v)
    for i in range(1, 5):
        e.run_once()
        assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == i and e.sent == []
        assert _disk("BTC")["reconcile_fail_cycles"] == i
    placed = {c[1] for c in v.calls_of("order")}
    assert placed == {"ETH", "HYPE"}                      # the others were processed in the very first cycle
    assert e.state["coins"]["ETH"]["reconcile_fail_cycles"] == 0
    e.run_once()                                          # 5th consecutive failure
    assert len(e.sent) == 1 and "BTC" in e.sent[0] and "open_orders down" in e.sent[0]
    for _ in range(3):
        e.run_once()
    assert len(e.sent) == 1 and e.state["coins"]["BTC"]["reconcile_fail_cycles"] == 8
    assert not e.state.get("halted") and v.calls_of("close") == []    # nothing flattened because of it
    v.open_orders_fail_for = set()                        # recovers: counter back to 0, later episodes alert again
    e.run_once()
    assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == 0 and len(e.sent) == 1
    v.open_orders_fail_for = {"BTC"}
    for _ in range(5):
        e.run_once()
    assert len(e.sent) == 2


def test_k_counter_is_persisted_even_when_sync_coin_raised(build):
    v = Venue()
    v.open_orders_fail_for = {"BTC"}
    e = build(v)
    with pytest.raises(ConnectionError):
        e.sync_coin("BTC")
    assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == 1
    assert _disk("BTC")["reconcile_fail_cycles"] == 1     # flushed by the failure path itself, not by run_once


def test_k_unreadable_mid_counts_five_cycles_then_alerts_and_recovers(build):
    v = Venue()
    del v.mids["BTC"]                                     # get_mid_price -> 0.0
    e = build(v)
    for i in range(1, 5):
        e.run_once()
        assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == i and e.sent == []
    assert {c[1] for c in v.calls_of("order")} == {"ETH", "HYPE"}
    e.run_once()
    assert len(e.sent) == 1 and "BTC" in e.sent[0]
    v.mids["BTC"] = 100.0
    e.run_once()
    assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == 0


def test_k_a_cycle_counts_once_even_with_several_failure_symptoms(build):
    v = Venue()
    v.user_state_raises_on = {"all"}                      # reconcile unreadable AND ...
    del v.mids["ETH"]                                     # ... another coin with no mid
    e = build(v)
    e.run_once()
    assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == 1
    assert e.state["coins"]["ETH"]["reconcile_fail_cycles"] == 1
    assert e.state["coins"]["HYPE"]["reconcile_fail_cycles"] == 1


def test_k_a_failing_coin_does_not_stop_another_coins_stop_exit_in_the_same_cycle(build):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0
    v.open_orders_fail_for = {"BTC"}
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.state["coins"]["HYPE"]["stop_pending"] = True       # HYPE comes after BTC in the universe
    e.run_once()
    assert v.positions["HYPE"] == 0.0
    assert e.state["coins"]["HYPE"]["stop_pending"] is False
    assert e.state["coins"]["BTC"]["reconcile_fail_cycles"] == 1


def test_k_stop_pending_cycle_neither_counts_nor_resets(build):
    e, v = _stop_setup(build)
    v.close_error = True
    c = e.state["coins"]["HYPE"]
    c["reconcile_fail_cycles"] = 3
    for _ in range(4):
        e.sync_coin("HYPE")
    assert c["stop_pending"] is True and c["reconcile_fail_cycles"] == 3


# ---- (f) R-M: halted reminder names unfinished stop-loss exits ---------------------------------------

def test_m_halted_reminder_lists_stop_pending_coins(build):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    e = build(v, halted=True)
    e.state["coins"]["HYPE"]["stop_pending"] = True
    e.state["last_halt_alert_ms"] = 0
    assert e.check_drawdown() is True
    assert len(e.sent) == 1 and "HYPE" in e.sent[0] and "stop" in e.sent[0].lower()
    assert "BTC" not in e.sent[0] and "ETH" not in e.sent[0]
    # D3 unchanged: no sends, no reads of orders/positions while halted without flatten_pending
    assert v.calls == [] and v.user_state_calls == 0 and v.open_orders_calls == 0
    assert v.positions == {"HYPE": 0.5}


def test_m_halted_reminder_without_stop_pending_does_not_mention_it(build):
    v = Venue()
    e = build(v, halted=True)
    e.state["last_halt_alert_ms"] = 0
    assert e.check_drawdown() is True
    assert len(e.sent) == 1 and "stop" not in e.sent[0].lower()


def test_m_run_once_while_halted_with_stop_pending_makes_zero_exchange_calls(build):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    e = build(v, halted=True, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.state["coins"]["HYPE"]["stop_pending"] = True
    e.state["last_halt_alert_ms"] = 0
    for _ in range(3):
        e.run_once()
    assert [c for c in v.calls if c[0] in ("cancel", "close", "order")] == []
    assert v.positions == {"HYPE": 0.5} and "HYPE" in e.sent[0]


# ---- (g) multi-cycle / run_once / resume --------------------------------------------------------------

def test_g_stop_pending_survives_several_partial_cycles_then_completes(build):
    e, v = _stop_setup(build, szi=1.0)
    v.close_fractions = [0.5, 0.5, 0.5]                   # 1.0 -> 0.5 -> 0.25 -> 0.125, then a full fill
    c = e.state["coins"]["HYPE"]
    for i in range(3):
        e.run_once()
        assert c["stop_pending"] is True and c["open_lots"] != {} and c["stopped_until_ms"] is None
        assert [o for o in v.calls_of("order") if o[1] == "HYPE"] == []   # BTC/ETH keep gridding
        v.mid = 80.0 + 30 * i                             # price wanders above the stop meanwhile
    assert len(e.sent) == 1 and "NOT VERIFIED" in e.sent[0]
    e.run_once()
    assert v.positions["HYPE"] == pytest.approx(0.0)
    assert c["stop_pending"] is False and c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert len(e.sent) == 2 and "NOT VERIFIED" not in e.sent[1]
    assert [o for o in v.calls_of("order") if o[1] == "HYPE"] == []   # BTC/ETH keep gridding
    assert v.calls_of("order_rejected") == []


def _trip_with_pending_stop(build, monkeypatch):
    """cycle 1: stop-loss exit fails (stop_pending); cycle 2: equity collapses, breaker trips, its
    flatten fails too -> halted + flatten_pending."""
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0
    v.close_error = True
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.run_once()
    c = e.state["coins"]["HYPE"]
    assert c["stop_pending"] is True and e.state.get("halted") is False
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    e.run_once()
    assert e.state["halted"] is True and e.state["flatten_pending"] is True
    assert c["stop_pending"] is True                      # nothing verified flat yet
    return e, v, c


def test_g_stop_pending_then_breaker_flatten_fails_then_halted_retry_succeeds(build, monkeypatch):
    e, v, c = _trip_with_pending_stop(build, monkeypatch)
    e.state["last_halt_alert_ms"] = 10**15
    n_orders = len(v.calls_of("order"))
    v.close_error = False
    e.run_once()                                          # halted: flatten_pending retry
    assert e.state["flatten_pending"] is False and v.positions["HYPE"] == pytest.approx(0.0)
    assert c["stop_pending"] is False and c["open_lots"] == {} and c["armed"] == {}
    assert any("FLATTEN COMPLETED" in m for m in e.sent)
    n_calls = len(v.calls)
    e.run_once()                                          # flag cleared: halted touches nothing more
    assert len(v.calls) == n_calls
    assert len(v.calls_of("order")) == n_orders


def test_g_restart_rearm_finishes_pending_flatten_then_resumes(build, monkeypatch):
    e, v, c = _trip_with_pending_stop(build, monkeypatch)
    e.rearm_if_recovered()                                # restart while the exchange still refuses to close
    assert e.state["halted"] is True and e.state["flatten_pending"] is True
    assert any("still NOT verified" in m for m in e.sent)
    v.close_error = False
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 950.0)
    e.rearm_if_recovered()                                # flat first, then the drawdown check (5% < 20%)
    assert v.positions["HYPE"] == pytest.approx(0.0)
    assert e.state["halted"] is False and e.state["flatten_pending"] is False
    assert c["stop_pending"] is False and c["open_lots"] == {}
    e.run_once()                                          # trading resumes without error
    assert e.state["halted"] is False


def test_g_exit_that_raised_midway_resumes_next_cycle(build, monkeypatch):
    e, v = _stop_setup(build)
    c = e.state["coins"]["HYPE"]
    real = e._flatten_round
    state = {"boom": True}

    def flaky(universe):
        if state["boom"]:
            state["boom"] = False
            raise RuntimeError("process hiccup between cancel and close")
        return real(universe)
    monkeypatch.setattr(e, "_flatten_round", flaky)
    with pytest.raises(RuntimeError):
        e.sync_coin("HYPE")                               # the flag was persisted before the exit started
    assert _disk("HYPE")["stop_pending"] is True and c["open_lots"] != {}
    assert c.get("reconcile_fail_cycles", 0) == 0         # a stop_pending cycle is not counted
    v.mid = 120.0                                         # price bounced: still the exit, nothing else
    e.sync_coin("HYPE")
    assert v.positions["HYPE"] == pytest.approx(0.0)
    assert c["stop_pending"] is False and c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert v.calls_of("order") == []


def test_g_run_once_survives_an_exit_that_raises_and_other_coins_proceed(build, monkeypatch):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.state["coins"]["ETH"]["stop_pending"] = True
    real = e._flatten_round

    def flaky(universe):
        if universe == ["ETH"]:
            raise RuntimeError("boom")
        return real(universe)
    monkeypatch.setattr(e, "_flatten_round", flaky)
    e.run_once()                                          # must not raise
    assert e.state["coins"]["ETH"]["stop_pending"] is True
    assert v.positions["HYPE"] == pytest.approx(0.0)      # HYPE (after ETH in the universe) still got its stop


# ---- (h) the settle sleep sits between the sends and the read-back ----------------------------------

def test_h_stop_path_sleeps_after_the_sends_and_before_the_readback(build, monkeypatch):
    monkeypatch.setattr(live_mod, "FLATTEN_SETTLE_SECONDS", 7)
    e, v = _stop_setup(build)
    monkeypatch.setattr(live_mod.time, "sleep", lambda s: v.calls.append(("sleep", s)))
    e.sync_coin("HYPE")
    kinds = [c[0] if c[0] != "read" else f"read:{c[1]}" for c in v.calls]
    assert kinds.count("sleep") == 1
    assert ("sleep", 7) in v.calls
    i_sleep = kinds.index("sleep")
    i_last_send = max(i for i, k in enumerate(kinds) if k in ("cancel", "close"))
    i_first_readback = min(i for i, k in enumerate(kinds) if i > i_sleep and k.startswith("read:"))
    assert i_last_send < i_sleep < i_first_readback
    assert kinds[i_first_readback:i_first_readback + 2] == ["read:open_orders", "read:user_state"]


def test_verify_flat_reads_orders_before_positions(build):
    """An order that is no longer resting when the order list is read cannot fill afterwards, so the
    szi read AFTER it already contains any fill it had. Reversing the two reads would leave a window."""
    v = Venue({"HYPE": 0.0})
    e = build(v)
    assert e._verify_flat(["HYPE"]) == (True, "")
    assert [c[1] for c in v.calls if c[0] == "read"] == ["open_orders", "user_state"]


# ---- third review round (2026-11-14): reminder wording and the failure streak across a stop ----
def test_m_reminder_does_not_claim_not_retried_when_the_flatten_retry_covers_the_coin(build, monkeypatch):
    v = Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0
    v.close_error = True
    e = build(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    e.run_once()                                   # stop fires, exit cannot close -> stop_pending
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    e.run_once()                                   # breaker trips, flatten fails -> halted + flatten_pending
    assert e.state["halted"] and e.state["flatten_pending"]
    e.state["last_halt_alert_ms"] = 0
    n_close = len(v.calls_of("close"))
    e.run_once()
    msg = e.sent[-1]
    assert len(v.calls_of("close")) > n_close      # the flatten retry did re-attempt HYPE this cycle
    assert "STOP-LOSS EXIT NEVER VERIFIED for HYPE" in msg
    assert "NOT retried while halted" not in msg and "covered by the flatten retry" in msg


def test_k_failure_streak_from_before_a_stop_does_not_resume_after_the_cooldown(build):
    e, v = _stop_setup(build)
    c = e.state["coins"]["HYPE"]
    c["reconcile_fail_cycles"] = 4                 # four flaky cycles just before the stop fired
    e.sync_coin("HYPE")                            # stop verified, cooldown starts
    assert c["stop_pending"] is False and c["reconcile_fail_cycles"] == 0
    c["stopped_until_ms"] = 1                      # cooldown over
    v.open_orders_fail_for = {"HYPE"}
    n = len(e.sent)
    with pytest.raises(ConnectionError):
        e.sync_coin("HYPE")                        # one failure a day later is cycle 1, not cycle 5
    assert len(e.sent) == n and c["reconcile_fail_cycles"] == 1
