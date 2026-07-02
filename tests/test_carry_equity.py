# tests/test_carry_equity.py
from hlvault.carry.equity import CarrySnapshot, take_snapshot


class _FakeInfo:
    def __init__(self, spot_usdc="400.0", spot_hype="9.0", hype_mid="66.0",
                 szi="-9.0", margin_used="200.0", upnl="-5.0", withdrawable="95.0"):
        self._spot_usdc, self._spot_hype = spot_usdc, spot_hype
        self._mid, self._szi = hype_mid, szi
        self._margin, self._upnl, self._withdrawable = margin_used, upnl, withdrawable

    def spot_user_state(self, address):
        return {"balances": [
            {"coin": "USDC", "total": self._spot_usdc, "hold": "0.0"},
            {"coin": "HYPE", "total": self._spot_hype, "hold": "0.0"},
        ]}

    def user_state(self, address):
        pos = [] if float(self._szi) == 0 else [{"position": {
            "coin": "HYPE", "szi": self._szi,
            "marginUsed": self._margin, "unrealizedPnl": self._upnl}}]
        return {"assetPositions": pos, "withdrawable": self._withdrawable}

    def all_mids(self):
        return {"HYPE": self._mid, "@107": self._mid}


def test_snapshot_totals_and_equity_from_one_read():
    info = _FakeInfo()
    s = take_snapshot(info, "0xabc", coin="HYPE", spot_pair="@107")
    assert s.spot_usdc == 400.0
    assert s.spot_coin_size == 9.0
    assert abs(s.spot_coin_ntl - 9.0 * 66.0) < 1e-9
    assert s.perp_short_size == 9.0           # abs of szi, short
    assert abs(s.perp_short_ntl - 9.0 * 66.0) < 1e-9
    assert s.perp_margin_used == 200.0
    assert s.perp_withdrawable == 95.0
    # equity = spot USDC + spot HYPE ntl + margin + upnl + withdrawable
    assert abs(s.equity - (400.0 + 594.0 + 200.0 - 5.0 + 95.0)) < 1e-9


def test_short_leverage_and_delta():
    s = take_snapshot(_FakeInfo(), "0xabc", coin="HYPE", spot_pair="@107")
    # leverage = short notional / (margin + upnl + withdrawable)
    assert abs(s.short_leverage - 594.0 / (200.0 - 5.0 + 95.0)) < 1e-9
    assert abs(s.delta_ntl - (594.0 - 594.0)) < 1e-9


def test_flat_wallet_has_zero_leverage_not_crash():
    info = _FakeInfo(spot_hype="0.0", szi="0.0", margin_used="0.0",
                     upnl="0.0", withdrawable="0.0", spot_usdc="1000.0")
    s = take_snapshot(info, "0xabc", coin="HYPE", spot_pair="@107")
    assert s.equity == 1000.0
    assert s.short_leverage == 0.0
    assert s.perp_short_size == 0.0


def test_long_perp_position_is_reported_negative_short():
    # a LONG perp position (szi > 0) must not masquerade as a short
    s = take_snapshot(_FakeInfo(szi="3.0"), "0xabc", coin="HYPE", spot_pair="@107")
    assert s.perp_short_size == -3.0  # signed: negative means "not short"
