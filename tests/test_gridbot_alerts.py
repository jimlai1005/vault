"""gridbot Telegram alerting: trip -> immediate alert; halted -> periodic reminder;
re-arm -> resumed alert. send_alert is always monkeypatched (no network in tests)."""
import json

import pytest

from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod
from hlvault.gridbot.live import GridBotEngine


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 1)
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 2)
    monkeypatch.setattr(cfg, "HALT_ALERT_INTERVAL_MINUTES", 60)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "chat")
    sent = []
    monkeypatch.setattr(live_mod, "send_alert", lambda tok, chat, msg: sent.append(msg) or True)
    e = GridBotEngine.__new__(GridBotEngine)
    e.info = object()
    e.exchange = None
    e.live_trading = False
    e._leverage_set = set()
    e.state = {"halted": False, "peak_equity": 1000.0, "last_fill_check_ms": 0,
               "coins": {}, "bad_equity_reads": 0, "drawdown_breach_cycles": 0}
    e.sent = sent
    return e


def test_trip_sends_immediate_alert_with_numbers(engine, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    monkeypatch.setattr(engine, "_flatten_everything", lambda: True)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is True
    assert len(engine.sent) == 1
    assert "30.0%" in engine.sent[0] and "1,000.00" in engine.sent[0] and "700.00" in engine.sent[0]
    assert engine.state["last_halt_alert_ms"] > 0


def test_trip_with_incomplete_flatten_alerts_twice(engine, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    monkeypatch.setattr(engine, "_flatten_everything", lambda: False)
    engine.check_drawdown()
    assert any("FLATTEN INCOMPLETE" in m for m in engine.sent)


def test_halted_reminder_repeats_only_after_interval(engine, monkeypatch):
    engine.state["halted"] = True
    engine.state["last_halt_alert_ms"] = 0
    now = [10_000_000_000]
    monkeypatch.setattr(live_mod.time, "time", lambda: now[0] / 1000.0)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine.check_drawdown()
    assert len(engine.sent) == 1 and "HALTED" in engine.sent[0]
    engine.check_drawdown()                       # same minute -> no new alert
    assert len(engine.sent) == 1
    now[0] += 59 * 60_000
    engine.check_drawdown()
    assert len(engine.sent) == 1
    now[0] += 2 * 60_000                          # 61 min after first -> reminder
    engine.check_drawdown()
    assert len(engine.sent) == 2
    assert "restart hl-gridbot" in engine.sent[1]


def test_halted_reminder_survives_equity_read_failure(engine, monkeypatch):
    engine.state["halted"] = True
    engine.state["last_halt_alert_ms"] = 0

    def boom(info, addr):
        raise RuntimeError("api down")
    monkeypatch.setattr(live_mod, "get_full_account_equity", boom)
    engine.check_drawdown()
    assert len(engine.sent) == 1 and "unreadable" in engine.sent[0].lower()


def test_rearm_sends_resumed_alert(engine, monkeypatch):
    engine.state["halted"] = True
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 950.0)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is False
    assert len(engine.sent) == 1 and "RE-ARMED" in engine.sent[0]


def test_rearm_still_breaching_alerts_with_reason(engine, monkeypatch):
    engine.state["halted"] = True
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is True
    assert len(engine.sent) == 1 and "still" in engine.sent[0].lower() and "30.0%" in engine.sent[0]


def test_unreadable_equity_halt_alerts(engine, monkeypatch):
    def boom(info, addr):
        raise RuntimeError("api down")
    monkeypatch.setattr(live_mod, "get_full_account_equity", boom)
    engine.check_drawdown()
    assert engine.sent == []                      # 1/2 failed reads: no alert yet
    engine.check_drawdown()                       # 2/2 -> halt without flatten
    assert engine.state["halted"] is True
    assert any("UNREADABLE" in m for m in engine.sent)


def test_alert_failure_never_blocks_halt(engine, monkeypatch):
    monkeypatch.setattr(live_mod, "send_alert", lambda tok, chat, msg: False)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    monkeypatch.setattr(engine, "_flatten_everything", lambda: True)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is True


class _FakeExchange:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def market_close(self, coin, sz):
        self.calls.append((coin, sz))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_market_flatten_returns_true_on_filled(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"totalSz": "0.0238", "avgPx": "2722.9", "oid": 1}}]}}})
    assert engine._market_flatten("ETH", 0.0238) is True
    assert engine.exchange.calls == [("ETH", 0.0238)]


def test_market_flatten_returns_true_when_no_position_left(engine):
    # SDK returns None when the coin has no position: nothing to close == flat
    engine.live_trading = True
    engine.exchange = _FakeExchange(None)
    assert engine._market_flatten("ETH", 0.0238) is True


def test_market_flatten_returns_false_on_rejected_status(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"error": "Insufficient margin"}]}}})
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_returns_false_on_err_status(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "err", "response": "rate limited"})
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_returns_false_on_exception(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange(RuntimeError("connection reset"))
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_dry_run_returns_true_without_calling_exchange(engine):
    engine.live_trading = False
    engine.exchange = _FakeExchange(RuntimeError("must not be called"))
    assert engine._market_flatten("ETH", 0.0238) is True
    assert engine.exchange.calls == []


def test_flatten_everything_drops_lot_only_when_both_cancel_and_flatten_confirmed(engine, monkeypatch):
    engine.state["coins"] = {"ETH": {"armed": {}, "open_lots": {
        "122": {"entry_price": 2749.6, "size": 0.0238, "tp_price": 2761.7, "tp_oid": 1}},
        "stopped_until_ms": None}}
    monkeypatch.setattr(engine, "_cancel", lambda coin, oid: True)
    monkeypatch.setattr(engine, "_market_flatten", lambda coin, size: True)
    assert engine._flatten_everything() is True
    assert engine.state["coins"]["ETH"]["open_lots"] == {}
    engine.state["coins"]["ETH"]["open_lots"]["122"] = {"entry_price": 2749.6, "size": 0.0238, "tp_price": 2761.7, "tp_oid": 1}
    monkeypatch.setattr(engine, "_market_flatten", lambda coin, size: False)
    assert engine._flatten_everything() is False
    assert "122" in engine.state["coins"]["ETH"]["open_lots"]


def test_market_flatten_returns_false_on_partial_fill(engine):
    # IOC with 5% slippage can fill only part of the size in a thin book; the rest is
    # cancelled by the exchange. That is NOT flat — the lot must stay tracked.
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"totalSz": "0.0100", "avgPx": "2722.9", "oid": 1}}]}}})
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_accepts_fill_within_size_rounding(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"totalSz": "0.02379", "avgPx": "2722.9", "oid": 1}}]}}})
    assert engine._market_flatten("ETH", 0.0238) is True


def test_trip_persists_halt_to_disk_before_flatten_and_alerts_after(engine, monkeypatch):
    import json as _json
    order = []
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)

    def fake_flatten():
        on_disk = _json.loads(cfg.STATE_FILE.read_text())
        order.append(("flatten", on_disk.get("halted"), len(engine.sent)))
        return True
    monkeypatch.setattr(engine, "_flatten_everything", fake_flatten)
    engine.check_drawdown()
    # flatten ran with halted already persisted and before any Telegram round-trip
    assert order == [("flatten", True, 0)]
    assert len(engine.sent) == 1 and "TRIPPED" in engine.sent[0]
