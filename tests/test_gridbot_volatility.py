import pandas as pd

from hlvault.gridbot.volatility import atr_pct, adaptive_step_pct


def test_atr_pct_zero_for_flat_price():
    candles = pd.DataFrame({"h": [100.0] * 20, "l": [100.0] * 20, "c": [100.0] * 20})
    assert atr_pct(candles, lookback=14) == 0.0


def test_atr_pct_positive_for_moving_price():
    candles = pd.DataFrame({
        "h": [100, 102, 101, 105, 103],
        "l": [99, 100, 99, 101, 100],
        "c": [100, 101, 100, 104, 102],
    })
    assert atr_pct(candles, lookback=5) > 0.0


def test_adaptive_step_pct_respects_bounds():
    assert adaptive_step_pct(0.0001, vol_k=1.0, min_step=0.002, max_step=0.05) == 0.002
    assert adaptive_step_pct(1.0, vol_k=1.0, min_step=0.002, max_step=0.05) == 0.05
    assert adaptive_step_pct(0.01, vol_k=1.0, min_step=0.002, max_step=0.05) == 0.01
