# tests/test_cta_risk.py
import math

import pytest

from hlvault.cta import risk


class _FakeInfo:
    """Fake honouring the on-chain verified no-resting-orders identity
    (vault CLAUDE.md API facts, 2026-07-04): `withdrawable` ALREADY includes
    unrealizedPnl, and accountValue == totalMarginUsed + withdrawable. The CTA
    engine is IoC-only (never rests orders), so its wallet always satisfies
    this identity."""

    def __init__(self, positions=None, spot_usdc=0.0, margin_used=0.0,
                 withdrawable=0.0):
        self._positions = positions or []
        self._spot_usdc = spot_usdc
        self._margin_used = margin_used
        self._withdrawable = withdrawable

    def user_state(self, address):
        return {
            "assetPositions": [{"position": p} for p in self._positions],
            "marginSummary": {
                "totalMarginUsed": str(self._margin_used),
                "accountValue": str(self._margin_used + self._withdrawable),
            },
            "withdrawable": str(self._withdrawable),
        }

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


def test_account_equity_counts_perp_free_collateral():
    # Regression for the THIRD equity-basis incident (2026-07-04): this wallet
    # parks part of its idle USDC as perp free collateral (`withdrawable`,
    # measured ~$281 = 28% of the account). The old gridbot basis
    # (spot USDC + Σ per-position marginUsed+upnl) is blind to that bucket and
    # would report 715 here — anchoring the MDD breaker's peak 28% too low.
    info = _FakeInfo(positions=[], spot_usdc=715.0, margin_used=0.0,
                     withdrawable=281.0)
    assert abs(risk.account_equity(info, "0xabc") - 996.0) < 1e-9  # NOT 715


def test_account_equity_does_not_add_upnl_on_top_of_withdrawable():
    # Regression for carry incident #2, direction updated for the new basis:
    # `withdrawable` ALREADY includes unrealizedPnl, so the basis must count
    # withdrawable and must NOT add upnl again. Numbers mirror the on-chain
    # verified carry snapshot: accountValue 281.13 == totalMarginUsed 63.34 +
    # withdrawable 217.79, with upnl -28.41 already inside withdrawable.
    info = _FakeInfo(
        positions=[{"coin": "BTC", "szi": "-0.01", "marginUsed": "63.34",
                    "unrealizedPnl": "-28.41"}],
        spot_usdc=715.0, margin_used=63.34, withdrawable=217.79)
    eq = risk.account_equity(info, "0xabc")
    assert abs(eq - (715.0 + 63.34 + 217.79)) < 1e-9
    # explicitly: adding upnl a second time is the carry double-count bug
    assert abs(eq - (715.0 + 63.34 + 217.79 + (-28.41))) > 1.0


def test_account_equity_does_not_read_asset_positions():
    # The basis is marginSummary.totalMarginUsed + withdrawable (+ spot USDC);
    # open positions' economics are already reflected in those two fields.
    # These position dicts lack the per-position marginUsed/unrealizedPnl keys
    # the old gridbot basis summed — a basis that still read assetPositions
    # would KeyError or return the wrong number here.
    info = _FakeInfo(
        positions=[{"coin": "BTC", "szi": "-0.5"}],  # no marginUsed / upnl keys
        spot_usdc=100.0, margin_used=40.0, withdrawable=60.0)
    assert abs(risk.account_equity(info, "0xabc") - 200.0) < 1e-9


def test_check_drawdown_sets_peak_then_halts_past_threshold():
    # equity 1000 spread across margin + free collateral (both buckets count)
    info_peak = _FakeInfo(margin_used=800.0, withdrawable=200.0)
    state = {"halted": False, "peak_equity": 0.0}
    halted, state = risk.check_drawdown(info_peak, "0xabc", state, 0.20)
    assert halted is False and state["peak_equity"] == 1000.0

    info_down = _FakeInfo(margin_used=790.0, withdrawable=0.0)
    halted, state = risk.check_drawdown(info_down, "0xabc", state, 0.20)
    assert halted is True and state["halted"] is True  # 21% dd


def test_check_drawdown_returns_true_immediately_when_already_halted():
    state = {"halted": True, "peak_equity": 1000.0}
    halted, out = risk.check_drawdown(_FakeInfo(), "0xabc", state, 0.20)
    assert halted is True and out is state


def test_check_drawdown_uses_same_snapshot_for_peak_and_current():
    # Peak and current must derive from ONE account_equity call (CLAUDE.md #1):
    # on the same cycle a fresh equity becomes both the new peak and current,
    # so drawdown is exactly 0 and never a phantom positive.
    info = _FakeInfo(margin_used=300.0, withdrawable=200.0)  # equity 500
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
