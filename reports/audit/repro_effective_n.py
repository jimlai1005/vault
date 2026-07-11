"""Audit repro (read-only) — Q1 & Q2 of the phase-2b adversarial audit.

Q1: Bonferroni effective-N. The phase-2b gate uses t > 2.9 assuming 24
INDEPENDENT trials (one-sided Bonferroni at 5%: z = norm.ppf(1 - 0.05/24)).
The 24 configs are heavily correlated (same 6 coins, overlapping TF/pctile/
fuel/side combinations share most of their trades) — an independence
assumption inflates the correction. This script reconstructs the 24 daily
return series exactly as research_cta_positioning_phase2b.py computes them
(by importing its own functions, not reimplementing the signal logic), builds
their correlation matrix, computes effective-N by two methods (Li & Ji 2005
eigenvalue method; average-pairwise-correlation approximation), and
recomputes the corrected significance threshold.

Q2: Selection-penalty applicability. Computes the t-stat / significance of
(a) the median config alone (no multiplicity correction — it's a single
    pre-declared statistic, not a post-hoc max), and
(b) an equal-weight ensemble across all 24 configs and across the 8
    short-only configs (the actually-proposed production side per the
    2026-07-06 synthesis report), again with no multiplicity correction
    since "deploy everything pre-declared" involves no cherry-picking.

Read-only: only reads scripts/research_cta_positioning_phase2b.py's functions
and the existing data/cache/{cta,coinalyze} parquet files. Writes nothing
outside reports/audit/.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import research_cta_positioning_phase2b as p2b  # noqa: E402

SYMBOLS = p2b.SYMBOLS
TFS = p2b.TFS
PCTILES = p2b.PCTILES
FUEL_LOOKBACKS = p2b.FUEL_LOOKBACKS
SIDES = p2b.SIDES


def build_all_config_daily_returns():
    """Reproduces main()'s data + simulate loop, returns (daily_df, stats_start,
    split_at) where daily_df has one column per config, index = calendar date,
    values = portfolio ($600 base) daily $ PnL, ALREADY restricted to
    stats_start: (matches what daily_stats() feeds into sharpe/tstat)."""
    frames = {}
    cov_starts, cov_ends = [], []
    for sym, coin in SYMBOLS.items():
        kls = p2b.load_klines(sym)
        oi, long_pct = p2b.load_coinalyze(coin)
        for tf in TFS:
            bars = p2b.bar_frame(kls[tf], oi, long_pct, tf)
            frames[(coin, tf)] = p2b.raw_indicators(bars, tf)
        b4 = frames[(coin, "4h")]
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())

    window_start = max(cov_starts)
    window_end = min(cov_ends)
    stats_start = (window_start + pd.Timedelta(days=p2b.CROWD_WARMUP_DAYS)).ceil("D")
    split_at = (window_start + (window_end - window_start) * p2b.SPLIT_FRACTION).ceil("D")

    daily_by_cfg = {}
    for tf in TFS:
        for pct in PCTILES:
            for fuel_lb in FUEL_LOOKBACKS:
                sigs = {coin: p2b.shifted_signals(frames[(coin, tf)], pct, fuel_lb)
                        for coin in SYMBOLS.values()}
                for side in SIDES:
                    cfg = f"{tf}-p{pct}-fuel{fuel_lb}-{side}"
                    per_coin = {}
                    for coin, sig in sigs.items():
                        bar_pnl, _trades = p2b.simulate(sig, side)
                        per_coin[coin] = bar_pnl.resample("1D").sum()
                    daily = pd.concat(per_coin.values(), axis=1).fillna(0).sum(axis=1)
                    daily_by_cfg[cfg] = daily.loc[stats_start:]

    daily_df = pd.DataFrame(daily_by_cfg).fillna(0.0)
    return daily_df, stats_start, split_at


def sharpe_tstat(d: pd.Series) -> tuple[float, float, int]:
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    tstat = mu / sd * math.sqrt(n) if sd > 0 else 0.0
    return sharpe, tstat, n


def li_ji_effective_n(corr: np.ndarray) -> float:
    """Li & Ji (2005) effective number of independent tests from an MxM
    correlation matrix's eigenvalues. f(lambda) = 1 if lambda>=1 else
    lambda - floor(lambda) (== lambda for 0<=lambda<1)."""
    eigvals = np.linalg.eigvalsh(corr)
    eigvals = np.clip(eigvals, 0, None)  # guard tiny negative numerical noise
    f = np.where(eigvals >= 1.0, 1.0, eigvals - np.floor(eigvals))
    return float(f.sum())


def avg_corr_effective_n(corr: np.ndarray) -> float:
    """M_eff = M / (1 + (M-1)*rho_bar), rho_bar = mean off-diagonal correlation."""
    m = corr.shape[0]
    off = corr[~np.eye(m, dtype=bool)]
    rho_bar = off.mean()
    return m / (1 + (m - 1) * rho_bar), rho_bar


def one_sided_z_threshold(alpha: float, m_eff: float) -> float:
    p = alpha / m_eff
    return float(stats.norm.ppf(1 - p))


def one_sided_t_threshold(alpha: float, m_eff: float, df: int) -> float:
    p = alpha / m_eff
    return float(stats.t.ppf(1 - p, df))


def main():
    daily_df, stats_start, split_at = build_all_config_daily_returns()
    n_days = len(daily_df)
    print(f"stats_start={stats_start.date()} split_at={split_at.date()} n_days={n_days}")
    print(f"configs: {list(daily_df.columns)}")

    # sanity check against the verdict's published numbers
    med_sharpes = {}
    for cfg in daily_df.columns:
        sh, ts, n = sharpe_tstat(daily_df[cfg])
        med_sharpes[cfg] = sh
    med_val = float(np.median(list(med_sharpes.values())))
    med_cfg = min(sorted(med_sharpes), key=lambda k: abs(med_sharpes[k] - med_val))
    best_cfg = max(sorted(med_sharpes), key=lambda k: med_sharpes[k])
    print(f"\n[sanity] median sharpe={med_val:.2f} (cfg {med_cfg}), "
          f"best cfg={best_cfg} sharpe={med_sharpes[best_cfg]:.2f}")
    sh_b, ts_b, n_b = sharpe_tstat(daily_df[best_cfg])
    sh_m, ts_m, n_m = sharpe_tstat(daily_df[med_cfg])
    print(f"[sanity] best tstat={ts_b:.3f} (verdict says 2.14)  "
          f"median-cfg tstat={ts_m:.3f} (verdict says 1.15)")

    # ---- Q1: effective-N Bonferroni ----
    corr = daily_df.corr().to_numpy()
    m = corr.shape[0]
    m_eff_liji = li_ji_effective_n(corr)
    m_eff_avg, rho_bar = avg_corr_effective_n(corr)
    print(f"\n=== Q1: correlation structure across {m} configs ===")
    print(f"mean off-diagonal corr = {rho_bar:.3f}")
    print(f"Li & Ji (2005) eigenvalue effective-N = {m_eff_liji:.2f}")
    print(f"avg-correlation-approx effective-N   = {m_eff_avg:.2f}")

    df_t = n_b - 1  # ~degrees of freedom for the t-stat's implicit t-test
    orig_z = one_sided_z_threshold(0.05, 24)
    orig_t = one_sided_t_threshold(0.05, 24, df_t)
    print(f"\noriginal declared threshold (M=24, normal approx): z={orig_z:.3f}  "
          f"(t-dist df={df_t}: t={orig_t:.3f})  [verdict used 2.9]")

    for label, m_eff in [("Li&Ji", m_eff_liji), ("avg-corr", m_eff_avg)]:
        z_c = one_sided_z_threshold(0.05, m_eff)
        t_c = one_sided_t_threshold(0.05, m_eff, df_t)
        passes = ts_b > t_c
        print(f"  corrected via {label} (M_eff={m_eff:.2f}): "
              f"z_threshold={z_c:.3f}  t_threshold(df={df_t})={t_c:.3f}  "
              f"best cfg tstat={ts_b:.3f}  -> {'PASS' if passes else 'FAIL'}")

    # ---- Q2: selection-penalty applicability ----
    print("\n=== Q2: significance without a 'pick-the-best' selection step ===")
    single_test_z = stats.norm.ppf(1 - 0.05)   # one-sided, uncorrected, alpha=0.05
    print(f"single-test one-sided 5% z threshold = {single_test_z:.3f}")
    print(f"median config ({med_cfg}) tstat = {ts_m:.3f} -> "
          f"{'PASS' if ts_m > single_test_z else 'FAIL'} vs uncorrected single-test bar")

    # equal-weight ensemble across all 24 configs
    ens24 = daily_df.mean(axis=1)
    sh_e24, ts_e24, n_e24 = sharpe_tstat(ens24)
    print(f"\nequal-weight ensemble of ALL 24 configs: sharpe={sh_e24:.2f} tstat={ts_e24:.3f} "
          f"-> {'PASS' if ts_e24 > single_test_z else 'FAIL'} vs uncorrected single-test bar")

    # equal-weight ensemble across the 8 short-only configs (declared production side)
    short_cols = [c for c in daily_df.columns if c.endswith("-short")]
    ens_short = daily_df[short_cols].mean(axis=1)
    sh_es, ts_es, n_es = sharpe_tstat(ens_short)
    print(f"equal-weight ensemble of the 8 SHORT-only configs: sharpe={sh_es:.2f} "
          f"tstat={ts_es:.3f} -> {'PASS' if ts_es > single_test_z else 'FAIL'} "
          f"vs uncorrected single-test bar")
    # also check this ensemble against the *original* 24-trial correction (conservative)
    print(f"  same short-ensemble vs the ORIGINAL declared bar (t>2.9): "
          f"{'PASS' if ts_es > 2.9 else 'FAIL'}")
    print(f"  same short-ensemble vs the Li&Ji-corrected bar (t>{one_sided_t_threshold(0.05, m_eff_liji, df_t):.3f}): "
          f"{'PASS' if ts_es > one_sided_t_threshold(0.05, m_eff_liji, df_t) else 'FAIL'}")


if __name__ == "__main__":
    main()
