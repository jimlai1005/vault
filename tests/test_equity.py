import pandas as pd

from hlvault.equity import (
    add_unrealized,
    daily_equity_from_fills,
    daily_returns_from_fills,
    passes_sample_gate,
)


def test_realized_pnl_accumulates_into_returns():
    fills = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "coin": ["BTC", "BTC"],
            "signed_sz": [0.0, 0.0],
            "px": [40000.0, 41000.0],
            "closedPnl": [100.0, -50.0],
            "fee": [0.0, 0.0],
        }
    )
    r = daily_returns_from_fills(fills, starting_equity=1000.0)
    assert abs(r.iloc[0] - 0.10) < 1e-9
    assert abs(r.iloc[1] - (1050 / 1100 - 1)) < 1e-9


def test_sample_gate_rejects_short_history():
    idx = pd.date_range("2026-01-01", periods=30, freq="D")
    assert not passes_sample_gate(pd.Series(0.0, index=idx), min_months=9)
    idx2 = pd.date_range("2025-01-01", periods=400, freq="D")
    assert passes_sample_gate(pd.Series(0.0, index=idx2), min_months=9)


def test_add_unrealized_marks_open_position():
    # open 1 BTC on day1 @ 40000, hold; price marks to 42000 on day2
    fills = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01"]),
            "coin": ["BTC"],
            "signed_sz": [1.0],
            "px": [40000.0],
            "closedPnl": [0.0],
            "fee": [0.0],
        }
    )
    days = pd.to_datetime(["2026-01-01", "2026-01-02"])
    equity = pd.Series([1000.0, 1000.0], index=days)  # no realized change
    prices = pd.DataFrame({"BTC": [40000.0, 42000.0]}, index=days)
    out = add_unrealized(equity, fills, prices)
    # day2 unrealized = position(1) * (42000-40000) = +2000
    assert abs(out.iloc[1] - 3000.0) < 1e-6
    assert abs(out.iloc[0] - 1000.0) < 1e-6
