"""CarryEngine live-loop tests. All exchange writes are captured by fakes;
conftest's autouse socket guard hard-fails any real network call."""
import time

from hlvault.carry import config as cfg
from hlvault.carry.live import CarryEngine, _round_spot_price


class _FakeInfo:
    def __init__(self, mid=100.0, spot_usdc=1000.0, spot_hype=0.0, szi=0.0,
                 margin="0.0", upnl="0.0", withdrawable="0.0"):
        self.mid, self._szi = mid, szi
        self._spot_usdc, self._spot_hype = spot_usdc, spot_hype
        self._margin, self._upnl, self._wd = margin, upnl, withdrawable

    def all_mids(self):
        return {"HYPE": str(self.mid), "@107": str(self.mid)}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc), "hold": "0"},
                             {"coin": "HYPE", "total": str(self._spot_hype), "hold": "0"}]}

    def user_state(self, address):
        pos = [] if float(self._szi) == 0 else [{"position": {
            "coin": "HYPE", "szi": str(self._szi), "marginUsed": self._margin,
            "unrealizedPnl": self._upnl}}]
        return {"assetPositions": pos, "withdrawable": self._wd}

    def meta(self):
        return {"universe": [{"name": "HYPE", "szDecimals": 2, "maxLeverage": 5}]}


class _FakeExchange:
    def __init__(self):
        self.orders = []
        self.transfers = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders.append({"coin": coin, "is_buy": is_buy, "size": size,
                            "px": px, "reduce_only": reduce_only})
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    def market_close(self, coin, size):
        self.orders.append({"coin": coin, "market_close": size})
        return {"status": "ok"}

    def usd_class_transfer(self, amount, to_perp):
        self.transfers.append((amount, to_perp))
        return {"status": "ok"}


def _engine(info, exchange, live=True, state=None):
    e = CarryEngine.__new__(CarryEngine)
    e.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    e.exchange = ResilientExchange(exchange)
    e.exchange_raw = exchange
    e.live_trading = live
    e.state = state or {"halted": False, "peak_equity": 0.0,
                        "_alerted_this_halt": False, "_flatten_complete": False,
                        "last_funding_check_ms": 0, "funding_ok": True}
    return e


def test_round_spot_price_rule():
    # SPOT rule (matches SDK Exchange._slippage_price for spot assets):
    # <=5 significant figures AND <=(8 - szDecimals) decimal places.
    # (Perp rule is 6 - szDecimals — see gridbot.exchange_utils.round_price.)
    assert _round_spot_price(66.123456789, 2) == 66.123        # sig figs bind
    assert _round_spot_price(0.00012345678, 0) == 0.00012346   # 8 decimals allowed
    # decimal clamp binds: szDecimals=2 -> max 6 decimals, NOT 0.00012346
    assert _round_spot_price(0.00012345678, 2) == 0.000123


def test_dry_run_executes_nothing(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=False)
    from hlvault.carry.engine import Action
    e._execute(Action("buy_spot", size=1.0))
    e._execute(Action("to_perp", amount=100.0))
    assert ex.orders == [] and ex.transfers == []


def test_execute_buy_spot_uses_spot_pair_and_rounding(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    monkeypatch.setattr(cfg, "SPOT_PAIR", "@107")
    monkeypatch.setattr(cfg, "SPOT_SZ_DECIMALS", 2)
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=66.123456), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("buy_spot", size=1.23456))
    o = ex.orders[0]
    assert o["coin"] == "@107"
    assert o["is_buy"] is True
    assert o["size"] == 1.23   # spot szDecimals=2
    assert o["reduce_only"] is False


def test_execute_open_short_is_perp_not_reduce_only(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("open_short", size=2.0))
    o = ex.orders[0]
    assert o["coin"] == "HYPE" and o["is_buy"] is False and o["reduce_only"] is False


def test_execute_close_short_is_reduce_only(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0, szi=-2.0, margin="100", withdrawable="50"), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("close_short", size=2.0))
    assert ex.orders[0]["reduce_only"] is True


def test_transfer_calls_usd_class_transfer(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("to_perp", amount=300.0))
    e._execute(Action("to_spot", amount=50.0))
    assert ex.transfers == [(300.0, True), (50.0, False)]


def test_drawdown_halt_persists_before_flatten(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    monkeypatch.setattr(cfg, "SPOT_PAIR", "@107")
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _CrashingExchange(_FakeExchange):
        def market_close(self, coin, size):
            raise RuntimeError("boom")

    calls = {"n": 0}

    class _DropInfo(_FakeInfo):
        def spot_user_state(self, address):
            calls["n"] += 1
            usdc = "1000.0" if calls["n"] <= 1 else "750.0"
            return {"balances": [{"coin": "USDC", "total": usdc, "hold": "0"},
                                 {"coin": "HYPE", "total": "1.0", "hold": "0"}]}

    # mid=20 (not the plan's 10) so both legs' notionals ($20) clear
    # MIN_ORDER_NOTIONAL ($12) and the flatten actually attempts (and crashes
    # on) market_close — with mid=10 the $10 legs were skipped as dust and
    # _flatten_complete would have been True, defeating the test's intent.
    info = _DropInfo(mid=20.0, szi=-1.0, margin="20", withdrawable="10")
    e = _engine(info, _CrashingExchange(), live=True)
    assert e.check_drawdown() is False   # first: sets peak (1000+20+20+0+10=1050)
    assert e.check_drawdown() is True    # second: 800/1050 -> ~23.8% dd -> halt
    from hlvault.carry.state import load_state
    assert load_state(cfg.STATE_FILE)["halted"] is True
    assert load_state(cfg.STATE_FILE)["_flatten_complete"] is False


def test_run_once_skips_planning_when_halted(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=True,
                state={"halted": True, "peak_equity": 1000.0,
                       "_alerted_this_halt": True, "_flatten_complete": True,
                       "last_funding_check_ms": 0, "funding_ok": True})
    e.run_once()
    assert ex.orders == [] and ex.transfers == []


def test_oversized_close_short_clamped_to_live_position(monkeypatch, tmp_path):
    # Regression: engine.py's underwater branch (perp_equity < 0, nothing
    # left to sell/transfer) plans close_short size = excess_ntl/mid, which
    # EXCEEDS the live short — test_carry_engine.py documents the clamp as
    # the live loop's job. Verify run_once bounds it by the real position.
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    monkeypatch.setattr(cfg, "SPOT_PAIR", "@107")
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    monkeypatch.setattr(cfg, "MAX_SHORT_LEVERAGE", 2.0)
    monkeypatch.setattr(cfg, "REBALANCE_LEVERAGE", 2.5)
    ex = _FakeExchange()
    # short 2.0 @ mid 10 (ntl $20), perp equity 5-15+0 = -10 (underwater),
    # no spot coin/USDC -> plan: close_short size = (20 - (-10*2.0))/10 = 4.0
    info = _FakeInfo(mid=10.0, spot_usdc=0.0, spot_hype=0.0, szi=-2.0,
                     margin="5", upnl="-15", withdrawable="0")
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 0.0,
                       "_alerted_this_halt": False, "_flatten_complete": False,
                       "last_funding_check_ms": int(time.time() * 1000),
                       "funding_ok": True})
    e.run_once()
    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["coin"] == "HYPE" and o["is_buy"] is True and o["reduce_only"] is True
    assert o["size"] == 2.0   # clamped to live short, NOT the planned 4.0


def test_second_halt_episode_alerts_and_flattens_again(monkeypatch, tmp_path):
    # Regression: without resetting _alerted_this_halt/_flatten_complete on
    # healthy cycles, a SECOND drawdown halt (after the operator clears
    # `halted`) would be silent: no alert, no flatten attempt.
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    monkeypatch.setattr(cfg, "COIN", "HYPE")
    monkeypatch.setattr(cfg, "SPOT_PAIR", "@107")
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _CrashingExchange(_FakeExchange):
        def __init__(self):
            super().__init__()
            self.close_calls = 0

        def market_close(self, coin, size):
            self.close_calls += 1
            raise RuntimeError("boom")

    # equity basis: usdc + 1.0*20 spot HYPE + (20+0+10) perp = usdc + 50
    info = _FakeInfo(mid=20.0, spot_usdc=1000.0, spot_hype=1.0, szi=-1.0,
                     margin="20", withdrawable="10")
    ex = _CrashingExchange()
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 0.0,
                       "_alerted_this_halt": False, "_flatten_complete": False,
                       "last_funding_check_ms": int(time.time() * 1000),
                       "funding_ok": True})

    # episode 1: peak 1050, drop to 800 -> ~23.8% dd -> halt, flatten crashes
    assert e.check_drawdown() is False
    info._spot_usdc = 750.0
    assert e.check_drawdown() is True
    assert ex.close_calls == 1
    assert e.state["_alerted_this_halt"] is True
    assert e.state["_flatten_complete"] is False

    # operator inspects, flattens manually, clears the halt; equity recovers
    e.state["halted"] = False
    info._spot_usdc = 1000.0
    e.run_once()   # healthy cycle -> flags re-armed
    assert e.state["_alerted_this_halt"] is False
    assert e.state["_flatten_complete"] is False

    # episode 2: drop to 650 -> ~38% dd -> must alert AND flatten again
    info._spot_usdc = 600.0
    assert e.check_drawdown() is True
    assert ex.close_calls == 2   # flatten attempted again, not silently skipped
    assert e.state["_alerted_this_halt"] is True
    assert e.state["_flatten_complete"] is False
