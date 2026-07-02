"""Regression test for a real bug found after ~15h live: a TP order placed
during sync_coin() was checked for "did it fill?" against a resting-orders
snapshot fetched BEFORE that TP existed, so it was always misread as filled
and immediately dropped from open_lots — silently disabling the stop-loss
and position-notional cap. See live.py's sync_coin for the fix."""
from hlvault.gridbot import config as cfg
from hlvault.gridbot.live import GridBotEngine
from hlvault.gridbot.strategy import level_price


class _FakeInfo:
    def __init__(self, mid, sz_decimals=3, max_leverage=10):
        self.mid = mid
        self._sz_decimals = sz_decimals
        self._max_leverage = max_leverage
        self.open_orders_calls = 0
        self._orders = []  # list of dicts: coin, oid, reduceOnly

    def all_mids(self):
        return {"HYPE": self.mid}

    def meta(self):
        return {"universe": [{"name": "HYPE", "szDecimals": self._sz_decimals,
                              "maxLeverage": self._max_leverage}]}

    def open_orders(self, address):
        self.open_orders_calls += 1
        return list(self._orders)

    def user_fills_by_time(self, address, start, end=None):
        return [{"oid": "buy-oid-1", "px": self.mid, "sz": "1.0"}]


class _FakeExchange:
    def __init__(self):
        self.next_oid = 100
        self.orders_placed = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        oid = self.next_oid
        self.next_oid += 1
        self.orders_placed.append({"coin": coin, "is_buy": is_buy, "size": size,
                                   "px": px, "reduce_only": reduce_only, "oid": oid})
        return {"response": {"data": {"statuses": [{"resting": {"oid": oid}}]}}}

    def cancel(self, coin, oid):
        return {"status": "ok"}

    def update_leverage(self, *a, **k):
        return {"status": "ok"}


def _make_engine(info, exchange, coin_state):
    engine = GridBotEngine.__new__(GridBotEngine)
    engine.live_trading = True
    engine.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    engine.exchange = ResilientExchange(exchange)
    engine.state = {"halted": False, "peak_equity": 1000.0, "last_fill_check_ms": 0,
                    "coins": {"HYPE": coin_state}}
    engine._sz_dec = {}
    engine._leverage_set = {"HYPE"}  # skip leverage calls for this test
    return engine


def test_fresh_tp_is_not_misread_as_filled_in_the_same_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "NUM_LEVELS", 3)
    monkeypatch.setattr(cfg, "STOP_BUFFER_PCT", 0.15)
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 1.0)

    anchor, step_pct = 100.0, 0.01
    buy_level = -1
    buy_oid = "buy-oid-1"
    info = _FakeInfo(mid=100.0)
    # the resting-orders snapshot fetched at the TOP of this cycle: the buy
    # order that's ABOUT to be detected as filled is already gone (simulates
    # it having just filled), and nothing else is resting yet.
    info._orders = []
    exchange = _FakeExchange()

    coin_state = {
        "anchor": anchor, "step_pct": step_pct,
        "notional_per_level": 50.0, "max_position_notional": 500.0,
        "armed": {str(buy_level): buy_oid}, "open_lots": {}, "stopped_until_ms": None,
    }
    engine = _make_engine(info, exchange, coin_state)

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert str(buy_level) in c["open_lots"], (
        "the lot just opened this cycle must still be tracked — "
        "it must not be immediately treated as TP-filled"
    )
    lot = c["open_lots"][str(buy_level)]
    assert lot["tp_oid"] == exchange.orders_placed[0]["oid"]
