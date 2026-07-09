import logging
import time

import pandas as pd
import pytest

from hlvault.cta import config as cfg
from hlvault.cta.live import CtaEngine


class _FakeInfo:
    def __init__(self, mid=100.0, positions=None, spot_usdc=1000.0, sz_decimals=3,
                 free_collateral=0.0):
        self.mid = mid
        self._positions = positions or []
        self._spot_usdc = spot_usdc
        self._sz = sz_decimals
        self._free = free_collateral

    def all_mids(self):
        return {c: str(self.mid) for c in ("BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP")}

    def user_state(self, address):
        # Honour the on-chain verified no-resting-orders identity (this engine
        # is IoC-only): withdrawable ALREADY includes unrealizedPnl, and
        # accountValue == totalMarginUsed + withdrawable.
        margin_used = sum(float(p.get("marginUsed", 0.0)) for p in self._positions)
        upnl = sum(float(p.get("unrealizedPnl", 0.0)) for p in self._positions)
        withdrawable = self._free + upnl
        return {
            "assetPositions": [{"position": p} for p in self._positions],
            "marginSummary": {"totalMarginUsed": str(margin_used),
                              "accountValue": str(margin_used + withdrawable)},
            "withdrawable": str(withdrawable),
        }

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}

    def meta(self):
        return {"universe": [{"name": c, "szDecimals": self._sz, "maxLeverage": 20}
                             for c in ("BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP")]}


class _FakeExchange:
    def __init__(self):
        self.orders = []
        self.closed = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders.append({"coin": coin, "is_buy": is_buy, "size": size,
                            "px": px, "reduce_only": reduce_only})
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    def market_close(self, coin, size):
        self.closed.append((coin, size))
        return {"status": "ok"}


def _engine(info, exchange, live=True, state=None):
    e = CtaEngine.__new__(CtaEngine)
    e.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    e.exchange = ResilientExchange(exchange)
    e.live_trading = live
    e.state = state or {"halted": False, "peak_equity": 0.0,
                        "_alerted_this_halt": False, "_flatten_complete": False,
                        "last_rebalance_ms": 0, "entries": {}}
    return e


def test_place_order_dry_run_does_nothing(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=False)
    e._place_order("BTC", is_buy=False, size=1.0, reduce_only=False)
    assert ex.orders == []


def test_place_order_short_open_is_sell_not_reduce_only(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0, sz_decimals=3), ex, live=True)
    e._place_order("BTC", is_buy=False, size=1.23456, reduce_only=False)
    o = ex.orders[0]
    assert o["coin"] == "BTC" and o["is_buy"] is False and o["reduce_only"] is False
    assert o["size"] == 1.234  # rounded to szDecimals=3


def test_flatten_everything_closes_all_and_clears_entries(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(positions=[
        {"coin": "BTC", "szi": "-0.5", "marginUsed": "10", "unrealizedPnl": "0"},
        {"coin": "ETH", "szi": "-1.0", "marginUsed": "10", "unrealizedPnl": "0"},
    ])
    ex = _FakeExchange()
    e = _engine(info, ex, live=True,
                state={"halted": True, "peak_equity": 100.0, "_alerted_this_halt": True,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1}, "ETH": {"dir": -1}}})
    ok = e._flatten_everything()
    assert ok is True
    assert ("BTC", 0.5) in ex.closed and ("ETH", 1.0) in ex.closed


def test_flatten_dry_run_skips(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(positions=[{"coin": "BTC", "szi": "-0.5", "marginUsed": "10",
                                 "unrealizedPnl": "0"}])
    ex = _FakeExchange()
    e = _engine(info, ex, live=False)
    e._flatten_everything()
    assert ex.closed == []


def test_drawdown_halt_persists_before_flatten(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _Crashing(_FakeExchange):
        def market_close(self, coin, size):
            raise RuntimeError("boom")

    calls = {"n": 0}

    class _DropInfo(_FakeInfo):
        def user_state(self, address):
            calls["n"] += 1
            eq = 1000.0 if calls["n"] == 1 else 790.0
            return {"assetPositions": [{"position": {"coin": "BTC", "szi": "-0.5",
                    "marginUsed": str(eq), "unrealizedPnl": "0"}}],
                    "marginSummary": {"totalMarginUsed": str(eq),
                                      "accountValue": str(eq)},
                    "withdrawable": "0"}

        def spot_user_state(self, address):
            return {"balances": []}

    e = _engine(_DropInfo(), _Crashing(), live=True)
    assert e.check_drawdown() is False   # sets peak 1000
    assert e.check_drawdown() is True    # 21% dd -> halt, flatten crashes
    from hlvault.cta.state import load_state
    assert load_state(cfg.STATE_FILE)["halted"] is True
    assert load_state(cfg.STATE_FILE)["_flatten_complete"] is False


def test_second_halt_episode_alerts_and_flattens_again(monkeypatch, tmp_path):
    # Regression (carry's two-episode breaker test, mirrored): without
    # re-arming _alerted_this_halt/_flatten_complete on a healthy cycle, a
    # SECOND drawdown halt (after the operator clears `halted`) would be silent
    # — no alert, no flatten attempt. Proves alert-once, retry-flatten-until-
    # complete, and healthy-cycle re-arm.
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", ["BTC"])
    monkeypatch.setattr(cfg, "REBALANCE_INTERVAL_HOURS", 4)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    # no-op data feed so the healthy run_once's maybe_rebalance makes NO
    # network call (tests must never touch the real world) and opens nothing.
    from hlvault.cta import data as data_mod

    class _NoData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return None

        def is_coin_stale(self, coin, staleness_hours):
            return True

    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    class _Crashing(_FakeExchange):
        def __init__(self):
            super().__init__()
            self.close_calls = 0

        def market_close(self, coin, size):
            self.close_calls += 1
            raise RuntimeError("boom")

    equities = {"v": 1000.0}

    class _DropInfo(_FakeInfo):
        def user_state(self, address):
            return {"assetPositions": [{"position": {"coin": "BTC", "szi": "-0.5",
                    "marginUsed": str(equities["v"]), "unrealizedPnl": "0"}}],
                    "marginSummary": {"totalMarginUsed": str(equities["v"]),
                                      "accountValue": str(equities["v"])},
                    "withdrawable": "0"}

        def spot_user_state(self, address):
            return {"balances": []}

    ex = _Crashing()
    e = _engine(_DropInfo(), ex, live=True,
                state={"halted": False, "peak_equity": 0.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": int(time.time() * 1000),
                       "entries": {}})

    # episode 1: peak 1000, drop to 790 -> 21% dd -> halt, flatten crashes
    assert e.check_drawdown() is False
    equities["v"] = 790.0
    assert e.check_drawdown() is True
    assert ex.close_calls == 1
    assert e.state["_alerted_this_halt"] is True
    assert e.state["_flatten_complete"] is False

    # operator inspects, flattens manually, clears the halt; equity recovers ->
    # a healthy run_once re-arms the flags (rebalance is due, no signal here)
    e.state["halted"] = False
    equities["v"] = 1000.0
    e.run_once()
    assert e.state["_alerted_this_halt"] is False
    assert e.state["_flatten_complete"] is False

    # episode 2: drop to 600 -> ~40% dd -> must alert AND flatten AGAIN
    equities["v"] = 600.0
    assert e.check_drawdown() is True
    assert ex.close_calls == 2   # flatten attempted again, not silently skipped
    assert e.state["_alerted_this_halt"] is True
    assert e.state["_flatten_complete"] is False


def test_run_once_skips_rebalance_when_halted(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=True,
                state={"halted": True, "peak_equity": 1000.0, "_alerted_this_halt": True,
                       "_flatten_complete": True, "last_rebalance_ms": 0, "entries": {}})
    e.run_once()
    assert ex.orders == []


def _short_signal_frame():
    # downtrend + rising long_pct (crowd_long) + rising OI (fuel) over 200 4h
    # bars. 200 (not the plan's 130): compute_signals uses
    # crowd_warmup_bars=30*6=180 as the rolling percentile's min_periods, and
    # maybe_rebalance drops the final forming bar, so a 130-bar frame leaves
    # 129 < 180 observations -> percentile all-NaN -> crowd_long False -> the
    # short never fires. 200 bars (199 after the forming-bar drop) clears
    # min_periods so the fresh-signal test exercises a real short entry. This
    # is the exact fixture-length fix the plan's implementer note authorizes
    # ("fix the TEST fixture length, not the production window"); it does not
    # weaken any assertion.
    import numpy as np
    n = 200
    idx = pd.date_range(pd.Timestamp.utcnow().floor("h") - pd.Timedelta(hours=4 * n),
                        periods=n, freq="4h")
    closes = 100 * 0.99 ** np.arange(n)
    return pd.DataFrame({"open": closes, "high": closes * 1.001, "low": closes * 0.999,
                         "close": closes, "oi_level": np.arange(n) + 10.0,
                         "long_pct": np.arange(n).astype(float)}, index=idx)


def test_maybe_rebalance_opens_short_on_fresh_short_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", ["BTC"])
    monkeypatch.setattr(cfg, "ENABLE_LONG", False)
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "REBALANCE_INTERVAL_HOURS", 4)
    monkeypatch.setattr(cfg, "NOTIONAL_PER_TRADE", 100.0)
    monkeypatch.setattr(cfg, "DATA_STALENESS_HOURS", 8)

    from hlvault.cta import data as data_mod

    class _FakeData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return False

    monkeypatch.setattr(data_mod, "CtaData", _FakeData)

    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, positions=[], sz_decimals=3), ex, live=True)
    e.maybe_rebalance()

    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["coin"] == "BTC" and o["is_buy"] is False and o["reduce_only"] is False
    assert "BTC" in e.state["entries"] and e.state["entries"]["BTC"]["dir"] == -1


def test_maybe_rebalance_skips_new_entry_when_stale_but_still_manages_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", ["BTC"])
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "REBALANCE_INTERVAL_HOURS", 4)
    monkeypatch.setattr(cfg, "DATA_STALENESS_HOURS", 8)
    monkeypatch.setattr(cfg, "STOP_ATR_MULT", 2.0)

    from hlvault.cta import data as data_mod

    class _StaleData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return True   # stale -> no new entry

    monkeypatch.setattr(data_mod, "CtaData", _StaleData)

    # existing SHORT position whose stop (110) is breached by live mid 120 -> must close
    ex = _FakeExchange()
    info = _FakeInfo(mid=120.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}], sz_decimals=3)
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1, "entry_px": 100.0, "stop": 110.0,
                                           "entry_ms": int(pd.Timestamp.utcnow().timestamp() * 1000)}}})
    e.maybe_rebalance()

    # no NEW open order, but the stopped-out short WAS closed (reduce-only) and entry cleared
    opens = [o for o in ex.orders if not o["reduce_only"]]
    assert opens == []
    assert ("BTC", 1.0) in ex.closed
    assert "BTC" not in e.state["entries"]


def test_init_raises_when_wallet_missing(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_PRIVATE_KEY", "")
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "")
    with pytest.raises(RuntimeError, match="WALLET_PRIVATE_KEY"):
        CtaEngine(live_trading=False)


# ---- crash-safe bookkeeping (opus review findings) ------------------------

class _NoData:
    """Feed stub: no frames, everything stale — no new entries possible."""

    def __init__(self, coins, lookback_bars):
        pass

    def frame_for(self, coin):
        return None

    def is_coin_stale(self, coin, staleness_hours):
        return True


def _rebalance_cfg(monkeypatch, tmp_path, universe=("BTC",)):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", list(universe))
    monkeypatch.setattr(cfg, "REBALANCE_INTERVAL_HOURS", 4)
    monkeypatch.setattr(cfg, "DATA_STALENESS_HOURS", 8)


def test_exit_close_failure_keeps_entry_alerts_and_retries(monkeypatch, tmp_path):
    # FINDING 1: a failed exit close must NOT pop the entry record — the real
    # position is still open, and without the entry its 2xATR stop / max-hold
    # would never be evaluated again. It must alert loudly and retry next cycle.
    _rebalance_cfg(monkeypatch, tmp_path)
    alerts = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, chat, msg: alerts.append(msg))
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    class _FailingClose(_FakeExchange):
        def __init__(self):
            super().__init__()
            self.close_calls = 0

        def market_close(self, coin, size):
            self.close_calls += 1
            raise RuntimeError("order rejected")  # semantic -> no internal retry

    ex = _FailingClose()
    # short whose stop (110) is breached by live mid 120 -> exit wanted
    info = _FakeInfo(mid=120.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1, "entry_px": 100.0, "stop": 110.0,
                                           "entry_ms": int(time.time() * 1000)}}})
    e.maybe_rebalance()
    assert ex.close_calls == 1
    assert "BTC" in e.state["entries"]                # bookkeeping survives the failure
    from hlvault.cta.state import load_state
    assert "BTC" in load_state(cfg.STATE_FILE)["entries"]   # ... and on disk
    assert any("BTC" in m and "FAILED" in m for m in alerts)  # loud

    # next cycle: the exit condition re-fires and the close is retried
    e.state["last_rebalance_ms"] = 0
    e.maybe_rebalance()
    assert ex.close_calls == 2
    assert "BTC" in e.state["entries"]


def test_orphan_position_flattened_with_alert(monkeypatch, tmp_path):
    # FINDING 2c: an HL position with no entries record (entry-side crash
    # window) has no stop/max-hold anchor -> reconcile by flattening, loudly.
    _rebalance_cfg(monkeypatch, tmp_path)
    alerts = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, chat, msg: alerts.append(msg))
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    ex = _FakeExchange()
    info = _FakeInfo(mid=100.0, positions=[{"coin": "BTC", "szi": "-0.5",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    e = _engine(info, ex, live=True)   # entries == {} -> BTC is an orphan
    e.maybe_rebalance()

    assert ("BTC", 0.5) in ex.closed                       # reduce-only flatten
    assert any("ORPHAN" in m and "BTC" in m for m in alerts)
    assert [o for o in ex.orders if not o["reduce_only"]] == []  # no re-entry this cycle
    assert "BTC" not in e.state["entries"]


def test_orphan_dry_run_logs_but_does_not_close(monkeypatch, tmp_path):
    # The orphan flatten is dry-run gated like every other exchange write.
    _rebalance_cfg(monkeypatch, tmp_path)
    monkeypatch.setattr("hlvault.cta.live.send_alert", lambda tok, chat, msg: None)
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    ex = _FakeExchange()
    info = _FakeInfo(mid=100.0, positions=[{"coin": "BTC", "szi": "-0.5",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    e = _engine(info, ex, live=False)
    e.maybe_rebalance()
    assert ex.closed == [] and ex.orders == []


def test_entry_persisted_before_next_coin(monkeypatch, tmp_path):
    # FINDING 2a: the entry must be on disk BEFORE the loop moves to the next
    # coin — a crash mid-loop must not orphan a just-opened position. Observed
    # via the feed: frame_for(ETH) runs at the start of ETH's processing, and
    # by then BTC's entry must already be persisted.
    _rebalance_cfg(monkeypatch, tmp_path, universe=("BTC", "ETH"))
    monkeypatch.setattr(cfg, "ENABLE_LONG", False)
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "NOTIONAL_PER_TRADE", 100.0)

    from hlvault.cta import data as data_mod
    from hlvault.cta.state import load_state
    feeds = []

    class _RecordingData:
        def __init__(self, coins, lookback_bars):
            self.entries_seen = {}
            feeds.append(self)

        def frame_for(self, coin):
            self.entries_seen[coin] = sorted(
                load_state(cfg.STATE_FILE).get("entries", {}).keys())
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return False

    monkeypatch.setattr(data_mod, "CtaData", _RecordingData)

    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, positions=[], sz_decimals=3), ex, live=True)
    e.maybe_rebalance()

    assert len(ex.orders) == 2
    assert feeds[0].entries_seen["BTC"] == []        # nothing persisted yet
    assert feeds[0].entries_seen["ETH"] == ["BTC"]   # BTC entry already on disk


def test_unconfirmed_order_records_no_entry(monkeypatch, tmp_path):
    # FINDING 3: _place_order that placed nothing (here: size rounds to zero)
    # must not produce an entry record for a position that does not exist.
    _rebalance_cfg(monkeypatch, tmp_path)
    monkeypatch.setattr(cfg, "ENABLE_LONG", False)
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "NOTIONAL_PER_TRADE", 10.0)   # 10/50 = 0.2 ...

    from hlvault.cta import data as data_mod

    class _FakeData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return False

    monkeypatch.setattr(data_mod, "CtaData", _FakeData)

    ex = _FakeExchange()
    # ... szDecimals=0 -> round_size(0.2, 0) == 0 -> nothing placed
    e = _engine(_FakeInfo(mid=50.0, positions=[], sz_decimals=0), ex, live=True)
    e.maybe_rebalance()
    assert ex.orders == []
    assert e.state["entries"] == {}


def test_no_entry_when_atr_nan(monkeypatch, tmp_path):
    # live-layer ATR gate: a short decision with NaN ATR (warmup) has no valid
    # stop level, so the live engine must refuse the entry.
    _rebalance_cfg(monkeypatch, tmp_path)
    monkeypatch.setattr(cfg, "ENABLE_LONG", False)
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)

    from hlvault.cta import data as data_mod, signals as signals_mod

    class _FakeData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return False

    monkeypatch.setattr(data_mod, "CtaData", _FakeData)
    monkeypatch.setattr(signals_mod, "compute_signals", lambda *a, **k: {
        "trend_up": False, "trend_dn": True, "crowd_long": True,
        "crowd_short": False, "fuel": True, "atr": float("nan"), "close": 50.0})

    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, positions=[], sz_decimals=3), ex, live=True)
    e.maybe_rebalance()
    assert ex.orders == []
    assert e.state["entries"] == {}


def test_exit_close_dry_run_gate(monkeypatch, tmp_path):
    # dry-run must not write to the exchange on the EXIT path either; the
    # simulated close still clears the entry (dry-run counts as success).
    _rebalance_cfg(monkeypatch, tmp_path)
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    ex = _FakeExchange()
    info = _FakeInfo(mid=120.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    e = _engine(info, ex, live=False,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1, "entry_px": 100.0, "stop": 110.0,
                                           "entry_ms": int(time.time() * 1000)}}})
    e.maybe_rebalance()
    assert ex.closed == [] and ex.orders == []   # no real exchange write
    assert "BTC" not in e.state["entries"]       # simulated close clears entry


def test_maxhold_exit_fires_when_sig_none(monkeypatch, tmp_path):
    # observation fix: max-hold is purely time-based, so it must fire even
    # during a data outage (frame None -> sig None). Stop NOT hit here, so the
    # only exit path is the sig-independent max-hold.
    _rebalance_cfg(monkeypatch, tmp_path)
    monkeypatch.setattr(cfg, "MAX_HOLD_DAYS", 14.0)
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    ex = _FakeExchange()
    info = _FakeInfo(mid=100.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    fifteen_days_ago = int(time.time() * 1000) - 15 * 86400_000
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1, "entry_px": 100.0, "stop": 200.0,
                                           "entry_ms": fifteen_days_ago}}})
    e.maybe_rebalance()
    assert ("BTC", 1.0) in ex.closed
    assert "BTC" not in e.state["entries"]


# ---- F4: MIN_ORDER_NOTIONAL gate ------------------------------------------

def test_min_notional_gate_blocks_sub_minimum_open(monkeypatch):
    # A new open whose rounded notional is below MIN_ORDER_NOTIONAL must not
    # be submitted (the venue would reject it anyway) and must return False so
    # the caller never records entry bookkeeping for it.
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, sz_decimals=3), ex, live=True)
    # 0.2 * $50 = $10 < $12 -> refused
    assert e._place_order("BTC", is_buy=False, size=0.2, reduce_only=False) is False
    assert ex.orders == []
    # 0.3 * $50 = $15 >= $12 -> placed
    assert e._place_order("BTC", is_buy=False, size=0.3, reduce_only=False) is True
    assert len(ex.orders) == 1


def test_min_notional_gate_does_not_block_reduce_only_close(monkeypatch):
    # The gate must NOT apply to reduce-only closes: a position that drifted
    # below the minimum notional must always remain closable.
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, sz_decimals=3), ex, live=True)
    # same sub-minimum notional ($10), but reduce-only -> allowed through
    assert e._place_order("BTC", is_buy=True, size=0.2, reduce_only=True) is True
    assert len(ex.orders) == 1 and ex.orders[0]["reduce_only"] is True


# ---- latent trap: missing/non-finite stop in entries -----------------------

@pytest.mark.parametrize("entry", [
    {"dir": -1, "entry_px": 100.0},                          # stop key missing
    {"dir": -1, "entry_px": 100.0, "stop": float("nan")},    # NaN stop
    {"dir": -1, "entry_px": 100.0, "stop": float("-inf")},   # non-finite stop
])
def test_missing_stop_alerts_and_skips_stop_check(monkeypatch, tmp_path, entry):
    # ent.get("stop", 0.0) was a latent trap: for a SHORT, stop_hit(-1, 0.0,
    # mid) is True at ANY positive mid, so a missing stop would instantly
    # force-close a healthy position. A missing/non-finite stop is a
    # bookkeeping anomaly: alert loudly, skip the stop check, keep the entry
    # (max-hold and signal exits stay active).
    _rebalance_cfg(monkeypatch, tmp_path)
    alerts = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, chat, msg: alerts.append(msg))
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    ex = _FakeExchange()
    info = _FakeInfo(mid=100.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    ent = dict(entry, entry_ms=int(time.time() * 1000))
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": ent}})
    e.maybe_rebalance()
    assert ex.closed == []                        # NOT force-closed on the bogus stop
    assert "BTC" in e.state["entries"]            # bookkeeping retained
    assert any("BTC" in m and "stop" in m.lower() for m in alerts)  # loud


def test_missing_stop_still_allows_maxhold_exit(monkeypatch, tmp_path):
    # The anomaly path must only disable the STOP check — the sig-independent
    # max-hold exit still protects the position.
    _rebalance_cfg(monkeypatch, tmp_path)
    monkeypatch.setattr(cfg, "MAX_HOLD_DAYS", 14.0)
    alerts = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, chat, msg: alerts.append(msg))
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _NoData)

    ex = _FakeExchange()
    info = _FakeInfo(mid=100.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}])
    fifteen_days_ago = int(time.time() * 1000) - 15 * 86400_000
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1, "entry_px": 100.0,
                                           "entry_ms": fifteen_days_ago}}})
    e.maybe_rebalance()
    assert ("BTC", 1.0) in ex.closed              # max-hold exit fired
    assert "BTC" not in e.state["entries"]
    assert any("stop" in m.lower() for m in alerts)  # anomaly still reported


# ---- MAX_GROSS_LEVERAGE structural entry cap -------------------------------

class _FreshShortData:
    """Feed stub: fresh short-signal frame for every coin."""

    def __init__(self, coins, lookback_bars):
        pass

    def frame_for(self, coin):
        return _short_signal_frame()

    def is_coin_stale(self, coin, staleness_hours):
        return False


def _cap_cfg(monkeypatch, tmp_path, universe=("BTC",)):
    _rebalance_cfg(monkeypatch, tmp_path, universe=universe)
    monkeypatch.setattr(cfg, "ENABLE_LONG", False)
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "NOTIONAL_PER_TRADE", 100.0)
    monkeypatch.setattr(cfg, "MAX_GROSS_LEVERAGE", 2.0)
    # No alert should fire in these tests, but the exit/orphan paths CAN
    # alert — mute structurally so a real token in .env.cta can never be used
    # (tests must not touch the real world).
    monkeypatch.setattr("hlvault.cta.live.send_alert", lambda tok, chat, msg: None)
    from hlvault.cta import data as data_mod
    monkeypatch.setattr(data_mod, "CtaData", _FreshShortData)


def test_gross_cap_blocks_new_entry_but_never_exits(monkeypatch, tmp_path, caplog):
    # (a) gross already over the cap -> the fresh BTC short is NOT opened,
    # while SOL's breached stop still closes (exits are risk-reducing and are
    # never gated). The ETH position is OUTSIDE the universe on purpose:
    # foreign/manual positions are real risk and must count toward gross.
    _cap_cfg(monkeypatch, tmp_path, universe=("BTC", "SOL"))

    ex = _FakeExchange()
    info = _FakeInfo(mid=50.0, spot_usdc=1000.0, positions=[
        {"coin": "SOL", "szi": "-1.0", "marginUsed": "10", "unrealizedPnl": "0"},
        {"coin": "ETH", "szi": "-50.0", "marginUsed": "40", "unrealizedPnl": "0"},
    ])
    # equity = 1000 spot + 50 marginUsed + 0 withdrawable = $1050 -> cap $2100
    # gross  = |-1|*50 (SOL) + |-50|*50 (ETH) = $2550 -> already over the cap
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1050.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"SOL": {"dir": -1, "entry_px": 100.0, "stop": 40.0,
                                           "entry_ms": int(time.time() * 1000)}}})
    with caplog.at_level(logging.INFO, logger="cta"):
        e.maybe_rebalance()

    assert [o for o in ex.orders if not o["reduce_only"]] == []   # BTC entry blocked
    assert ("SOL", 1.0) in ex.closed                              # stop exit still fired
    assert "BTC" not in e.state["entries"]
    assert "SOL" not in e.state["entries"]                        # exit bookkeeping cleared
    assert any("gross-leverage cap" in r.message and "BTC" in r.message
               for r in caplog.records)


def test_gross_cap_accumulates_within_one_cycle(monkeypatch, tmp_path, caplog):
    # (b) two fresh signals in ONE cycle: equity $75 -> cap $150. BTC's $100
    # open fits; it must be charged against the cycle budget immediately so
    # ETH's $100 (cumulative $200 > $150) is blocked. Without same-cycle
    # accumulation both checks would pass independently and blow the cap.
    _cap_cfg(monkeypatch, tmp_path, universe=("BTC", "ETH"))

    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, positions=[], spot_usdc=75.0, sz_decimals=3),
                ex, live=True)
    with caplog.at_level(logging.INFO, logger="cta"):
        e.maybe_rebalance()

    opens = [o for o in ex.orders if not o["reduce_only"]]
    assert len(opens) == 1 and opens[0]["coin"] == "BTC"
    assert "BTC" in e.state["entries"] and "ETH" not in e.state["entries"]
    assert any("gross-leverage cap" in r.message and "ETH" in r.message
               for r in caplog.records)


def test_gross_cap_zero_equity_blocks_entry_without_exception(monkeypatch, tmp_path, caplog):
    # (d) equity == 0 (empty wallet): the cap must treat it as over-limit —
    # no entry, an ERROR log, and NO exception. The per-coin isolation wrapper
    # logs "cycle processing failed" on any raise, so its absence proves the
    # guard path is exception-free (a naive division by equity would raise).
    _cap_cfg(monkeypatch, tmp_path, universe=("BTC",))

    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, positions=[], spot_usdc=0.0), ex, live=True)
    with caplog.at_level(logging.INFO, logger="cta"):
        e.maybe_rebalance()

    assert ex.orders == [] and e.state["entries"] == {}
    assert any(r.levelno == logging.ERROR and "BTC" in r.message
               and "equity" in r.message for r in caplog.records)
    assert not any("cycle processing failed" in r.message for r in caplog.records)


def test_gross_cap_missing_mid_counts_zero_and_warns(monkeypatch, tmp_path, caplog):
    # A position in a coin all_mids cannot price contributes $0 to gross (with
    # a loud warning) instead of crashing the cycle. Understating gross only
    # loosens an entry-blocking cap — it can never block a risk-reducing exit —
    # so the tolerant direction is deliberate.
    _cap_cfg(monkeypatch, tmp_path, universe=("BTC",))

    ex = _FakeExchange()
    info = _FakeInfo(mid=50.0, spot_usdc=1000.0, positions=[
        {"coin": "FOO", "szi": "-1000.0", "marginUsed": "0", "unrealizedPnl": "0"}])
    e = _engine(info, ex, live=True)
    with caplog.at_level(logging.INFO, logger="cta"):
        e.maybe_rebalance()

    opens = [o for o in ex.orders if not o["reduce_only"]]
    assert len(opens) == 1 and opens[0]["coin"] == "BTC"   # cap evaluated on gross=0
    assert any(r.levelno == logging.WARNING and "FOO" in r.message
               for r in caplog.records)


# ---- beta sleeve (Alpha+Beta instance B) -----------------------------------

def _beta_engine(monkeypatch, info, ex, *, frac=0.25, universe=("ETH","SOL","HYPE","DOGE","XRP"),
                 tol=0.10, live=True, state=None):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "BETA_TARGET_FRACTION", frac)
    monkeypatch.setattr(cfg, "BETA_COIN", "BTC")
    monkeypatch.setattr(cfg, "BETA_REBALANCE_TOLERANCE", tol)
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", list(universe))
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    return _engine(info, ex, live=live, state=state)


def test_beta_disabled_places_no_beta_order(monkeypatch):
    # frac=0 => _maybe_rebalance_beta returns immediately (wallet-A regression)
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0, spot_usdc=1000.0), ex, frac=0.0)
    e._maybe_rebalance_beta(equity=1000.0, pos_by_coin={}, gross_state={"equity":1000.0,"gross":0.0})
    assert ex.orders == [] and ex.closed == []

def test_beta_opens_to_target_when_flat(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    gs = {"equity":1000.0, "gross":0.0}
    e._maybe_rebalance_beta(equity=1000.0, pos_by_coin={}, gross_state=gs)
    # target $250 @ mid100 -> buy ~2.5 BTC, non-reduce-only (idempotent-open)
    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["coin"] == "BTC" and o["is_buy"] is True and o["reduce_only"] is False
    assert abs(o["size"] - 2.5) < 0.05
    assert abs(gs["gross"] - 250.0) < 1.0   # gross charged by the beta target

def test_beta_within_tolerance_no_order(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25, tol=0.10)
    # current BTC long = 2.4 @100 = $240 vs target $250 -> 4% dev < 10% band
    e._maybe_rebalance_beta(1000.0, {"BTC": 2.4}, {"equity":1000.0,"gross":240.0})
    assert ex.orders == [] and ex.closed == []

def test_beta_trims_with_reduce_only_when_over_target(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25, tol=0.05)
    # current $400 vs target $250 -> trim $150 as a reduce-only sell (idempotent)
    gs = {"equity":1000.0, "gross":400.0}
    e._maybe_rebalance_beta(1000.0, {"BTC": 4.0}, gs)
    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["is_buy"] is False and o["reduce_only"] is True
    assert abs(gs["gross"] - 250.0) < 1.0

def test_beta_adjustment_below_min_notional_skipped(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25, tol=0.0)
    # target $250 vs current $245 -> $5 adjustment < MIN_ORDER_NOTIONAL $12
    e._maybe_rebalance_beta(1000.0, {"BTC": 2.45}, {"equity":1000.0,"gross":245.0})
    assert ex.orders == []

def test_beta_short_position_is_anomaly_no_trade(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    e._maybe_rebalance_beta(1000.0, {"BTC": -1.0}, {"equity":1000.0,"gross":100.0})
    assert ex.orders == [] and ex.closed == []   # alerts + skips, never flips a short

def test_beta_nonpositive_equity_skips(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    e._maybe_rebalance_beta(0.0, {}, {"equity":0.0,"gross":0.0})
    assert ex.orders == []


class _FailingOrderExchange(_FakeExchange):
    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        raise RuntimeError("exchange rejected order")   # semantic -> single attempt


def test_beta_order_failure_alerts_with_instance_prefix(monkeypatch):
    # Review finding (observation, sub-project G2): a beta adjustment that
    # fails to place used to only log a warning, unlike the alpha exit-close
    # failure path which alerts loudly (live.py's exit-close except branch).
    # An operator watching only Telegram must see this too.
    ex = _FailingOrderExchange()
    alerts = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, chat, msg: alerts.append(msg))
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    gs = {"equity": 1000.0, "gross": 0.0}
    e._maybe_rebalance_beta(equity=1000.0, pos_by_coin={}, gross_state=gs)
    assert ex.orders == []                 # the raise means nothing was recorded as placed
    assert len(alerts) == 1
    assert alerts[0].startswith(f"{cfg.INSTANCE_LABEL.upper()} ")
    assert "BTC" in alerts[0]

def test_flatten_everything_closes_beta_btc(monkeypatch):
    # MDD halt: _flatten_everything iterates ALL positions incl. the beta BTC long
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    pos = [{"coin":"BTC","szi":"2.5","marginUsed":"25","unrealizedPnl":"0"}]
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0, positions=pos), ex, live=True)
    assert e._flatten_everything() is True
    assert ("BTC", 2.5) in ex.closed

def test_alert_prefix_is_CTA_for_wallet_a(monkeypatch):
    # INSTANCE_LABEL "cta" -> alert prefix "CTA": wallet-A text unchanged
    monkeypatch.setattr(cfg, "INSTANCE_LABEL", "cta")
    sent = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, cid, msg: sent.append(msg))
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    e = _engine(_FakeInfo(), _FakeExchange(), live=True,
                state={"halted":False,"peak_equity":1e9,"_alerted_this_halt":False,
                       "_flatten_complete":False,"last_rebalance_ms":0,"entries":{}})
    # drive a halt so the drawdown alert fires (peak >> current)
    e.check_drawdown()
    assert sent and sent[0].startswith("CTA ")
