#!/usr/bin/env python3
"""
Reconciliation script (diagnostic only -- NOT part of the repo).

Hypothesis under test: the ONLY root cause of the G-L2 verdict flip between
scripts/cta_l_stage1_gates.py (implementer) and scripts/cta_l_stage1_verify_t6.py
(blind verifier T6) is the MDD denominator convention:
  - implementer: dd = (eq - running_peak) / running_peak   [cta_l_stage1_gates.py:92-102, 186-192]
  - verifier:    dd = cr - running_peak(cr, floored at 0)  [cta_l_stage1_verify_t6.py:60-65]
    (== eq - running_peak_eq, i.e. NOT divided by anything -- "fixed base" = the
    constant initial equity of 1.0, since dividing by 1.0 is a no-op)

This script takes the IMPLEMENTER's pipeline verbatim (imports
scripts/cta_l_stage1_gates.py, reuses its load_returns/ann_return_frac/
sharpe_frac/g_l1_check/FOLDS/BASE/ANN_DAYS/MDD_FLOOR/G_L1_MULT unchanged) and
substitutes ONLY the MDD function with a byte-for-byte port of the verifier's
cumulative_mdd (cta_l_stage1_verify_t6.py:60-65), applied to the SAME
fraction-of-$500 return arrays the implementer's script already loads.
Nothing else in the implementer's pipeline is touched. Does not modify any
file under scripts/ or data/cache/cta_l/; writes only to this scratchpad dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path("/Users/jim/projects/vault")
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import cta_l_stage1_gates as gates  # noqa: E402  (implementer's script, imported read-only)

CACHE_DIR = gates.CACHE_DIR
BASE = gates.BASE
ANN_DAYS = gates.ANN_DAYS
MDD_FLOOR = gates.MDD_FLOOR
G_L1_MULT = gates.G_L1_MULT
FOLDS = gates.FOLDS


# ---------------------------------------------------------------------------
# The ONE substituted function: verifier's fixed-base MDD, ported verbatim
# from cta_l_stage1_verify_t6.py:60-65 (cumulative_mdd), operating on the
# same fraction-of-BASE ndarray the implementer's mdd_frac (gates.py:92-102)
# consumes.
# ---------------------------------------------------------------------------
def mdd_frac_fixed_base(returns: np.ndarray) -> float:
    """Verbatim port of cta_l_stage1_verify_t6.py:60-65 cumulative_mdd.
    cr = cumsum(returns); peak = running max of cr, floored at 0 via a
    prepended 0.0 anchor (== running max of equity floored at the seed
    value 1.0, in eq-space); dd = cr - peak (NOT divided by peak or by
    anything else -- this is what makes it 'fixed-base': the implicit
    denominator is the constant 1.0 initial equity)."""
    if len(returns) == 0:
        return 0.0
    cr = np.cumsum(returns)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cr]))[1:]
    dd = cr - peak
    return float(dd.min())


def mar_fixed(returns: np.ndarray) -> float:
    """Identical to gates.mar() (gates.py:113-117) except calling
    mdd_frac_fixed_base instead of gates.mdd_frac."""
    denom = max(abs(mdd_frac_fixed_base(returns)), MDD_FLOOR)
    return gates.ann_return_frac(returns) / denom


# ---------------------------------------------------------------------------
# Recompute the implementer's whole table with only the MDD swap applied.
# ---------------------------------------------------------------------------
def main() -> None:
    b0 = gates.load_returns("b0")
    v1 = gates.load_returns("v1")
    gates.assert_aligned(b0, v1, "main window B0 vs V1")
    ret_b0, ret_v1 = b0.to_numpy(), v1.to_numpy()

    out = []
    out.append("# Reconciliation: implementer pipeline + verifier fixed-base MDD\n")

    # ---- G-L1 ----
    ann_b0 = gates.ann_return_frac(ret_b0)
    ann_v1 = gates.ann_return_frac(ret_v1)
    mdd_b0 = mdd_frac_fixed_base(ret_b0)
    mdd_v1 = mdd_frac_fixed_base(ret_v1)
    mar_b0 = mar_fixed(ret_b0)
    mar_v1 = mar_fixed(ret_v1)
    ratio_full = mar_v1 / mar_b0 if mar_b0 != 0 else float("nan")
    g1_ok, g1_branch, g1_ratio = gates.g_l1_check(mar_v1, mar_b0, ret_v1, ret_b0)

    out.append("## G-L1 (recomputed with fixed-base MDD)\n")
    out.append(f"- n_days: {len(b0)}")
    out.append(f"- B0 annualized return: {ann_b0:.12f}")
    out.append(f"- B0 MDD (signed, fraction): {mdd_b0:.12f}")
    out.append(f"- B0 MAR: {mar_b0:.12f}")
    out.append(f"- V1 annualized return: {ann_v1:.12f}")
    out.append(f"- V1 MDD (signed, fraction): {mdd_v1:.12f}")
    out.append(f"- V1 MAR: {mar_v1:.12f}")
    out.append(f"- MAR(V1)/MAR(B0): {ratio_full:.12f}")
    out.append(f"- G-L1: {'PASS' if g1_ok else 'FAIL'} (branch={g1_branch})\n")

    # ---- G-L2 ----
    out.append("## G-L2 (recomputed with fixed-base MDD)\n")
    fold_pass = 0
    fold_detail = []
    for fname, fs, fe in FOLDS:
        rb = b0.loc[fs:fe].to_numpy()
        rv = v1.loc[fs:fe].to_numpy()
        a_b0 = gates.ann_return_frac(rb)
        a_v1 = gates.ann_return_frac(rv)
        d_b0 = mdd_frac_fixed_base(rb)
        d_v1 = mdd_frac_fixed_base(rv)
        mb = mar_fixed(rb)
        mv = mar_fixed(rv)
        ok = mv >= mb
        fold_pass += int(ok)
        fold_detail.append((fname, fs, fe, len(rb), a_b0, d_b0, mb, a_v1, d_v1, mv, ok))
        out.append(f"### {fname} ({fs}..{fe}, n={len(rb)})")
        out.append(f"- B0: ann_ret={a_b0:.12f} mdd={d_b0:.12f} MAR={mb:.12f}")
        out.append(f"- V1: ann_ret={a_v1:.12f} mdd={d_v1:.12f} MAR={mv:.12f}")
        out.append(f"- V1 MAR >= B0 MAR: {ok}\n")
    g2_ok = fold_pass >= 4
    out.append(f"- folds where V1 MAR >= B0 MAR: {fold_pass}/6")
    out.append(f"- G-L2: {'PASS' if g2_ok else 'FAIL'}\n")

    # ---- G-L3 (Sharpe point estimates only -- MDD-independent, sanity check) ----
    sharpe_b0 = gates.sharpe_frac(ret_b0)
    sharpe_v1 = gates.sharpe_frac(ret_v1)
    out.append("## G-L3 sanity (Sharpe point estimates, MDD-independent)\n")
    out.append(f"- Sharpe(B0), point estimate: {sharpe_b0:.12f}")
    out.append(f"- Sharpe(V1), point estimate: {sharpe_v1:.12f}")
    out.append(f"- delta-Sharpe, point estimate: {sharpe_v1 - sharpe_b0:.12f}\n")

    # ---- G-L4 ----
    b0c = gates.load_returns("b0_cost15")
    v1c = gates.load_returns("v1_cost15")
    gates.assert_aligned(b0c, v1c, "cost15 B0 vs V1")
    ret_b0c, ret_v1c = b0c.to_numpy(), v1c.to_numpy()
    ann_b0c = gates.ann_return_frac(ret_b0c)
    ann_v1c = gates.ann_return_frac(ret_v1c)
    mdd_b0c = mdd_frac_fixed_base(ret_b0c)
    mdd_v1c = mdd_frac_fixed_base(ret_v1c)
    mar_b0c = mar_fixed(ret_b0c)
    mar_v1c = mar_fixed(ret_v1c)
    ratio_c15 = mar_v1c / mar_b0c if mar_b0c != 0 else float("nan")
    g4_ok, g4_branch, g4_ratio = gates.g_l1_check(mar_v1c, mar_b0c, ret_v1c, ret_b0c)

    out.append("## G-L4 (recomputed with fixed-base MDD)\n")
    out.append(f"- n_days: {len(b0c)}")
    out.append(f"- B0(cost15): ann_ret={ann_b0c:.12f} mdd={mdd_b0c:.12f} MAR={mar_b0c:.12f}")
    out.append(f"- V1(cost15): ann_ret={ann_v1c:.12f} mdd={mdd_v1c:.12f} MAR={mar_v1c:.12f}")
    out.append(f"- MAR(V1)/MAR(B0) at cost15: {ratio_c15:.12f}")
    out.append(f"- G-L4: {'PASS' if g4_ok else 'FAIL'} (branch={g4_branch})\n")

    # ---- G-L5 ----
    out.append("## G-L5 (recomputed with fixed-base MDD)\n")
    ep_pass_all = True
    ep_detail = {}
    for ep in ("ep30", "ep60", "ep90"):
        b0e = gates.load_returns(f"b0_{ep}")
        v1e = gates.load_returns(f"v1_{ep}")
        gates.assert_aligned(b0e, v1e, f"{ep} B0 vs V1")
        rb, rv = b0e.to_numpy(), v1e.to_numpy()
        a_b0e = gates.ann_return_frac(rb)
        a_v1e = gates.ann_return_frac(rv)
        d_b0e = mdd_frac_fixed_base(rb)
        d_v1e = mdd_frac_fixed_base(rv)
        mb = mar_fixed(rb)
        mv = mar_fixed(rv)
        ok = mv >= mb
        ep_pass_all = ep_pass_all and ok
        ep_detail[ep] = (a_b0e, d_b0e, mb, a_v1e, d_v1e, mv, ok)
        out.append(f"### {ep}: n_days={len(rb)}, window end={b0e.index.max().date()}")
        out.append(f"- B0: ann_ret={a_b0e:.12f} mdd={d_b0e:.12f} MAR={mb:.12f}")
        out.append(f"- V1: ann_ret={a_v1e:.12f} mdd={d_v1e:.12f} MAR={mv:.12f}")
        out.append(f"- direction V1 MAR >= B0 MAR: {ok}\n")
    out.append(f"- G-L5: {'PASS' if ep_pass_all else 'FAIL'}\n")

    text = "\n".join(out)
    print(text)
    out_path = Path(__file__).parent / "recon_output.md"
    out_path.write_text(text + "\n")
    print(f"\n[wrote {out_path}]", file=sys.stderr)


if __name__ == "__main__":
    main()
