from hlvault.momentum import config as cfg
from hlvault.momentum.live import MomentumEngine


class _FakeInfo:
    def __init__(self, mid, positions=None, spot_usdc=1000.0):
        self.mid = mid
        self._positions = positions or []
        self._spot_usdc = spot_usdc

    def all_mids(self):
        return {"BTC": self.mid}

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}


class _FakeExchange:
    def __init__(self):
        self.orders_placed = []
        self.closed = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders_placed.append({"coin": coin, "is_buy": is_buy, "size": size, "reduce_only": reduce_only})
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
                             "_alerted_this_halt": False}
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
