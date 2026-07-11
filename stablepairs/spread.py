"""Spread construction with a FROZEN cointegration vector (the fix for the drifting
beta/z bug in the original Pine). Beta, mean and std are estimated on the train
window only, then held fixed out-of-sample.
"""
import numpy as np
import pandas as pd


def ols_beta(la: np.ndarray, lb: np.ndarray) -> float:
    """OLS slope of la on lb  ==  cov(la,lb)/var(lb)."""
    lb = np.asarray(lb, dtype=float)
    la = np.asarray(la, dtype=float)
    v = np.var(lb)
    return float(np.cov(la, lb)[0, 1] / v) if v > 0 else np.nan


def build_spread(la: pd.Series, lb: pd.Series, train_frac: float = 0.6):
    """Return (spread, z, params). Everything frozen on the first `train_frac`."""
    n = len(la)
    ntrain = max(50, int(n * train_frac))
    beta = ols_beta(la.iloc[:ntrain].values, lb.iloc[:ntrain].values)
    spread = la - beta * lb
    mu = float(spread.iloc[:ntrain].mean())
    sd = float(spread.iloc[:ntrain].std())
    z = (spread - mu) / sd if sd > 0 else spread * np.nan
    return spread, z, {"beta": beta, "mu": mu, "sd": sd, "ntrain": ntrain}


def ar1_halflife(spread: pd.Series) -> dict:
    """AR(1) on the spread: ds = a + b*s[-1]. kappa = -b, half-life = ln2/kappa.
    kappa here is in the SAME per-bar convention the Pine regime filter uses.
    """
    s = spread.dropna()
    ds = s.diff().dropna()
    sl = s.shift(1).dropna().reindex(ds.index)
    m = np.isfinite(ds.values) & np.isfinite(sl.values)
    if m.sum() < 20:
        return {"b": np.nan, "kappa": np.nan, "half_life": np.inf}
    b = float(np.polyfit(sl.values[m], ds.values[m], 1)[0])
    kappa = -b
    hl = float(np.log(2) / kappa) if kappa > 0 else np.inf
    return {"b": b, "kappa": kappa, "half_life": hl}
