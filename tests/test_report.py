import numpy as np
import pandas as pd

from hlvault.report import verdict


def test_go_when_oos_significantly_positive_and_beats_btc():
    rng = np.random.default_rng(5)
    oos = pd.Series(rng.normal(0.002, 0.01, 250))
    btc = pd.Series(rng.normal(0.0, 0.02, 250))
    v = verdict(oos, btc)
    assert v.decision == "GO"
    assert v.oos_tstat > 2


def test_nogo_when_oos_not_distinguishable_from_zero():
    rng = np.random.default_rng(6)
    oos = pd.Series(rng.normal(0.0, 0.02, 250))
    btc = pd.Series(rng.normal(0.0, 0.02, 250))
    v = verdict(oos, btc)
    assert v.decision == "NO-GO"
