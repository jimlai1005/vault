import numpy as np
import pandas as pd

from hlvault.pipeline import select_at


def _make_panel(seed=0):
    rng = np.random.default_rng(seed)
    n = 400
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    btc = pd.Series(rng.normal(0, 0.02, n), index=idx)
    eth = pd.Series(rng.normal(0, 0.025, n), index=idx)
    # alpha trader: real positive intercept, modest beta, low noise
    alpha_r = 0.001 + 0.3 * btc + 0.2 * eth + rng.normal(0, 0.004, n)
    # pure beta trader: no alpha, all market
    beta_r = 1.0 * btc + 0.5 * eth + rng.normal(0, 0.004, n)
    panel = pd.DataFrame({"alpha": alpha_r, "beta": beta_r}, index=idx)
    return panel, btc, eth


def test_select_keeps_alpha_drops_pure_beta():
    panel, btc, eth = _make_panel()
    w = select_at(panel, btc, eth, top_n=5, min_alpha_tstat=2.0, min_history_months=9)
    assert "alpha" in w.index
    assert "beta" not in w.index
    assert abs(w.sum() - 1.0) < 1e-9


def test_select_respects_sample_gate():
    panel, btc, eth = _make_panel()
    short = panel.iloc[:40]  # ~40 days < 9 months
    w = select_at(short, btc, eth, top_n=5, min_history_months=9)
    assert w.empty
