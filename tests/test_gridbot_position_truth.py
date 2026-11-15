"""T4 of docs/plans/gridbot-position-truth.md (plus R-D, R-E, R-F): every cycle the books are
reconciled against the EXCHANGE's szi, the notional cap is measured on the exchange's szi and
counts resting buys, and an unexplained position gap only alerts + pauses new buys — it is never
traded (owner decision D2).

All I/O is a stateful fake venue (positions + resting orders); nothing touches the network."""
import sys

import pytest

from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod
from hlvault.gridbot.live import GridBotEngine
from hlvault.gridbot.resilience import ResilientExchange
from hlvault.gridbot.strategy import level_price

COIN = "HYPE"
CANCEL_OK = {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}


class Venue:
    """Fake exchange + info over one book. Orders carry the real openOrders shape
    (coin/side/limitPx/sz/oid/origSz); `final` remembers how an order that left the book ended."""

    mid = 100.0

    def __init__(self, szi=0.0):
        self.szi = szi
        self.orders: list[dict] = []
        self.final: dict = {}                 # oid -> (status, orig, remaining, limit_px)
        self.events: list[tuple] = []         # ordered ("order"|"cancel"|"close"|"user_state"|"open_orders", ...)
        self.placed: list[dict] = []          # every order() call
        self.cancels: list = []               # oids, in call order
        self.closes: list = []
        self.user_state_error: Exception | None = None
        self.close_error = False
        self.next_oid = 9000

    # ---- helpers for tests ----
    def add_resting(self, oid, side, px, orig, remaining=None):
        self.orders.append({"coin": COIN, "side": side, "limitPx": str(px),
                            "sz": str(orig if remaining is None else remaining), "oid": oid,
                            "timestamp": 1, "origSz": str(orig)})

    def drop_externally(self, oid, status="canceled"):
        """The order leaves the book without us cancelling it (zero fill)."""
        o = next(o for o in self.orders if o["oid"] == oid)
        self.orders.remove(o)
        self.final[oid] = (status, o["origSz"], o["origSz"], o["limitPx"])

    def buys(self):
        return [p for p in self.placed if p["is_buy"]]

    def sells_or_closes(self):
        return [p for p in self.placed if not p["is_buy"]] + self.closes

    # ---- info ----
    def user_state(self, address):
        self.events.append(("user_state",))
        if self.user_state_error:
            raise self.user_state_error
        pos = [] if self.szi == 0 else [{"type": "oneWay", "position": {"coin": COIN, "szi": repr(self.szi)}}]
        return {"assetPositions": pos}

    def open_orders(self, address):
        self.events.append(("open_orders",))
        return [dict(o) for o in self.orders]

    def all_mids(self):
        return {COIN: self.mid}

    def meta(self):
        return {"universe": [{"name": COIN, "szDecimals": 3, "maxLeverage": 10}]}

    def query_order_by_oid(self, address, oid):
        for o in self.orders:
            if o["oid"] == oid:
                return {"status": "order", "order": {"order": dict(o), "status": "open"}}
        status, orig, remaining, px = self.final.get(oid, ("canceled", "0.5", "0.5", "99.0"))
        return {"status": "order", "order": {"order": {
            "coin": COIN, "side": "B", "limitPx": px, "sz": remaining, "oid": oid, "origSz": orig},
            "status": status}}

    # ---- exchange ----
    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.events.append(("order", is_buy))
        oid = self.next_oid
        self.next_oid += 1
        self.placed.append({"coin": coin, "is_buy": is_buy, "size": size, "px": px,
                            "reduce_only": reduce_only, "oid": oid})
        self.add_resting(oid, "B" if is_buy else "A", px, size)
        return {"response": {"data": {"statuses": [{"resting": {"oid": oid}}]}}}

    def cancel(self, coin, oid):
        self.events.append(("cancel", oid))
        self.cancels.append(oid)
        o = next((o for o in self.orders if o["oid"] == oid), None)
        if o is not None:
            self.orders.remove(o)
            self.final[oid] = ("canceled", o["origSz"], o["origSz"], o["limitPx"])
        return CANCEL_OK

    def market_close(self, coin, sz):
        self.events.append(("close", sz))
        self.closes.append(("close", coin, sz))
        if self.close_error:
            return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "no liquidity"}]}}}
        self.szi = 0.0
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": [
            {"filled": {"totalSz": repr(sz), "avgPx": "1.0", "oid": 1}}]}}}

    def update_leverage(self, *a, **k):
        return {"status": "ok"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", [COIN])
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "NUM_LEVELS", 6)
    monkeypatch.setattr(cfg, "STOP_BUFFER_PCT", 0.15)
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 1.0)
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "HALT_ALERT_INTERVAL_MINUTES", 60)
    monkeypatch.setattr(live_mod, "FLATTEN_SETTLE_SECONDS", 0)
    sent: list[str] = []
    monkeypatch.setattr(live_mod, "send_alert", lambda tok, chat, msg: sent.append(msg) or True)

    def build(venue=None, lots=None, armed=None, cap=300.0, live=True, halted=False, pending=None):
        """anchor 100, step 1%, mid 100 -> desired levels -6..-1. `lots`: {level: size} (size*100 is
        its notional at mid; each lot's TP is added to the venue as a resting order)."""
        venue = venue or Venue()
        e = GridBotEngine.__new__(GridBotEngine)
        e.live_trading = live
        e.info = venue
        e.exchange = ResilientExchange(venue)
        e._sz_dec = {}
        e._leverage_set = {COIN}
        c = {"anchor": 100.0, "step_pct": 0.01, "notional_per_level": 50.0, "max_position_notional": cap,
             "armed": {}, "open_lots": {}, "stopped_until_ms": None}
        for lvl, size in (lots or {}).items():
            tp_oid = 5000 + abs(lvl)
            c["open_lots"][str(lvl)] = {"entry_price": level_price(100.0, 0.01, lvl), "size": size,
                                        "tp_price": level_price(100.0, 0.01, lvl + 1), "tp_oid": tp_oid}
            venue.add_resting(tp_oid, "A", level_price(100.0, 0.01, lvl + 1), size)
        for lvl in (armed or []):
            oid = 7000 + abs(lvl)
            c["armed"][str(lvl)] = oid
            venue.add_resting(oid, "B", level_price(100.0, 0.01, lvl), 0.5)
        e.state = {"halted": halted, "peak_equity": 1000.0, "last_fill_check_ms": 0,
                   "bad_equity_reads": 0, "drawdown_breach_cycles": 0, "coins": {COIN: c}}
        if pending is not None:
            e.state["flatten_pending"] = pending
        e.sent = sent
        e.venue = venue
        e.c = c
        return e

    return build


def _armed_oid(level):
    return 7000 + abs(level)


# ---- (a) gap: alert on the 2nd consecutive cycle, once; buys paused; clears --------------------

def test_a_gap_alerts_on_second_cycle_once_pauses_buys_and_clears(env):
    v = Venue(szi=0.7)                                      # books: one 0.5 lot -> gap +0.2
    e = env(v, lots={-9: 0.5}, cap=1000.0)
    assert "gap_cycles" not in e.c                           # old state files have no such key

    e.sync_coin(COIN)                                       # cycle 1: gap seen, no alert, grid built as usual
    assert e.c["gap_cycles"] == 1 and e.sent == []
    assert len(v.buys()) == 6 and len(e.c["armed"]) == 6

    v.drop_externally(e.c["armed"]["-3"])                   # a rung disappears; normally re-placed
    n = len(v.buys())
    e.sync_coin(COIN)                                       # cycle 2: alert once, no new buy
    assert e.c["gap_cycles"] == 2
    assert len(e.sent) == 1 and "HYPE" in e.sent[0] and "0.7" in e.sent[0] and "0.5" in e.sent[0] and "+0.2" in e.sent[0]
    assert len(v.buys()) == n and "-3" not in e.c["armed"]

    e.sync_coin(COIN)                                       # cycle 3: no repeat alert, still paused
    assert e.c["gap_cycles"] == 3 and len(e.sent) == 1 and len(v.buys()) == n

    v.szi = 0.5                                             # gap clears
    e.sync_coin(COIN)
    assert e.c["gap_cycles"] == 0 and len(e.sent) == 1
    assert len(v.buys()) == n + 1 and "-3" in e.c["armed"]

    v.szi = 0.9                                             # a new gap is a new episode: alerts again after 2 cycles
    e.sync_coin(COIN)
    assert len(e.sent) == 1
    e.sync_coin(COIN)
    assert len(e.sent) == 2

    assert v.sells_or_closes() == []                         # (f) nothing traded to "fix" the gap


def test_a2_negative_gap_exchange_has_less_than_books_also_counts(env):
    v = Venue(szi=0.0)
    e = env(v, lots={-9: 0.5}, cap=1000.0)                  # TP still resting, but exchange shows nothing
    e.sync_coin(COIN)
    e.sync_coin(COIN)
    assert e.c["gap_cycles"] == 2 and len(e.sent) == 1 and "-0.5" in e.sent[0]
    assert v.sells_or_closes() == []


def test_a3_gap_below_half_a_size_unit_is_float_noise(env):
    v = Venue(szi=0.5 + 0.0004)                              # szDecimals 3 -> tolerance 0.0005
    e = env(v, lots={-9: 0.5}, cap=1000.0)
    for _ in range(3):
        e.sync_coin(COIN)
    assert e.c["gap_cycles"] == 0 and e.sent == [] and len(v.buys()) == 6


def test_a4_dry_run_never_alerts_counts_or_blocks_on_a_gap(env):
    v = Venue(szi=0.7)                                       # real wallet holds size the dry-run books never saw
    e = env(v, lots={}, cap=1000.0, live=False)
    for _ in range(3):
        e.sync_coin(COIN)
    assert e.sent == [] and e.c.get("gap_cycles", 0) == 0
    assert v.placed == []                                    # dry-run sends nothing; the grid is still "armed"
    assert len(e.c["armed"]) == 6


# ---- (b) partial fills are not gaps ------------------------------------------------------------

def test_b_partial_tp_fill_with_matching_szi_is_not_a_gap(env):
    v = Venue(szi=0.2)                                      # lot 0.5, TP part-filled 0.3 -> 0.2 left
    e = env(v, lots={-9: 0.5}, cap=1000.0)
    v.orders[0]["sz"] = "0.2"                                # TP: origSz 0.5, remaining 0.2
    for _ in range(3):
        e.sync_coin(COIN)
    assert e.c["gap_cycles"] == 0 and e.sent == []
    assert "-9" in e.c["open_lots"]                          # the lot is still the books' (TP still resting)
    assert len(e.c["armed"]) == 6


def test_b2_partial_armed_buy_fill_with_matching_szi_is_not_a_gap(env):
    v = Venue(szi=0.3)                                      # no lots; armed -1 buy filled 0.3 of 0.5
    e = env(v, armed=[-1], cap=1000.0)
    next(o for o in v.orders if o["oid"] == _armed_oid(-1))["sz"] = "0.2"
    for _ in range(3):
        e.sync_coin(COIN)
    assert e.c["gap_cycles"] == 0 and e.sent == []
    assert e.c["armed"]["-1"] == _armed_oid(-1) and e.c["open_lots"] == {}


# ---- (c) unreadable position ---------------------------------------------------------------------

def test_c_unreadable_position_means_no_new_buys_no_gap_and_counter_untouched(env, caplog):
    v = Venue(szi=0.7)
    v.user_state_error = ConnectionError("user_state down")
    e = env(v, lots={-9: 0.5}, cap=1000.0)
    e.c["gap_cycles"] = 1
    for _ in range(3):
        e.sync_coin(COIN)
    assert v.buys() == [] and e.c["armed"] == {}
    assert e.sent == [] and e.c["gap_cycles"] == 1
    assert "unreadable" in caplog.text
    assert v.sells_or_closes() == []


def test_c2_unreadable_position_still_settles_what_the_exchange_reports(env):
    # settlement (armed buy gone from the book -> lot + TP) is not gated on the position read
    v = Venue()
    v.user_state_error = ConnectionError("down")
    e = env(v, armed=[-1], cap=1000.0)
    oid = _armed_oid(-1)
    v.orders = [o for o in v.orders if o["oid"] != oid]
    v.final[oid] = ("filled", "0.5", "0.0", "99.0")
    e.sync_coin(COIN)
    assert e.c["open_lots"]["-1"]["size"] == 0.5 and e.c["armed"] == {}
    assert [p["reduce_only"] for p in v.placed] == [True]    # the TP, and no buy


# ---- (d) R-F: the cap counts resting buys, deepest shed first --------------------------------------

def test_d_at_cap_six_lots_all_six_resting_buys_cancelled_deepest_first(env):
    v = Venue(szi=3.0)                                       # 6 lots x 0.5 x 100 = 300 = cap
    e = env(v, lots={-12: 0.5, -11: 0.5, -10: 0.5, -9: 0.5, -8: 0.5, -7: 0.5},
            armed=[-6, -5, -4, -3, -2, -1], cap=300.0)
    e.sync_coin(COIN)
    assert v.cancels == [_armed_oid(l) for l in (-6, -5, -4, -3, -2, -1)]
    assert e.c["armed"] == {} and v.buys() == []
    assert e.c["gap_cycles"] == 0 and e.sent == []


def test_d2_three_lots_keep_only_the_three_nearest_buys(env):
    v = Venue(szi=1.5)                                       # exposure 150 -> room for 3 buys of 50
    e = env(v, lots={-9: 0.5, -8: 0.5, -7: 0.5}, armed=[-6, -5, -4, -3, -2, -1], cap=300.0)
    e.sync_coin(COIN)
    assert v.cancels == [_armed_oid(l) for l in (-6, -5, -4)]
    assert sorted(e.c["armed"], key=int) == ["-3", "-2", "-1"]
    assert v.buys() == []


def test_d3_empty_book_places_all_six_nearest_first(env):
    v = Venue(szi=0.0)
    e = env(v, cap=300.0)
    e.sync_coin(COIN)
    assert len(v.buys()) == 6 and len(e.c["armed"]) == 6
    pxs = [p["px"] for p in v.buys()]
    assert pxs == sorted(pxs, reverse=True)                   # nearest to the price first


def test_d4_new_buys_stop_when_cap_would_be_exceeded_nearest_levels_kept(env):
    v = Venue(szi=1.5)                                       # exposure 150 -> only 3 buys fit
    e = env(v, lots={-9: 0.5, -8: 0.5, -7: 0.5}, cap=300.0)
    e.sync_coin(COIN)
    assert sorted(e.c["armed"], key=int) == ["-3", "-2", "-1"]
    assert len(v.buys()) == 3


# ---- (e) the cap is measured on the exchange, not the books -------------------------------------------

def test_e_books_empty_but_exchange_at_cap_places_no_buy(env):
    v = Venue(szi=3.0)                                       # 300 at mid = cap; books know nothing
    e = env(v, lots={}, cap=300.0)
    e.sync_coin(COIN)
    assert v.buys() == [] and e.c["armed"] == {}
    assert e.c["gap_cycles"] == 1 and e.sent == []           # first cycle of the gap: not alerted yet
    e.sync_coin(COIN)
    assert len(e.sent) == 1 and v.buys() == []
    assert v.sells_or_closes() == []                          # (f)


def test_e2_untracked_size_cancels_existing_buys_via_the_cap(env):
    v = Venue(szi=3.0)
    e = env(v, lots={}, armed=[-3, -2, -1], cap=300.0)
    e.sync_coin(COIN)
    assert e.c["armed"] == {} and len(v.cancels) == 3
    assert v.sells_or_closes() == []


def test_f_gap_cycles_never_send_a_sell_or_close(env):
    for szi in (0.7, 3.0, -0.4):
        v = Venue(szi=szi)
        e = env(v, lots={-9: 0.5}, cap=300.0)
        for _ in range(4):
            e.sync_coin(COIN)
        assert v.sells_or_closes() == [], szi
        assert [p for p in v.placed if p["reduce_only"]] == []   # not even a protective TP for the gap


# ---- (g) R-E: re-arm finishes a pending flatten first -----------------------------------------------------

def test_g_pending_flatten_not_verified_stays_halted_and_alerts(env, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 990.0)   # equity itself looks recovered
    v = Venue(szi=0.8)
    v.close_error = True
    e = env(v, halted=True, pending=True)
    e.rearm_if_recovered()
    assert e.state["halted"] is True and e.state["flatten_pending"] is True
    assert any("NOT verified" in m and "szi=0.8" in m for m in e.sent)
    assert len(v.closes) == live_mod.FLATTEN_MAX_ROUNDS


def test_g2_pending_flatten_verified_and_drawdown_recovered_rearms(env, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 990.0)
    v = Venue(szi=0.8)
    e = env(v, halted=True, pending=True)
    e.rearm_if_recovered()
    assert v.szi == 0.0 and v.closes == [("close", COIN, 0.8)]
    assert e.state["halted"] is False and e.state["flatten_pending"] is False


def test_g3_pending_flatten_verified_but_drawdown_still_breaching_stays_halted(env, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    v = Venue(szi=0.8)
    e = env(v, halted=True, pending=True)
    e.rearm_if_recovered()
    assert v.szi == 0.0
    assert e.state["halted"] is True and e.state["flatten_pending"] is False


def test_g4_no_pending_flag_rearm_touches_no_position(env, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 990.0)
    v = Venue(szi=0.8)                                       # owner's own position while the bot was halted
    e = env(v, halted=True)                                  # old state: no flatten_pending key
    e.rearm_if_recovered()
    assert e.state["halted"] is False
    assert v.events == [] and v.closes == []


# ---- R-D: settle pause between sends and read-back -----------------------------------------------------------

def test_d_flatten_pauses_between_sends_and_read_back_every_round(env, monkeypatch):
    sleeps = []
    v = Venue(szi=0.8)
    v.close_error = True                                     # never flat -> 3 rounds
    e = env(v)
    monkeypatch.setattr(live_mod, "FLATTEN_SETTLE_SECONDS", 1)
    monkeypatch.setattr(live_mod.time, "sleep", lambda s: (sleeps.append(s), v.events.append(("sleep", s))))
    assert e._flatten_everything() is False
    assert sleeps == [1, 1, 1]
    ev = v.events
    for i, x in enumerate(ev):
        if x[0] == "sleep":
            before = [y[0] for y in ev[:i]]
            after = [y[0] for y in ev[i + 1:]]
            assert before[-1] == "user_state" or before[-1] == "close" or before[-1] == "open_orders"
            last_close = max(j for j, y in enumerate(ev[:i]) if y[0] == "close")
            assert not any(y[0] == "sleep" for y in ev[last_close:i])      # one pause per close
            assert after[0] in ("open_orders", "user_state")               # read-back follows the pause


def test_d2_dry_run_flatten_does_not_sleep(env, monkeypatch):
    sleeps = []
    monkeypatch.setattr(live_mod, "FLATTEN_SETTLE_SECONDS", 1)
    monkeypatch.setattr(live_mod.time, "sleep", sleeps.append)
    e = env(Venue(), live=False)
    assert e._flatten_everything() is True
    assert sleeps == []


# ---- (h) --status ------------------------------------------------------------------------------------------------

def _run_status(monkeypatch, engine):
    monkeypatch.setattr(sys, "argv", ["live", "--status"])
    monkeypatch.setattr(live_mod, "GridBotEngine", lambda live_trading=None: engine)
    monkeypatch.setattr(live_mod, "equity_breakdown", lambda info, addr: {
        "portfolio_value": 1.0, "spot_usdc_total": 1.0, "spot_usdc_hold": 0.0, "spot_coins": 0.0,
        "unpriced_coins": [], "perp_account_value": 1.0, "abstraction": "x"})
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 1.0)
    monkeypatch.setattr(engine, "bootstrap_if_needed", lambda: None)
    live_mod.main()


def test_h_status_prints_szi_tracked_gap_without_side_effects(env, monkeypatch, capsys):
    v = Venue(szi=0.7)
    e = env(v, lots={-9: 0.5}, cap=300.0)
    e.c["gap_cycles"] = 1
    before = dict(e.c)
    _run_status(monkeypatch, e)
    out = capsys.readouterr().out
    assert "szi=0.7" in out and "tracked=0.5" in out and "gap=+0.2" in out
    assert v.placed == [] and v.cancels == [] and v.closes == []
    assert e.c["gap_cycles"] == 1 and e.c == before and e.sent == []


def test_h2_status_survives_unreadable_position(env, monkeypatch, capsys):
    v = Venue(szi=0.7)
    v.user_state_error = ConnectionError("user_state down")
    e = env(v, lots={-9: 0.5}, cap=300.0)
    e.c["gap_cycles"] = 1
    _run_status(monkeypatch, e)
    out = capsys.readouterr().out
    assert "UNREADABLE" in out and "HYPE" in out
    assert e.c["gap_cycles"] == 1 and v.placed == [] and v.cancels == []


def test_h3_status_survives_unreadable_order_list(env, monkeypatch, capsys):
    v = Venue(szi=0.7)

    def boom(address):
        raise ConnectionError("open_orders down")
    v.open_orders = boom
    e = env(v, lots={-9: 0.5}, cap=300.0)
    _run_status(monkeypatch, e)
    assert "UNREADABLE" in capsys.readouterr().out
