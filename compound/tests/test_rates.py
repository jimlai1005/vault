import pytest

from compound import rates


def test_daily_apr_roundtrip():
    assert rates.daily_to_apr(0.0003715) == pytest.approx(0.1356, abs=1e-4)
    assert rates.apr_to_daily(rates.daily_to_apr(0.00025)) == pytest.approx(0.00025)


def test_target_floor_in_daily_terms():
    # 12% APR net target == gross daily ~0.000387 at 15% fee
    gross_daily_needed = rates.apr_to_daily(0.12) / (1 - 0.15)
    assert gross_daily_needed == pytest.approx(0.000387, abs=1e-6)


def test_net_daily_fee():
    assert rates.net_daily(0.0004, 0.15) == pytest.approx(0.00034)
    with pytest.raises(ValueError):
        rates.net_daily(0.0004, 1.0)
    with pytest.raises(ValueError):
        rates.net_daily(0.0004, -0.1)


def test_apy_exceeds_apr():
    daily = 0.000387
    assert rates.daily_to_apy(daily) > rates.daily_to_apr(daily)
