"""Sub-project L Stage 1, plan T2 — regression-guard self-test for
scripts/cta_l_stage1.py (simulate_l / run_cell_l).

Verifies the four structural properties spec §3 requires of the new sizing-
hook engine before it can be trusted for any Stage-1 config run (T4):

  Guard 0/1  Engine anchor    m_fn≡1.0, slippage=0  =>  bit-identical daily
                              returns to the audited original
                              cta_proxy_lib.run_cell() / p2b.simulate() path.
  Guard 2    Ledger equality  m_fn≡1.0 vs a non-constant m_fn: identical
                              (coin, entry_ts, exit_ts) trade sets — sizing
                              must never change entry/exit timing.
  Guard 3    Linear scaling   m_fn≡0.5 daily returns == 0.5 * (m_fn≡1.0 daily
                              returns), rtol=1e-12, atol=0 — catches a "forgot
                              to scale fee/slippage by m" silent-inflation bug.
  Guard 4    Cost hand-check  one trade's engine-recorded fees vs a manual
                              0.055%/side * actual notional * 2 sides calc.

Read-only: only touches data/cache/cta_proxy/*.parquet (local cache, no
network, no orders). Config pinned to phase-2b's production cell
"4h-p10-fuel24-short" (crowd-on), 5-coin universe, spec's hardcoded main
window 2020-09-14 -> 2026-06-30.

Usage: .venv/bin/python scripts/cta_l_stage1_selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_l_stage1 as l1     # noqa: E402
import cta_proxy_lib as lib   # noqa: E402

TF, PCTILE, FUEL_LB, SIDE, CROWD_ON = "4h", 10, 24, "short", True
WINDOW = (pd.Timestamp("2020-09-14"), pd.Timestamp("2026-06-30"))
SLIPPAGE = l1.DEFAULT_SLIPPAGE_PER_SIDE   # 1bp


def m_const(value: float):
    return lambda _coin, _ts: value


def main() -> int:
    print("=== T2 self-test: scripts/cta_l_stage1.py sizing-hook guards ===")
    print(f"config: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}  crowd_on={CROWD_ON}  "
          f"universe={list(lib.SYMBOLS_5.values())}")
    print(f"window: [{WINDOW[0]:%Y-%m-%d} .. {WINDOW[1]:%Y-%m-%d}]")

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage (pre-window-slice): [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]")
    stats_start = (WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    print(f"stats_start: {stats_start:%Y-%m-%d}\n")

    all_pass = True

    # ---------------------------------------------------- Guard 0/1: anchor
    print("--- Guard 0/1: engine anchor (m_fn≡1.0, slippage=0) ---")
    r_orig = lib.run_cell(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                           FUEL_LB, stats_start, window=WINDOW)
    r_anchor = l1.run_cell_l(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                              FUEL_LB, stats_start, window=WINDOW,
                              m_fn=l1.const_m, slippage_per_side=0.0)
    orig_daily = r_orig["daily"].rename("ret").to_frame()
    new_daily = r_anchor["daily"].rename("ret").to_frame()
    try:
        pd.testing.assert_frame_equal(orig_daily, new_daily, check_exact=True)
        print(f"assert_frame_equal(check_exact=True): PASS  "
              f"({len(orig_daily)} daily rows compared)")
    except AssertionError as e:
        all_pass = False
        print(f"assert_frame_equal(check_exact=True): FAIL\n{e}")

    # bonus scalar cross-check (not the gate itself, but cheap corroboration)
    scalar_ok = (r_orig["pnl"] == r_anchor["pnl"]
                 and r_orig["sharpe"] == r_anchor["sharpe"]
                 and r_orig["mdd_pct"] == r_anchor["mdd_pct"]
                 and r_orig["trades"] == r_anchor["trades"])
    print(f"scalar cross-check (pnl/sharpe/mdd/trades all ==): "
          f"{'PASS' if scalar_ok else 'FAIL'}")
    print(f"  orig : pnl={r_orig['pnl']:.6f} sharpe={r_orig['sharpe']:.6f} "
          f"mdd%={r_orig['mdd_pct']:.6f} trades={r_orig['trades']}")
    print(f"  new  : pnl={r_anchor['pnl']:.6f} sharpe={r_anchor['sharpe']:.6f} "
          f"mdd%={r_anchor['mdd_pct']:.6f} trades={r_anchor['trades']}")
    all_pass = all_pass and scalar_ok
    print()

    # ---------------------------------------------- Guard 2: ledger equality
    print("--- Guard 2: trade ledger equality (m_fn≡1.0 vs m≡0.7, slippage=1bp) ---")
    r_b0 = l1.run_cell_l(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                          FUEL_LB, stats_start, window=WINDOW,
                          m_fn=l1.const_m, slippage_per_side=SLIPPAGE)
    r_v = l1.run_cell_l(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                         FUEL_LB, stats_start, window=WINDOW,
                         m_fn=m_const(0.7), slippage_per_side=SLIPPAGE)
    set_b0 = {(t["coin"], t["entry_time"], t["exit_time"]) for t in r_b0["all_trades"]}
    set_v = {(t["coin"], t["entry_time"], t["exit_time"]) for t in r_v["all_trades"]}
    sym_diff = set_b0 ^ set_v
    ledger_ok = len(sym_diff) == 0
    print(f"|B0 trades|={len(set_b0)}  |V(m=0.7) trades|={len(set_v)}  "
          f"symmetric-difference size={len(sym_diff)}: {'PASS' if ledger_ok else 'FAIL'}")
    if not ledger_ok:
        print(f"  sample diffs: {list(sym_diff)[:5]}")
    all_pass = all_pass and ledger_ok
    print()

    # ---------------------------------------------- Guard 3: linear scaling
    print("--- Guard 3: linear scaling (m_fn≡0.5 daily == 0.5 * B0 daily, slippage=1bp) ---")
    r_half = l1.run_cell_l(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                            FUEL_LB, stats_start, window=WINDOW,
                            m_fn=m_const(0.5), slippage_per_side=SLIPPAGE)
    index_ok = r_b0["daily"].index.equals(r_half["daily"].index)
    print(f"daily index identical (B0 vs m=0.5): {'PASS' if index_ok else 'FAIL'}")
    all_pass = all_pass and index_ok
    if index_ok:
        b0_vals = r_b0["daily"].to_numpy()
        half_vals = r_half["daily"].to_numpy()
        scale_ok = bool(np.allclose(half_vals, 0.5 * b0_vals, rtol=1e-12, atol=0))
        max_reldiff = float(np.max(np.abs(half_vals - 0.5 * b0_vals)
                                    / np.where(b0_vals != 0, np.abs(b0_vals), 1.0)))
        print(f"np.allclose(m=0.5 daily, 0.5*B0 daily, rtol=1e-12, atol=0): "
              f"{'PASS' if scale_ok else 'FAIL'}  (max |diff|/|B0| where B0!=0 = {max_reldiff:.3e})")
        all_pass = all_pass and scale_ok
    print()

    # ------------------------------------------ Guard 4: cost hand-check
    print("--- Guard 4: cost hand-calc spot check (one trade from m=0.7 run) ---")
    sample = sorted(r_v["all_trades"], key=lambda t: (t["coin"], t["entry_time"]))[0]
    fee_rate = l1.FEE_RATE
    slip_rate = SLIPPAGE
    manual_notional = l1.NOTIONAL * sample["m"]
    manual_fee_side = (fee_rate + slip_rate) * manual_notional
    manual_fees_total = manual_fee_side * 2   # entry + exit, both sides
    engine_fees = sample["fees"]
    cost_ok = abs(manual_fees_total - engine_fees) < 1e-9
    print(f"trade: coin={sample['coin']} entry={sample['entry_time']} "
          f"exit={sample['exit_time']} m={sample['m']} notional={sample['notional']:.4f}")
    print(f"  manual: notional=100*{sample['m']}={manual_notional:.4f}  "
          f"fee/side=(0.045%+0.01%)*notional={manual_fee_side:.6f}  "
          f"total(2 sides)={manual_fees_total:.6f}")
    print(f"  engine: notional={sample['notional']:.6f}  fees(entry+exit)={engine_fees:.6f}")
    print(f"  match (< 1e-9): {'PASS' if cost_ok else 'FAIL'}")
    all_pass = all_pass and cost_ok
    print()

    print("=== SUMMARY ===")
    print(f"Guard 0/1 (engine anchor)     : {'PASS' if scalar_ok else 'FAIL'}")
    print(f"Guard 2   (ledger equality)   : {'PASS' if ledger_ok else 'FAIL'}")
    print(f"Guard 3   (linear scaling)    : {'PASS' if (index_ok and scale_ok) else 'FAIL'}")
    print(f"Guard 4   (cost hand-check)   : {'PASS' if cost_ok else 'FAIL'}")
    print(f"\nALL GUARDS: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
