import numpy as np
import pandas as pd

from hlvault.metrics import deflated_sharpe, max_drawdown, sharpe


def test_sharpe_known_value():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.001, 0.01, 252))
    s = sharpe(r, rf=0.0)
    assert abs(s - (r.mean() / r.std(ddof=1) * np.sqrt(252))) < 1e-9


def test_max_drawdown_simple():
    eq = pd.Series([1.0, 1.2, 0.9, 1.1])
    assert abs(max_drawdown(eq) - (-0.25)) < 1e-9


def test_deflated_sharpe_penalizes_many_trials():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.001, 0.01, 252))
    dsr_few = deflated_sharpe(r, n_trials=1)
    dsr_many = deflated_sharpe(r, n_trials=300)
    assert dsr_many < dsr_few
