import pandas as pd

from hlvault.reconstruct import daily_pnl_panel, returns_panel


def _fills():
    return pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02"]
            ),
            "user": ["0xA", "0xB", "0xA", "0xB"],
            "closedPnl": [100.0, 10.0, -30.0, 5.0],
            "fee": [1.0, 0.0, 1.0, 0.0],
        }
    )


def test_daily_pnl_panel_sums_per_day_per_user():
    p = daily_pnl_panel(_fills())
    assert p.loc[pd.Timestamp("2026-01-01"), "0xA"] == 99.0  # 100 - 1 fee
    assert p.loc[pd.Timestamp("2026-01-02"), "0xA"] == -31.0  # -30 - 1
    assert p.loc[pd.Timestamp("2026-01-01"), "0xB"] == 10.0


def test_returns_panel_anchors_to_account_value():
    p = daily_pnl_panel(_fills())
    # 0xA total pnl = 99 - 31 = 68; current av = 1068 -> E0 ~= 1000
    r = returns_panel(p, {"0xa": 1068.0, "0xb": 1015.0})
    # day1 0xA: pnl 99 / equity_prev ~1000 = ~0.099
    assert abs(r.loc[pd.Timestamp("2026-01-01"), "0xA"] - 0.099) < 1e-4
    # day2 0xA: pnl -31 / equity_prev ~1099
    assert abs(r.loc[pd.Timestamp("2026-01-02"), "0xA"] - (-31 / 1099)) < 1e-4


def test_returns_panel_keeps_profitable_withdrawer():
    # Withdrawer: total PnL (+400) > current av (200), so the naive backward
    # anchor would go negative and the OLD code dropped this winner. The
    # drawdown-implied floor (trough -1000 -> E0 ~= 1100) keeps it, with all
    # daily returns staying within the quality bound.
    days = pd.to_datetime(
        ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
    )
    fills = pd.DataFrame(
        {
            "time": days,
            "user": ["0xA"] * 5,
            "closedPnl": [-1000.0, 200.0, 200.0, 200.0, 800.0],  # cum trough -1000
            "fee": [0.0] * 5,
        }
    )
    p = daily_pnl_panel(fills)
    r = returns_panel(p, {"0xa": 200.0}, max_abs_daily_return=3.0)
    assert "0xA" in r.columns
    assert r["0xA"].notna().all() and (r["0xA"].abs() <= 3.0).all()


def test_returns_panel_drops_unknown_account_value():
    p = daily_pnl_panel(_fills())
    r = returns_panel(p, {"0xb": 1015.0})   # no av for 0xA
    assert "0xA" not in r.columns
    assert "0xB" in r.columns
