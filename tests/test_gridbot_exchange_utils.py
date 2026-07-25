from hlvault.gridbot.exchange_utils import (
    get_account_equity, get_full_account_equity, round_price, round_size,
)


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


class _FakeInfoFull:
    def __init__(self, account_value, spot_usdc):
        self._av = account_value
        self._spot = spot_usdc

    def user_state(self, address):
        return {"marginSummary": {"accountValue": str(self._av)},
                "assetPositions": [], "withdrawable": "0"}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot)}]}


def test_full_equity_is_spot_plus_perp_account_value():
    # live measurement 2026-07-25: spot 1048.04 + perp accountValue 46.63,
    # accountValue == marginUsed + withdrawable + resting-order reserved margin
    info = _FakeInfoFull(account_value=46.63, spot_usdc=1048.04)
    assert abs(get_full_account_equity(info, "0xabc") - 1094.67) < 1e-9


def test_full_equity_counts_free_margin_the_old_basis_missed():
    # 2026-07-21 incident shape: flat book, all cash on the perp side —
    # old basis read $0.00, full basis must see the account value
    info = _FakeInfoFull(account_value=1077.96, spot_usdc=0.0)
    assert get_account_equity(info, "0xabc") == 0.0
    assert abs(get_full_account_equity(info, "0xabc") - 1077.96) < 1e-9


def test_full_equity_tolerates_missing_margin_summary():
    class _Empty:
        def user_state(self, address):
            return {}

        def spot_user_state(self, address):
            return {"balances": [{"coin": "USDC", "total": "12.5"}]}

    assert get_full_account_equity(_Empty(), "0xabc") == 12.5
