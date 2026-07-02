from unittest.mock import patch

import pandas as pd

from hlvault.prices import get_candles, get_daily_returns

_RAW = [
    {"t": 1700000000000, "o": "10", "h": "12", "l": "9", "c": "11"},
    {"t": 1700086400000, "o": "11", "h": "13", "l": "10", "c": "12"},
]


def test_get_candles_returns_ohlc_frame_sorted_by_day():
    with patch("hlvault.prices._fetch_candles_raw", return_value=_RAW):
        df = get_candles("BTC", "1d", 0, 1)
    assert list(df.columns) == ["day", "o", "h", "l", "c"]
    assert len(df) == 2
    assert df["c"].tolist() == [11.0, 12.0]
    assert df["day"].is_monotonic_increasing


def test_get_candles_empty_response_returns_empty_frame_with_columns():
    with patch("hlvault.prices._fetch_candles_raw", return_value=[]):
        df = get_candles("BTC", "1d", 0, 1)
    assert list(df.columns) == ["day", "o", "h", "l", "c"]
    assert df.empty


def test_get_daily_returns_unchanged_after_refactor():
    with patch("hlvault.prices._fetch_candles_raw", return_value=_RAW):
        r = get_daily_returns("BTC", 0, 1)
    assert len(r) == 1
    assert abs(r.iloc[0] - (12.0 / 11.0 - 1.0)) < 1e-9
