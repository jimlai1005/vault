import numpy as np
import pandas as pd

from hlvault.cta import signals


def _bars(closes, oi, long_pct, highs=None, lows=None):
    n = len(closes)
    idx = pd.date_range("2025-08-01", periods=n, freq="4h")
    return pd.DataFrame({
        "open": closes, "high": highs or [c * 1.001 for c in closes],
        "low": lows or [c * 0.999 for c in closes], "close": closes,
        "oi_level": oi, "long_pct": long_pct,
    }, index=idx)


def test_ema_trend_up_and_down_direction():
    up = signals.ema_trend(pd.Series(100 * 1.01 ** np.arange(120)), 20, 50, 50)
    assert up["trend_up"].iloc[-1] and not up["trend_dn"].iloc[-1]
    dn = signals.ema_trend(pd.Series(100 * 0.99 ** np.arange(120)), 20, 50, 50)
    assert dn["trend_dn"].iloc[-1] and not dn["trend_up"].iloc[-1]


def test_ema_trend_warmup_suppresses_early_bars():
    up = signals.ema_trend(pd.Series(100 * 1.01 ** np.arange(120)), 20, 50, 50)
    assert not up["trend_up"].iloc[10] and not up["trend_dn"].iloc[10]


def test_crowding_percentile_last_value_rank():
    # last value is the max of a rising series -> percentile ~100
    s = pd.Series(np.arange(200.0))
    pct = signals.crowd_percentile(s, window_bars=90 * 6, warmup_bars=30 * 6)
    assert pct.iloc[-1] > 99.0


def test_crowd_flags_high_pct_is_crowd_long_low_is_crowd_short():
    # rising long_pct -> latest is top decile -> crowd_long True, crowd_short False
    lp_rising = pd.Series(np.arange(200.0))
    pr = signals.crowd_percentile(lp_rising, 90 * 6, 30 * 6)
    assert signals.is_crowd_long(pr.iloc[-1], pctile=10) is True
    assert signals.is_crowd_short(pr.iloc[-1], pctile=10) is False
    # falling long_pct -> latest is bottom decile -> crowd_short True
    lp_falling = pd.Series(np.arange(200.0)[::-1].astype(float))
    pf = signals.crowd_percentile(lp_falling, 90 * 6, 30 * 6)
    assert signals.is_crowd_short(pf.iloc[-1], pctile=10) is True
    assert signals.is_crowd_long(pf.iloc[-1], pctile=10) is False


def test_fuel_ok_true_when_oi_rose_over_lookback():
    oi = pd.Series([10.0] * 10 + [11.0])  # rose vs 6 bars ago
    assert signals.fuel_ok(oi, lookback_bars=6) is True
    oi_flat = pd.Series([10.0] * 11)
    assert signals.fuel_ok(oi_flat, lookback_bars=6) is False


def test_atr_positive_on_volatile_series():
    closes = list(100 + np.cumsum(np.random.default_rng(1).normal(0, 2, 80)))
    bars = _bars(closes, [10.0] * 80, [50.0] * 80)
    atr = signals.atr(bars, period=14, warmup_bars=50)
    assert atr.iloc[-1] > 0 and np.isnan(atr.iloc[10])


def test_decide_crowded_long_downtrend_fuel_gives_SHORT():
    # THE reversal rule: retail crowded long + downtrend + OI rising -> SHORT
    d = signals.decide(trend_up=False, trend_dn=True, crowd_long=True,
                       crowd_short=False, fuel=True,
                       enable_long=True, enable_short=True)
    assert d == "short"


def test_decide_crowded_short_uptrend_fuel_gives_LONG():
    d = signals.decide(trend_up=True, trend_dn=False, crowd_long=False,
                       crowd_short=True, fuel=True,
                       enable_long=True, enable_short=True)
    assert d == "long"


def test_decide_short_disabled_returns_flat_even_when_short_conditions_met():
    d = signals.decide(trend_up=False, trend_dn=True, crowd_long=True,
                       crowd_short=False, fuel=True,
                       enable_long=True, enable_short=False)
    assert d == "flat"


def test_decide_long_disabled_is_default_live_config():
    # live default: long off, short on -> long setup yields flat, short setup shorts
    long_setup = signals.decide(True, False, False, True, True,
                                enable_long=False, enable_short=True)
    short_setup = signals.decide(False, True, True, False, True,
                                 enable_long=False, enable_short=True)
    assert long_setup == "flat" and short_setup == "short"


def test_decide_no_fuel_is_flat():
    assert signals.decide(False, True, True, False, fuel=False,
                          enable_long=True, enable_short=True) == "flat"


def test_should_exit_on_trend_flip_fuel_fail_and_maxhold():
    # short position: trend no longer down -> exit
    assert signals.should_exit(direction=-1, trend_up=False, trend_dn=False,
                               fuel=True, held_days=1.0, max_hold_days=14) == "flip"
    # short position: fuel fails -> exit
    assert signals.should_exit(-1, False, True, fuel=False, held_days=1.0,
                               max_hold_days=14) == "fuel"
    # held too long -> exit
    assert signals.should_exit(-1, False, True, fuel=True, held_days=15.0,
                               max_hold_days=14) == "maxhold"
    # healthy short -> hold (None)
    assert signals.should_exit(-1, False, True, fuel=True, held_days=1.0,
                               max_hold_days=14) is None


def test_compute_signals_end_to_end_matches_direction():
    # 200 downtrend bars (>= crowd warmup 30d*6=180), rising long_pct (crowded
    # long), rising OI -> SHORT. Needs > crowd_warmup_bars of history or the
    # rolling percentile stays NaN (min_periods not met) and crowd_long is False.
    n = 200
    closes = list(100 * 0.99 ** np.arange(n))
    oi = list(np.arange(float(n)) + 10)
    long_pct = list(np.arange(float(n)))
    bars = _bars(closes, oi, long_pct)
    out = signals.compute_signals(bars, ema_fast=20, ema_slow=50,
                                  trend_warmup_bars=50, crowd_pctile=10,
                                  crowd_window_bars=90 * 6, crowd_warmup_bars=30 * 6,
                                  fuel_lookback_bars=6, atr_period=14)
    assert out["trend_dn"] and out["crowd_long"] and out["fuel"]
    assert out["atr"] > 0
    d = signals.decide(out["trend_up"], out["trend_dn"], out["crowd_long"],
                       out["crowd_short"], out["fuel"],
                       enable_long=False, enable_short=True)
    assert d == "short"
