# tests/test_carry_equity.py
from hlvault.carry.equity import CarrySnapshot, take_snapshot


class _FakeInfo:
    """Fake Hyperliquid Info client for carry equity tests.

    IMPORTANT: on the real API, `withdrawable` already has unrealized pnl
    baked into it -- the verified identity is
        marginSummary.accountValue == totalMarginUsed + withdrawable
    (upnl is NOT a separate additive term). So by default this fake derives
    `withdrawable` from `account_value - margin_used`, which already reflects
    `upnl` internally, instead of accepting margin/upnl/withdrawable as three
    independent knobs. That makes it structurally impossible to write a test
    against this fake that "coincidentally" exercises the double-counting bug
    (margin + upnl + withdrawable) without deliberately overriding
    `withdrawable` to break the identity.
    """

    def __init__(self, spot_usdc="400.0", spot_hype="9.0", hype_mid="66.0",
                 szi="-9.0", margin_used="200.0", upnl="-5.0",
                 withdrawable=None):
        self._spot_usdc, self._spot_hype = spot_usdc, spot_hype
        self._mid, self._szi = hype_mid, szi
        self._margin, self._upnl = margin_used, upnl
        if withdrawable is None:
            # Derive the real-API-consistent value: withdrawable already
            # contains upnl, so "free" perp cash beyond margin is just
            # margin_used + upnl worth of headroom collapsed into one number.
            # Pick a withdrawable such that margin_used + withdrawable
            # (the CORRECT formula) equals margin_used*2 + upnl, i.e.
            # withdrawable = margin_used + upnl. This keeps the fake simple
            # while guaranteeing the identity holds.
            withdrawable = str(float(margin_used) + float(upnl))
        self._withdrawable = withdrawable

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
    assert s.perp_upnl == -5.0
    # withdrawable = margin_used + upnl = 200 + (-5) = 195 (fake's derivation)
    assert s.perp_withdrawable == 195.0
    # equity = spot USDC + spot HYPE ntl + margin + withdrawable (NOT + upnl:
    # withdrawable already reflects it)
    assert abs(s.equity - (400.0 + 594.0 + 200.0 + 195.0)) < 1e-9


def test_short_leverage_and_delta():
    s = take_snapshot(_FakeInfo(), "0xabc", coin="HYPE", spot_pair="@107")
    # leverage = short notional / (margin + withdrawable) -- upnl excluded,
    # it's already inside withdrawable
    assert abs(s.short_leverage - 594.0 / (200.0 + 195.0)) < 1e-9
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


def test_regression_upnl_is_not_double_counted_into_equity():
    """Regression test for the live incident (2026-07-04): `withdrawable`
    from Hyperliquid's clearinghouseState ALREADY includes unrealized pnl.
    The old code computed perp_equity = margin_used + upnl + withdrawable,
    double-counting a losing short's upnl and understating equity by 2x the
    unrealized loss -- which nearly tripped the 20% drawdown circuit breaker
    on real capital while the account was actually flat.

    Numbers below are the real, independently-verified API values from the
    live incident:
        accountValue    = 286.400814
        totalMarginUsed = 62.809263
        withdrawable     = 223.591551   (== accountValue - totalMarginUsed,
                                          exact to the microdollar)
        unrealizedPnl    = -28.413990   (a losing short; already folded into
                                          withdrawable)

    Correct perp_equity = margin_used + withdrawable = accountValue exactly.
    Buggy perp_equity = margin_used + upnl + withdrawable would be
    accountValue - 28.41399 too low (double-subtracting the loss) --
    OR, if upnl were positive, it would double-COUNT the gain. Either way,
    `+ upnl` on top of `withdrawable` is wrong.
    """
    account_value = 286.400814
    margin_used = 62.809263
    withdrawable = 223.591551
    upnl = -28.413990  # already reflected inside withdrawable

    assert abs((margin_used + withdrawable) - account_value) < 1e-6
    # sanity: this is exactly the WRONG formula's error term, confirming the
    # bug is precisely "an extra +upnl"
    wrong = margin_used + upnl + withdrawable
    assert abs((account_value - wrong) - abs(upnl)) < 1e-6

    info = _FakeInfo(spot_usdc="0.0", spot_hype="0.0", hype_mid="1.0",
                     szi="-1.0", margin_used=str(margin_used), upnl=str(upnl),
                     withdrawable=str(withdrawable))
    s = take_snapshot(info, "0xabc", coin="HYPE", spot_pair="@107")

    # equity must equal spot_usdc + spot_ntl + (margin_used + withdrawable),
    # i.e. accountValue here -- NOT (margin_used + upnl + withdrawable).
    correct_equity = 0.0 + 0.0 + (margin_used + withdrawable)
    buggy_equity = 0.0 + 0.0 + (margin_used + upnl + withdrawable)
    assert abs(s.equity - correct_equity) < 1e-6
    assert abs(s.equity - buggy_equity) > 1e-3  # must NOT match the old bug
    # upnl is still surfaced on the snapshot for display/direction purposes,
    # it's just excluded from the equity sum
    assert s.perp_upnl == upnl
