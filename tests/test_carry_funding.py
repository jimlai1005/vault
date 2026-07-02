from unittest.mock import patch

from hlvault.carry.funding import trailing_funding_apr, funding_ok


def _rates(hourly_rate, hours):
    return [{"fundingRate": str(hourly_rate), "time": 1000 + i} for i in range(hours)]


def test_trailing_funding_apr_annualizes_hourly_mean():
    # 1bp/hour = 0.0001 * 24 * 365 = 87.6% APR
    with patch("hlvault.carry.funding._fetch_funding", return_value=_rates(0.0001, 168)):
        apr = trailing_funding_apr("HYPE", days=7)
    assert abs(apr - 0.0001 * 24 * 365) < 1e-9


def test_trailing_funding_apr_empty_history_is_zero():
    with patch("hlvault.carry.funding._fetch_funding", return_value=[]):
        assert trailing_funding_apr("HYPE", days=7) == 0.0


def test_funding_ok_thresholds():
    assert funding_ok(0.05, exit_apr=0.0) is True
    assert funding_ok(-0.01, exit_apr=0.0) is False
    assert funding_ok(0.0, exit_apr=0.0) is False  # strictly greater required
