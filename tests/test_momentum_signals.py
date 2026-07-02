import numpy as np
import pandas as pd

from hlvault.momentum.signals import (
    composite_score, daily_log_returns, score_to_position, position_signal,
)


def test_daily_log_returns_matches_manual_calc():
    close = pd.Series([100.0, 110.0, 121.0])
    r = daily_log_returns(close)
    assert len(r) == 2
    assert abs(r.iloc[0] - np.log(1.1)) < 1e-9


def test_composite_score_is_strongly_positive_for_steady_uptrend():
    # 150 days of a steady +0.5%/day trend, near-zero noise
    close = pd.Series(100 * (1.005 ** np.arange(150)))
    r = daily_log_returns(close)
    score = composite_score(r)
    assert score.dropna().iloc[-1] > 1.0  # clearly positive risk-adjusted momentum


def test_composite_score_is_near_zero_for_flat_noise():
    rng = np.random.default_rng(42)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 150)))
    r = daily_log_returns(close)
    score = composite_score(r)
    assert abs(score.dropna().iloc[-1]) < 1.5  # no persistent drift -> small score


def test_score_to_position_zero_inside_threshold_band():
    assert score_to_position(0.3, entry_threshold=0.5) == 0.0
    assert score_to_position(-0.3, entry_threshold=0.5) == 0.0


def test_score_to_position_ramps_and_clips():
    assert score_to_position(0.5, entry_threshold=0.5) == 0.0
    assert abs(score_to_position(1.0, entry_threshold=0.5) - 1.0) < 1e-9
    assert abs(score_to_position(2.0, entry_threshold=0.5) - 1.0) < 1e-9  # clipped
    assert score_to_position(-1.0, entry_threshold=0.5) < 0.0


def test_position_signal_is_vectorized_score_to_position():
    scores = pd.Series([0.0, 1.0, -1.0])
    out = position_signal(scores, entry_threshold=0.5)
    assert out.tolist() == [score_to_position(s, 0.5) for s in scores]
