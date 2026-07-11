"""Read-only reproduction: quantifies the statistical power of the alpha
t-stat >= 2.0 selection criterion (hlvault.factors.alpha_beta /
pipeline.select_at) at the sample sizes actually available (6-9mo gates ->
n~180-336 daily obs) and at the residual-volatility levels actually observed
in the real 99-trader universe.

Method: Monte Carlo. Draw real historical BTC/ETH daily-return blocks (so the
regressor side has real market structure/autocorrelation), inject a KNOWN
daily alpha + Gaussian idiosyncratic noise at a given residual std, refit the
exact same alpha_beta() OLS+HAC used in production, and measure the fraction
of trials where alpha_tstat >= 2.0 ("power" for that true alpha).

Residual-vol buckets (p25/median/p75 = 0.6%/3.7%/5.5% daily) are taken
directly from the real reconstructed 99-trader panel (see
reports/audit/J-oos-findings.md §evidence for the describe() table).

Run: .venv/bin/python reports/audit/repro_oos_alpha_power.py
(read-only: only reads data/cache/prices.parquet, writes nothing)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hlvault.factors import alpha_beta  # noqa: E402

rng = np.random.default_rng(42)


def simulate_power(btc, eth, n_days, resid_std, ann_alpha, n_trials=400,
                    beta_btc=0.3, beta_eth=0.1):
    daily_alpha = ann_alpha / 252.0
    passes, tstats = 0, []
    max_start = max(len(btc) - n_days, 1)
    for _ in range(n_trials):
        start = rng.integers(0, max_start)
        b = btc.iloc[start:start + n_days].reset_index(drop=True)
        e = eth.iloc[start:start + n_days].reset_index(drop=True)
        noise = rng.normal(0, resid_std, n_days)
        r = pd.Series(daily_alpha + beta_btc * b.values + beta_eth * e.values + noise)
        try:
            fit = alpha_beta(r, b, e)
        except Exception:
            continue
        tstats.append(fit.alpha_tstat)
        if np.isfinite(fit.alpha_tstat) and fit.alpha_tstat >= 2.0:
            passes += 1
    return (passes / len(tstats) if tstats else float("nan"))


def main():
    prices = pd.read_parquet(ROOT / "data/cache/prices.parquet")
    btc, eth = prices["btc"].dropna(), prices["eth"].dropna()
    common = btc.index.intersection(eth.index)
    btc, eth = btc.loc[common], eth.loc[common]

    print(f"{'n_days':>7} {'resid_std':>16} {'ann_alpha':>10} {'power':>8}")
    for n_days in [180, 270]:
        for resid_std, label in [(0.006, "p25"), (0.037, "median"), (0.055, "p75")]:
            for ann_alpha in [0.0, 0.10, 0.20, 0.30, 0.50, 1.00]:
                power = simulate_power(btc, eth, n_days, resid_std, ann_alpha)
                print(f"{n_days:>7} {resid_std:>10.3f}({label:>6}) {ann_alpha:>9.0%} {power:>8.1%}")


if __name__ == "__main__":
    main()
