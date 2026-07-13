import math

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


# ---- B1 vol-target sizing (sub-project L Stage 1) --------------------------

def test_ewma_log_return_vol_matches_independent_hand_recursion():
    # Independent RiskMetrics zero-mean EWMA recursion, written separately
    # from signals.ewma_log_return_vol's own recursion (not a re-call of the
    # function under test) -- spec requirement: hand-calc cross-check, not a
    # self-comparison.
    closes = pd.Series([100.0, 101.0, 99.0, 102.5, 98.0, 97.0, 103.0, 105.0, 104.2, 110.0])
    span = 4
    bars_per_year = 2190.0
    got = signals.ewma_log_return_vol(closes, span, bars_per_year)

    alpha = 2.0 / (span + 1)
    px = closes.to_numpy()
    n = len(px)
    expected = [float("nan")] * n
    var_prev = None
    for i in range(1, n):
        r = math.log(px[i] / px[i - 1])
        r2 = r * r
        var_i = r2 if var_prev is None else (1 - alpha) * var_prev + alpha * r2
        var_prev = var_i
        expected[i] = math.sqrt(var_i) * math.sqrt(bars_per_year)

    assert math.isnan(got.iloc[0])
    for i in range(1, n):
        assert abs(got.iloc[i] - expected[i]) < 1e-9, (i, got.iloc[i], expected[i])


def test_ewma_log_return_vol_on_constant_ratio_series_is_steady_state():
    # A perfectly smooth exponential path (log return constant every bar) has
    # a well-known closed form: the RiskMetrics recursion's seed (var_1=r^2)
    # IS the fixed point, so sigma is the SAME constant at every bar from
    # index 1 onward. This is the exact close-path used by _short_signal_frame
    # in test_cta_live.py and test_compute_signals_end_to_end_matches_direction
    # above (100 * 0.99**i) -- pinning its sigma here gives every B1 live-layer
    # test a hand-checkable expected value instead of an opaque one.
    n = 200
    closes = pd.Series(100 * 0.99 ** np.arange(n))
    sigma = signals.ewma_log_return_vol(closes, span=180, bars_per_year=2190.0)
    r = math.log(0.99)
    expected = abs(r) * math.sqrt(2190.0)
    assert abs(sigma.iloc[-1] - expected) < 1e-9
    # steady-state from bar 1 onward (no warmup drift on a constant-return path)
    assert abs(sigma.iloc[5] - expected) < 1e-9
    assert abs(sigma.iloc[-1] - 0.4706) < 1e-3   # ~47% annualized, sanity anchor


def test_sizing_multiplier_disabled_path_not_applicable_returns_baseline_shape():
    # sizing_multiplier itself has no "disabled" branch (config.py's
    # SIGMA_TARGET is None gates the call entirely) -- this test documents
    # that at sigma_target == sigma (target exactly matches realized vol) the
    # multiplier is 1.0, the natural "no scaling" case.
    n = 200
    closes = pd.Series(100 * 0.99 ** np.arange(n))
    r = math.log(0.99)
    sigma_actual = abs(r) * math.sqrt(2190.0)
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=sigma_actual, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert fail is None
    assert abs(m - 1.0) < 1e-9
    assert abs(sigma - sigma_actual) < 1e-9


def test_sizing_multiplier_scales_down_when_target_below_realized_vol():
    n = 200
    closes = pd.Series(100 * 0.99 ** np.arange(n))
    r = math.log(0.99)
    sigma_actual = abs(r) * math.sqrt(2190.0)   # ~0.4706
    target = 0.20   # well below realized vol, well above clip_lo*sigma_actual
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=target, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert fail is None
    expected_m = target / sigma_actual
    assert 0.25 < expected_m < 1.0   # sanity: this case must land strictly inside the clip band
    assert abs(m - expected_m) < 1e-6


def test_sizing_multiplier_clips_at_lower_bound():
    n = 200
    closes = pd.Series(100 * 0.99 ** np.arange(n))
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=0.02, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert fail is None
    assert m == 0.25   # clipped: 0.02/sigma_actual << 0.25


def test_sizing_multiplier_clips_at_upper_bound_cap_only():
    n = 200
    closes = pd.Series(100 * 0.99 ** np.arange(n))
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=5.0, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert fail is None
    assert m == 1.0   # clipped: target/sigma_actual >> 1.0, cap-only (never amplifies)


def test_sizing_multiplier_insufficient_bars_is_fail_safe_m_one():
    # Fewer than span+1 closes -> not enough log returns to trust the EWMA:
    # fail-safe m=1.0 with a non-None reason string the caller must log.
    closes = pd.Series(100 * 0.99 ** np.arange(50))
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=0.60, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert m == 1.0
    assert math.isnan(sigma)
    assert fail is not None and "insufficient" in fail.lower()


def test_sizing_multiplier_zero_sigma_is_fail_safe_m_one():
    # Review finding (minor 2): the "sigma non-finite / <= 0" branch. A
    # perfectly CONSTANT price series has zero log return every bar, so the
    # EWMA variance is exactly 0 -> sigma == 0.0: dividing sigma_target by it
    # would blow up (inf -> clipped to 1.0 by accident, hiding the anomaly).
    # The fail-safe must fire instead: m=1.0, sigma reported NaN, and a
    # non-None reason string the caller logs (principle #3: loud degradation).
    closes = pd.Series([100.0] * 200)
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=0.60, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert m == 1.0
    assert math.isnan(sigma)
    assert fail is not None and "not computable" in fail.lower()


def test_sizing_multiplier_nan_sigma_is_fail_safe_m_one():
    # Same branch, non-finite flavor: a NaN LAST close makes the final bar's
    # log return NaN, so the EWMA at the decision bar is NaN -> fail-safe,
    # never a NaN-sized order. (A NaN in the MIDDLE of the window would
    # reseed the recursion a few bars later -- the seed rule var_i = r_i^2
    # when var_{i-1} is NaN -- so only a trailing NaN reliably exercises the
    # non-finite branch at the point of use.)
    vals = list(100 * 0.99 ** np.arange(200))
    vals[-1] = float("nan")
    closes = pd.Series(vals)
    m, sigma, fail = signals.sizing_multiplier(
        closes, sigma_target=0.60, span_bars=180, clip_lo=0.25, clip_hi=1.0)
    assert m == 1.0
    assert math.isnan(sigma)
    assert fail is not None and "not computable" in fail.lower()
