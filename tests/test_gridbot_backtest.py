import pandas as pd

from hlvault.gridbot.strategy import GridConfig
from hlvault.gridbot.backtest import run_backtest


def make_cfg(**overrides):
    base = dict(
        coin="TEST", step_pct=0.01, num_levels=3, notional_per_level=100.0,
        max_position_notional=1000.0, stop_buffer_pct=0.05, cooldown_candles=2,
        fee_rate=0.0,
    )
    base.update(overrides)
    return GridConfig(**base)


def test_backtest_handles_multiple_events_in_one_candle():
    # a single sharp candle that fills several levels AND closes a prior TP —
    # multiple events land on the exact same timestamp; must not crash on reindex.
    candles = pd.DataFrame({
        "t": pd.date_range("2024-01-01", periods=3, freq="h"),
        "h": [100.0, 100.0, 105.0],
        "l": [100.0, 90.0, 100.0],
        "c": [100.0, 90.0, 105.0],
    })
    cfg = make_cfg(num_levels=5)
    res = run_backtest(candles, cfg)
    assert res.num_fills >= 2
    assert len(res.equity_curve) == len(candles)


def test_backtest_flat_price_produces_no_trades():
    candles = pd.DataFrame({
        "t": pd.date_range("2024-01-01", periods=10, freq="h"),
        "h": [100.0] * 10, "l": [100.0] * 10, "c": [100.0] * 10,
    })
    res = run_backtest(candles, make_cfg())
    assert res.num_fills == 0 and res.total_pnl == 0.0


def test_backtest_profits_from_a_round_trip_dip_and_recovery():
    candles = pd.DataFrame({
        "t": pd.date_range("2024-01-01", periods=3, freq="h"),
        "h": [100.0, 100.0, 103.0],
        "l": [100.0, 97.0, 100.0],
        "c": [100.0, 97.0, 103.0],
    })
    res = run_backtest(candles, make_cfg(step_pct=0.01, fee_rate=0.0))
    assert res.total_pnl > 0
