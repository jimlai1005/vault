#!/usr/bin/env python3
"""
Blind independent re-derivation (T6) of sub-project L Stage 1 gates G-L1..G-L5.

Reads ONLY:
  - docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md (spec, §2/§3) [read by hand, not by this script]
  - data/cache/cta_l/*.csv (daily pnl series, $500 fixed basis, per manifest.json)

Does NOT import any repo module. Does NOT read gates_table.md or any cta_l_stage1*.py script.
Uses only numpy / pandas.

Output: data/cache/cta_l/gates_table_t6.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple, Union

CTA_L_DIR = Path("data/cache/cta_l")
OUT_PATH = CTA_L_DIR / "gates_table_t6.md"

BASIS = 500.0          # fixed $500 basis (5 coins x $100), per spec §2
ANN_DAYS = 365.0       # annualization factor, per spec §2 ("年化 √365")
MDD_FLOOR = 0.005       # 0.5% floor on |MDD|, per spec §2 ("每折 MDD 取 max(|MDD|, 0.5%)")
STD_DDOF = 1            # sample stdev (judgment call, see notes)

G_L1_THRESHOLD = 1.3
G_L3_CI_LOWER_BOUND = -0.15
BLOCK_EXPECTED_LEN = 20.0
N_BOOT = 10_000
SEED = 42

FOLDS = [
    ("F1", "2020-09-14", "2021-12-31"),
    ("F2", "2022-01-01", "2022-12-31"),
    ("F3", "2023-01-01", "2023-12-31"),
    ("F4", "2024-01-01", "2024-12-31"),
    ("F5", "2025-01-01", "2025-12-31"),
    ("F6", "2026-01-01", "2026-06-30"),
]


def load_returns(path: Path) -> pd.Series:
    """Load daily pnl csv -> daily arithmetic return series (fraction of $500 basis), indexed by date."""
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    r = df.set_index("date")["pnl"] / BASIS
    return r


def annualized_return(r: pd.Series) -> float:
    """Non-compounding arithmetic annualized return: sum(r) * 365 / n_days."""
    n = len(r)
    return float(r.sum() * ANN_DAYS / n)


def cumulative_mdd(r: pd.Series) -> float:
    """Non-compounding cumulative-sum equity path, running peak, max drawdown (signed, negative)."""
    cr = r.cumsum().to_numpy()
    peak = np.maximum.accumulate(np.concatenate([[0.0], cr]))[1:]
    dd = cr - peak
    return float(dd.min()) if len(dd) else 0.0


def mar(r: pd.Series) -> tuple[float, float, float]:
    """Returns (MAR, annualized_return, mdd_signed). MAR uses floored |MDD| denominator."""
    ann = annualized_return(r)
    mdd_signed = cumulative_mdd(r)
    denom = max(abs(mdd_signed), MDD_FLOOR)
    return ann / denom, ann, mdd_signed


def sharpe(r: pd.Series | np.ndarray) -> float:
    """Annualized Sharpe of a daily return series: mean/std * sqrt(365), sample stdev (ddof=1)."""
    arr = np.asarray(r, dtype=float)
    std = arr.std(ddof=STD_DDOF)
    if std == 0:
        return float("nan")
    return float(arr.mean() / std * np.sqrt(ANN_DAYS))


def slice_dates(r: pd.Series, start: str, end: str) -> pd.Series:
    return r.loc[(r.index >= pd.Timestamp(start)) & (r.index <= pd.Timestamp(end))]


# ---------------------------------------------------------------------------
# G-L3: paired stationary block bootstrap on Delta Sharpe
# ---------------------------------------------------------------------------

def stationary_bootstrap_resample_indices(n: int, expected_block: float, rng: np.random.Generator) -> np.ndarray:
    """
    One stationary-bootstrap (Politis & Romano 1994) resample index array of length n.

    Algorithm (judgment call, spec does not spell out block-generation mechanics beyond
    "expected block 20d"):
      - block length L_i ~ Geometric(p = 1/expected_block), numpy convention (support {1,2,...}).
      - block start S_i ~ discrete Uniform{0, ..., n-1}.
      - Blocks are laid out in order; for block i, its contributed indices are
        (S_i, S_i+1, ..., S_i+L_i-1) taken modulo n (circular / wrap-around stationary bootstrap).
      - Blocks are appended until the concatenated index length >= n, then truncated to exactly n.
      - Per resample, lengths are drawn first (vectorized, one rng.geometric call with a safety
        upper bound on block count), then starts (one rng.integers call) -- fixed draw order.
    """
    max_blocks = int(np.ceil(n / expected_block * 6)) + 20  # generous safety margin
    p = 1.0 / expected_block
    lengths = rng.geometric(p, size=max_blocks)
    starts = rng.integers(0, n, size=max_blocks)
    cum = np.cumsum(lengths)
    nblocks = int(np.searchsorted(cum, n) + 1)
    nblocks = min(nblocks, max_blocks)
    idx_parts = []
    total = 0
    for i in range(nblocks):
        L = int(lengths[i])
        S = int(starts[i])
        block = (S + np.arange(L)) % n
        idx_parts.append(block)
        total += L
        if total >= n:
            break
    idx = np.concatenate(idx_parts)[:n]
    return idx


def paired_block_bootstrap_delta_sharpe(r_v: pd.Series, r_b: pd.Series,
                                          expected_block: float, n_boot: int, seed: int
                                          ) -> tuple[np.ndarray, float, float]:
    """
    Joint (paired) resampling of (r_variant, r_baseline) using identical block index sequences per
    resample so day-pairing is preserved within each drawn day. Each leg's Sharpe computed on its
    own resampled series; delta = Sharpe(variant) - Sharpe(baseline). Returns (deltas array,
    point-estimate Sharpe_variant, point-estimate Sharpe_baseline) on the *original* (unresampled)
    series.
    """
    assert list(r_v.index) == list(r_b.index), "variant/baseline date index must be identical for paired resampling"
    n = len(r_v)
    v_arr = r_v.to_numpy()
    b_arr = r_b.to_numpy()
    rng = np.random.default_rng(seed)

    deltas = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = stationary_bootstrap_resample_indices(n, expected_block, rng)
        sv = sharpe(v_arr[idx])
        sb = sharpe(b_arr[idx])
        deltas[i] = sv - sb

    point_sv = sharpe(v_arr)
    point_sb = sharpe(b_arr)
    return deltas, point_sv, point_sb


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    lines = []
    lines.append("# Sub-project L Stage 1 — blind independent re-derivation (T6)\n")
    lines.append("Computed directly from spec §2/§3 formulas applied to `data/cache/cta_l/*.csv`. "
                  "No repo modules imported; gates_table.md and cta_l_stage1*.py were not read.\n")

    # -------------------- full window B0 / V1 --------------------
    r_b0 = load_returns(CTA_L_DIR / "b0.csv")
    r_v1 = load_returns(CTA_L_DIR / "v1.csv")
    assert list(r_b0.index) == list(r_v1.index), "b0/v1 date index mismatch"

    mar_b0, ann_b0, mdd_b0 = mar(r_b0)
    mar_v1, ann_v1, mdd_v1 = mar(r_v1)
    ratio_full = mar_v1 / mar_b0 if mar_b0 != 0 else float("nan")

    lines.append("## G-L1: full-window MAR ratio\n")
    lines.append(f"- n_days: {len(r_b0)}")
    lines.append(f"- B0 annualized return: {ann_b0:.12f}")
    lines.append(f"- B0 MDD (signed, fraction): {mdd_b0:.12f}")
    lines.append(f"- B0 MAR: {mar_b0:.12f}")
    lines.append(f"- V1 annualized return: {ann_v1:.12f}")
    lines.append(f"- V1 MDD (signed, fraction): {mdd_v1:.12f}")
    lines.append(f"- V1 MAR: {mar_v1:.12f}")
    lines.append(f"- MAR(V1)/MAR(B0): {ratio_full:.12f}")
    lines.append(f"- threshold: {G_L1_THRESHOLD}")

    if mar_b0 <= 0:
        sharpe_dt_full = sharpe((r_v1 - r_b0).to_numpy())
        gl1_pass = (mar_v1 > 0) and (sharpe_dt_full > 0)
        lines.append(f"- MAR(B0) <= 0 fallback branch triggered. MAR(V1) > 0: {mar_v1 > 0}; "
                      f"Sharpe(d_t) = {sharpe_dt_full:.12f} > 0: {sharpe_dt_full > 0}")
    else:
        gl1_pass = ratio_full >= G_L1_THRESHOLD
    lines.append(f"- **G-L1: {'PASS' if gl1_pass else 'FAIL'}**\n")

    # -------------------- G-L2: 6-fold MAR --------------------
    lines.append("## G-L2: 6-fold MAR (V1 >= B0 count, threshold >=4/6)\n")
    lines.append("Per-fold basis reset: cumulative equity path (for MDD) restarts at 0 at each "
                  "fold's first day (judgment call #1 below); annualization denominator (\"天數\") "
                  "uses each fold's own day count.\n")
    fold_pass_count = 0
    fold_rows = []
    for name, start, end in FOLDS:
        fb0 = slice_dates(r_b0, start, end)
        fv1 = slice_dates(r_v1, start, end)
        assert len(fb0) == len(fv1), f"{name}: length mismatch"
        m_b0, a_b0, d_b0 = mar(fb0)
        m_v1, a_v1, d_v1 = mar(fv1)
        ok = m_v1 >= m_b0
        fold_pass_count += int(ok)
        fold_rows.append((name, start, end, len(fb0), a_b0, d_b0, m_b0, a_v1, d_v1, m_v1, ok))
        lines.append(f"### {name} ({start} .. {end}, n={len(fb0)})")
        lines.append(f"- B0: ann_ret={a_b0:.12f} mdd={d_b0:.12f} MAR={m_b0:.12f}")
        lines.append(f"- V1: ann_ret={a_v1:.12f} mdd={d_v1:.12f} MAR={m_v1:.12f}")
        lines.append(f"- V1 MAR >= B0 MAR: {ok}\n")
    gl2_pass = fold_pass_count >= 4
    lines.append(f"- folds where V1 MAR >= B0 MAR: {fold_pass_count}/6")
    lines.append(f"- **G-L2: {'PASS' if gl2_pass else 'FAIL'}**\n")

    # -------------------- G-L3: paired block bootstrap ΔSharpe --------------------
    lines.append("## G-L3: paired stationary block bootstrap on ΔSharpe (90% CI)\n")
    deltas, point_sv, point_sb = paired_block_bootstrap_delta_sharpe(
        r_v1, r_b0, BLOCK_EXPECTED_LEN, N_BOOT, SEED
    )
    point_delta = point_sv - point_sb
    ci_lo, ci_hi = np.percentile(deltas, [5, 95])
    boot_mean = deltas.mean()
    boot_std = deltas.std(ddof=1)
    gl3_pass = ci_lo > G_L3_CI_LOWER_BOUND

    lines.append(f"- B={N_BOOT}, expected block length={BLOCK_EXPECTED_LEN}, seed={SEED}")
    lines.append(f"- point-estimate Sharpe(V1): {point_sv:.12f}")
    lines.append(f"- point-estimate Sharpe(B0): {point_sb:.12f}")
    lines.append(f"- point-estimate ΔSharpe (V1 - B0): {point_delta:.12f}")
    lines.append(f"- bootstrap ΔSharpe distribution mean: {boot_mean:.12f}")
    lines.append(f"- bootstrap ΔSharpe distribution std (ddof=1): {boot_std:.12f}")
    lines.append(f"- 90% CI: [{ci_lo:.12f}, {ci_hi:.12f}]  (5th/95th percentile, linear interpolation)")
    lines.append(f"- threshold: CI lower bound > {G_L3_CI_LOWER_BOUND}")
    lines.append(f"- **G-L3: {'PASS' if gl3_pass else 'FAIL'}**\n")

    # -------------------- G-L4: cost x1.5 --------------------
    lines.append("## G-L4: cost x1.5 (0.0825%/side) — repeat G-L1 rule\n")
    r_b0_c15 = load_returns(CTA_L_DIR / "b0_cost15.csv")
    r_v1_c15 = load_returns(CTA_L_DIR / "v1_cost15.csv")
    assert list(r_b0_c15.index) == list(r_v1_c15.index)

    mar_b0_c15, ann_b0_c15, mdd_b0_c15 = mar(r_b0_c15)
    mar_v1_c15, ann_v1_c15, mdd_v1_c15 = mar(r_v1_c15)
    ratio_c15 = mar_v1_c15 / mar_b0_c15 if mar_b0_c15 != 0 else float("nan")

    lines.append(f"- n_days: {len(r_b0_c15)}")
    lines.append(f"- B0(cost15): ann_ret={ann_b0_c15:.12f} mdd={mdd_b0_c15:.12f} MAR={mar_b0_c15:.12f}")
    lines.append(f"- V1(cost15): ann_ret={ann_v1_c15:.12f} mdd={mdd_v1_c15:.12f} MAR={mar_v1_c15:.12f}")
    lines.append(f"- MAR(V1)/MAR(B0) at cost15: {ratio_c15:.12f}")

    if mar_b0_c15 <= 0:
        sharpe_dt_c15 = sharpe((r_v1_c15 - r_b0_c15).to_numpy())
        gl4_pass = (mar_v1_c15 > 0) and (sharpe_dt_c15 > 0)
        lines.append(f"- MAR(B0,cost15) <= 0 fallback branch triggered. MAR(V1)>0: {mar_v1_c15>0}; "
                      f"Sharpe(d_t)={sharpe_dt_c15:.12f} > 0: {sharpe_dt_c15 > 0}")
    else:
        gl4_pass = ratio_c15 >= G_L1_THRESHOLD
    lines.append(f"- **G-L4: {'PASS' if gl4_pass else 'FAIL'}**\n")

    # -------------------- G-L5: endpoint sensitivity --------------------
    lines.append("## G-L5: endpoint sensitivity (-30/-60/-90d), direction check only (V1 >= B0)\n")
    ep_pass_all = True
    for ep in ("ep30", "ep60", "ep90"):
        r_b0_ep = load_returns(CTA_L_DIR / f"b0_{ep}.csv")
        r_v1_ep = load_returns(CTA_L_DIR / f"v1_{ep}.csv")
        assert list(r_b0_ep.index) == list(r_v1_ep.index)
        m_b0_ep, a_b0_ep, d_b0_ep = mar(r_b0_ep)
        m_v1_ep, a_v1_ep, d_v1_ep = mar(r_v1_ep)
        direction_ok = m_v1_ep >= m_b0_ep
        ep_pass_all = ep_pass_all and direction_ok
        lines.append(f"### {ep}: n_days={len(r_b0_ep)}, window end = {r_b0_ep.index.max().date()}")
        lines.append(f"- B0: ann_ret={a_b0_ep:.12f} mdd={d_b0_ep:.12f} MAR={m_b0_ep:.12f}")
        lines.append(f"- V1: ann_ret={a_v1_ep:.12f} mdd={d_v1_ep:.12f} MAR={m_v1_ep:.12f}")
        lines.append(f"- direction V1 MAR >= B0 MAR: {direction_ok}\n")
    lines.append(f"- **G-L5: {'PASS' if ep_pass_all else 'FAIL'}**\n")

    # -------------------- overall --------------------
    all_pass = gl1_pass and gl2_pass and gl3_pass and gl4_pass and ep_pass_all
    lines.append("## Overall\n")
    lines.append(f"- G-L1: {'PASS' if gl1_pass else 'FAIL'}")
    lines.append(f"- G-L2: {'PASS' if gl2_pass else 'FAIL'}")
    lines.append(f"- G-L3: {'PASS' if gl3_pass else 'FAIL'}")
    lines.append(f"- G-L4: {'PASS' if gl4_pass else 'FAIL'}")
    lines.append(f"- G-L5: {'PASS' if ep_pass_all else 'FAIL'}")
    lines.append(f"- **Stage 1 overall: {'GO (all gates pass)' if all_pass else 'NO-GO (>=1 gate fails)'}**\n")

    # -------------------- judgment-call notes --------------------
    lines.append("## Judgment calls / implementation choices not spelled out verbatim in spec §2/§3\n")
    lines.append("These are exactly the points a diff against the implementer's own gate table should "
                  "focus on:\n")
    lines.append("1. **Per-fold MDD basis**: interpreted \"每折 MDD\" as an intra-fold reset — the "
                  "cumulative equity path (for drawdown purposes) restarts at 0 on the fold's first day, "
                  "independent of any drawdown carried over from a prior fold. (Alternative reading: "
                  "use the single continuous whole-window equity path and read off the local min/max "
                  "within the fold's date range, which could import pre-existing drawdown from before "
                  "the fold started.)")
    lines.append("2. **0.5% MDD floor scope**: applied the `max(|MDD|, 0.5%)` floor uniformly to every "
                  "MAR computation (full window, each fold, cost15, each endpoint variant) even though "
                  "spec text attaches the floor sentence specifically to \"每折\" (each fold). Floor never "
                  "actually binds in any of the computed windows here (all |MDD| >> 0.5%), so this choice "
                  "is inert for this run but is recorded for completeness.")
    lines.append("3. **Sharpe formula**: `mean(r) / std(r, ddof=1) * sqrt(365)` on the daily return series "
                  "(sample stdev, ddof=1; annualization factor sqrt(365) to match the day-count convention "
                  "spec uses elsewhere for MAR's \"年化 √365\"). Spec does not give a Sharpe formula "
                  "explicitly outside the DSR/MAR context, so this is the most literal read of \"annualized "
                  "daily Sharpe\" consistent with the rest of §2.")
    lines.append("4. **manifest.json `summary.sharpe` / `summary.mdd_pct` were NOT used or reconciled "
                  "against** — those fields are produced by whatever engine generated the CSVs/manifest, "
                  "not necessarily under the spec's exact MAR/MDD/Sharpe formulas (spot check: recomputing "
                  "B0 full-window Sharpe/MDD from `b0.csv` under the formulas above gives "
                  "Sharpe≈0.30696/0.30689 (ddof0/ddof1) and MDD≈-33.619%, vs manifest's reported "
                  "0.309090/-32.504% — a real but modest discrepancy, consistent with a different "
                  "pipeline/convention, not a bug in this re-derivation). Per task instructions, all "
                  "statistics here are computed strictly from spec §2/§3 formulas applied to the raw "
                  "daily pnl columns, ignoring manifest.json's own summary stats.")
    lines.append("5. **Stationary block bootstrap mechanics** (spec only specifies \"stationary block "
                  "bootstrap\", expected block 20d, B=10,000, seed 42; does not specify the RNG call "
                  "sequence or boundary handling): implemented as circular/wrap-around stationary "
                  "bootstrap (Politis & Romano 1994) — block length ~ Geometric(p=1/20) (numpy convention, "
                  "support {1,2,...}), block start ~ discrete Uniform{0,...,n-1}, indices for a block are "
                  "`(start + arange(length)) % n` (wrap past the end of the series rather than truncating "
                  "at the boundary). Per resample: block lengths are drawn first via one vectorized "
                  "`rng.geometric` call (with a generous upper bound on block count), then block starts "
                  "via one vectorized `rng.integers` call — this exact draw order/vectorization affects "
                  "the specific numbers produced from seed 42 and is the most likely single source of "
                  "numeric divergence from an independently-written implementation, even if both "
                  "implementations agree on \"stationary bootstrap, geometric block length 20, seed 42\" "
                  "in prose.")
    lines.append("6. **90% CI method**: empirical percentile method — `numpy.percentile(deltas, [5, 95])` "
                  "(linear interpolation, numpy default), not bias-corrected/BCa.")
    lines.append("7. **G-L5 \"direction\" definition**: read literally as `MAR(V1) >= MAR(B0)` at each "
                  "endpoint (the same relation as the non-fallback branch of G-L1), not the full 1.3x "
                  "magnitude threshold — per spec wording \"G-L1 的方向（V1 ≥ B0）零翻轉\".")
    lines.append("8. **Fold annualization denominator**: each fold's \"天數\" (days) is that fold's own "
                  "row/day count (e.g. F6 ≈ 181 days), not a fixed 365 — matches \"Σ日報酬 × 365 ÷ 天數\" "
                  "read literally per-slice.")
    lines.append("9. **Appendix-only paired ΔMAR bootstrap** (mentioned in spec §2 as report-only, not a "
                  "gate) was intentionally NOT computed — out of scope of the requested G-L1..G-L5 table.")

    OUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT_PATH}")
    print(f"G-L1={'PASS' if gl1_pass else 'FAIL'} G-L2={'PASS' if gl2_pass else 'FAIL'} "
          f"G-L3={'PASS' if gl3_pass else 'FAIL'} G-L4={'PASS' if gl4_pass else 'FAIL'} "
          f"G-L5={'PASS' if ep_pass_all else 'FAIL'}")


if __name__ == "__main__":
    main()
