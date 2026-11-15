"""R-G / R-H / R-I of docs/plans/gridbot-position-truth.md (reviewer findings after T4).

R-G (Critical): a stop-loss exit that did not verify flat must keep running until the read-back is
flat, no matter where the price goes. Before the fix a bounce above the stop price made the normal
flow read the (already cancelled) TP as "filled" and delete the lot: an exchange position with no TP,
no stop and no book entry (same consequence as 2026-11-05).
R-H (Warning): a reconcile that cannot be read for RECONCILE_FAIL_ALERT_CYCLES cycles in a row alerts once.
R-I (Suggestion): the gap alert is flag-based (`gap_cycles >= N and not gap_alerted`), not `== N`.

All I/O is a stateful fake venue; nothing touches the network."""
import json

import pytest

from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod

import test_gridbot_flatten_truth as ft
import test_gridbot_position_truth as pt
from test_gridbot_flatten_truth import _no_flatten_settle_sleep  # noqa: F401  (autouse: never really sleep)

env_ft = ft.env     # fixture re-exported under another name: stop-loss scenarios (several coins, partial closes)
env_pt = pt.env     # fixture re-exported under another name: reconcile scenarios (one coin, resting-order shape)


def _stop_engine(env, szi=0.5, lot_size=0.5, **kw):
    v = ft.Venue({"HYPE": szi}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 80.0       # lot at level -1: stop = 99 * 0.85 = 84.15 -> triggered
    e = env(v, lots={"HYPE": {"-1": ft._lot(lot_size)}}, **kw)
    return e, v


# ---- (a) R-G: partial close, then the price bounces above the stop ---------------------------------

def test_g_a_partial_stop_then_bounce_keeps_closing_until_verified(env_ft, monkeypatch):
    e, v = _stop_engine(env_ft)
    v.close_fractions = [0.5]                     # cycle 1: only half of the position gets closed
    tp_filled_calls = []
    real = e._on_tp_filled
    monkeypatch.setattr(e, "_on_tp_filled", lambda coin, lvl: (tp_filled_calls.append((coin, lvl)), real(coin, lvl)))
    c = e.state["coins"]["HYPE"]

    e.sync_coin("HYPE")                           # cycle 1: stop triggers, exit not verified
    assert v.positions["HYPE"] == pytest.approx(0.25)
    assert c["open_lots"] != {} and c["stop_pending"] is True and c["stopped_until_ms"] is None
    assert len(e.sent) == 1 and "HYPE" in e.sent[0] and "0.25" in e.sent[0]

    v.mid = 95.0                                  # bounced above the stop price (84.15)
    e.sync_coin("HYPE")                           # cycle 2: still the exit, whatever the price
    assert v.positions["HYPE"] == pytest.approx(0.0)
    assert c["open_lots"] == {} and c["stop_pending"] is False and c["stopped_until_ms"] is not None
    assert len(e.sent) == 2 and "verified" in e.sent[1].lower() and "HYPE" in e.sent[1]
    assert v.calls_of("order") == []              # no new buy, no new TP, in either cycle
    assert tp_filled_calls == []                  # the lot was never "TP filled"-deleted
    assert c["armed"] == {}


def test_g_a2_pending_cycle_does_nothing_but_the_exit(env_ft):
    e, v = _stop_engine(env_ft)
    v.close_error = True                          # exit cannot finish: several cycles stay pending
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["stop_pending"] is True
    v.mid = 200.0                                 # far above any stop from here on
    for _ in range(3):
        e.sync_coin("HYPE")
        assert v.calls_of("order") == []          # never a buy / TP
        assert c["open_lots"] != {} and c["stop_pending"] is True
    assert len(e.sent) == 1                       # repeated failures do not repeat the alert
    assert len(v.calls_of("close")) >= 4          # the exit really re-ran every cycle (1 close per run)


def test_g_a3_stop_pending_is_persisted_before_the_exit_runs(env_ft, monkeypatch):
    e, v = _stop_engine(env_ft)
    seen = {}

    def spy(coin):
        seen["on_disk"] = json.loads(cfg.STATE_FILE.read_text())["coins"][coin].get("stop_pending")
        return True
    monkeypatch.setattr(e, "_stop_loss_exit", spy)
    e.sync_coin("HYPE")
    assert seen["on_disk"] is True                # a crash inside the exit must leave the flag behind
    assert json.loads(cfg.STATE_FILE.read_text())["coins"]["HYPE"]["stop_pending"] is False


def test_g_a4_stop_pending_is_not_blocked_by_the_cooldown_gate(env_ft):
    e, v = _stop_engine(env_ft, szi=0.5)
    c = e.state["coins"]["HYPE"]
    c["stop_pending"] = True
    c["stopped_until_ms"] = 10**15                # a cooldown stamp left over must not skip the exit
    e.sync_coin("HYPE")
    assert v.positions["HYPE"] == pytest.approx(0.0)
    assert c["stop_pending"] is False


# ---- (b) R-G: position unreadable at the stop -------------------------------------------------------

def test_g_b_unreadable_position_stays_pending_alerts_once_then_completes(env_ft):
    e, v = _stop_engine(env_ft)
    v.user_state_raises_on = {"all"}
    c = e.state["coins"]["HYPE"]

    e.sync_coin("HYPE")
    assert c["stop_pending"] is True and c["open_lots"] != {}
    assert len(e.sent) == 1 and "HYPE" in e.sent[0] and "unreadable" in e.sent[0].lower()

    v.mid = 95.0
    e.sync_coin("HYPE")
    e.sync_coin("HYPE")                           # 3 cycles unreadable in total
    assert len(e.sent) == 1 and c["stop_pending"] is True
    assert v.calls_of("close") == [] and v.calls_of("order") == []

    v.user_state_raises_on = set()                # 4th cycle: readable
    e.sync_coin("HYPE")
    assert v.positions["HYPE"] == pytest.approx(0.0)
    assert c["stop_pending"] is False and c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert len(e.sent) == 2 and "verified" in e.sent[1].lower()
    assert v.calls_of("order") == []


def test_g_b2_first_try_success_sends_one_verified_alert_and_clears_flag(env_ft):
    e, v = _stop_engine(env_ft)                   # R-L: a clean first-try stop-loss is announced too
    e.sync_coin("HYPE")
    c = e.state["coins"]["HYPE"]
    assert c["stop_pending"] is False and c["open_lots"] == {} and c["stopped_until_ms"] is not None
    assert len(e.sent) == 1 and "verified" in e.sent[0].lower() and "HYPE" in e.sent[0]


# ---- (c) R-G: old state files / books cleared ---------------------------------------------------------

def test_g_c_old_state_without_stop_pending_runs_normally(env_ft):
    v = ft.Venue({"HYPE": 0.5}, orders=[{"coin": "HYPE", "oid": 55}])
    v.mid = 100.0                                 # above the stop: ordinary cycle
    e = env_ft(v, lots={"HYPE": {"-1": ft._lot(0.5)}})
    c = e.state["coins"]["HYPE"]
    assert "stop_pending" not in c
    e.sync_coin("HYPE")                           # must not KeyError, must not treat the lot as stopped
    assert "-1" in c["open_lots"] and not c.get("stop_pending")
    assert v.calls_of("close") == []


def test_g_c2_old_state_stop_trigger_ends_with_flag_false(env_ft):
    e, v = _stop_engine(env_ft)
    assert "stop_pending" not in e.state["coins"]["HYPE"]
    e.sync_coin("HYPE")
    assert e.state["coins"]["HYPE"]["stop_pending"] is False


def test_g_c3_clear_tracked_books_clears_stop_pending(env_ft):
    e = env_ft(ft.Venue())
    e.state["coins"]["BTC"]["stop_pending"] = True
    e.state["coins"]["ETH"]["stop_pending"] = True
    e._clear_tracked_books()
    assert [e.state["coins"][c]["stop_pending"] for c in ("BTC", "ETH", "HYPE")] == [False, False, False]


def test_g_c4_flatten_everything_success_clears_stop_pending(env_ft):
    v = ft.Venue({"HYPE": 0.5})
    e = env_ft(v)
    e.state["coins"]["HYPE"]["stop_pending"] = True
    assert e._flatten_everything() is True
    assert e.state["coins"]["HYPE"]["stop_pending"] is False


# ---- (d) R-H: reconcile unreadable for N cycles in a row ----------------------------------------------

def _break_orig_sz(v):
    """openOrders answers without origSz: the reconcile (partial-fill accounting) cannot parse it."""
    orig = v.open_orders

    def oo(addr):
        return [{k: x for k, x in o.items() if k != "origSz"} for o in orig(addr)]
    v.open_orders = oo
    return orig


def test_h_d_reconcile_unreadable_alerts_once_at_five_resets_on_recovery(env_pt):
    v = pt.Venue(szi=0.0)
    e = env_pt(v, cap=300.0)
    e.sync_coin(pt.COIN)                          # cycle 1: healthy, grid built
    n_buys = len(v.buys())
    assert n_buys > 0 and e.sent == []
    healthy = v.open_orders
    _break_orig_sz(v)

    for i in range(1, 5):
        e.sync_coin(pt.COIN)
        assert e.c["reconcile_fail_cycles"] == i and e.sent == []
    e.sync_coin(pt.COIN)                          # 5th consecutive failure
    assert e.c["reconcile_fail_cycles"] == 5 and len(e.sent) == 1
    assert "HYPE" in e.sent[0] and "origSz" in e.sent[0]       # last error is attached
    for _ in range(3):                            # cycles 6-8: no repeat
        e.sync_coin(pt.COIN)
    assert e.c["reconcile_fail_cycles"] == 8 and len(e.sent) == 1
    assert len(v.buys()) == n_buys                # nothing traded or flattened because of it
    assert v.sells_or_closes() == [] and v.cancels == []
    assert not e.state.get("halted")

    v.open_orders = healthy                       # readable again
    e.sync_coin(pt.COIN)
    assert e.c["reconcile_fail_cycles"] == 0 and len(e.sent) == 1

    _break_orig_sz(v)                             # breaks again: a new episode alerts again at 5
    for _ in range(4):
        e.sync_coin(pt.COIN)
    assert len(e.sent) == 1
    e.sync_coin(pt.COIN)
    assert len(e.sent) == 2


def test_h_d2_dry_run_never_alerts_on_unreadable_reconcile(env_pt):
    v = pt.Venue(szi=0.0)
    e = env_pt(v, cap=300.0, live=False)
    v.user_state_error = ConnectionError("down")
    for _ in range(7):
        e.sync_coin(pt.COIN)
    assert e.sent == []


def test_h_d3_unreadable_position_also_counts(env_pt):
    v = pt.Venue(szi=0.0)
    v.user_state_error = ConnectionError("user_state down")
    e = env_pt(v, cap=300.0)
    for _ in range(5):
        e.sync_coin(pt.COIN)
    assert len(e.sent) == 1 and "user_state down" in e.sent[0]


# ---- (e) R-I: flag-based gap alert ----------------------------------------------------------------------

def test_i_e_stale_gap_counter_alerts_on_first_cycle_once_and_pauses_buys(env_pt):
    v = pt.Venue(szi=0.7)
    e = env_pt(v, cap=1000.0)
    e.c["gap_cycles"] = 4                         # left over from before a halt/flatten/stop
    e.sync_coin(pt.COIN)
    assert len(e.sent) == 1 and e.c["gap_alerted"] is True and v.buys() == []
    for _ in range(2):
        e.sync_coin(pt.COIN)
    assert len(e.sent) == 1 and v.buys() == []


def test_i_e2_gap_clearing_resets_counter_and_flag_then_new_episode_alerts_after_two_cycles(env_pt):
    v = pt.Venue(szi=0.7)
    e = env_pt(v, cap=1000.0)
    e.sync_coin(pt.COIN)
    e.sync_coin(pt.COIN)
    assert len(e.sent) == 1 and e.c["gap_alerted"] is True
    v.szi = 0.0                                   # gap gone
    e.sync_coin(pt.COIN)
    assert e.c["gap_cycles"] == 0 and e.c["gap_alerted"] is False
    v.szi = 0.9                                   # new episode
    e.sync_coin(pt.COIN)
    assert len(e.sent) == 1
    e.sync_coin(pt.COIN)
    assert len(e.sent) == 2


def test_i_e3_books_cleared_and_verified_stop_reset_gap_state(env_ft):
    e = env_ft(ft.Venue())
    for c in e.state["coins"].values():
        c["gap_cycles"], c["gap_alerted"] = 6, True
    e._clear_tracked_books()
    assert all(c["gap_cycles"] == 0 and c["gap_alerted"] is False for c in e.state["coins"].values())

    e2, v2 = _stop_engine(env_ft)
    h = e2.state["coins"]["HYPE"]
    h["gap_cycles"], h["gap_alerted"] = 3, True
    e2.sync_coin("HYPE")
    assert h["stop_pending"] is False and h["gap_cycles"] == 0 and h["gap_alerted"] is False
