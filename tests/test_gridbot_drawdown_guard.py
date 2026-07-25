"""Regression tests for the gridbot drawdown circuit breaker (v2 semantics).

2026-07-21 incident: a flat book with cash parked in perp free margin read as
$0.00 through the old equity basis and tripped a phantom 100% drawdown —
flattening and halting on a failed read, with no operator self-service way
back. The breaker must now:
- treat non-positive or failed equity reads as read failures (skip cycle,
  loud, no flatten), escalating to halt-without-flatten after
  MAX_BAD_EQUITY_READS consecutive failures (counter persisted so a
  crash/restart loop cannot reset the countdown);
- require DRAWDOWN_CONFIRM_CYCLES consecutive breaching readings before
  flatten+halt (debounce against one-sample glitches);
- on service restart, re-arm only if the measured drawdown has actually
  recovered below the threshold (rearm_if_recovered), never resetting peak.
"""
from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod
from hlvault.gridbot.live import GridBotEngine
from hlvault.gridbot.state import load_state


def _make_engine(peak=1000.0, halted=False):
    engine = GridBotEngine.__new__(GridBotEngine)
    engine.live_trading = True
    engine.info = object()  # only reachable via the patched equity fn
    engine.exchange = None
    engine.state = {"halted": halted, "peak_equity": peak,
                    "last_fill_check_ms": 0, "coins": {}}
    engine._sz_dec = {}
    engine._leverage_set = set()
    return engine


def _forbid_flatten(engine):
    def boom():
        raise AssertionError("flatten must not run in this scenario")
    engine._flatten_everything = boom


# ---- failed / implausible reads -----------------------------------------

def test_zero_equity_read_skips_cycle_without_flatten_or_halt(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 10)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 0.0)
    engine = _make_engine(peak=1077.96)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is False
    assert engine.state["peak_equity"] == 1077.96
    assert engine.state["bad_equity_reads"] == 1
    assert "EQUITY READ IMPLAUSIBLE" in caplog.text


def test_negative_equity_read_skips_cycle_without_flatten_or_halt(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 10)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: -20.0)
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is False
    assert engine.state["peak_equity"] == 1000.0


def test_equity_read_exception_skips_cycle_without_flatten_or_halt(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 10)

    def raise_io(info, addr):
        raise ConnectionError("simulated transport failure")

    monkeypatch.setattr(live_mod, "get_full_account_equity", raise_io)
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is False
    assert engine.state["peak_equity"] == 1000.0
    assert "EQUITY READ FAILED" in caplog.text


# ---- real breach with confirmation debounce ------------------------------

def test_real_drawdown_trips_breaker_when_confirm_cycles_is_one(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 1)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine = _make_engine(peak=1000.0)
    called = []
    engine._flatten_everything = lambda: called.append(True)
    assert engine.check_drawdown() is True
    assert called == [True]
    assert engine.state["halted"] is True
    assert (tmp_path / "state.json").exists()


def test_breach_needs_consecutive_confirm_cycles(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 3)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine = _make_engine(peak=1000.0)
    called = []
    engine._flatten_everything = lambda: called.append(True)
    assert engine.check_drawdown() is True   # breach 1/3 — no flatten yet
    assert called == []
    assert engine.state["halted"] is False
    assert engine.state["drawdown_breach_cycles"] == 1
    assert engine.check_drawdown() is True   # breach 2/3
    assert called == []
    assert engine.state["halted"] is False
    assert engine.check_drawdown() is True   # breach 3/3 — flatten + halt
    assert called == [True]
    assert engine.state["halted"] is True


def test_breach_counter_resets_on_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 3)
    readings = iter([700.0, 990.0, 700.0])
    monkeypatch.setattr(live_mod, "get_full_account_equity",
                        lambda info, addr: next(readings))
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True   # breach 1/3
    assert engine.state["drawdown_breach_cycles"] == 1
    assert engine.check_drawdown() is False  # recovered — counter resets
    assert engine.state["drawdown_breach_cycles"] == 0
    assert engine.check_drawdown() is True   # breach again: back to 1/3
    assert engine.state["halted"] is False


def test_failed_read_between_breaches_neither_resets_nor_advances_breach_counter(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 3)
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 10)
    readings = iter([700.0, 0.0, 700.0, 700.0])
    monkeypatch.setattr(live_mod, "get_full_account_equity",
                        lambda info, addr: next(readings))
    engine = _make_engine(peak=1000.0)
    called = []
    engine._flatten_everything = lambda: called.append(True)
    assert engine.check_drawdown() is True   # breach 1/3
    assert engine.state["drawdown_breach_cycles"] == 1
    assert engine.check_drawdown() is True   # failed read: breach counter untouched
    assert engine.state["drawdown_breach_cycles"] == 1
    assert engine.state["bad_equity_reads"] == 1
    assert engine.check_drawdown() is True   # breach 2/3 — interleaved failure did not reset it
    assert engine.state["drawdown_breach_cycles"] == 2
    assert called == []
    assert engine.check_drawdown() is True   # breach 3/3 — flatten + halt
    assert called == [True]
    assert engine.state["halted"] is True


def test_breach_counter_persists_across_restart(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(cfg, "STATE_FILE", state_file)
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 3)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True   # breach 1/3, persisted
    assert engine.check_drawdown() is True   # breach 2/3, persisted
    assert engine.state["halted"] is False
    engine2 = _make_engine(peak=1000.0)
    engine2.state = load_state(state_file)
    called = []
    engine2._flatten_everything = lambda: called.append(True)
    assert engine2.state["drawdown_breach_cycles"] == 2
    assert engine2.check_drawdown() is True  # breach 3/3 across the restart
    assert called == [True]
    assert engine2.state["halted"] is True


# ---- healthy path ---------------------------------------------------------

def test_healthy_equity_passes_updates_peak_and_resets_counters(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 1050.0)
    engine = _make_engine(peak=1000.0)
    engine.state["bad_equity_reads"] = 5
    engine.state["drawdown_breach_cycles"] = 2
    _forbid_flatten(engine)
    assert engine.check_drawdown() is False
    assert engine.state["halted"] is False
    assert engine.state["peak_equity"] == 1050.0
    assert engine.state["bad_equity_reads"] == 0
    assert engine.state["drawdown_breach_cycles"] == 0


def test_halted_state_short_circuits_before_any_equity_read(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")

    def must_not_be_called(info, addr):
        raise AssertionError("equity must not be fetched while halted")

    monkeypatch.setattr(live_mod, "get_full_account_equity", must_not_be_called)
    engine = _make_engine(halted=True)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True


# ---- failed-read escalation ------------------------------------------------

def test_consecutive_bad_reads_escalate_to_halt_without_flatten(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 3)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 0.0)
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is False
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is False
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is True
    assert (tmp_path / "state.json").exists()
    # once halted, the next cycle short-circuits on the halted flag
    assert engine.check_drawdown() is True


def test_successful_read_resets_escalation_counter(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 2)
    readings = iter([0.0, 1050.0, 0.0])
    monkeypatch.setattr(live_mod, "get_full_account_equity",
                        lambda info, addr: next(readings))
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True   # bad read 1/2
    assert engine.state["halted"] is False
    assert engine.check_drawdown() is False  # healthy read resets the counter
    assert engine.state["bad_equity_reads"] == 0
    assert engine.check_drawdown() is True   # bad read again: back to 1/2
    assert engine.state["halted"] is False


def test_bad_read_counter_persists_across_restart(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(cfg, "STATE_FILE", state_file)
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 3)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 0.0)
    engine = _make_engine(peak=1000.0)
    _forbid_flatten(engine)
    assert engine.check_drawdown() is True   # 1/3
    assert engine.check_drawdown() is True   # 2/3
    assert engine.state["halted"] is False
    engine2 = _make_engine(peak=1000.0)
    engine2.state = load_state(state_file)
    _forbid_flatten(engine2)
    assert engine2.state["bad_equity_reads"] == 2
    assert engine2.check_drawdown() is True  # 3/3 — escalates across the restart
    assert engine2.state["halted"] is True


# ---- restart re-arm ---------------------------------------------------------

def test_rearm_recovers_when_drawdown_back_under_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 990.0)
    engine = _make_engine(peak=1000.0, halted=True)
    engine.state["bad_equity_reads"] = 10
    engine.state["drawdown_breach_cycles"] = 3
    _forbid_flatten(engine)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is False
    assert engine.state["bad_equity_reads"] == 0
    assert engine.state["drawdown_breach_cycles"] == 0
    assert engine.state["peak_equity"] == 1000.0  # peak never reset by restart
    assert (tmp_path / "state.json").exists()


def test_rearm_stays_halted_when_still_breaching(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine = _make_engine(peak=1000.0, halted=True)
    _forbid_flatten(engine)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is True


def test_rearm_stays_halted_on_failed_read(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")

    def raise_io(info, addr):
        raise ConnectionError("simulated transport failure")

    monkeypatch.setattr(live_mod, "get_full_account_equity", raise_io)
    engine = _make_engine(peak=1000.0, halted=True)
    _forbid_flatten(engine)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is True


def test_rearm_stays_halted_on_implausible_read(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 0.0)
    engine = _make_engine(peak=1000.0, halted=True)
    _forbid_flatten(engine)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is True


def test_rearm_is_noop_when_not_halted(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")

    def must_not_be_called(info, addr):
        raise AssertionError("equity must not be fetched when not halted")

    monkeypatch.setattr(live_mod, "get_full_account_equity", must_not_be_called)
    engine = _make_engine(halted=False)
    _forbid_flatten(engine)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is False
