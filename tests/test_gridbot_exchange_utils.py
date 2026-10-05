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
                 coins=None, universe=None, mids=None, portfolio=None):
        self._av = account_value
        self._spot = spot_usdc
        self._hold = hold
        self._abstraction = abstraction
        self._coins = coins or []          # list of (coin, token, total)
        self._universe = universe or []    # list of (pair_name, base_token, quote_token)
        self._mids = mids or {}
        self._portfolio = portfolio  # list of (ts_ms, value) or None
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
        assert payload["user"] == "0xabc"
        if payload["type"] == "userAbstraction":
            return self._abstraction
        if payload["type"] == "portfolio":
            if self._portfolio is None:
                raise RuntimeError("portfolio endpoint down")
            hist = [[ts, str(v)] for ts, v in self._portfolio]
            return [["day", {"accountValueHistory": hist, "pnlHistory": [], "vlm": "0"}],
                    ["week", {"accountValueHistory": hist, "pnlHistory": [], "vlm": "0"}]]
        raise AssertionError(payload)

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
    assert abs(get_full_account_equity(info, "0xabc", spot_basis="usdc") - 1094.67) < 1e-9


def test_full_equity_counts_free_margin_the_old_basis_missed():
    # 2026-07-21 incident shape: flat book, all cash on the perp side —
    # old basis read $0.00, full basis must see the account value
    info = _FakeInfoFull(account_value=1077.96, spot_usdc=0.0)
    assert get_account_equity(info, "0xabc") == 0.0
    assert abs(get_full_account_equity(info, "0xabc", spot_basis="usdc") - 1077.96) < 1e-9


def test_full_equity_tolerates_missing_margin_summary():
    class _Empty:
        def user_state(self, address):
            return {}

        def spot_user_state(self, address):
            return {"balances": [{"coin": "USDC", "total": "12.5"}]}

        def post(self, path, payload):
            return "none"

    assert get_full_account_equity(_Empty(), "0xabc", spot_basis="usdc") == 12.5


import time


def _now_ms():
    return int(time.time() * 1000)


def test_all_basis_returns_portfolio_latest_point():
    # 2026-10-05: HL portfolio 1393.66 = USDC 686.48 + UBTC 708.46 - hold already handled by HL
    info = _FakeInfoFull(account_value=46.42, spot_usdc=686.48, hold=46.42,
                         portfolio=[(_now_ms() - 3_600_000, 1356.36), (_now_ms(), 1393.66)])
    assert get_full_account_equity(info, "0xabc", spot_basis="all") == 1393.66
    assert ("spot_meta",) not in info.calls


def test_all_basis_stale_point_raises(monkeypatch):
    from hlvault.gridbot import config as cfg
    monkeypatch.setattr(cfg, "PORTFOLIO_MAX_AGE_SECONDS", 300)
    info = _FakeInfoFull(account_value=0.0, spot_usdc=1.0,
                         portfolio=[(_now_ms() - 10 * 60_000, 1393.66)])
    import pytest
    with pytest.raises(ValueError, match="stale"):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_all_basis_empty_history_raises():
    import pytest
    info = _FakeInfoFull(account_value=0.0, spot_usdc=1.0, portfolio=[])
    with pytest.raises(ValueError, match="portfolio"):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_all_basis_endpoint_error_propagates():
    import pytest
    info = _FakeInfoFull(account_value=0.0, spot_usdc=1.0, portfolio=None)
    with pytest.raises(RuntimeError):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_usdc_basis_is_spot_usdc_total_plus_account_value_unchanged():
    # pre-2026-10 behaviour, byte-for-byte: no hold adjustment, no spot coins, no portfolio call
    info = _FakeInfoFull(account_value=46.42, spot_usdc=686.48, hold=46.42,
                         abstraction="unifiedAccount", coins=[("UBTC", 197, 1.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "86000"},
                         portfolio=[(_now_ms(), 9999.0)])
    assert abs(get_full_account_equity(info, "0xabc", spot_basis="usdc") - 732.90) < 1e-9
    assert ("post", "portfolio") not in info.calls and ("spot_meta",) not in info.calls


def test_default_basis_comes_from_config(monkeypatch):
    from hlvault.gridbot import config as cfg
    info = _FakeInfoFull(account_value=10.0, spot_usdc=100.0, portfolio=[(_now_ms(), 555.0)])
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "usdc")
    assert get_full_account_equity(info, "0xabc") == 110.0
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "all")
    assert get_full_account_equity(info, "0xabc") == 555.0


def test_breakdown_is_informational_and_never_raises_on_unpriced_coin():
    info = _FakeInfoFull(account_value=46.42, spot_usdc=686.48, hold=46.42,
                         abstraction="unifiedAccount",
                         coins=[("UBTC", 197, 0.0081968513), ("XYZ", 999, 3.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "86244.0"},
                         portfolio=[(_now_ms(), 1393.66)])
    bd = equity_breakdown(info, "0xabc")
    assert bd["spot_usdc_total"] == 686.48
    assert bd["spot_usdc_hold"] == 46.42
    assert abs(bd["spot_coins"] - 0.0081968513 * 86244.0) < 1e-6
    assert bd["perp_account_value"] == 46.42
    assert bd["portfolio_value"] == 1393.66
    assert bd["unpriced_coins"] == ["XYZ"]
    assert bd["abstraction"] == "unifiedAccount"
