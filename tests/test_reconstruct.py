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
    # 0xA total pnl = 99 - 31 = 68; current av = 1068 -> equity_0(before)=1000
    r = returns_panel(p, {"0xa": 1068.0, "0xb": 1015.0})
    # day1 0xA: pnl 99 / equity_prev 1000 = 0.099
    assert abs(r.loc[pd.Timestamp("2026-01-01"), "0xA"] - 0.099) < 1e-9
    # day2 0xA: pnl -31 / equity_prev 1099 = -0.0282...
    assert abs(r.loc[pd.Timestamp("2026-01-02"), "0xA"] - (-31 / 1099)) < 1e-9


def test_returns_panel_drops_nonpositive_equity():
    p = daily_pnl_panel(_fills())
    # give 0xA a tiny account value so reconstructed equity goes negative
    r = returns_panel(p, {"0xa": 1.0, "0xb": 1015.0})
    assert "0xA" not in r.columns
    assert "0xB" in r.columns
