"""Fresh-context blind verifier for sub-project L Stage 2, ablation A2.

Independently re-derives, from raw daily-pnl CSVs only, per
`docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md`:
  1. The six B0/B1 numeric anchors (§1) + B0/B1 trade counts.
  2. G-A.1  DSR(d_t; N=14) via src/hlvault/metrics.py:deflated_sharpe (unique formula, §2).
     d_t = r_a2 - r_v1 (A1 NOT merged per manifest_a2.json -> A2 baseline == B1 == v1.csv).
  3. G-A.2  six hard-coded folds (§2), count of folds with ΔMAR >= 0.
  4. G-A.3  cost x1.5 pair, Sharpe(d_t) > 0.
  5. G-A.4  three endpoint-truncation pairs (-30/-60/-90d), Sharpe(d_t) > 0 for all three.
  6. Reporting items: nonzero days of d_t, main-window Sharpe(d_t).

Adapted from scripts/cta_l_stage2_verify_a1.py (blind lineage, prior verifier's script;
not the implementer's). Deliberately does NOT read: a2_gates.md, a1_gates.md, any
cta_l_stage*_gates*.py script, or reports/. This script is the sole source of truth
for the independent re-derivation; its numbers are compared against the implementer's
a2_gates.md by the orchestrating (non-blind) session, not by this script.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hlvault.metrics import deflated_sharpe  # noqa: E402

CTA_L = ROOT / "data" / "cache" / "cta_l"
CTA_L2 = ROOT / "data" / "cache" / "cta_l2"
BASIS = 500.0
MDD_FLOOR = 0.005
ANN_DAYS = 365
N_TRIALS_A2 = 14

FOLDS = [
    ("F1", "2020-09-14", "2021-12-31"),
    ("F2", "2022-01-01", "2022-12-31"),
    ("F3", "2023-01-01", "2023-12-31"),
    ("F4", "2024-01-01", "2024-12-31"),
    ("F5", "2025-01-01", "2025-12-31"),
    ("F6", "2026-01-01", "2026-06-30"),
]


def load_daily(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, float_precision="round_trip", parse_dates=["date"])
    df = df.set_index("date")
    df["r"] = df["pnl"] / BASIS
    return df


def fixed_basis_mdd(r: pd.Series) -> float:
    eq = 1.0 + r.cumsum()
    peak = eq.cummax()
    return float((eq - peak).min())


def mar(r: pd.Series, n_days: int | None = None) -> tuple[float, float, float]:
    """Returns (MAR, ann, mdd)."""
    nd = n_days if n_days is not None else len(r)
    ann = float(r.sum()) * ANN_DAYS / nd
    mdd = fixed_basis_mdd(r)
    m = ann / max(abs(mdd), MDD_FLOOR)
    return m, ann, mdd


def sharpe365(r: pd.Series) -> float:
    sd = r.std(ddof=1)
    if sd == 0 or pd.isna(sd):
        return 0.0
    return float(r.mean() / sd * np.sqrt(ANN_DAYS))


def count_trades(path: Path) -> int:
    df = pd.read_csv(path, float_precision="round_trip")
    return len(df)


lines: list[str] = []


def emit(s: str = "") -> None:
    lines.append(s)


# ---------------------------------------------------------------------------
# 1. Six numeric anchors + trade counts
# ---------------------------------------------------------------------------
emit("# CTA L Stage 2 A2 — Fresh-context blind verification")
emit()
emit("## 1. Numeric anchors (relative tol 1e-9)")
emit()

ANCHORS = {
    "B0 MAR": "0.108912676802",
    "B0 MDD": "-0.336189359482",
    "B0 Sharpe": "0.306891680973",
    "B1 MAR": "0.299355395590",
    "B1 MDD": "-0.152055268750",
    "B1 Sharpe": "0.499956120997",
}

b0 = load_daily(CTA_L / "b0.csv")
v1 = load_daily(CTA_L / "v1.csv")

b0_n = len(b0)
v1_n = len(v1)
b0_mar, b0_ann, b0_mdd = mar(b0["r"], b0_n)
b0_sh = sharpe365(b0["r"])
v1_mar, v1_ann, v1_mdd = mar(v1["r"], v1_n)
v1_sh = sharpe365(v1["r"])

computed = {
    "B0 MAR": b0_mar,
    "B0 MDD": b0_mdd,
    "B0 Sharpe": b0_sh,
    "B1 MAR": v1_mar,
    "B1 MDD": v1_mdd,
    "B1 Sharpe": v1_sh,
}

anchor_ok = True
for k, anchor_str in ANCHORS.items():
    anchor_val = float(anchor_str)
    got = computed[k]
    rel_err = abs(got - anchor_val) / max(abs(anchor_val), 1e-15)
    ok = rel_err < 1e-9
    anchor_ok &= ok
    emit(f"- {k}: anchor={anchor_str}  computed={got:.15f}  rel_err={rel_err:.3e}  {'PASS' if ok else 'FAIL'}")

b0_trades_n = count_trades(CTA_L / "b0_trades.csv")
v1_trades_n = count_trades(CTA_L / "v1_trades.csv")
trades_ok = (b0_trades_n == 759) and (v1_trades_n == 759)
anchor_ok &= trades_ok
emit(f"- B0/B1 trade count: B0={b0_trades_n} V1={v1_trades_n} (expect 759/759)  {'PASS' if trades_ok else 'FAIL'}")
emit()
emit(f"n_days: B0={b0_n} V1={v1_n}  (n_days used as len(csv), incl. warmup zero-return rows, per §2)")
emit()

if not anchor_ok:
    emit("## ANCHOR MISMATCH — halting per instructions, gates NOT computed.")
    (CTA_L2 / "a2_gates_verify.md").write_text("\n".join(lines) + "\n")
    print("ANCHOR MISMATCH — see data/cache/cta_l2/a2_gates_verify.md")
    sys.exit(1)

emit("All six anchors + trade counts reproduced within 1e-9 relative tolerance.")
emit()
emit(
    "Baseline note: manifest_a2.json states A1 NOT MERGED (G-A.1 DSR FAIL) -> "
    "A2 baseline == B1 (v1.csv), not B1+A1. This verifier uses v1.csv as baseline "
    "throughout, consistent with that manifest note and with §1's B1 definition."
)
emit()

# ---------------------------------------------------------------------------
# 2. G-A.1 — DSR(d_t; N=14), main window, a2 vs v1
# ---------------------------------------------------------------------------
emit("## 2. G-A.1 — DSR(d_t; N=14), main window")
emit()

a2 = load_daily(CTA_L2 / "a2.csv")
assert a2.index.equals(v1.index), "a2.csv / v1.csv date index mismatch"
d_t_main = (a2["r"] - v1["r"]).copy()
d_t_main.index = a2.index  # keep DatetimeIndex; deflated_sharpe doesn't care about index type

dsr_val = deflated_sharpe(d_t_main, n_trials=N_TRIALS_A2)
ga1_pass = dsr_val >= 0.95
emit(f"- index equality assert: PASS (n={len(d_t_main)} days)")
emit(f"- DSR(d_t; N=14) = {dsr_val:.15f}")
emit(f"- threshold: >= 0.95")
emit(f"- G-A.1 = {'PASS' if ga1_pass else 'FAIL'}")
edge_band_lo, edge_band_hi = 0.95 * 0.9, 0.95 * 1.1
if edge_band_lo <= dsr_val <= edge_band_hi:
    emit(f"  (EDGE BAND: within ±10% of 0.95 threshold [{edge_band_lo:.4f}, {edge_band_hi:.4f}] — §2 邊緣帶條款 applies)")
emit()

# ---------------------------------------------------------------------------
# 3. G-A.2 — six folds, ΔMAR >= 0 count
# ---------------------------------------------------------------------------
emit("## 3. G-A.2 — six folds, ΔMAR = MAR_variant - MAR_baseline >= 0")
emit()

fold_pass_count = 0
fold_rows = []
for name, start, end in FOLDS:
    a2_fold = a2.loc[start:end, "r"]
    v1_fold = v1.loc[start:end, "r"]
    assert a2_fold.index.equals(v1_fold.index), f"{name} index mismatch"
    n_days_fold = len(a2_fold)
    mar_variant, ann_v, mdd_v = mar(a2_fold, n_days_fold)
    mar_baseline, ann_b, mdd_b = mar(v1_fold, n_days_fold)
    delta = mar_variant - mar_baseline
    passed = delta >= 0
    fold_pass_count += int(passed)
    fold_rows.append((name, start, end, n_days_fold, mar_variant, mar_baseline, delta, passed))
    emit(
        f"- {name} [{start}..{end}] n_days={n_days_fold}: "
        f"MAR_variant={mar_variant:.15f} MAR_baseline={mar_baseline:.15f} "
        f"ΔMAR={delta:.15f} {'PASS' if passed else 'FAIL'}"
    )

ga2_pass = fold_pass_count >= 4
emit()
emit(f"- folds passing: {fold_pass_count}/6 (threshold >=4)")
emit(f"- G-A.2 = {'PASS' if ga2_pass else 'FAIL'}")
if fold_pass_count == 4:
    emit("  (§2 邊緣帶條款: 恰為 4/6 視為邊緣，不得寫「穩健」)")
emit()

# ---------------------------------------------------------------------------
# 4. G-A.3 — cost x1.5, Sharpe(d_t) > 0
# ---------------------------------------------------------------------------
emit("## 4. G-A.3 — cost x1.5 pair (a2_cost15 vs v1_cost15), Sharpe(d_t) > 0")
emit()

a2_c15 = load_daily(CTA_L2 / "a2_cost15.csv")
v1_c15 = load_daily(CTA_L / "v1_cost15.csv")
assert a2_c15.index.equals(v1_c15.index), "a2_cost15.csv / v1_cost15.csv date index mismatch"
d_t_c15 = a2_c15["r"] - v1_c15["r"]
sharpe_c15 = sharpe365(d_t_c15)
ga3_pass = sharpe_c15 > 0
emit(f"- index equality assert: PASS (n={len(d_t_c15)} days)")
emit(f"- Sharpe(d_t_cost15) = {sharpe_c15:.15f}")
emit(f"- G-A.3 = {'PASS' if ga3_pass else 'FAIL'}")
emit()

# ---------------------------------------------------------------------------
# 5. G-A.4 — three endpoint pairs, Sharpe(d_t) > 0 for all three
# ---------------------------------------------------------------------------
emit("## 5. G-A.4 — endpoint truncation pairs, Sharpe(d_t) > 0 (all three)")
emit()

ep_results = {}
for suffix in ("ep30", "ep60", "ep90"):
    a2_ep = load_daily(CTA_L2 / f"a2_{suffix}.csv")
    v1_ep = load_daily(CTA_L / f"v1_{suffix}.csv")
    assert a2_ep.index.equals(v1_ep.index), f"a2_{suffix}.csv / v1_{suffix}.csv date index mismatch"
    d_t_ep = a2_ep["r"] - v1_ep["r"]
    sh = sharpe365(d_t_ep)
    ep_results[suffix] = sh
    emit(f"- {suffix}: index equality assert PASS (n={len(d_t_ep)} days), Sharpe(d_t) = {sh:.15f}  {'PASS' if sh > 0 else 'FAIL'}")

ga4_pass = all(v > 0 for v in ep_results.values())
emit(f"- G-A.4 = {'PASS' if ga4_pass else 'FAIL'} (absolute judgement; main-window Sharpe(d_t) below is descriptive only)")
emit()

# ---------------------------------------------------------------------------
# 6. Reporting items
# ---------------------------------------------------------------------------
emit("## 6. Reporting items (not gates)")
emit()
nonzero_days = int((d_t_main != 0).sum())
nonzero_pct = nonzero_days / len(d_t_main) * 100
sharpe_main_dt = sharpe365(d_t_main)
emit(f"- d_t (main window) nonzero days: {nonzero_days} / {len(d_t_main)} ({nonzero_pct:.4f}%)")
emit(f"- main-window Sharpe(d_t) = {sharpe_main_dt:.15f}")
if dsr_val >= 0.95 and (dsr_val <= 0.95 * 1.10) and nonzero_pct < 5:
    emit("  (§9-5 flag: G-A.1 恰壓線通過且 d_t 非零日 <5% — DSR 樂觀方向須標註並降級敘述)")
emit()

# ---------------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------------
emit("## 7. Summary")
emit()
emit(f"- G-A.1 (DSR>=0.95, N=14): {'PASS' if ga1_pass else 'FAIL'}  (DSR={dsr_val:.12f})")
emit(f"- G-A.2 (>=4/6 folds ΔMAR>=0): {'PASS' if ga2_pass else 'FAIL'}  ({fold_pass_count}/6)")
emit(f"- G-A.3 (cost15 Sharpe(d_t)>0): {'PASS' if ga3_pass else 'FAIL'}  ({sharpe_c15:.12f})")
emit(f"- G-A.4 (3 endpoints Sharpe(d_t)>0): {'PASS' if ga4_pass else 'FAIL'}  ({ep_results})")
emit()

emit("## 8. Discretion log (protocol-underspecified points, resolved per most literal reading)")
emit()
DISCRETION = [
    "Baseline for d_t = a2 - baseline: manifest_a2.json explicitly states A1 was NOT merged "
    "(G-A.1 DSR FAIL, per its a1_status field and baseline_note field), so A2's baseline is "
    "B1 (v1.csv) directly, not a hypothetical B1+A1 series. No B1+A1 csv exists in data/cache/ "
    "to compute against even if this reading were wrong, which corroborates it structurally.",
    "n_days for each window (full/fold/cost15/endpoint) taken as len(csv slice) for that "
    "window, i.e. actual calendar-day row count within the window/fold date range — per §2 "
    "'0.5% 下限統一套用所有窗' sentence implying the same MAR formula (incl. its n_days "
    "convention) applies uniformly to all window types.",
    "Fold n_days_fold used for both MAR_variant and MAR_baseline ann annualization (rather "
    "than a shared global n_days) — folds have identical row counts for a2 vs v1 by "
    "construction (index-equal), so this is not actually a live discretion point (both give "
    "identical n_days), but noted for completeness.",
    "General Sharpe (anchors, G-A.3, G-A.4, reporting) uses the §2 formula "
    "mean(r)/std(r,ddof=1)*sqrt(365), computed directly — NOT metrics.sharpe() (ANN=252). "
    "Verified against the B0/B1 anchor values (365-based formula reproduces the six anchors "
    "to <1e-9 relative error). metrics.py's sharpe()/ANN=252 is used only internally by "
    "deflated_sharpe() for G-A.1, per §2's 'DSR 唯一公式' clause pointing at that specific "
    "function as-is. Note: inside deflated_sharpe(), sr = sharpe(r,rf)/sqrt(ANN) algebraically "
    "reduces to mean(r)/std(r,ddof=1) regardless of the ANN constant used (252 vs 365 cancels "
    "out), so the ANN=252 hardcoding inside metrics.py does not actually create a live "
    "discrepancy for the DSR computation itself.",
    "deflated_sharpe(d_t_main, n_trials=14) called with the raw d_t Series (DatetimeIndex, "
    "pandas skew/kurt use only values not index) — no additional detrending or dropna applied; "
    "protocol does not call for either and d_t is expected sparse-but-fully-defined (no NaNs "
    "possible since d_t is a same-length pairwise subtraction of two zero-filled daily series).",
    "MDD floor 0.005 applied uniformly (full window, folds, cost15, endpoints) per explicit "
    "§2 text.",
    "Fold boundaries sliced via pandas .loc[start:end] on a DatetimeIndex (inclusive on both "
    "ends), matching the closed calendar-date ranges given in §2.",
    "sharpe365() returns 0.0 if std==0 (degenerate/constant series) — not triggered in this "
    "run (all six computed Sharpes and G-A.3/G-A.4 Sharpes have nonzero std), documented as "
    "defensive fallback only.",
    "a2_sens_p95.csv / a2_sens_p99.csv (ramp-upper sensitivity variants, §5) exist in "
    "data/cache/cta_l2/ but are NOT used by any G-A.1..4 gate per §7's explicit gate list "
    "(gates reference only main a2, a2_cost15, a2_ep30/60/90) and are 'only-reporting' per §5 "
    "'敏感度（只呈報）' — deliberately not read/used by this verifier for gate computation.",
]
for i, d in enumerate(DISCRETION, 1):
    emit(f"{i}. {d}")

(CTA_L2 / "a2_gates_verify.md").write_text("\n".join(lines) + "\n")
print("Wrote data/cache/cta_l2/a2_gates_verify.md")
print()
print(f"G-A.1={'PASS' if ga1_pass else 'FAIL'} (DSR={dsr_val:.12f})")
print(f"G-A.2={'PASS' if ga2_pass else 'FAIL'} ({fold_pass_count}/6)")
print(f"G-A.3={'PASS' if ga3_pass else 'FAIL'} (Sharpe={sharpe_c15:.12f})")
print(f"G-A.4={'PASS' if ga4_pass else 'FAIL'} ({ep_results})")
print(f"d_t nonzero days: {nonzero_days}/{len(d_t_main)} ({nonzero_pct:.4f}%)")
print(f"main-window Sharpe(d_t): {sharpe_main_dt:.12f}")
