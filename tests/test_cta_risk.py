# tests/test_cta_risk.py
import math

import pytest

from hlvault.cta import risk


class _FakeInfo:
    def __init__(self, positions, spot_usdc):
        self._positions = positions
        self._spot_usdc = spot_usdc

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}


def test_position_size_is_notional_over_price():
    assert abs(risk.position_size(100.0, price=50.0) - 2.0) < 1e-9
    assert risk.position_size(100.0, price=0.0) == 0.0  # guard divide-by-zero


def test_stop_level_short_is_above_entry_long_is_below():
    # SHORT (dir -1): stop = entry + mult*atr (above); LONG (dir 1): below
    assert risk.stop_level(direction=-1, entry_px=100.0, atr=5.0, mult=2.0) == 110.0
    assert risk.stop_level(direction=1, entry_px=100.0, atr=5.0, mult=2.0) == 90.0


def test_stop_hit_short_triggers_when_price_rises_to_stop():
    # short stop at 110; price 111 -> hit ; price 105 -> not hit
    assert risk.stop_hit(direction=-1, stop=110.0, price=111.0) is True
    assert risk.stop_hit(direction=-1, stop=110.0, price=105.0) is False


def test_stop_hit_long_triggers_when_price_falls_to_stop():
    assert risk.stop_hit(direction=1, stop=90.0, price=89.0) is True
    assert risk.stop_hit(direction=1, stop=90.0, price=95.0) is False


def test_account_equity_uses_gridbot_basis_usdc_plus_perp_only():
    # equity = spot USDC + sum(marginUsed + upnl). NO withdrawable (carry bug guard).
    info = _FakeInfo(positions=[
        {"coin": "BTC", "szi": "-0.01", "marginUsed": "300", "unrealizedPnl": "-5"},
    ], spot_usdc=700.0)
    assert abs(risk.account_equity(info, "0xabc") - (700.0 + 300.0 - 5.0)) < 1e-9


def test_account_equity_ignores_withdrawable_field_if_present():
    # Regression guard for the 2026-07-04 carry double-count bug: even if a
    # `withdrawable` field is present in user_state, the CTA equity basis must
    # NOT add it — equity stays spot USDC + Σ(marginUsed + upnl).
    class _InfoWithWithdrawable(_FakeInfo):
        def user_state(self, address):
            return {"withdrawable": "9999",
                    "assetPositions": [{"position": p} for p in self._positions]}

    info = _InfoWithWithdrawable(positions=[
        {"coin": "BTC", "szi": "-0.01", "marginUsed": "300", "unrealizedPnl": "-5"},
    ], spot_usdc=700.0)
    # carry's buggy basis would be 700 + 9999 + 300 - 5; correct basis excludes withdrawable
    assert abs(risk.account_equity(info, "0xabc") - (700.0 + 300.0 - 5.0)) < 1e-9


def test_check_drawdown_sets_peak_then_halts_past_threshold():
    info_peak = _FakeInfo([{"coin": "BTC", "szi": "-0.01", "marginUsed": "1000",
                            "unrealizedPnl": "0"}], spot_usdc=0.0)
    state = {"halted": False, "peak_equity": 0.0}
    halted, state = risk.check_drawdown(info_peak, "0xabc", state, 0.20)
    assert halted is False and state["peak_equity"] == 1000.0

    info_down = _FakeInfo([{"coin": "BTC", "szi": "-0.01", "marginUsed": "790",
                            "unrealizedPnl": "0"}], spot_usdc=0.0)
    halted, state = risk.check_drawdown(info_down, "0xabc", state, 0.20)
    assert halted is True and state["halted"] is True  # 21% dd


def test_check_drawdown_returns_true_immediately_when_already_halted():
    state = {"halted": True, "peak_equity": 1000.0}
    halted, out = risk.check_drawdown(_FakeInfo([], 0.0), "0xabc", state, 0.20)
    assert halted is True and out is state


def test_check_drawdown_uses_same_snapshot_for_peak_and_current():
    # Peak and current must derive from ONE account_equity call (CLAUDE.md #1):
    # on the same cycle a fresh equity becomes both the new peak and current,
    # so drawdown is exactly 0 and never a phantom positive.
    info = _FakeInfo([{"coin": "BTC", "szi": "-0.01", "marginUsed": "500",
                       "unrealizedPnl": "0"}], spot_usdc=0.0)
    state = {"halted": False, "peak_equity": 0.0}
    halted, state = risk.check_drawdown(info, "0xabc", state, 0.20)
    assert halted is False and state["peak_equity"] == 500.0


# ---- (A) ATR entry gate: NaN / non-positive ATR must not size or stop ----

def test_atr_gate_ok_rejects_nan_and_nonpositive():
    assert risk.atr_gate_ok(5.0) is True
    assert risk.atr_gate_ok(float("nan")) is False
    assert risk.atr_gate_ok(0.0) is False
    assert risk.atr_gate_ok(-1.0) is False


def test_stop_level_nan_atr_returns_nan_not_garbage():
    # warmup ATR is NaN; stop must propagate NaN (caller gate rejects entry)
    # rather than silently producing a stop level the engine would trade on.
    assert math.isnan(risk.stop_level(direction=-1, entry_px=100.0,
                                      atr=float("nan"), mult=2.0))


def test_stop_level_nonpositive_atr_returns_nan():
    assert math.isnan(risk.stop_level(direction=-1, entry_px=100.0, atr=0.0, mult=2.0))
    assert math.isnan(risk.stop_level(direction=1, entry_px=100.0, atr=-3.0, mult=2.0))
