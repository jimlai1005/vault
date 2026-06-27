import numpy as np
import pandas as pd

from hlvault.weights import hrp_weights, shrunk_cov


def test_hrp_downweights_correlated_cluster():
    rng = np.random.default_rng(7)
    n = 600
    base = rng.normal(0, 0.01, n)
    df = pd.DataFrame(
        {
            "A": base + rng.normal(0, 0.001, n),
            "B": base + rng.normal(0, 0.001, n),
            "C": base + rng.normal(0, 0.001, n),
            "D": rng.normal(0, 0.01, n),
        }
    )
    w = hrp_weights(df)
    assert abs(w.sum() - 1.0) < 1e-9
    assert w["D"] > w["A"]


def test_shrunk_cov_is_psd():
    rng = np.random.default_rng(8)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 5)))
    cov = shrunk_cov(df)
    eig = np.linalg.eigvalsh(cov)
    assert (eig > -1e-10).all()
