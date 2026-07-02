from hlvault.momentum.risk import (
    check_drawdown, compute_order, risk_budget_per_coin, target_position_notional,
)


def test_risk_budget_matches_gridbot_allocator_inverse_vol_capped():
    # same algorithm as hlvault.gridbot.allocator.allocate_capital — this
    # test just confirms momentum's wrapper calls it correctly, not a
    # re-derivation of the inverse-vol math (already tested there).
    budgets = risk_budget_per_coin({"BTC": 0.01, "ETH": 0.02}, 1000.0, 0.6)
    assert abs(sum(budgets.values()) - 1000.0) < 1e-6
    assert budgets["BTC"] > budgets["ETH"]  # lower vol -> bigger budget


def test_target_position_notional_scales_by_signal_and_leverage():
    assert target_position_notional(1.0, risk_budget=100.0, max_leverage=3.0) == 300.0
    assert target_position_notional(-0.5, risk_budget=100.0, max_leverage=3.0) == -150.0
    assert target_position_notional(0.0, risk_budget=100.0, max_leverage=3.0) == 0.0


def test_target_position_notional_clips_out_of_range_signal():
    assert target_position_notional(2.0, risk_budget=100.0, max_leverage=3.0) == 300.0
    assert target_position_notional(-2.0, risk_budget=100.0, max_leverage=3.0) == -300.0


def test_compute_order_opens_new_long_from_flat():
    order = compute_order(current_size=0.0, target_notional=1000.0, price=100.0, min_order_notional=10.0)
    assert order == {"is_buy": True, "size": 10.0, "reduce_only": False}


def test_compute_order_reduces_existing_long_without_flipping():
    # long 10 @ price 100 (notional 1000), target notional 400 -> sell down to 4
    order = compute_order(current_size=10.0, target_notional=400.0, price=100.0, min_order_notional=10.0)
    assert order == {"is_buy": False, "size": 6.0, "reduce_only": True}


def test_compute_order_flip_long_to_short_is_not_reduce_only():
    order = compute_order(current_size=5.0, target_notional=-500.0, price=100.0, min_order_notional=10.0)
    assert order["is_buy"] is False
    assert order["reduce_only"] is False  # crosses zero, not a pure reduce


def test_compute_order_returns_none_below_min_notional():
    order = compute_order(current_size=1.0, target_notional=101.0, price=100.0, min_order_notional=10.0)
    assert order is None


def test_check_drawdown_halts_at_threshold_using_one_equity_source():
    calls = {"n": 0}

    class FakeInfo:
        def user_state(self, address):
            calls["n"] += 1
            # first call: equity 1000 (sets peak); second call: equity 790 (21% down)
            equity = 1000.0 if calls["n"] == 1 else 790.0
            return {"assetPositions": [{"position": {"marginUsed": str(equity), "unrealizedPnl": "0"}}]}

        def spot_user_state(self, address):
            return {"balances": []}

    info = FakeInfo()
    state = {"halted": False, "peak_equity": 0.0}
    halted, state = check_drawdown(info, "0xabc", state, max_drawdown_pct=0.20)
    assert halted is False
    assert state["peak_equity"] == 1000.0

    halted, state = check_drawdown(info, "0xabc", state, max_drawdown_pct=0.20)
    assert halted is True
    assert state["halted"] is True


def test_check_drawdown_stays_halted_without_recomputing_equity():
    class BoomInfo:
        def user_state(self, address):
            raise AssertionError("must not re-check equity once halted")

        def spot_user_state(self, address):
            raise AssertionError("must not re-check equity once halted")

    halted, state = check_drawdown(BoomInfo(), "0xabc", {"halted": True, "peak_equity": 1000.0}, 0.20)
    assert halted is True
