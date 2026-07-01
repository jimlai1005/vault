from hlvault.gridbot.exchange_utils import get_account_equity, round_price, round_size


class _FakeInfo:
    def __init__(self, positions, spot_usdc):
        self._positions = positions
        self._spot_usdc = spot_usdc

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}


def test_equity_is_spot_plus_position_economics_not_margin_summary():
    # regression: marginSummary.accountValue was observed swinging
    # $0 -> $335 -> $6.58 purely from resting-order count with equity flat
    # near $1000 — using it caused a false-positive drawdown halt.
    info = _FakeInfo(
        positions=[{"marginUsed": "2.62", "unrealizedPnl": "0.08"}],
        spot_usdc=1000.15,
    )
    equity = get_account_equity(info, "0xabc")
    assert abs(equity - (1000.15 + 2.62 + 0.08)) < 1e-9


def test_equity_with_no_positions_is_just_spot():
    info = _FakeInfo(positions=[], spot_usdc=1000.0)
    assert get_account_equity(info, "0xabc") == 1000.0


def test_round_price_respects_significant_figures_and_decimals():
    assert round_price(63704.567, sz_decimals=3) == 63705  # 5 sig figs, 3 decimals allowed
    assert round_price(1.234567, sz_decimals=2) == 1.2346  # 6-2=4 decimals, 5 sig figs


def test_round_size_truncates_not_rounds():
    assert round_size(0.5559, sz_decimals=2) == 0.55
