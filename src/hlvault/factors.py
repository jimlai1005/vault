"""Stage 5: regress trader returns on BTC/ETH. Keep residual + alpha; drop
pure-beta traders. Newey-West HAC SEs for autocorrelation-robust t-stats."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import statsmodels.api as sm


@dataclass
class FactorFit:
    alpha: float
    beta_btc: float
    beta_eth: float
    alpha_tstat: float
    r_squared: float
    residual: pd.Series


def alpha_beta(r: pd.Series, btc: pd.Series, eth: pd.Series) -> FactorFit:
    df = pd.concat([r, btc, eth], axis=1, keys=["r", "btc", "eth"]).dropna()
    X = sm.add_constant(df[["btc", "eth"]])
    model = sm.OLS(df["r"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    resid = pd.Series(model.resid, index=df.index)
    return FactorFit(
        alpha=float(model.params["const"]),
        beta_btc=float(model.params["btc"]),
        beta_eth=float(model.params["eth"]),
        alpha_tstat=float(model.tvalues["const"]),
        r_squared=float(model.rsquared),
        residual=resid,
    )


def is_pure_beta(fit: FactorFit, min_alpha_tstat: float = 2.0) -> bool:
    return fit.alpha_tstat < min_alpha_tstat
