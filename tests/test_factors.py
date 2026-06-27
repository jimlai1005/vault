import numpy as np
import pandas as pd

from hlvault.factors import alpha_beta


def test_recovers_known_alpha_beta():
    rng = np.random.default_rng(3)
    n = 500
    btc = pd.Series(rng.normal(0, 0.02, n))
    eth = pd.Series(rng.normal(0, 0.025, n))
    true_alpha, b_btc, b_eth = 0.0008, 0.5, 0.3
    noise = rng.normal(0, 0.005, n)
    r = true_alpha + b_btc * btc + b_eth * eth + noise
    res = alpha_beta(pd.Series(r), btc, eth)
    assert abs(res.alpha - true_alpha) < 0.0005
    assert abs(res.beta_btc - b_btc) < 0.05
    assert res.alpha_tstat > 2
