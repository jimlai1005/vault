#!/usr/bin/env python3
"""Sub-project L Stage 2, plan T4/T6 -- generalized G-A gate score sheet.

Computes protocol (docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md)
Sec.7 G-A.1..G-A.4 for a given ablation (A1: event-calendar de-risking, A2:
signal-strength scaling, ...) vs its current baseline, plus Sec.9.5
reporting-only items, purely by reading the daily-pnl / trade-ledger csvs
already written to data/cache/cta_l/ (B0/B1 baseline, read-only) and
data/cache/cta_l2/ (variant runs, read-only per ablation). This script
performs NO simulation of any kind and does NOT import cta_l_stage2.py,
cta_l_stage1.py, cta_proxy_lib.py, or any other engine/simulation module --
only pandas/numpy/json reads, plus `hlvault.metrics.deflated_sharpe` (a pure
calculation function the task brief explicitly allow-lists).

This was originally a single-ablation (A1) script; T6 generalized it to take
`--ablation`/`--n-trials` so the same statistical machinery (MDD/MAR/Sharpe/
DSR/bootstrap formulas, gate thresholds, fold boundaries -- all frozen by the
protocol) can be reused for A2 without copy-pasting or risking a silent
formula drift between ablations. The generalization touches ONLY: which
files are read (a1* vs a2* vs ...), the DSR N constant, the two
reporting-only sensitivity-group file suffixes/labels, which trades-csv
column holds the ablation's own entry-locked factor (distinct from m_total
for A2's continuous ramp; none for A1 whose mechanism is a post-entry
resize, so its `m` column already **is** m_total), and cosmetic text
(ablation label, "judge next ablation" pointer, protocol section reference
for the sensitivity appendix). No statistical formula, threshold, fold
boundary, or bootstrap parameter was touched -- see ABLATION_CONFIG below,
which is the only new structural surface.

Usage:
    .venv/bin/python scripts/cta_l_stage2_gates.py --ablation a1           # A1
        writes data/cache/cta_l2/a1_gates.md and prints it to stdout
    .venv/bin/python scripts/cta_l_stage2_gates.py --ablation a2 \\
        --n-trials 14                                                      # A2
        writes data/cache/cta_l2/a2_gates.md and prints it to stdout
    ... --selftest      # variant:=baseline (V1-vs-V1) plumbing check for
        G-A.1..G-A.4 only; reporting-only appendix items (which depend on
        real variant artifacts) are skipped with an explicit note.
    ... --no-write       # print to stdout only, do not write the *_gates.md

Red lines (task brief): no .env* read/printed, no network, no writes under
data/cache/cta_l/, no modification of any existing file (in particular:
a1*.csv / a1_gates.md are read-only inputs once A1 is closed -- always pass
--no-write when re-running --ablation a1 for the regression check).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from hlvault.metrics import deflated_sharpe

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_L = REPO_ROOT / "data" / "cache" / "cta_l"        # baseline (B0/B1=V1), read-only
CACHE_L2 = REPO_ROOT / "data" / "cache" / "cta_l2"       # variant runs, read-only
PROTOCOL_PATH = "docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md"

BASE = 500.0
ANN_DAYS = 365.0
MDD_FLOOR = 0.005          # protocol Sec.2: "0.5% 下限統一套用所有窗"
DSR_THRESHOLD = 0.95       # protocol Sec.7 G-A.1
FOLD_MIN_PASS = 4          # protocol Sec.7 G-A.2: ">=4 折"

BOOT_BLOCK = 20            # protocol Sec.2: expected block 20d
BOOT_B = 10_000            # protocol Sec.2: B=10,000
BOOT_SEED = 42             # protocol Sec.2: numpy.random.default_rng(42)
CI_LO_PCTL, CI_HI_PCTL = 5.0, 95.0   # protocol Sec.2: [5th, 95th], linear interpolation

EDGE_BAND = 0.10           # protocol Sec.2: "±10% 帶內"

ANCHOR_RELTOL = 1e-9

# protocol Sec.1 numeric anchors (full precision, gate script must reproduce
# to rel-tol 1e-9 before emitting any gate table). Baseline-only -- identical
# for every ablation (B0/B1 do not change as ablations are judged).
ANCHORS = {
    "B0 full-window MAR": 0.108912676802,
    "B0 full-window MDD": -0.336189359482,
    "B0 full-window Sharpe": 0.306891680973,
    "B1 full-window MAR": 0.299355395590,
    "B1 full-window MDD": -0.152055268750,
    "B1 full-window Sharpe": 0.499956120997,
}
ANCHOR_TRADE_COUNT = 759   # protocol Sec.1: "B0/B1 trade 數（主窗）759/759"

FOLDS = [
    ("F1", "2020-09-14", "2021-12-31"),
    ("F2", "2022-01-01", "2022-12-31"),
    ("F3", "2023-01-01", "2023-12-31"),
    ("F4", "2024-01-01", "2024-12-31"),
    ("F5", "2025-01-01", "2025-12-31"),
    ("F6", "2026-01-01", "2026-06-30"),
]  # protocol Sec.2: "六折硬編"

ENDPOINTS = ("_ep30", "_ep60", "_ep90")  # protocol Sec.7 G-A.4

# ---------------------------------------------------------------------------
# Ablation config -- the ONLY per-ablation surface (T6 generalization).
# Everything else below is shared statistical machinery, unmodified from the
# A1-only script. protocol Sec.2 line 47-48: "N 累計：A1 用 N=11、A2 用
# N=14、A3 用 N=17". Baseline is always the B1 (v1*.csv) files in this
# script's current usage: A1 failed G-A.1 and did not merge (see
# data/cache/cta_l2/a1_gates.md / manifest_a1.json), so A2's baseline is
# also B1 (manifest_a2.json "a1_status": "NOT MERGED ... A2 baseline = B1")
# -- baseline_path() below intentionally stays hardcoded to v1*.csv; it is
# NOT a per-ablation config knob because judging A3 (if reached) against a
# post-merge baseline would need a real code change and re-review, not a
# silent config flip.
# ---------------------------------------------------------------------------
ABLATION_CONFIG: dict[str, dict] = {
    "a1": {
        "n_trials_default": 11,
        "next_label": "A2",
        "sens_section": "Sec.4",
        "sens_groups": [
            ("noresize (禁縮舊倉)", "_sens_noresize"),
            ("w48 (窗 [T-48h,T+6h])", "_sens_w48"),
        ],
        "factor_col": None,     # A1's mechanism is a post-entry resize, not
                                 # an entry-time multiplier -- its `m` column
                                 # (always reported, see m_total block below)
                                 # already *is* the full m_total story.
        "factor_label": None,
        "edge_a1_suffix": True,  # protocol Sec.9 point 6 is A1-specific.
    },
    "a2": {
        "n_trials_default": 14,
        "next_label": "A3",
        "sens_section": "Sec.5",
        "sens_groups": [
            ("p95 (ramp 上端 97→95)", "_sens_p95"),
            ("p99 (ramp 上端 97→99)", "_sens_p99"),
        ],
        "factor_col": "m_a2",   # a2_trades.csv's own entry-locked ramp
                                 # multiplier, distinct from `m`=m_total.
        "factor_label": "m_A2",
        "edge_a1_suffix": False,
    },
    "a3": {
        "n_trials_default": 17,
        "next_label": "Stage 2 verdict",  # A1/A2 both failed to merge (see
                                 # a1_gates.md/a2_gates.md), so A3 vs B1 is
                                 # the last of the three pre-registered
                                 # ablations (protocol Sec.10) -- there is no
                                 # A4 to hand off to next.
        "sens_section": "Sec.6",
        "sens_groups": [
            ("sma100 (SMA 200d→100d)", "_sens_sma100"),
            ("sma300 (SMA 200d→300d)", "_sens_sma300"),
        ],
        "factor_col": "m_a3",   # a3_trades.csv's own entry-locked regime
                                 # multiplier, distinct from `m`=m_total.
        "factor_label": "m_A3",
        "edge_a1_suffix": False,
    },
}


# ---------------------------------------------------------------------------
# CSV loading -- the ONLY data source, csv/json reads only.
# ---------------------------------------------------------------------------

def load_returns(path: Path) -> pd.Series:
    """Load a daily-pnl csv -> daily fraction-of-$500 return series indexed
    by UTC calendar date. float_precision='round_trip' per T3's recorded
    1-ULP fast-parser discrepancy."""
    df = pd.read_csv(path, parse_dates=["date"], float_precision="round_trip")
    df = df.set_index("date").sort_index()
    return (df["pnl"] / BASE).rename(path.stem)


def load_trades(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["entry_ts", "exit_ts"],
                        float_precision="round_trip")


def assert_aligned(a: pd.Series, b: pd.Series, ctx: str) -> None:
    """protocol Sec.2: 'd_t 計算前 assert 兩 csv 的 DatetimeIndex 完全相等
    ... 禁止 align/reindex'."""
    if not a.index.equals(b.index):
        diff = a.index.symmetric_difference(b.index)
        raise ValueError(
            f"[{ctx}] DatetimeIndex mismatch between '{a.name}' and '{b.name}': "
            f"{len(a)} vs {len(b)} rows, first diffs: {diff[:5].tolist()}"
        )


# ---------------------------------------------------------------------------
# Core statistics (protocol Sec.1 MDD, Sec.2 MAR/Sharpe/DSR/d_t) -- frozen,
# ablation-independent.
# ---------------------------------------------------------------------------

def mdd_frac(returns: np.ndarray) -> float:
    """protocol Sec.1: fixed-basis MDD. eq_t = 1 + cumsum(r); MDD =
    min_t[eq_t - running_max(eq)_t]. NOT peak-relative ratio -- verified
    against the Sec.1 numeric anchors to reproduce them at rel-tol 1e-9
    (additive form only)."""
    if len(returns) == 0:
        return 0.0
    eq = 1.0 + np.cumsum(returns)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    return float(dd.min())


def ann_return_frac(returns: np.ndarray) -> float:
    """protocol Sec.2: ann = sum(r) * 365 / n_days (non-compounding)."""
    n = len(returns)
    if n == 0:
        return 0.0
    return float(np.sum(returns) * ANN_DAYS / n)


def mar(returns: np.ndarray) -> float:
    """protocol Sec.2: MAR = ann / max(|MDD|, 0.005), floor applied
    uniformly to every window (full/fold/cost15/endpoint)."""
    denom = max(abs(mdd_frac(returns)), MDD_FLOOR)
    return ann_return_frac(returns) / denom


def sharpe_frac(returns: np.ndarray) -> float:
    """protocol Sec.2: Sharpe = mean(r)/std(r,ddof=1) * sqrt(365). Returns
    NaN (not a crash, not a silent 0) when the series has zero variance --
    the degenerate case is surfaced explicitly by the gate wrappers below,
    per T4 acceptance criterion 2."""
    n = len(returns)
    if n < 2:
        return float("nan")
    sd = np.std(returns, ddof=1)
    if sd <= 0:
        return float("nan")
    return float(np.mean(returns) / sd * np.sqrt(ANN_DAYS))


def rel_err(val: float, ref: float) -> float:
    if ref == 0:
        return abs(val)
    return abs(val - ref) / abs(ref)


# ---------------------------------------------------------------------------
# Gate-specific degenerate-aware wrappers -- frozen, ablation-independent
# (n_trials is already a parameter, not a hardcoded constant).
# ---------------------------------------------------------------------------

def dsr_gate(d_t: pd.Series, n_trials: int) -> tuple[float, bool]:
    """G-A.1. DSR formula is the sole import from hlvault.metrics (task
    brief: 'DSR：唯一公式 src/hlvault/metrics.py:35 的解析版'), used exactly
    as written (including its internal ANN=252 annualization -- that is
    part of 'the' formula per the brief, not a discretion point for this
    script to alter). Explicit degenerate guard: an exact-zero-variance d_t
    makes the underlying Sharpe/skew/kurt inputs degenerate (a d_t series
    identical to itself under --selftest), so DSR is reported as
    'degenerate, gate vacuous' rather than as a numeric value that would
    otherwise still (non-crashingly) come out of metrics.deflated_sharpe
    for an all-zero series -- see discretion log item 1."""
    std = float(d_t.to_numpy(dtype=float).std(ddof=1))
    if std == 0.0:
        return float("nan"), True
    return float(deflated_sharpe(d_t, n_trials=n_trials)), False


def sharpe_dt_gate(d_t: pd.Series) -> tuple[float, bool]:
    """G-A.3 / G-A.4 / descriptive Sharpe(d_t). Same degenerate convention
    as dsr_gate (discretion log item 2)."""
    val = sharpe_frac(d_t.to_numpy(dtype=float))
    return val, (val != val)  # NaN check


# ---------------------------------------------------------------------------
# Paired stationary block bootstrap (protocol Sec.2, reporting-only) --
# frozen, ablation-independent.
# ---------------------------------------------------------------------------

def stationary_bootstrap_indices(n: int, B: int, expected_block: int,
                                  seed: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap index generator, vectorized over
    the B replicate dimension, circular (mod n) wraparound (protocol Sec.2:
    'circular wraparound (Politis-Romano)'). Deterministic given
    (n, B, expected_block, seed) -- a numpy Generator carries no external
    state, so re-instantiating it with the same seed reproduces the same
    draws bit-for-bit (verified under acceptance criterion 4)."""
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


def bootstrap_delta_sharpe(v: pd.Series, b: pd.Series, B: int,
                            expected_block: int, seed: int) -> dict:
    n = len(v)
    indices = stationary_bootstrap_indices(n, B, expected_block, seed)
    rv = v.to_numpy(dtype=float)[indices]
    rb = b.to_numpy(dtype=float)[indices]
    mean_v, mean_b = rv.mean(axis=1), rb.mean(axis=1)
    std_v = rv.std(axis=1, ddof=1)
    std_b = rb.std(axis=1, ddof=1)
    sharpe_v = np.where(std_v > 0, mean_v / std_v * np.sqrt(ANN_DAYS), 0.0)
    sharpe_b = np.where(std_b > 0, mean_b / std_b * np.sqrt(ANN_DAYS), 0.0)
    delta = sharpe_v - sharpe_b
    lo, hi = np.percentile(delta, [CI_LO_PCTL, CI_HI_PCTL])
    return {
        "delta": delta,
        "ci_lo": float(lo),
        "ci_hi": float(hi),
        "point_v": sharpe_frac(v.to_numpy(dtype=float)),
        "point_b": sharpe_frac(b.to_numpy(dtype=float)),
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fnum(x: float, decimals: int = 12) -> str:
    if x != x:  # NaN
        return "NaN"
    return f"{x:.{decimals}f}"


def pf(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def deg_or(ok: bool, degenerate: bool) -> str:
    return "N/A (degenerate, gates vacuous)" if degenerate else pf(ok)


# ---------------------------------------------------------------------------
# Anchor verification (task brief: must run first, abort on any failure) --
# frozen, ablation-independent (B0/B1 baseline only).
# ---------------------------------------------------------------------------

def verify_anchors() -> tuple[bool, list[str]]:
    lines: list[str] = []
    ok_all = True

    b0 = load_returns(CACHE_L / "b0.csv")
    b1 = load_returns(CACHE_L / "v1.csv")
    assert_aligned(b0, b1, "anchor check: B0 vs B1(V1)")

    computed = {
        "B0 full-window MAR": mar(b0.to_numpy()),
        "B0 full-window MDD": mdd_frac(b0.to_numpy()),
        "B0 full-window Sharpe": sharpe_frac(b0.to_numpy()),
        "B1 full-window MAR": mar(b1.to_numpy()),
        "B1 full-window MDD": mdd_frac(b1.to_numpy()),
        "B1 full-window Sharpe": sharpe_frac(b1.to_numpy()),
    }
    for name, ref in ANCHORS.items():
        val = computed[name]
        err = rel_err(val, ref)
        ok = err < ANCHOR_RELTOL
        ok_all &= ok
        lines.append(f"- {name}: computed={fnum(val)} anchor={fnum(ref)} "
                      f"rel_err={err:.3e} tol=1e-9 -> {'OK' if ok else 'FAIL'}")

    t_b0 = len(load_trades(CACHE_L / "b0_trades.csv"))
    t_b1 = len(load_trades(CACHE_L / "v1_trades.csv"))
    trade_ok = (t_b0 == ANCHOR_TRADE_COUNT) and (t_b1 == ANCHOR_TRADE_COUNT)
    ok_all &= trade_ok
    lines.append(f"- B0/B1 trade count: computed={t_b0}/{t_b1} "
                  f"anchor={ANCHOR_TRADE_COUNT}/{ANCHOR_TRADE_COUNT} -> "
                  f"{'OK' if trade_ok else 'FAIL'}")

    return ok_all, lines


# ---------------------------------------------------------------------------
# Main gate computation
# ---------------------------------------------------------------------------

def variant_path(ablation: str, suffix: str, selftest: bool) -> Path:
    return (CACHE_L / f"v1{suffix}.csv") if selftest else (CACHE_L2 / f"{ablation}{suffix}.csv")


def baseline_path(suffix: str) -> Path:
    return CACHE_L / f"v1{suffix}.csv"


def load_pair(ablation: str, suffix: str, selftest: bool, ctx: str) -> tuple[pd.Series, pd.Series]:
    v = load_returns(variant_path(ablation, suffix, selftest))
    b = load_returns(baseline_path(suffix))
    assert_aligned(v, b, ctx)
    return v, b


def run(ablation: str, n_trials: int, selftest: bool) -> str:
    cfg = ABLATION_CONFIG[ablation]
    ablation_label = ablation.upper()
    next_label = cfg["next_label"]

    lines: list[str] = []
    mode_label = "SELFTEST (variant:=baseline, V1 vs V1)" if selftest else f"REAL ({ablation_label} vs B1/V1)"
    lines.append(f"# CTA Sub-project L Stage 2 -- {ablation_label} Gate Table [{mode_label}]")
    lines.append("")
    lines.append(f"Source: `{CACHE_L2.relative_to(REPO_ROOT)}/{ablation}*.csv` (variant, T-run "
                 f"output, read-only) vs `{CACHE_L.relative_to(REPO_ROOT)}/v1*.csv` "
                 f"(B1 baseline, read-only). Gate definitions: `{PROTOCOL_PATH}` Sec.7.")
    lines.append("")

    # ------------------------------------------------------------- Anchors
    anchors_ok, anchor_lines = verify_anchors()
    lines.append("## Sec.1 numeric-anchor reproduction (must pass before any gate is emitted)")
    lines.append("")
    lines.extend(anchor_lines)
    lines.append("")
    if not anchors_ok:
        lines.append("**ABORT: one or more numeric anchors failed to reproduce at rel-tol "
                      "1e-9. No gate table emitted.**")
        return "\n".join(lines)
    lines.append("All six numeric anchors + trade count reproduced at rel-tol < 1e-9. "
                 "Proceeding to gate table.")
    lines.append("")

    # ------------------------------------------------------- main-window d_t
    v_main, b_main = load_pair(ablation, "", selftest, "main window: variant vs baseline")
    d_t_main = (v_main - b_main).rename("d_t_main")

    # ---------------------------------------------------------------- G-A.1
    dsr_val, dsr_degenerate = dsr_gate(d_t_main, n_trials)
    ga1_pass = (not dsr_degenerate) and (dsr_val >= DSR_THRESHOLD)
    lines.append(f"## G-A.1 -- DSR(d_t), N={n_trials} (protocol Sec.7 line 139)")
    lines.append("")
    lines.append(f"- n_days = {len(d_t_main)}, std(d_t) = "
                 f"{fnum(float(d_t_main.to_numpy().std(ddof=1)))}")
    lines.append(f"- DSR(d_t; N={n_trials}) = {fnum(dsr_val)} "
                 f"(via `src/hlvault/metrics.py:35 deflated_sharpe`, unmodified)")
    lines.append(f"- threshold: DSR >= {DSR_THRESHOLD}")
    lines.append(f"- **G-A.1: {deg_or(ga1_pass, dsr_degenerate)}**")
    lines.append("")

    # ---------------------------------------------------------------- G-A.2
    lines.append("## G-A.2 -- 6-fold delta-MAR (protocol Sec.2 fold defs, Sec.7 line 140)")
    lines.append("")
    lines.append("Per-fold equity reset to 1.0 at the fold's own start (fixed-basis "
                 "MDD within the fold, protocol Sec.2).")
    lines.append("")
    lines.append("| Fold | Window | n_days | MAR(baseline) | MAR(variant) | delta-MAR | >=0 |")
    lines.append("|---|---|---|---|---|---|---|")
    fold_pass = 0
    fold_rows = []
    for fname, fs, fe in FOLDS:
        rv = v_main.loc[fs:fe].to_numpy()
        rb = b_main.loc[fs:fe].to_numpy()
        mv, mb = mar(rv), mar(rb)
        delta = mv - mb
        ok = delta >= 0.0
        fold_pass += int(ok)
        fold_rows.append((fname, fs, fe, len(rv), mb, mv, delta, ok))
        lines.append(f"| {fname} | {fs}..{fe} | {len(rv)} | {fnum(mb)} | {fnum(mv)} | "
                     f"{fnum(delta)} | {pf(ok)} |")
    ga2_pass = fold_pass >= FOLD_MIN_PASS
    lines.append("")
    lines.append(f"Folds with delta-MAR>=0: **{fold_pass}/6** (threshold >={FOLD_MIN_PASS}). "
                 f"**G-A.2: {pf(ga2_pass)}**")
    lines.append("")

    # ---------------------------------------------------------------- G-A.3
    v_c15, b_c15 = load_pair(ablation, "_cost15", selftest, "cost15: variant vs baseline")
    d_t_c15 = (v_c15 - b_c15).rename("d_t_cost15")
    sharpe_c15, c15_degenerate = sharpe_dt_gate(d_t_c15)
    ga3_pass = (not c15_degenerate) and (sharpe_c15 > 0.0)
    lines.append("## G-A.3 -- cost x1.5, Sharpe(d_t) > 0 (protocol Sec.7 line 141)")
    lines.append("")
    lines.append(f"- n_days = {len(d_t_c15)}")
    lines.append(f"- Sharpe(d_t, cost15) = {fnum(sharpe_c15)}")
    lines.append(f"- threshold: Sharpe(d_t) > 0")
    lines.append(f"- **G-A.3: {deg_or(ga3_pass, c15_degenerate)}**")
    lines.append("")

    # ---------------------------------------------------------------- G-A.4
    lines.append("## G-A.4 -- 3 endpoints, Sharpe(d_t) > 0 absolute (protocol Sec.7 line 142)")
    lines.append("")
    lines.append("| Endpoint | n_days | Sharpe(d_t) | >0 |")
    lines.append("|---|---|---|---|")
    ep_results = {}
    ga4_pass = True
    for ep in ENDPOINTS:
        v_ep, b_ep = load_pair(ablation, ep, selftest, f"{ep}: variant vs baseline")
        d_t_ep = (v_ep - b_ep).rename(f"d_t{ep}")
        s_val, deg = sharpe_dt_gate(d_t_ep)
        ok = (not deg) and (s_val > 0.0)
        ga4_pass = ga4_pass and ok
        ep_results[ep] = (s_val, deg, ok, len(d_t_ep))
        lines.append(f"| {ep.lstrip('_')} | {len(d_t_ep)} | {fnum(s_val)} | "
                     f"{deg_or(ok, deg)} |")
    sharpe_dt_main, main_degenerate = sharpe_dt_gate(d_t_main)
    lines.append("")
    lines.append(f"Main-window Sharpe(d_t) = {fnum(sharpe_dt_main)} "
                 f"(descriptive only, not part of G-A.4's judgment per protocol Sec.7 "
                 f"line 142: '主窗 Sharpe(d_t) 僅作敘述，不參與判準').")
    lines.append(f"**G-A.4: {pf(ga4_pass)}**")
    lines.append("")

    # ---------------------------------------------------------------- Summary
    gates = [("G-A.1", ga1_pass, dsr_degenerate), ("G-A.2", ga2_pass, False),
             ("G-A.3", ga3_pass, c15_degenerate), ("G-A.4", ga4_pass, False)]
    lines.append("## Summary")
    lines.append("")
    lines.append("| Gate | Result |")
    lines.append("|---|---|")
    for gname, ok, deg in gates:
        lines.append(f"| {gname} | {deg_or(ok, deg)} |")
    n_pass = sum(1 for _, ok, deg in gates if ok and not deg)
    any_degenerate = any(deg for _, _, deg in gates)
    lines.append("")
    if any_degenerate:
        lines.append(f"**{n_pass}/4 gates PASS, >=1 gate degenerate/vacuous.** Per protocol "
                     f"Sec.7: all 4 PASS => {ablation_label} merges into baseline; any 1 "
                     f"FAIL/vacuous => {ablation_label} closes (no retry), continue to "
                     f"{next_label}. Verdict narrative is a "
                     f"downstream task's responsibility, not this script's.")
    else:
        all_pass = n_pass == 4
        lines.append(f"**{n_pass}/4 gates PASS.** Per protocol Sec.7: "
                     f"{'all 4 PASS => ' + ablation_label + ' merges into baseline, judge ' + next_label + ' next.' if all_pass else 'any 1 FAIL => ' + ablation_label + ' closes (no retry), continue to ' + next_label + '.'}")
    lines.append("")

    # ------------------------------------------------- Sec.9.5 reporting items
    lines.append("## Reporting items (protocol Sec.9.5, not gates)")
    lines.append("")

    nonzero_mask = d_t_main.to_numpy() != 0.0
    n_nonzero = int(nonzero_mask.sum())
    pct_nonzero = n_nonzero / len(d_t_main) * 100.0
    lines.append("### d_t (main window) non-zero days (Sec.9.5 point 5)")
    lines.append("")
    lines.append(f"- non-zero days: {n_nonzero} / {len(d_t_main)} ({fnum(pct_nonzero, 4)}%)")
    lines.append("")

    if selftest:
        sens_files = " / ".join(f"`{ablation}{suffix}.csv`" for _, suffix in cfg["sens_groups"])
        lines.append("### m_total distribution, sensitivity groups, bootstrap CI")
        lines.append("")
        lines.append(f"Skipped under --selftest: these read `{ablation}_trades.csv` / "
                     f"{sens_files}, which are real-{ablation_label}-run "
                     "artifacts with no baseline-only analogue meaningful to substitute.")
        lines.append("")
    else:
        trades = load_trades(CACHE_L2 / f"{ablation}_trades.csv")
        m = trades["m"].dropna()
        lines.append(f"### m_total distribution ({ablation}_trades.csv `m` column, entry-locked)")
        lines.append("")
        lines.append(f"- n = {len(m)}")
        lines.append(f"- min={fnum(float(m.min()))} median={fnum(float(m.median()))} "
                     f"mean={fnum(float(m.mean()))} max={fnum(float(m.max()))}")
        at_1 = float((m >= 1.0 - 1e-12).mean() * 100.0) if len(m) else float("nan")
        lines.append(f"- % at m==1.0 (uncapped): {fnum(at_1, 4)}%")
        lines.append("")

        factor_col = cfg["factor_col"]
        if factor_col is not None and factor_col != "m":
            fac = trades[factor_col].dropna()
            factor_label = cfg["factor_label"]
            lines.append(f"### {factor_label} distribution ({ablation}_trades.csv "
                         f"`{factor_col}` column, entry-locked)")
            lines.append("")
            lines.append(f"- n = {len(fac)}")
            lines.append(f"- min={fnum(float(fac.min()))} median={fnum(float(fac.median()))} "
                         f"mean={fnum(float(fac.mean()))} max={fnum(float(fac.max()))}")
            at_1_fac = float((fac >= 1.0 - 1e-12).mean() * 100.0) if len(fac) else float("nan")
            lines.append(f"- % at {factor_label}==1.0 (uncapped): {fnum(at_1_fac, 4)}%")
            lines.append("")

        lines.append(f"### Sensitivity groups ({cfg['sens_section']} point at bottom): "
                     "full-window MAR and Sharpe(d_t), variant vs baseline main window")
        lines.append("")
        lines.append("| Sensitivity | file | n_days | MAR(variant) | Sharpe(d_t) |")
        lines.append("|---|---|---|---|---|")
        for name, suffix in cfg["sens_groups"]:
            path = CACHE_L2 / f"{ablation}{suffix}.csv"
            v_s = load_returns(path)
            assert_aligned(v_s, b_main, f"{name}: sensitivity vs baseline main")
            mv_s = mar(v_s.to_numpy())
            d_t_s = (v_s - b_main).rename(f"d_t{suffix}")
            s_val_s, deg_s = sharpe_dt_gate(d_t_s)
            lines.append(f"| {name} | {ablation}{suffix}.csv | {len(v_s)} | {fnum(mv_s)} | "
                         f"{fnum(s_val_s) if not deg_s else 'degenerate'} |")
        lines.append("")

        lines.append("### Paired delta-Sharpe stationary block bootstrap (main window, "
                     "reporting only, protocol Sec.2)")
        lines.append("")
        lines.append(f"Method: joint resample of aligned (r_variant,t, r_baseline,t) pairs, "
                     f"stationary bootstrap, expected block={BOOT_BLOCK}d "
                     f"(Geometric p=1/{BOOT_BLOCK}), B={BOOT_B}, "
                     f"seed=numpy.random.default_rng({BOOT_SEED}), circular wraparound "
                     f"(Politis-Romano), CI=[{CI_LO_PCTL:.0f}th, {CI_HI_PCTL:.0f}th] "
                     f"percentile (numpy linear interpolation).")
        lines.append("")
        boot = bootstrap_delta_sharpe(v_main, b_main, BOOT_B, BOOT_BLOCK, BOOT_SEED)
        point_delta = boot["point_v"] - boot["point_b"]
        lines.append(f"- Sharpe(baseline), point estimate: {fnum(boot['point_b'])}")
        lines.append(f"- Sharpe(variant), point estimate: {fnum(boot['point_v'])}")
        lines.append(f"- delta-Sharpe, point estimate: {fnum(point_delta)}")
        lines.append(f"- delta-Sharpe {CI_LO_PCTL:.0f}-{CI_HI_PCTL:.0f}% CI: "
                     f"[{fnum(boot['ci_lo'])}, {fnum(boot['ci_hi'])}]")
        lines.append("")

    # ------------------------------------------------- Honesty-clause auto-flags
    lines.append("## Honesty-clause auto-flags (protocol Sec.9)")
    lines.append("")
    flags: list[str] = []
    if (not dsr_degenerate) and ga1_pass:
        if abs(dsr_val - DSR_THRESHOLD) / DSR_THRESHOLD <= EDGE_BAND and pct_nonzero < 5.0:
            flags.append(f"Sec.9.5 point 5: G-A.1 DSR={fnum(dsr_val,6)} passes within a 10% "
                         f"band above the {DSR_THRESHOLD} threshold AND d_t non-zero days "
                         f"({fnum(pct_nonzero,4)}%) < 5% -- DSR's optimistic-direction bias "
                         f"(skew/kurt instability on a near-degenerate series, iid violation "
                         f"from entry-locking) must be flagged and the PASS described as "
                         f"non-robust, not a clean pass.")
    if fold_pass == FOLD_MIN_PASS:
        edge_suffix = (" per Sec.9.6 (A1's G-A.2 is expected to be near-coinflip)."
                       if cfg["edge_a1_suffix"] else ".")
        flags.append(f"protocol Sec.2 edge-band clause: G-A.2 fold count is exactly "
                     f"{FOLD_MIN_PASS}/6, the threshold itself -- must not be described as "
                     f"'robust'{edge_suffix}")
    if flags:
        for f in flags:
            lines.append(f"- FLAGGED: {f}")
    else:
        lines.append("- none triggered.")
    lines.append("")

    # ------------------------------------------------- Discretion log
    lines.append("## Discretion log (task brief acceptance criterion 5)")
    lines.append("")
    lines.append("Protocol Sec.1-Sec.9 pins down nearly everything explicitly; the "
                 "residual discretion points found while implementing this script are:")
    lines.append("")
    lines.append("1. **DSR degenerate-series threshold**: protocol Sec.9.5 point 5 "
                 "discusses DSR's optimistic bias on near-degenerate d_t (sparse non-zero "
                 "days) but does not define an exact 'undefined' cutoff. This script treats "
                 "`std(d_t, ddof=1) == 0.0` (exact) as the degenerate trigger and reports "
                 "'N/A (degenerate, gates vacuous)' instead of a numeric DSR -- note that "
                 "`hlvault.metrics.deflated_sharpe` itself does NOT crash or return NaN on "
                 "an all-zero pandas Series (pandas `.skew()`/`.kurt()` return 0.0, not NaN, "
                 "for a constant series with n>=3), so this guard is this script's own "
                 "addition on top of the imported formula, applied conservatively rather "
                 "than trusting a DSR value computed on a mathematically degenerate input.")
    lines.append("2. **Same degenerate guard applied to G-A.3/G-A.4** (Sharpe(d_t) with "
                 "zero-variance d_t -> NaN, reported as 'N/A (degenerate)') for consistency "
                 "with G-A.1, though protocol Sec.9.5 only calls this out explicitly for "
                 "DSR.")
    lines.append("3. **Stationary bootstrap block-generation mechanics** (reporting-only, "
                 "not a gate): protocol Sec.2 specifies 'expected block 20d "
                 "(Geometric p=1/20) ... circular wraparound (Politis-Romano)' but not the "
                 "exact per-step algorithm. Implemented as a Bernoulli block-continuation "
                 "walk (continue previous index+1 w.p. 1-1/20, else jump to a fresh uniform "
                 "start), vectorized over B replicates, matching the convention already used "
                 "in `scripts/cta_l_stage1_gates.py`'s G-L3 gate.")
    lines.append("4. **Edge-band (Sec.2 '±10%') applied only where a non-zero threshold "
                 "makes a relative percentage meaningful** (G-A.1's 0.95, and G-A.2's "
                 "explicit 4/6 special-case from Sec.9.6) -- not applied to G-A.3/G-A.4 "
                 "whose threshold is exactly 0 (a relative band around 0 is undefined).")
    lines.append("5. **m_total distribution / sensitivity-table formatting**: protocol "
                 "Sec.9.5 says these must be reported but does not specify exact summary "
                 "statistics; this script reports min/median/mean/max/%-at-cap for m, and "
                 "MAR(variant)+Sharpe(d_t) per sensitivity config, mirroring the Stage 1 "
                 "gate script's Appendix B/C format.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablation", choices=sorted(ABLATION_CONFIG), default="a1",
                     help="Which ablation to judge (a1, a2, ...).")
    ap.add_argument("--n-trials", type=int, default=None,
                     help="DSR cumulative trial count N. Defaults to the protocol Sec.2 "
                          "value for --ablation (a1=11, a2=14); if given explicitly it "
                          "must match that frozen value (no silent protocol override).")
    ap.add_argument("--selftest", action="store_true",
                     help="Run variant:=baseline (V1-vs-V1) self-comparison instead of "
                          "the real ablation-vs-baseline gates.")
    ap.add_argument("--no-write", action="store_true",
                     help="Print to stdout only, do not write <ablation>_gates.md.")
    args = ap.parse_args()

    cfg = ABLATION_CONFIG[args.ablation]
    n_trials = args.n_trials if args.n_trials is not None else cfg["n_trials_default"]
    if n_trials != cfg["n_trials_default"]:
        raise SystemExit(
            f"--n-trials {n_trials} does not match protocol Sec.2's frozen N="
            f"{cfg['n_trials_default']} for ablation {args.ablation!r}; refusing to run "
            f"with a silently non-protocol DSR N. Omit --n-trials to use the default."
        )

    text = run(ablation=args.ablation, n_trials=n_trials, selftest=args.selftest)
    print(text)

    if not args.selftest and not args.no_write:
        out_path = CACHE_L2 / f"{args.ablation}_gates.md"
        out_path.write_text(text + "\n")
        print(f"\n[wrote {out_path.relative_to(REPO_ROOT)}]", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
