import pandas as pd

from hlvault.reconstruct import daily_pnl_panel, returns_panel


def test_drops_trader_with_implausible_daily_return():
    # 0xBLOWUP: tiny account, a single day with PnL many times its equity ->
    # reconstructed daily return explodes -> should be dropped by quality gate.
    fills = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "user": ["0xblowup", "0xblowup"],
            "closedPnl": [1.0, 5000.0],   # 5000x swing vs ~unit equity
            "fee": [0.0, 0.0],
        }
    )
    p = daily_pnl_panel(fills)
    r = returns_panel(p, {"0xblowup": 10.0}, max_abs_daily_return=3.0)
    assert "0xblowup" not in r.columns


def test_keeps_sane_trader():
    fills = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "user": ["0xok", "0xok"],
            "closedPnl": [50.0, -30.0],
            "fee": [0.0, 0.0],
        }
    )
    p = daily_pnl_panel(fills)
    r = returns_panel(p, {"0xok": 10000.0}, max_abs_daily_return=3.0)
    assert "0xok" in r.columns
