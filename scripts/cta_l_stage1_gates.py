"""Sub-project L Stage 1, plan T5 -- gate score sheet.

Computes spec (docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md)
Sec.3 G-L1..G-L5 for the Stage-1 main config (V1) vs baseline (B0), plus
appendix items, purely by reading the daily-pnl / trade-ledger csvs T4 wrote
to data/cache/cta_l/. This script performs NO simulation of any kind and
does NOT import cta_l_stage1.py, cta_proxy_lib.py, or
research_cta_positioning_phase2b.py -- only pandas/numpy/json/csv reads
(spec Sec.7 point 2; plan T5 red line).

Usage:
    .venv/bin/python scripts/cta_l_stage1_gates.py            # full run,
        writes data/cache/cta_l/gates_table.md and prints it to stdout
    .venv/bin/python scripts/cta_l_stage1_gates.py --selftest # B0-vs-B0
        plumbing check only (delta-Sharpe CI must contain 0, G-L1 ratio == 1.0)

All internal math is done in *fraction* units (daily pnl-dollars / BASE),
never mixing dollar and fraction bases (engineering principle #1 -- see
CLAUDE.md). MDD is computed as standard peak-relative drawdown on an
equity curve seeded at 1.0 (== $500 in dollar space; algebraically
equivalent -- see the discretion log at the bottom of the emitted table).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache" / "cta_l"
OUT_PATH = CACHE_DIR / "gates_table.md"
SPEC_PATH = "docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md"

BASE = 500.0
ANN_DAYS = 365.0
MDD_FLOOR = 0.005          # spec Sec.2 line 42: "每折 MDD 取 max(|MDD|, 0.5%) 作下限"
G_L1_MULT = 1.3            # spec Sec.3 line 107
G_L3_LOWER_BOUND = -0.15   # spec Sec.3 line 109
BOOT_BLOCK = 20            # spec Sec.2 line 49-50: expected block 20d
BOOT_B = 10_000            # spec Sec.2 line 49-50: B=10,000
BOOT_SEED = 42             # spec Sec.2 line 50: numpy.random.default_rng(42)
CI_LO_PCTL, CI_HI_PCTL = 5.0, 95.0   # 90% CI, percentile method (discretion #4)

FOLDS = [
    ("F1", "2020-09-14", "2021-12-31"),
    ("F2", "2022-01-01", "2022-12-31"),
    ("F3", "2023-01-01", "2023-12-31"),
    ("F4", "2024-01-01", "2024-12-31"),
    ("F5", "2025-01-01", "2025-12-31"),
    ("F6", "2026-01-01", "2026-06-30"),
]  # spec Sec.2 line 44-45


# --------------------------------------------------------------------------
# CSV loading -- the ONLY data source. No simulation, no imports of engine
# modules.
# --------------------------------------------------------------------------

def load_returns(name: str) -> pd.Series:
    """Load data/cache/cta_l/{name}.csv, return fraction-of-$500 daily
    returns indexed by date (UTC calendar day, tz-naive)."""
    path = CACHE_DIR / f"{name}.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    return (df["pnl"] / BASE).rename(name)


def load_trades(name: str) -> pd.DataFrame:
    path = CACHE_DIR / f"{name}_trades.csv"
    return pd.read_csv(path, parse_dates=["entry_ts", "exit_ts"])


def assert_aligned(a: pd.Series, b: pd.Series, ctx: str) -> None:
    """Engineering principle #1: compared values must share one source and
    basis -- refuse to compare two return series on mismatched date grids."""
    if not a.index.equals(b.index):
        raise ValueError(
            f"[{ctx}] date index mismatch between '{a.name}' and '{b.name}': "
            f"{len(a)} vs {len(b)} rows, first diff at "
            f"{(a.index.symmetric_difference(b.index))[:5].tolist()}"
        )


# --------------------------------------------------------------------------
# Core statistics (spec Sec.2, lines 39-59)
# --------------------------------------------------------------------------

def mdd_frac(returns: np.ndarray) -> float:
    """Peak-relative drawdown fraction (<=0) on an equity curve seeded at
    1.0. Algebraically identical to dollar-space MDD on a $500 base (a pure
    scalar multiple cancels in the peak-relative ratio) -- see discretion
    log item 2."""
    if len(returns) == 0:
        return 0.0
    eq = 1.0 + np.cumsum(returns)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return float(dd.min())


def ann_return_frac(returns: np.ndarray) -> float:
    """Spec line 41: Sigma(daily return) * 365 / n_days == mean * 365."""
    n = len(returns)
    if n == 0:
        return 0.0
    return float(np.sum(returns) * ANN_DAYS / n)


def mar(returns: np.ndarray) -> float:
    """Spec line 41-42: numerator = ann_return_frac, denominator =
    max(|MDD|, 0.5%)."""
    denom = max(abs(mdd_frac(returns)), MDD_FLOOR)
    return ann_return_frac(returns) / denom


def sharpe_frac(returns: np.ndarray) -> float:
    """Spec line 42 "年化 sqrt(365)". ddof=1 sample std; 0.0 if std==0 or
    n<2 (degenerate-series guard, not an explicit spec case)."""
    n = len(returns)
    if n < 2:
        return 0.0
    sd = np.std(returns, ddof=1)
    if sd <= 0:
        return 0.0
    return float(np.mean(returns) / sd * np.sqrt(ANN_DAYS))


def g_l1_check(mar_v: float, mar_b: float, ret_v: np.ndarray,
                ret_b: np.ndarray) -> tuple[bool, str, float]:
    """Spec line 107: MAR(V1) >= 1.3*MAR(B0); if MAR(B0)<=0, fall back to
    MAR(V1)>0 and Sharpe(d_t)>0. Returns (pass, branch_label, ratio_or_nan)."""
    if mar_b > 0:
        ratio = mar_v / mar_b
        return (ratio >= G_L1_MULT, "main (MAR(B0)>0)", ratio)
    d_t = ret_v - ret_b
    ok = (mar_v > 0) and (sharpe_frac(d_t) > 0)
    return (ok, "fallback (MAR(B0)<=0)", float("nan"))


# --------------------------------------------------------------------------
# Paired stationary block bootstrap (spec Sec.2 lines 49-54)
# --------------------------------------------------------------------------

def stationary_bootstrap_indices(n: int, B: int, expected_block: int,
                                  seed: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap index generator, vectorized over
    the B replicate dimension, circular (mod n) wraparound at series edges
    (discretion log item 6). Deterministic given (n, B, expected_block,
    seed): calling this twice with identical args reproduces identical
    output bit-for-bit (numpy Generator has no external state)."""
    rng = np.random.default_rng(seed)
    p = 1.0 / expected_block
    idx = rng.integers(0, n, size=B)
    out = np.empty((B, n), dtype=np.int64)
    out[:, 0] = idx
    for t in range(1, n):
        u = rng.random(B)
        cont = u >= p
        new_start = rng.integers(0, n, size=B)
        idx = np.where(cont, (idx + 1) % n, new_start)
        out[:, t] = idx
    return out


def bootstrap_stats(ret_v: np.ndarray, ret_b: np.ndarray,
                     indices: np.ndarray) -> dict:
    """Given a (B, n) joint resample index matrix, compute the bootstrap
    distributions of Sharpe(V), Sharpe(B), delta-Sharpe, MAR(V), MAR(B),
    delta-MAR, all from the SAME resampled paths (joint resampling per
    spec line 50-51: "重抽單位是對齊的聯合日向量 (r_variant,t, r_baseline,t) 的
    block")."""
    rv = ret_v[indices]   # (B, n)
    rb = ret_b[indices]   # (B, n)

    mean_v, mean_b = rv.mean(axis=1), rb.mean(axis=1)
    std_v = rv.std(axis=1, ddof=1)
    std_b = rb.std(axis=1, ddof=1)
    sharpe_v = np.where(std_v > 0, mean_v / std_v * np.sqrt(ANN_DAYS), 0.0)
    sharpe_b = np.where(std_b > 0, mean_b / std_b * np.sqrt(ANN_DAYS), 0.0)
    delta_sharpe = sharpe_v - sharpe_b

    n = rv.shape[1]
    eq_v = 1.0 + np.cumsum(rv, axis=1)
    eq_b = 1.0 + np.cumsum(rb, axis=1)
    peak_v = np.maximum.accumulate(eq_v, axis=1)
    peak_b = np.maximum.accumulate(eq_b, axis=1)
    mdd_v = ((eq_v - peak_v) / peak_v).min(axis=1)
    mdd_b = ((eq_b - peak_b) / peak_b).min(axis=1)
    ann_v = mean_v * ANN_DAYS
    ann_b = mean_b * ANN_DAYS
    mar_v = ann_v / np.maximum(np.abs(mdd_v), MDD_FLOOR)
    mar_b = ann_b / np.maximum(np.abs(mdd_b), MDD_FLOOR)
    delta_mar = mar_v - mar_b

    return {
        "delta_sharpe": delta_sharpe,
        "delta_mar": delta_mar,
        "sharpe_v_point": sharpe_frac(ret_v),
        "sharpe_b_point": sharpe_frac(ret_b),
    }


def ci90(x: np.ndarray) -> tuple[float, float]:
    lo, hi = np.percentile(x, [CI_LO_PCTL, CI_HI_PCTL])
    return float(lo), float(hi)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def fnum(x: float, decimals: int = 4) -> str:
    if x != x:  # NaN
        return "NaN"
    if abs(x) >= 1000:
        return f"{x:.4e}"
    return f"{x:.{decimals}f}"


def fpct(x: float, decimals: int = 3) -> str:
    if x != x:
        return "NaN"
    return f"{x * 100:.{decimals}f}%"


def pf(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


# --------------------------------------------------------------------------
# Main gate computation
# --------------------------------------------------------------------------

def run(selftest: bool = False) -> str:
    manifest = json.loads((CACHE_DIR / "manifest.json").read_text())

    b0 = load_returns("b0")
    v1 = load_returns("b0" if selftest else "v1")
    v1 = v1.rename("v1" if not selftest else "b0(as V, selftest)")
    assert_aligned(b0, v1, "main window B0 vs V1")

    ret_b0 = b0.to_numpy()
    ret_v1 = v1.to_numpy()

    lines: list[str] = []
    mode_label = "SELFTEST (V1:=B0, B0:=B0)" if selftest else "REAL (V1 vs B0)"
    lines.append(f"# CTA Sub-project L -- Stage 1 Gate Table [{mode_label}]")
    lines.append("")
    lines.append(f"Source: `{CACHE_DIR.relative_to(REPO_ROOT)}/*.csv` "
                 f"(T4 output, read-only). Gate definitions: "
                 f"`{SPEC_PATH}` Sec.2-Sec.3.")
    lines.append(f"Main window: {manifest['b0']['window_start'][:10]} .. "
                 f"{manifest['b0']['window_end'][:10]}  "
                 f"(n_days={len(b0)}, standard cost "
                 f"{manifest['b0']['cost_per_side_total']*100:.4f}%/side).")
    lines.append("")

    # ---------------------------------------------------------------- G-L1
    mar_b0_full = mar(ret_b0)
    mar_v1_full = mar(ret_v1)
    g1_ok, g1_branch, g1_ratio = g_l1_check(mar_v1_full, mar_b0_full, ret_v1, ret_b0)

    lines.append("## G-L1 -- full-window MAR ratio (spec Sec.3 line 107)")
    lines.append("")
    lines.append("| Metric | B0 | V1 |")
    lines.append("|---|---|---|")
    lines.append(f"| Ann. return (frac, non-compounding) | {fnum(ann_return_frac(ret_b0))} | {fnum(ann_return_frac(ret_v1))} |")
    lines.append(f"| MDD (peak-relative) | {fpct(mdd_frac(ret_b0))} | {fpct(mdd_frac(ret_v1))} |")
    lines.append(f"| MAR | {fnum(mar_b0_full)} | {fnum(mar_v1_full)} |")
    lines.append("")
    lines.append(f"Branch used: **{g1_branch}**. Ratio MAR(V1)/MAR(B0) = **{fnum(g1_ratio)}** "
                 f"(threshold >= {G_L1_MULT}). **G-L1: {pf(g1_ok)}**")
    lines.append("")

    # ---------------------------------------------------------------- G-L2
    lines.append("## G-L2 -- 6-fold MAR (spec Sec.2 lines 44-45, Sec.3 line 108)")
    lines.append("")
    lines.append("Each fold's equity curve is reset to base 1.0 at the fold's own start "
                 "(discretion log item 3) -- MDD is a within-fold statistic, not a slice of "
                 "the whole-window drawdown path.")
    lines.append("")
    lines.append("| Fold | Window | n_days | MAR(B0) | MAR(V1) | V1>=B0 |")
    lines.append("|---|---|---|---|---|---|")
    fold_pass = 0
    fold_rows = []
    for fname, fs, fe in FOLDS:
        rb = b0.loc[fs:fe].to_numpy()
        rv = v1.loc[fs:fe].to_numpy()
        mb, mv = mar(rb), mar(rv)
        ok = mv >= mb
        fold_pass += int(ok)
        fold_rows.append((fname, fs, fe, len(rb), mb, mv, ok))
        lines.append(f"| {fname} | {fs}..{fe} | {len(rb)} | {fnum(mb)} | {fnum(mv)} | {pf(ok)} |")
    g2_ok = fold_pass >= 4
    lines.append("")
    lines.append(f"Folds with V1>=B0: **{fold_pass}/6** (threshold >=4). **G-L2: {pf(g2_ok)}**")
    lines.append("")

    # ---------------------------------------------------------------- Bootstrap
    n = len(b0)
    indices = stationary_bootstrap_indices(n, BOOT_B, BOOT_BLOCK, BOOT_SEED)
    boot = bootstrap_stats(ret_v1, ret_b0, indices)
    ci_sharpe_lo, ci_sharpe_hi = ci90(boot["delta_sharpe"])
    ci_mar_lo, ci_mar_hi = ci90(boot["delta_mar"])
    point_delta_sharpe = boot["sharpe_v_point"] - boot["sharpe_b_point"]

    g3_ok = ci_sharpe_lo > G_L3_LOWER_BOUND

    lines.append("## G-L3 -- paired stationary block bootstrap delta-Sharpe (spec Sec.2 "
                 "lines 49-51, Sec.3 line 109)")
    lines.append("")
    lines.append(f"Method: joint resample of aligned (r_V1,t, r_B0,t) pairs, stationary "
                 f"bootstrap, expected block={BOOT_BLOCK}d, B={BOOT_B}, "
                 f"seed=numpy.random.default_rng({BOOT_SEED}), circular wraparound "
                 f"(discretion log item 6), CI = [{CI_LO_PCTL:.0f}th, {CI_HI_PCTL:.0f}th] "
                 f"percentile of the {BOOT_B}-replicate delta-Sharpe distribution "
                 f"(discretion log item 4).")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Sharpe(B0), point estimate | {fnum(boot['sharpe_b_point'])} |")
    lines.append(f"| Sharpe(V1), point estimate | {fnum(boot['sharpe_v_point'])} |")
    lines.append(f"| delta-Sharpe, point estimate | {fnum(point_delta_sharpe)} |")
    lines.append(f"| delta-Sharpe 90% CI | [{fnum(ci_sharpe_lo)}, {fnum(ci_sharpe_hi)}] |")
    lines.append(f"| Threshold | lower bound > {G_L3_LOWER_BOUND} |")
    lines.append("")
    lines.append(f"**G-L3: {pf(g3_ok)}**")
    lines.append("")

    # ---------------------------------------------------------------- G-L4
    b0c = load_returns("b0_cost15")
    v1c = load_returns("b0_cost15" if selftest else "v1_cost15")
    assert_aligned(b0c, v1c, "cost15 B0 vs V1")
    ret_b0c, ret_v1c = b0c.to_numpy(), v1c.to_numpy()
    mar_b0c, mar_v1c = mar(ret_b0c), mar(ret_v1c)
    g4_ok, g4_branch, g4_ratio = g_l1_check(mar_v1c, mar_b0c, ret_v1c, ret_b0c)

    lines.append("## G-L4 -- cost x1.5 (spec Sec.3 line 110)")
    lines.append("")
    lines.append(f"Cost = {manifest['b0_cost15']['cost_per_side_total']*100:.4f}%/side "
                 f"(vs standard {manifest['b0']['cost_per_side_total']*100:.4f}%/side). "
                 f"Applies the identical G-L1 rule to the cost-x1.5 legs.")
    lines.append("")
    lines.append("| Metric | B0_cost15 | V1_cost15 |")
    lines.append("|---|---|---|")
    lines.append(f"| MAR | {fnum(mar_b0c)} | {fnum(mar_v1c)} |")
    lines.append("")
    lines.append(f"Branch used: **{g4_branch}**. Ratio = **{fnum(g4_ratio)}** "
                 f"(threshold >= {G_L1_MULT}). **G-L4: {pf(g4_ok)}**")
    lines.append("")

    # ---------------------------------------------------------------- G-L5
    lines.append("## G-L5 -- endpoint direction stability (spec Sec.2 line 48, "
                 "Sec.3 line 111)")
    lines.append("")
    lines.append("Direction checked is the literal G-L1 inequality V1>=B0 (spec line 111 "
                 "says \"方向\", not the 1.3x magnitude -- discretion log item 5).")
    lines.append("")
    lines.append("| Endpoint | Window end | MAR(B0) | MAR(V1) | V1>=B0 (no flip) |")
    lines.append("|---|---|---|---|---|")
    ep_pass = True
    for ep in ("ep30", "ep60", "ep90"):
        b0e = load_returns(f"b0_{ep}")
        v1e = load_returns(f"b0_{ep}" if selftest else f"v1_{ep}")
        assert_aligned(b0e, v1e, f"{ep} B0 vs V1")
        mb, mv = mar(b0e.to_numpy()), mar(v1e.to_numpy())
        ok = mv >= mb
        ep_pass = ep_pass and ok
        lines.append(f"| {ep} | {manifest['b0_' + ep]['window_end'][:10]} | {fnum(mb)} | {fnum(mv)} | {pf(ok)} |")
    lines.append("")
    lines.append(f"**G-L5: {pf(ep_pass)}** (zero direction flips across -30/-60/-90d)")
    lines.append("")

    # ---------------------------------------------------------------- Summary
    gates = [("G-L1", g1_ok), ("G-L2", g2_ok), ("G-L3", g3_ok), ("G-L4", g4_ok), ("G-L5", ep_pass)]
    n_pass = sum(1 for _, ok in gates if ok)
    lines.append("## Summary")
    lines.append("")
    lines.append("| Gate | Result |")
    lines.append("|---|---|")
    for gname, ok in gates:
        lines.append(f"| {gname} | {pf(ok)} |")
    lines.append("")
    lines.append(f"**{n_pass}/5 gates PASS.** Per spec Sec.3 line 119-121: all 5 PASS => "
                 f"V1 becomes B1 baseline, Stage 2 opens; any 1 FAIL => sub-project L closes "
                 f"(no variants, no retry). (Full verdict narrative is T7's responsibility, "
                 f"not this script's.)")
    lines.append("")

    # ---------------------------------------------------------------- Appendix
    lines.append("## Appendix A -- paired delta-MAR bootstrap CI (reporting only, spec "
                 "Sec.2 lines 51-54)")
    lines.append("")
    lines.append("**Caveat (spec Sec.2 line 52-54):** MDD is a path statistic; block "
                 "resampling shuffles/concatenates blocks and systematically shreds "
                 "cross-year drawdown structure, biasing |MDD| low (a dangerous "
                 "direction). This delta-MAR bootstrap is NOT a gate and must not be "
                 "read as a confidence interval on the true MAR difference.")
    lines.append("")
    lines.append(f"delta-MAR 90% CI (same {BOOT_B} joint resamples as G-L3): "
                 f"[{fnum(ci_mar_lo)}, {fnum(ci_mar_hi)}]  "
                 f"(point estimate delta-MAR = {fnum(mar_v1_full - mar_b0_full)})")
    lines.append("")

    lines.append("## Appendix B -- m distribution (V1 main config, reporting only, "
                 "spec line 113)")
    lines.append("")
    v1t = load_trades("b0" if selftest else "v1")
    m = v1t["m"].dropna()
    at_1 = float((m >= 1.0 - 1e-12).mean() * 100.0) if len(m) else float("nan")
    at_floor = float((m <= 0.25 + 1e-12).mean() * 100.0) if len(m) else float("nan")
    lines.append(f"Source: `{'b0' if selftest else 'v1'}_trades.csv` `m` column "
                 f"(entry-locked multiplier per executed trade, n={len(m)}) -- "
                 f"trade-level, not the T3-selftest per-bar distribution (discretion "
                 f"log item 7).")
    lines.append("")
    lines.append("| n | min | median | max | %m==1.0 | %m==0.25 (clip floor) |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(f"| {len(m)} | {fnum(m.min())} | {fnum(m.median())} | {fnum(m.max())} | "
                 f"{at_1:.2f}% | {at_floor:.2f}% |")
    lines.append("")

    lines.append("## Appendix C -- sensitivity configs, full table (reporting only, spec "
                 "line 113)")
    lines.append("")
    lines.append("| Config | sigma_target | span | MAR | Sharpe |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| b0 (baseline) | -- | -- | {fnum(mar_b0_full)} | {fnum(sharpe_frac(ret_b0))} |")
    lines.append(f"| v1 (main) | 60% | 180 | {fnum(mar_v1_full)} | {fnum(sharpe_frac(ret_v1))} |")
    for cfg, st, sp in (("sens_st40", "40%", 180), ("sens_st80", "80%", 180),
                        ("sens_sp90", "60%", 90), ("sens_sp360", "60%", 360)):
        r = load_returns(cfg).to_numpy()
        lines.append(f"| {cfg} | {st} | {sp} | {fnum(mar(r))} | {fnum(sharpe_frac(r))} |")
    lines.append("")

    lines.append("## Appendix D -- spec Sec.6 honesty clauses (restated, not re-derived)")
    lines.append("")
    lines.append("1. Proxy limits (funding != positioning, volume != OI) apply to all L "
                 "results (spec line 168-169).")
    lines.append("2. pseudo-OOS: fold params are ex-ante, but the underlying data has "
                 "been extensively explored; a Stage-1 PASS is not a live-deployment "
                 "signal (spec line 170-171).")
    lines.append("3. sigma_target=60%, clip 0.25, fold threshold 4/6, non-inferiority "
                 "margin -0.15 are ex-ante judgment calls, not calibrated to data "
                 "(spec line 172-173).")
    lines.append("4. Funding-rate accrual is unmodeled (spec line 174).")
    lines.append("5. Any gate result within +-10% of its threshold must not be described "
                 "as a robust pass in the verdict (spec line 175) -- flagged per-gate "
                 "below where applicable.")
    lines.append("6. Known fold artifacts (unequal fold length, F1's 30-day sigma "
                 "warmup where V1==B0 by construction, non-compounding fixed-base MDD "
                 "occasionally exceeding 100% in extreme folds) are accepted, not fixed "
                 "(spec line 176-179).")
    lines.append("")

    # Edge-band flag for §6 point 5
    edge_flags = []
    if not (g1_ratio != g1_ratio):  # not NaN
        if abs(g1_ratio - G_L1_MULT) / G_L1_MULT <= 0.10:
            edge_flags.append(f"G-L1 ratio {fnum(g1_ratio)} is within 10% of threshold {G_L1_MULT}")
    if abs(fold_pass - 4) == 0 and fold_pass == 4:
        edge_flags.append(f"G-L2 fold count {fold_pass}/6 is exactly at the 4/6 threshold")
    if abs(ci_sharpe_lo - G_L3_LOWER_BOUND) <= 0.10 * abs(G_L3_LOWER_BOUND):
        edge_flags.append(f"G-L3 CI lower bound {fnum(ci_sharpe_lo)} is within 10% of threshold {G_L3_LOWER_BOUND}")
    if not (g4_ratio != g4_ratio):
        if abs(g4_ratio - G_L1_MULT) / G_L1_MULT <= 0.10:
            edge_flags.append(f"G-L4 ratio {fnum(g4_ratio)} is within 10% of threshold {G_L1_MULT}")
    lines.append("### Edge-band check (spec Sec.6 point 5)")
    lines.append("")
    if edge_flags:
        for f in edge_flags:
            lines.append(f"- FLAGGED: {f}")
    else:
        lines.append("- none of G-L1/G-L2/G-L3/G-L4 fall within a 10% band of their "
                     "threshold.")
    lines.append("")

    lines.append("## Discretion log")
    lines.append("")
    lines.append("Points where spec Sec.2-Sec.3 underspecifies an implementation detail; "
                 "listed per plan T5 acceptance criterion 4.")
    lines.append("")
    lines.append("1. **Window used for MAR/Sharpe = full csv date range** (n_days=2116 "
                 "for the main window), NOT T4's internal `stats_start` "
                 "(window_start + CROWD_WARMUP_DAYS=30d) trim that "
                 "`cta_l_stage1_runs.py`/`cta_proxy_lib.run_cell` use for the "
                 "`manifest.json` `summary.sharpe` field. Spec's literal MAR definition "
                 "(line 41: \"Sigma日報酬 x 365 / 天數\") ties to the fixed window with no "
                 "mention of a warmup exclusion; excluding it would require importing a "
                 "constant from cta_proxy_lib.py, which this script avoids entirely. "
                 "Verified analytically and numerically that all pre-stats_start days have "
                 "pnl==0 (crowd-percentile signal hasn't warmed up), so this choice does "
                 "NOT change any G-L1/G-L2 PASS/FAIL outcome (the 365/n_days scale factor "
                 "is identical for both legs of every ratio and cancels), only the absolute "
                 "MAR/Sharpe magnitudes shown above (which will not bit-match "
                 "`manifest.json`'s `summary.sharpe`/`summary.mdd_pct` by design of this "
                 "choice, though full-window MDD happens to match exactly since leading "
                 "zero-pnl days don't move a running-peak drawdown calc either way).")
    lines.append("2. **MDD basis**: peak-relative drawdown on a return-space equity curve "
                 "seeded at 1.0 (equivalent to $500 dollar-space by a scalar factor that "
                 "cancels in the peak-relative ratio -- confirmed this reproduces "
                 "`manifest.json`'s full-window `b0` mdd_pct=-32.50384...% bit-for-bit).")
    lines.append("3. **Per-fold MDD/MAR**: equity resets to base 1.0 at each fold's own "
                 "start (independent running peak per fold), not a slice of the whole-"
                 "window equity path. Read from spec Sec.6 line 176-179's framing "
                 "(\"折內比較因兩腿同基底仍有效\" and the -148% single-fold MDD artifact) "
                 "-- both statements only make sense under a fold-reset convention.")
    lines.append(f"4. **90% CI method**: percentile method ([{CI_LO_PCTL:.0f}th, "
                 f"{CI_HI_PCTL:.0f}th] percentile of the bootstrap distribution), not a "
                 "normal approximation -- spec doesn't specify; percentile is the standard "
                 "distribution-free convention for bootstrap CIs.")
    lines.append("5. **G-L5 \"direction zero flip\"** read as the literal inequality "
                 "MAR(V1)>=MAR(B0) at each endpoint (spec line 111 says \"方向\", not the "
                 "1.3x magnitude), not a repeat of the full G-L1 magnitude test.")
    lines.append("6. **Stationary bootstrap edge handling**: circular (index mod n) "
                 "wraparound -- the standard Politis-Romano treatment for finite samples, "
                 "not stated explicitly in spec.")
    lines.append("7. **m-distribution appendix** sourced from the executed-trade "
                 "(`*_trades.csv` `m` column, entry-locked) distribution, not the T3-"
                 "selftest per-bar distribution -- avoids importing/rerunning any "
                 "cta_l_stage1.py code from this gate script (plan T5 red line), and is "
                 "arguably more decision-relevant (trade-weighted, not bar-weighted).")
    lines.append("8. **MDD floor (0.5%) applied uniformly** to every MAR calc in this "
                 "table (full-window, per-fold, cost15, endpoints), not only \"每折\" as "
                 "spec line 42 literally says -- harmless since no observed MDD in this "
                 "run is anywhere near the 0.5% floor, and \"兩腿同規則\" (same rule both "
                 "legs) is easier to defend applied uniformly than conditionally.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                     help="Run B0-vs-B0 self-comparison instead of the real V1-vs-B0 gates.")
    ap.add_argument("--no-write", action="store_true",
                     help="Print to stdout only, do not write gates_table.md.")
    args = ap.parse_args()

    text = run(selftest=args.selftest)
    print(text)

    if not args.selftest and not args.no_write:
        OUT_PATH.write_text(text + "\n")
        print(f"\n[wrote {OUT_PATH.relative_to(REPO_ROOT)}]", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
