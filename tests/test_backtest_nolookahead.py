import numpy as np
import pandas as pd

from hlvault.backtest import walk_forward


def test_selection_ignores_future_data():
    idx = pd.date_range("2025-01-01", periods=300, freq="D")
    rng = np.random.default_rng(2)
    panel = pd.DataFrame(
        rng.normal(0, 0.01, (300, 4)), index=idx, columns=list("abcd")
    )

    seen_max_dates = []

    def select(as_of, data):
        seen_max_dates.append(data.index.max())
        w = data.mean().nlargest(2)
        return pd.Series(0.5, index=w.index)

    res = walk_forward(panel, select, rebalance_days=30, horizon_days=30)
    for as_of, mx in zip(res.rebalance_dates, seen_max_dates):
        assert mx <= as_of


def test_oos_segments_are_future_of_selection():
    idx = pd.date_range("2025-01-01", periods=200, freq="D")
    panel = pd.DataFrame(0.001, index=idx, columns=list("ab"))

    def select(as_of, data):
        return pd.Series(0.5, index=["a", "b"])

    res = walk_forward(panel, select, rebalance_days=30, horizon_days=30)
    assert res.oos_returns.index.min() > res.rebalance_dates[0]
