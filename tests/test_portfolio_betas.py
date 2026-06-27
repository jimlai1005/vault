import numpy as np
import pandas as pd

from hlvault.pipeline import portfolio_betas


def test_portfolio_betas_weighted_average():
    rng = np.random.default_rng(0)
    n = 300
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    btc = pd.Series(rng.normal(0, 0.02, n), index=idx)
    eth = pd.Series(rng.normal(0, 0.02, n), index=idx)
    # trader A: beta_btc 1.0; trader B: beta_btc 0.0
    a = 1.0 * btc + rng.normal(0, 0.003, n)
    b = 0.0 * btc + rng.normal(0, 0.003, n)
    past = pd.DataFrame({"A": a, "B": b}, index=idx)
    w = pd.Series({"A": 0.5, "B": 0.5})
    bb, be = portfolio_betas(past, w, btc, eth)
    assert abs(bb - 0.5) < 0.1   # 0.5*1.0 + 0.5*0.0
