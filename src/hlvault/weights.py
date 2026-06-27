"""Stage 7: covariance-aware weights. Ledoit-Wolf shrinkage on Sigma; HRP as
primary (auto-penalizes correlated clusters); risk-parity + fractional-Kelly
as comparators."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf


def shrunk_cov(returns: pd.DataFrame) -> np.ndarray:
    return LedoitWolf().fit(returns.values).covariance_


def _ivp(cov: np.ndarray) -> np.ndarray:
    ivp = 1.0 / np.diag(cov)
    return ivp / ivp.sum()


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    w = _ivp(sub)
    return float(w @ sub @ w)


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    if returns.shape[1] == 1:
        return pd.Series([1.0], index=returns.columns)
    cov = pd.DataFrame(
        shrunk_cov(returns), index=returns.columns, columns=returns.columns
    )
    corr = returns.corr().values
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
    link = linkage(squareform(dist, checks=False), method="single")
    order = leaves_list(link)
    cols = returns.columns[order].tolist()
    covv = cov.loc[cols, cols].values
    pos = {c: i for i, c in enumerate(cols)}
    w = pd.Series(1.0, index=cols)
    clusters = [cols]
    while clusters:
        clusters = [
            c[j:k]
            for c in clusters
            for j, k in ((0, len(c) // 2), (len(c) // 2, len(c)))
            if len(c) > 1
        ]
        for i in range(0, len(clusters), 2):
            left, right = clusters[i], clusters[i + 1]
            vl = _cluster_var(covv, [pos[c] for c in left])
            vr = _cluster_var(covv, [pos[c] for c in right])
            alpha = 1 - vl / (vl + vr)
            w[left] *= alpha
            w[right] *= 1 - alpha
    return (w / w.sum()).reindex(returns.columns)


def risk_parity_weights(returns: pd.DataFrame) -> pd.Series:
    cov = shrunk_cov(returns)
    return pd.Series(_ivp(cov), index=returns.columns)


def fractional_kelly_weights(returns: pd.DataFrame, fraction: float) -> pd.Series:
    cov = shrunk_cov(returns)
    mu = returns.mean().values
    raw = np.linalg.pinv(cov) @ mu
    raw = np.clip(raw, 0, None)
    if raw.sum() == 0:
        raw = np.ones_like(raw)
    w = fraction * raw / raw.sum()
    return pd.Series(w / w.sum(), index=returns.columns)
