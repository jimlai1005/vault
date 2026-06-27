import pandas as pd

from hlvault.prices import candles_to_returns


def test_candles_to_returns_close_to_close():
    candles = [
        {"t": 1753488000000, "c": "100"},
        {"t": 1753574400000, "c": "110"},
        {"t": 1753660800000, "c": "99"},
    ]
    r = candles_to_returns(candles)
    assert len(r) == 2
    assert abs(r.iloc[0] - 0.10) < 1e-9
    assert abs(r.iloc[1] - (-0.10)) < 1e-9


def test_candles_to_returns_empty():
    assert candles_to_returns([]).empty
