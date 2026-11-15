"""T3 of docs/plans/gridbot-position-truth.md: flatten and stop-loss exits are
driven by the EXCHANGE's positions/orders (never the bot's own books) and only
count as done after a read-back. 2026-11-05: flatten followed state, left
BTC 0.00962 / ETH 0.0972 / HYPE 7.43 untracked and unprotected, halt then
looked at nothing and the loss grew from 20% to 40%.

All I/O is a stateful fake venue; nothing touches the network."""
import json

import pytest

from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod
from hlvault.gridbot.live import GridBotEngine
from hlvault.gridbot.resilience import ResilientExchange


@pytest.fixture(autouse=True)
def _no_flatten_settle_sleep(monkeypatch):
    """R-D (T4): live flatten pauses between its sends and the read-back; never really sleep in tests."""
    monkeypatch.setattr(live_mod, "FLATTEN_SETTLE_SECONDS", 0)

CANCEL_OK = {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}
CANCEL_ERR = {"status": "ok", "response": {"type": "cancel", "data": {"statuses": [
    {"error": "Order was never placed, already canceled, or filled."}]}}}
UNIVERSE = ["BTC", "ETH", "HYPE"]


def _order_status(oid, status, orig, remaining, limit_px="94.2"):
    return {"status": "order", "order": {"order": {
        "coin": "HYPE", "side": "B", "limitPx": limit_px, "sz": remaining, "oid": oid,
        "origSz": orig, "tif": "Alo", "reduceOnly": False, "orderType": "Limit"},
        "status": status, "statusTimestamp": 1}}


class Venue:
    """Fake exchange + info sharing one book of positions and resting orders."""

    def __init__(self, positions=None, orders=None):
        self.positions = dict(positions or {})
        self.orders = [dict(o) for o in (orders or [])]
        self.calls = []                       # ("cancel"|"close"|"order", ...)
        self.user_state_calls = 0
        self.open_orders_calls = 0
        self.user_state_raises_on = set()     # 1-based call indexes that raise; {"all"} = every call
        self.close_fractions = []             # per market_close call: fraction filled (default 1.0)
        self.close_error = False
        self.cancel_response = CANCEL_OK
        self.order_status = {}
        self.next_oid = 9000

    # ---- info ----
    def user_state(self, address):
        self.user_state_calls += 1
        if "all" in self.user_state_raises_on or self.user_state_calls in self.user_state_raises_on:
            raise ConnectionError("user_state down")
        return {"assetPositions": [
            {"type": "oneWay", "position": {"coin": c, "szi": repr(v)}}
            for c, v in self.positions.items() if v != 0.0]}

    def open_orders(self, address):
        self.open_orders_calls += 1
        return [dict(o) for o in self.orders]

    def all_mids(self):
        return {"HYPE": self.mid}

    mid = 100.0

    def meta(self):
        return {"universe": [{"name": c, "szDecimals": 3, "maxLeverage": 10} for c in UNIVERSE]}

    def query_order_by_oid(self, address, oid):
        r = self.order_status[oid]
        if isinstance(r, Exception):
            raise r
        return r

    # ---- exchange ----
    def cancel(self, coin, oid):
        self.calls.append(("cancel", coin, oid))
        if self.cancel_response is CANCEL_OK:
            self.orders = [o for o in self.orders if o["oid"] != oid]
        return self.cancel_response

    def market_close(self, coin, sz):
        self.calls.append(("close", coin, sz))
        if self.close_error:
            return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "no liquidity"}]}}}
        frac = self.close_fractions.pop(0) if self.close_fractions else 1.0
        filled = round(sz * frac, 8)
        szi = self.positions.get(coin, 0.0)
        self.positions[coin] = szi - filled if szi > 0 else szi + filled
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": [
            {"filled": {"totalSz": repr(filled), "avgPx": "1.0", "oid": 1}}]}}}

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.calls.append(("order", coin, is_buy, size, px, reduce_only))
        oid = self.next_oid
        self.next_oid += 1
        self.orders.append({"coin": coin, "oid": oid})
        return {"response": {"data": {"statuses": [{"resting": {"oid": oid}}]}}}

    def update_leverage(self, *a, **k):
        return {"status": "ok"}

    def calls_of(self, kind):
        return [c for c in self.calls if c[0] == kind]


def _lot(size, level=-1, tp_oid=55):
    return {"entry_price": 99.0, "size": size, "tp_price": 100.0, "tp_oid": tp_oid}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", list(UNIVERSE))
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 1)
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 2)
    monkeypatch.setattr(cfg, "HALT_ALERT_INTERVAL_MINUTES", 60)
    monkeypatch.setattr(cfg, "NUM_LEVELS", 3)
    monkeypatch.setattr(cfg, "STOP_BUFFER_PCT", 0.15)
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 1.0)
    monkeypatch.setattr(cfg, "COOLDOWN_HOURS", 1.0)
    sent = []
    monkeypatch.setattr(live_mod, "send_alert", lambda tok, chat, msg: sent.append(msg) or True)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)

    def build(venue=None, lots=None, armed=None, live=True, halted=False, pending=None):
        venue = venue or Venue()
        e = GridBotEngine.__new__(GridBotEngine)
        e.live_trading = live
        e.info = venue
        e.exchange = ResilientExchange(venue)
        e._sz_dec = {}
        e._leverage_set = set(UNIVERSE)
        e.state = {"halted": halted, "peak_equity": 1000.0, "last_fill_check_ms": 0,
                   "bad_equity_reads": 0, "drawdown_breach_cycles": 0,
                   "coins": {c: {"anchor": 100.0, "step_pct": 0.01, "notional_per_level": 50.0,
                                 "max_position_notional": 500.0, "armed": {}, "open_lots": {},
                                 "stopped_until_ms": None} for c in UNIVERSE}}
        for coin, ls in (lots or {}).items():
            e.state["coins"][coin]["open_lots"] = ls
        for coin, ar in (armed or {}).items():
            e.state["coins"][coin]["armed"] = ar
        if pending is not None:
            e.state["flatten_pending"] = pending
        e.sent = sent
        e.venue = venue
        return e

    return build


# ---- _flatten_everything -----------------------------------------------------

def test_a_empty_state_but_exchange_holds_three_positions_all_closed(env):
    v = Venue({"BTC": 0.00962, "ETH": 0.0972, "HYPE": 7.43})
    e = env(v)
    assert e._flatten_everything() is True
    assert sorted(v.calls_of("close")) == [("close", "BTC", 0.00962), ("close", "ETH", 0.0972),
                                            ("close", "HYPE", 7.43)]
    assert all(x == 0.0 for x in v.positions.values())
    assert e.state["flatten_pending"] is False


def test_a2_short_position_is_closed_with_absolute_size(env):
    v = Venue({"ETH": -0.5})
    e = env(v)
    assert e._flatten_everything() is True
    assert v.calls_of("close") == [("close", "ETH", 0.5)]


def test_b_exchange_position_double_the_lot_closes_exchange_quantity(env):
    v = Venue({"BTC": 0.01})
    e = env(v, lots={"BTC": {"-1": _lot(0.005)}})
    assert e._flatten_everything() is True
    assert v.calls_of("close") == [("close", "BTC", 0.01)]
    assert e.state["coins"]["BTC"]["open_lots"] == {}


def test_c_unknown_universe_orders_cancelled_non_universe_untouched(env):
    v = Venue({"SOL": 3.0, "BTC": 0.01},
              orders=[{"coin": "BTC", "oid": 1}, {"coin": "HYPE", "oid": 2}, {"coin": "SOL", "oid": 3},
                      {"coin": "@107", "oid": 4}])
    e = env(v)           # state knows none of these
    assert e._flatten_everything() is True
    assert sorted(c[2] for c in v.calls_of("cancel")) == [1, 2]
    assert [c[1] for c in v.calls_of("close")] == ["BTC"]
    assert v.positions["SOL"] == 3.0
    assert sorted(o["oid"] for o in v.orders) == [3, 4]


def test_d_half_filled_close_is_retried_within_one_call(env):
    v = Venue({"ETH": 0.1})
    v.close_fractions = [0.5]
    e = env(v)
    assert e._flatten_everything() is True
    closes = v.calls_of("close")
    assert len(closes) == 2 and closes[0] == ("close", "ETH", 0.1) and closes[1][2] == pytest.approx(0.05)
    assert v.positions["ETH"] == pytest.approx(0.0)


def test_e_still_open_after_three_rounds_keeps_state_and_flags_pending(env, caplog):
    v = Venue({"BTC": 0.01}, orders=[{"coin": "ETH", "oid": 7}])
    v.close_error = True
    v.cancel_response = CANCEL_ERR
    e = env(v, lots={"BTC": {"-1": _lot(0.01)}}, armed={"ETH": {"-2": 7}})
    assert e._flatten_everything() is False
    assert len(v.calls_of("close")) == 3
    assert e.state["flatten_pending"] is True
    assert e.state["coins"]["BTC"]["open_lots"] == {"-1": _lot(0.01)}
    assert e.state["coins"]["ETH"]["armed"] == {"-2": 7}
    assert "BTC szi=0.01" in e._flatten_detail and "ETH szi=0 open_orders=1" in e._flatten_detail
    assert "BTC szi=0.01" in caplog.text


def test_f_unreadable_positions_is_failure_not_flat(env):
    v = Venue({"BTC": 0.01})
    v.user_state_raises_on = {"all"}
    e = env(v, lots={"BTC": {"-1": _lot(0.01)}})
    assert e._flatten_everything() is False
    assert e.state["flatten_pending"] is True
    assert e.state["coins"]["BTC"]["open_lots"] == {"-1": _lot(0.01)}
    assert "unreadable" in e._flatten_detail
    assert v.calls_of("close") == []


def test_f2_read_fails_only_at_verification_is_not_success(env):
    v = Venue({"BTC": 0.01})
    v.user_state_raises_on = {2, 4, 6}     # the three verify reads; every round's pre-close read works
    e = env(v, lots={"BTC": {"-1": _lot(0.01)}})
    assert e._flatten_everything() is False
    assert e.state["flatten_pending"] is True
    assert e.state["coins"]["BTC"]["open_lots"] != {}


def test_f3_order_list_unreadable_is_failure(env):
    v = Venue()

    def boom(address):
        raise ConnectionError("down")
    v.open_orders = boom
    e = env(v)
    assert e._flatten_everything() is False
    assert e.state["flatten_pending"] is True


def test_flatten_never_sends_an_opening_order(env):
    v = Venue({"BTC": 0.01, "ETH": -0.2}, orders=[{"coin": "HYPE", "oid": 1}])
    e = env(v)
    e._flatten_everything()
    assert v.calls_of("order") == []


def test_dry_run_flatten_sends_and_reads_nothing_and_clears_books(env):
    v = Venue({"BTC": 0.01}, orders=[{"coin": "BTC", "oid": 1}])
    e = env(v, live=False, lots={"BTC": {"-1": _lot(0.01)}}, armed={"ETH": {"-2": "dryrun-ETH-1"}})
    assert e._flatten_everything() is True
    assert v.calls == [] and v.user_state_calls == 0 and v.open_orders_calls == 0
    assert e.state["coins"]["BTC"]["open_lots"] == {} and e.state["coins"]["ETH"]["armed"] == {}
    assert e.state["flatten_pending"] is False


# ---- circuit breaker integration -----------------------------------------------

def test_trip_alert_states_verified_flat(env):
    v = Venue({"BTC": 0.01})
    e = env(v)
    assert e.check_drawdown() is True
    assert e.state["halted"] is True and e.state["flatten_pending"] is False
    assert len(e.sent) == 1 and "verified" in e.sent[0].lower() and "BTC, ETH, HYPE" in e.sent[0]
    assert json.loads(cfg.STATE_FILE.read_text())["flatten_pending"] is False


def test_trip_incomplete_persists_pending_and_lists_remaining_szi(env):
    v = Venue({"BTC": 0.01, "HYPE": 7.43})
    v.close_error = True
    e = env(v)
    assert e.check_drawdown() is True
    assert e.state["halted"] is True and e.state["flatten_pending"] is True
    assert json.loads(cfg.STATE_FILE.read_text())["flatten_pending"] is True
    txt = " ".join(e.sent)
    assert "FLATTEN INCOMPLETE" in txt and "BTC szi=0.01" in txt and "HYPE szi=7.43" in txt


def test_g_halted_with_pending_retries_flatten_then_clears_flag_and_alerts_once(env):
    v = Venue({"BTC": 0.01, "ETH": 0.1})
    e = env(v, halted=True, pending=True)
    e.state["last_halt_alert_ms"] = 10**15            # reminder interval not elapsed
    assert e.check_drawdown() is True
    assert v.positions == {"BTC": 0.0, "ETH": 0.0}
    assert e.state["flatten_pending"] is False
    assert len(e.sent) == 1 and "verified" in e.sent[0].lower()
    n_calls = len(v.calls)
    assert e.check_drawdown() is True                  # flag cleared: no further action, no further alert
    assert len(v.calls) == n_calls and len(e.sent) == 1


def test_g2_halted_pending_still_failing_keeps_flag_and_reminder_lists_remaining(env):
    v = Venue({"BTC": 0.01})
    v.close_error = True
    e = env(v, halted=True, pending=True)
    e.state["last_halt_alert_ms"] = 0
    assert e.check_drawdown() is True
    assert e.state["flatten_pending"] is True
    assert len(e.sent) == 1 and "FLATTEN STILL PENDING" in e.sent[0] and "BTC szi=0.01" in e.sent[0]


def test_h_halted_without_pending_touches_nothing(env):
    v = Venue({"BTC": 0.01}, orders=[{"coin": "BTC", "oid": 1}])
    e = env(v, halted=True)                            # old state files: no flatten_pending key
    e.state["last_halt_alert_ms"] = 10**15
    assert "flatten_pending" not in e.state
    assert e.check_drawdown() is True
    e.state["flatten_pending"] = False
    assert e.check_drawdown() is True
    assert v.calls == [] and v.user_state_calls == 0 and v.open_orders_calls == 0
    assert v.positions == {"BTC": 0.01}


def test_d_equity_unreadable_halt_does_not_flatten_or_set_pending(env, monkeypatch):
    def boom(info, addr):
        raise RuntimeError("api down")
    monkeypatch.setattr(live_mod, "get_full_account_equity", boom)
    v = Venue({"BTC": 0.01})
    e = env(v)
    e.check_drawdown()
    e.check_drawdown()
    assert e.state["halted"] is True
    assert not e.state.get("flatten_pending")
    assert v.calls == [] and v.user_state_calls == 0


def test_e_rearm_clears_flatten_pending(env, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 950.0)
    e = env(Venue(), halted=True, pending=True)
    e.rearm_if_recovered()
    assert e.state["halted"] is False and e.state["flatten_pending"] is False


# ---- stop-loss -----------------------------------------------------------------

def _stop_engine(env, szi, lots_size=0.5, **kw):
    v = Venue({"HYPE": szi}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0       # lot at level -1: stop = 99 * 0.85 = 84.15 -> triggered
    e = env(v, lots={"HYPE": {"-1": _lot(lots_size)}}, **kw)
    return e, v


def test_i_stop_loss_closes_exchange_szi_not_sum_of_lots(env):
    e, v = _stop_engine(env, szi=1.0)
    e.sync_coin("HYPE")
    assert v.calls_of("close") == [("close", "HYPE", 1.0)]
    c = e.state["coins"]["HYPE"]
    assert c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert v.orders == []                                   # TP cancelled


def test_i2_stop_loss_readback_nonzero_keeps_lots_and_no_cooldown(env):
    e, v = _stop_engine(env, szi=1.0)
    v.close_fractions = [0.5, 0.0, 0.0]
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["open_lots"] != {} and c["stopped_until_ms"] is None
    # next cycle retries and finishes
    v.close_fractions = []
    e.sync_coin("HYPE")
    assert c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert v.positions["HYPE"] == pytest.approx(0.0)


def test_i3_stop_loss_unreadable_position_keeps_lots(env):
    e, v = _stop_engine(env, szi=1.0)
    v.user_state_raises_on = {"all"}
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["open_lots"] != {} and c["stopped_until_ms"] is None
    assert v.calls_of("close") == []


def test_i4_stop_loss_unconfirmed_cancel_of_a_raced_buy_closes_szi_but_is_not_done(env):
    # R-J (was: "armed buy that filled during cancel is settled then closed"): the stop no longer settles
    # buys one by one. It cancels everything the exchange shows, closes the WHOLE szi, and only a
    # read-back with no order resting and szi 0 completes it. Here the cancel keeps answering "error"
    # (orders stay on the book) -> szi is closed but the exit is not verified.
    e, v = _stop_engine(env, szi=0.8, armed={"HYPE": {"-2": 777}})
    v.orders.append({"coin": "HYPE", "oid": 777})
    v.cancel_response = CANCEL_ERR                          # cancel raced the fill
    v.order_status[777] = _order_status(777, "filled", orig="0.3", remaining="0.0")
    v.positions["HYPE"] = 0.8                               # 0.5 lot + 0.3 that just filled
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert v.positions["HYPE"] == pytest.approx(0.0)        # whole exchange szi closed
    assert v.calls_of("close") == [("close", "HYPE", 0.8)]
    assert v.calls_of("order") == []                        # no TP for the 0.3 fill: the position is gone
    assert c["stopped_until_ms"] is None                    # orders still resting (cancel kept failing) -> retry
    assert c["stop_pending"] is True and c["armed"] == {"-2": 777} and "-1" in c["open_lots"]


def test_i5_stop_loss_armed_buy_still_open_blocks_completion(env):
    e, v = _stop_engine(env, szi=0.5, armed={"HYPE": {"-2": 777}})
    v.orders.append({"coin": "HYPE", "oid": 777})
    v.cancel_response = CANCEL_ERR
    v.order_status[777] = _order_status(777, "open", orig="0.3", remaining="0.3")
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["armed"] == {"-2": 777} and c["stopped_until_ms"] is None and c["open_lots"] != {}


def test_i6_stop_loss_tp_already_filled_does_not_wedge(env):
    # TP filled earlier (not resting any more, cancel answers "unconfirmed"): the exit must still finish
    e, v = _stop_engine(env, szi=0.2)
    v.orders = []
    v.cancel_response = CANCEL_ERR
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert v.calls_of("close") == [("close", "HYPE", 0.2)]
