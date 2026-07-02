from hlvault.momentum import config as cfg
from hlvault.momentum.live import MomentumEngine


class _FakeInfo:
    def __init__(self, mid, positions=None, spot_usdc=1000.0, sz_decimals=3):
        self.mid = mid
        self._positions = positions or []
        self._spot_usdc = spot_usdc
        self._sz_decimals = sz_decimals

    def all_mids(self):
        return {"BTC": self.mid}

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}

    def meta(self):
        return {"universe": [{"name": "BTC", "szDecimals": self._sz_decimals, "maxLeverage": 10}]}


class _FakeExchange:
    def __init__(self):
        self.orders_placed = []
        self.orders_placed_px = []
        self.closed = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders_placed.append({"coin": coin, "is_buy": is_buy, "size": size, "reduce_only": reduce_only})
        self.orders_placed_px.append(px)
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    def market_close(self, coin, size):
        self.closed.append((coin, size))
        return {"status": "ok"}


def _make_engine(info, exchange, state=None, live_trading=True):
    engine = MomentumEngine.__new__(MomentumEngine)
    engine.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    engine.exchange = ResilientExchange(exchange)
    engine.state = state or {"halted": False, "peak_equity": 0.0, "last_rebalance_ms": 0,
                             "_alerted_this_halt": False, "_flatten_complete": False}
    engine.live_trading = live_trading
    return engine


def test_flatten_everything_closes_every_open_position(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0, positions=[
        {"coin": "BTC", "szi": "1.5", "marginUsed": "10", "unrealizedPnl": "0"},
        {"coin": "ETH", "szi": "-2.0", "marginUsed": "10", "unrealizedPnl": "0"},
    ])
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange, live_trading=True)

    engine._flatten_everything()

    assert ("BTC", 1.5) in exchange.closed
    assert ("ETH", 2.0) in exchange.closed


def test_flatten_everything_skips_zero_size_positions(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0, positions=[
        {"coin": "BTC", "szi": "0.0", "marginUsed": "0", "unrealizedPnl": "0"},
    ])
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange, live_trading=True)

    engine._flatten_everything()

    assert exchange.closed == []


def test_flatten_everything_dry_run_does_not_call_exchange(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0, positions=[
        {"coin": "BTC", "szi": "1.5", "marginUsed": "10", "unrealizedPnl": "0"},
    ])
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange, live_trading=False)

    engine._flatten_everything()

    assert exchange.closed == []


def test_place_order_dry_run_does_not_call_exchange(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0)
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)
    engine.live_trading = False

    engine._place_order("BTC", {"is_buy": True, "size": 1.0, "reduce_only": False})

    assert exchange.orders_placed == []


def test_place_order_live_calls_exchange_with_reduce_only_flag(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0)
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)
    engine.live_trading = True

    engine._place_order("BTC", {"is_buy": False, "size": 2.0, "reduce_only": True})

    assert exchange.orders_placed == [{"coin": "BTC", "is_buy": False, "size": 2.0, "reduce_only": True}]


def test_place_order_rounds_price_and_size_to_venue_tick_rules(monkeypatch):
    # mid=63482.7 -> raw limit_px (buy, +5% slippage) = 66656.835, which has
    # 8 significant figures and would likely be rejected by the real
    # exchange. round_price must clip it to <=5 sig figs / <=(6-szDecimals)
    # decimals (szDecimals=1 here -> <=5 decimals, but 5 sig figs binds
    # first): 66656.835 -> 66657 (rounded to 5 sig figs, 0 decimals since
    # 6-1=5 decimals doesn't bind before the 5-sig-fig rule does at this
    # magnitude).
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=63482.7, sz_decimals=1)
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)
    engine.live_trading = True

    engine._place_order("BTC", {"is_buy": True, "size": 1.23456, "reduce_only": False})

    assert len(exchange.orders_placed) == 1
    placed = exchange.orders_placed[0]
    assert placed["size"] == 1.2  # rounded to 1 decimal (szDecimals=1)
    # sanity: the raw unrounded price must NOT have been sent verbatim
    raw_px = 63482.7 * 1.05
    from hlvault.gridbot.exchange_utils import round_price
    expected_px = round_price(raw_px, 1)
    assert exchange.orders_placed_px[0] == expected_px
    assert exchange.orders_placed_px[0] != raw_px


def test_check_drawdown_persists_halt_before_flatten_is_attempted(monkeypatch, tmp_path):
    # Regression guard for the documented caller obligation in risk.check_drawdown:
    # the halt flag must be written to disk BEFORE any flatten is attempted, so a
    # crash mid-flatten doesn't lose it. We simulate a crash during flatten (the
    # fake exchange's market_close raises) and confirm the on-disk state file
    # already shows halted=True even though flatten never completed.
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _CrashingExchange(_FakeExchange):
        def market_close(self, coin, size):
            raise RuntimeError("simulated network crash mid-flatten")

    calls = {"n": 0}

    class _DrawdownInfo(_FakeInfo):
        def user_state(self, address):
            calls["n"] += 1
            equity = 1000.0 if calls["n"] == 1 else 790.0  # 21% down on 2nd call
            positions = [{"coin": "BTC", "szi": "1.0", "marginUsed": str(equity), "unrealizedPnl": "0"}]
            return {"assetPositions": [{"position": p} for p in positions]}

        def spot_user_state(self, address):
            # marginUsed alone represents total equity for this test (matches
            # test_momentum_risk.py's equivalent fixture) — a nonzero spot
            # balance here would dilute the drawdown below the 20% threshold.
            return {"balances": []}

    info = _DrawdownInfo(mid=100.0)
    exchange = _CrashingExchange()
    engine = _make_engine(info, exchange, live_trading=True)

    engine.check_drawdown()  # first call: sets peak, no halt
    halted = engine.check_drawdown()  # second call: 21% down -> halts, flatten crashes

    assert halted is True
    from hlvault.momentum.state import load_state
    persisted = load_state(cfg.STATE_FILE)
    assert persisted["halted"] is True, (
        "halted must be persisted to disk even though the flatten attempt crashed"
    )


def test_check_drawdown_retries_flatten_until_success_but_alerts_only_once(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _FlakyExchange(_FakeExchange):
        def __init__(self):
            super().__init__()
            self.market_close_calls = 0

        def market_close(self, coin, size):
            self.market_close_calls += 1
            if self.market_close_calls == 1:
                raise RuntimeError("simulated transient failure on first attempt")
            self.closed.append((coin, size))

    calls = {"n": 0}

    class _DrawdownInfo(_FakeInfo):
        def user_state(self, address):
            calls["n"] += 1
            equity = 1000.0 if calls["n"] == 1 else 790.0
            positions = [{"coin": "BTC", "szi": "1.0", "marginUsed": str(equity), "unrealizedPnl": "0"}]
            return {"assetPositions": [{"position": p} for p in positions]}

        def spot_user_state(self, address):
            return {"balances": []}

    info = _DrawdownInfo(mid=100.0)
    exchange = _FlakyExchange()
    engine = _make_engine(info, exchange, live_trading=True)

    engine.check_drawdown()  # sets peak
    halted1 = engine.check_drawdown()  # detects drawdown, flatten fails (1st market_close call raises)
    assert halted1 is True
    assert exchange.market_close_calls == 1
    assert engine.state["_flatten_complete"] is False

    halted2 = engine.check_drawdown()  # retries flatten, succeeds this time
    assert halted2 is True
    assert exchange.market_close_calls == 2
    assert engine.state["_flatten_complete"] is True
    assert ("BTC", 1.0) in exchange.closed
