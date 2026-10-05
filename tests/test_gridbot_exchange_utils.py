from hlvault.gridbot.exchange_utils import (
    equity_breakdown, get_account_equity, get_full_account_equity, round_price, round_size,
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
    def __init__(self, account_value, spot_usdc, hold=0.0, abstraction="none",
                 coins=None, universe=None, mids=None):
        self._av = account_value
        self._spot = spot_usdc
        self._hold = hold
        self._abstraction = abstraction
        self._coins = coins or []          # list of (coin, token, total)
        self._universe = universe or []    # list of (pair_name, base_token, quote_token)
        self._mids = mids or {}
        self.calls = []

    def user_state(self, address):
        return {"marginSummary": {"accountValue": str(self._av)},
                "assetPositions": [], "withdrawable": "0"}

    def spot_user_state(self, address):
        bals = [{"coin": "USDC", "token": 0, "total": str(self._spot), "hold": str(self._hold)}]
        bals += [{"coin": c, "token": t, "total": str(tot), "hold": "0.0"} for c, t, tot in self._coins]
        return {"balances": bals}

    def post(self, path, payload):
        self.calls.append(("post", payload["type"]))
        assert payload == {"type": "userAbstraction", "user": "0xabc"}
        return self._abstraction

    def spot_meta(self):
        self.calls.append(("spot_meta",))
        return {"universe": [{"name": n, "index": i, "tokens": [b, q]}
                             for i, (n, b, q) in enumerate(self._universe)],
                "tokens": []}

    def all_mids(self):
        self.calls.append(("all_mids",))
        return dict(self._mids)


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

        def post(self, path, payload):
            return "none"

    assert get_full_account_equity(_Empty(), "0xabc") == 12.5


def test_full_equity_counts_spot_coins_at_usdc_mid():
    # 2026-09-22 incident shape: owner swapped ~$699 USDC into 0.0082 UBTC.
    # Old basis dropped by the whole purchase; new basis must be flat.
    def make():
        return _FakeInfoFull(account_value=0.0, spot_usdc=686.21,
                             coins=[("UBTC", 197, 0.0081968513)],
                             universe=[("@142", 197, 0), ("@234", 197, 360)],
                             mids={"@142": "86244.0", "@234": "86300.0"})
    info = make()
    bd = equity_breakdown(info, "0xabc", spot_basis="all")
    assert abs(bd["spot_coins"] - 0.0081968513 * 86244.0) < 1e-6
    # one call -> spot_meta and all_mids each called exactly once
    assert info.calls.count(("spot_meta",)) == 1 and info.calls.count(("all_mids",)) == 1
    assert abs(get_full_account_equity(make(), "0xabc", spot_basis="all")
               - (686.21 + 0.0081968513 * 86244.0)) < 1e-6


def test_full_equity_usdc_basis_ignores_spot_coins_and_skips_meta_calls():
    info = _FakeInfoFull(account_value=10.0, spot_usdc=100.0,
                         coins=[("UBTC", 197, 1.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "86244.0"})
    assert get_full_account_equity(info, "0xabc", spot_basis="usdc") == 110.0
    assert ("spot_meta",) not in info.calls and ("all_mids",) not in info.calls


def test_full_equity_zero_balance_coins_do_not_trigger_meta_calls():
    info = _FakeInfoFull(account_value=0.0, spot_usdc=50.0,
                         coins=[("USDE", 235, 0.0), ("USDT0", 268, 0.0)])
    assert get_full_account_equity(info, "0xabc", spot_basis="all") == 50.0
    assert ("spot_meta",) not in info.calls


def test_full_equity_raises_when_spot_coin_has_no_usdc_pair():
    import pytest
    info = _FakeInfoFull(account_value=0.0, spot_usdc=50.0,
                         coins=[("XYZ", 999, 3.0)],
                         universe=[("@500", 999, 360)], mids={"@500": "1.0"})
    with pytest.raises(ValueError, match="XYZ"):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_full_equity_unified_account_does_not_double_count_hold():
    # measured 2026-10-05 07:50 UTC before the owner closed manual positions:
    # spot USDC total 685.65 (hold 176.38), perp accountValue 173.03, UBTC 0.0081968513 @ 86244
    # HL portfolio accountValue at that moment ~1,390
    info = _FakeInfoFull(account_value=173.03, spot_usdc=685.65, hold=176.38,
                         abstraction="unifiedAccount",
                         coins=[("UBTC", 197, 0.0081968513)],
                         universe=[("@142", 197, 0)], mids={"@142": "86244.0"})
    bd = equity_breakdown(info, "0xabc", spot_basis="all")
    assert abs(bd["spot_hold_adjust"] + 176.38) < 1e-9
    total = get_full_account_equity(info, "0xabc", spot_basis="all")
    assert abs(total - ((685.65 - 176.38) + 173.03 + 0.0081968513 * 86244.0)) < 1e-6
    assert 1385.0 < total < 1395.0


def test_full_equity_non_unified_account_keeps_hold():
    # non-unified: spot hold is just resting spot orders - still the owner's money
    info = _FakeInfoFull(account_value=20.0, spot_usdc=100.0, hold=30.0, abstraction="none")
    bd = equity_breakdown(info, "0xabc", spot_basis="all")
    assert bd["spot_hold_adjust"] == 0.0
    assert get_full_account_equity(info, "0xabc", spot_basis="all") == 120.0


def test_full_equity_default_basis_comes_from_config(monkeypatch):
    from hlvault.gridbot import config as cfg
    info = _FakeInfoFull(account_value=0.0, spot_usdc=100.0,
                         coins=[("UBTC", 197, 1.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "5.0"})
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "usdc")
    assert get_full_account_equity(info, "0xabc") == 100.0
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "all")
    assert get_full_account_equity(info, "0xabc") == 105.0
