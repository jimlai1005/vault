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

    def query_order_by_oid(self, address, oid):
        # buy resolution now reads the order's own final state (orderStatus)
        return _order_status(oid, "filled", orig="1.0", remaining="0.0", limit_px=str(self.mid))


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


# ---------------------------------------------------------------------------
# T2 (docs/plans/gridbot-position-truth.md §3.3/§5.1): an armed buy may only
# leave state when its fill is accounted for (lot + TP) or it is confirmed
# unfilled and no longer open. Payload shapes below are the real orderStatus
# responses captured 2026-11-14.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402

BUY_OID = 595708894064
CANCEL_OK = {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}
CANCEL_RACED_FILL = {"status": "ok", "response": {"type": "cancel", "data": {"statuses": [
    {"error": "Order was never placed, already canceled, or filled."}]}}}


def _order_status(oid, status, orig, remaining, limit_px="94.2", ts=1793890875821):
    return {"status": "order", "order": {"order": {
        "coin": "HYPE", "side": "B", "limitPx": limit_px, "sz": remaining, "oid": oid,
        "timestamp": ts, "triggerCondition": "N/A", "isTrigger": False, "triggerPx": "0.0",
        "children": [], "isPositionTpsl": False, "reduceOnly": False, "orderType": "Limit",
        "origSz": orig, "tif": "Alo", "cloid": None},
        "status": status, "statusTimestamp": ts + 1405470}}


class _OrderInfo(_FakeInfo):
    """open_orders reports whatever the fake exchange has placed (plus
    `extra_resting`), so only the oid under test is ever not-resting.
    query_order_by_oid answers from `responses[oid]`: a dict is returned, an
    Exception is raised. fills-by-time must never be consulted."""

    def __init__(self, exchange, mid=100.0):
        super().__init__(mid=mid)
        self.exchange = exchange
        self.extra_resting = []
        self.responses = {}
        self.query_calls = []

    def open_orders(self, address):
        placed = [{"coin": "HYPE", "oid": o["oid"]} for o in self.exchange.orders_placed]
        return placed + list(self.extra_resting)

    def query_order_by_oid(self, address, oid):
        self.query_calls.append((address, oid))
        r = self.responses[oid]
        if isinstance(r, Exception):
            raise r
        return r

    def user_fills_by_time(self, address, start, end=None):
        raise AssertionError("buy resolution must not use user_fills_by_time")


class _ConfigurableExchange(_FakeExchange):
    def __init__(self, cancel_response=CANCEL_OK):
        super().__init__()
        self.cancel_response = cancel_response
        self.cancel_calls = []
        self.fail_reduce_only = False

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        if reduce_only and self.fail_reduce_only:
            return {"status": "err", "response": "rejected"}
        return super().order(coin, is_buy, size, px, order_type=order_type, reduce_only=reduce_only)

    def cancel(self, coin, oid):
        self.cancel_calls.append(oid)
        if isinstance(self.cancel_response, Exception):
            raise self.cancel_response
        return self.cancel_response

    def tps(self):
        return [o for o in self.orders_placed if o["reduce_only"]]


@pytest.fixture
def grid(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "NUM_LEVELS", 3)
    monkeypatch.setattr(cfg, "STOP_BUFFER_PCT", 0.15)
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 1.0)

    def build(armed_level, cancel_response=CANCEL_OK, resting=False):
        """anchor 100, mid 100 -> desired levels -3..-1; level -6 is stale (recentre
        target), -1 is wanted (reconcile-by-snapshot path)."""
        exchange = _ConfigurableExchange(cancel_response)
        info = _OrderInfo(exchange)
        if resting:
            info.extra_resting.append({"coin": "HYPE", "oid": BUY_OID})
        coin_state = {"anchor": 100.0, "step_pct": 0.01, "notional_per_level": 50.0,
                      "max_position_notional": 500.0, "armed": {str(armed_level): BUY_OID},
                      "open_lots": {}, "stopped_until_ms": None}
        engine = _make_engine(info, exchange, coin_state)
        engine.state["last_fill_check_ms"] = 4_000_000_000_000   # far in the future of every fixture timestamp
        return engine, info, exchange

    return build


def test_recentre_cancel_unconfirmed_then_filled_builds_lot_and_tp(grid):
    engine, info, ex = grid(-6, cancel_response=CANCEL_RACED_FILL, resting=True)
    info.responses[BUY_OID] = _order_status(BUY_OID, "filled", orig="0.5", remaining="0.0")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert ex.cancel_calls == [BUY_OID]
    assert info.query_calls == [(cfg.WALLET_ADDRESS, BUY_OID)]
    assert "-6" not in c["armed"]
    lot = c["open_lots"]["-6"]
    assert lot["size"] == 0.5 and lot["entry_price"] == 94.2
    assert len(ex.tps()) == 1
    tp = ex.tps()[0]
    assert tp["size"] == 0.5 and tp["is_buy"] is False and tp["oid"] == lot["tp_oid"]


def test_fill_before_last_fill_check_window_is_still_recorded(grid):
    engine, info, ex = grid(-1)          # not resting -> reconcile branch
    info.responses[BUY_OID] = _order_status(BUY_OID, "filled", orig="0.5", remaining="0.0", ts=1_000)
    assert engine.state["last_fill_check_ms"] > 1_000

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert c["open_lots"]["-1"]["size"] == 0.5
    assert "-1" not in c["armed"]
    assert len(ex.tps()) == 1 and ex.tps()[0]["size"] == 0.5


def test_partial_fill_then_cancelled_uses_filled_quantity(grid):
    engine, info, ex = grid(-1)
    info.responses[BUY_OID] = _order_status(BUY_OID, "canceled", orig="0.03", remaining="0.01")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert c["open_lots"]["-1"]["size"] == 0.02
    assert [t["size"] for t in ex.tps()] == [0.02]


def test_canceled_with_zero_fill_drops_armed_without_lot_or_tp(grid):
    engine, info, ex = grid(-6, cancel_response=CANCEL_RACED_FILL, resting=True)
    info.responses[BUY_OID] = _order_status(BUY_OID, "canceled", orig="0.5", remaining="0.5")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert "-6" not in c["armed"]
    assert c["open_lots"] == {}
    assert ex.tps() == []


@pytest.mark.parametrize("bad_first_answer", [
    {"status": "unknownOid"},
    ConnectionError("orderStatus timed out"),
    {"status": "order", "order": {"status": "filled"}},        # payload missing the inner order
    {"status": "order", "order": {"order": {"origSz": "x", "sz": "0", "limitPx": "94.2"}, "status": "filled"}},
])
def test_unknown_or_failed_query_keeps_armed_until_a_later_cycle_sees_the_fill(grid, bad_first_answer):
    engine, info, ex = grid(-1)
    c = engine.state["coins"]["HYPE"]
    info.responses[BUY_OID] = bad_first_answer

    engine.sync_coin("HYPE")
    assert c["armed"]["-1"] == BUY_OID
    assert c["open_lots"] == {} and ex.tps() == []

    info.responses[BUY_OID] = _order_status(BUY_OID, "filled", orig="0.5", remaining="0.0")
    engine.sync_coin("HYPE")
    assert c["open_lots"]["-1"]["size"] == 0.5
    assert len(ex.tps()) == 1


def test_confirmed_cancel_with_zero_fill_removes_armed_after_reading_order_status(grid):
    # R-A (2026-11-14): even a confirmed cancel is followed by an order-status read,
    # because the buy may have part-filled before the cancel landed.
    engine, info, ex = grid(-6, cancel_response=CANCEL_OK, resting=True)
    info.responses[BUY_OID] = _order_status(BUY_OID, "canceled", orig="0.5", remaining="0.5")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert "-6" not in c["armed"] and c["open_lots"] == {}
    assert ex.tps() == []
    assert ex.cancel_calls == [BUY_OID]
    assert info.query_calls == [(cfg.WALLET_ADDRESS, BUY_OID)]


def test_confirmed_cancel_after_partial_fill_builds_lot_for_filled_part(grid):
    engine, info, ex = grid(-6, cancel_response=CANCEL_OK, resting=True)
    info.responses[BUY_OID] = _order_status(BUY_OID, "canceled", orig="0.5", remaining="0.2")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert ex.cancel_calls == [BUY_OID]
    assert "-6" not in c["armed"]
    assert c["open_lots"]["-6"]["size"] == 0.3
    assert [t["size"] for t in ex.tps()] == [0.3]


def test_cancel_exception_falls_back_to_order_status_not_pop(grid):
    engine, info, ex = grid(-6, cancel_response=RuntimeError("boom"), resting=True)
    info.responses[BUY_OID] = _order_status(BUY_OID, "open", orig="0.5", remaining="0.5")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert c["armed"]["-6"] == BUY_OID          # still resting on the exchange -> still tracked
    assert info.query_calls == [(cfg.WALLET_ADDRESS, BUY_OID)]


def test_still_open_partially_filled_order_stays_armed(grid):
    engine, info, ex = grid(-1)
    info.responses[BUY_OID] = _order_status(BUY_OID, "open", orig="0.5", remaining="0.2")

    engine.sync_coin("HYPE")

    c = engine.state["coins"]["HYPE"]
    assert c["armed"]["-1"] == BUY_OID and c["open_lots"] == {} and ex.tps() == []


def test_fill_whose_tp_placement_fails_is_not_forgotten_and_is_retried(grid):
    engine, info, ex = grid(-1)
    info.responses[BUY_OID] = _order_status(BUY_OID, "filled", orig="0.5", remaining="0.0")
    ex.fail_reduce_only = True

    engine.sync_coin("HYPE")
    c = engine.state["coins"]["HYPE"]
    assert c["armed"]["-1"] == BUY_OID and c["open_lots"] == {}

    ex.fail_reduce_only = False
    engine.sync_coin("HYPE")
    assert c["open_lots"]["-1"]["size"] == 0.5 and len(ex.tps()) == 1


def test_dryrun_order_ids_are_dropped_without_querying(grid):
    engine, info, ex = grid(-1)
    engine.live_trading = False
    c = engine.state["coins"]["HYPE"]
    c["armed"]["-1"] = "dryrun-HYPE-99.0"

    engine._resolve_buy("HYPE", -1, "dryrun-HYPE-99.0")

    assert "-1" not in c["armed"] and info.query_calls == []
    assert engine._cancel("HYPE", "dryrun-HYPE-99.0") == "cancelled"


@pytest.mark.parametrize("response,expected", [
    (CANCEL_OK, "cancelled"),
    ({"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success", "success"]}}}, "cancelled"),
    (CANCEL_RACED_FILL, "unconfirmed"),
    ({"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success", {"error": "x"}]}}}, "unconfirmed"),
    ({"status": "ok"}, "unconfirmed"),
    ({"status": "err", "response": "nope"}, "unconfirmed"),
    (None, "unconfirmed"),
    (RuntimeError("boom"), "failed"),
])
def test_cancel_three_states(grid, response, expected):
    engine, info, ex = grid(-1, cancel_response=response)
    assert engine._cancel("HYPE", BUY_OID) == expected
