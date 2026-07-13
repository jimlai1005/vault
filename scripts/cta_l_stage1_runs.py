"""Sub-project L Stage 1, plan T4 — run all 14 configs, write csvs + manifest.

Every simulation Stage-1 needs is produced HERE, once, and cached to
data/cache/cta_l/ as (daily-pnl csv, trade-ledger csv) pairs. T5 (gate script)
and T6 (independent verifier) read ONLY these csvs — no simulation happens
downstream of this script (plan T4 / spec §7 point 1).

Engine: scripts/cta_l_stage1.py's simulate_l()/run_cell_l() (T2, all 4 guards
PASS) for the sizing hook, and build_sigma_m()/make_m_fn() (T3, guards PASS)
for the per-coin EWMA-vol multiplier table. Config pinned to phase-2b's
production cell "4h-p10-fuel24-short" (crowd_on=True), 5-coin universe
(lib.SYMBOLS_5), main window hardcoded 2020-09-14T00:00Z -> 2026-06-30T00:00Z
(spec §2 — no "N days back from today").

Cost x1.5 (G-L4, configs *_cost15): spec §3 gives the TOTAL only
(0.0825%/side); the fee/slippage split is left unspecified. This script
scales BOTH components by 1.5x (proportional split, preserving the standard
run's 0.045%-fee : 0.01%-slippage ratio) rather than dumping the whole delta
onto slippage alone: fee_rate=1.5*FEE_RATE=0.000675, slippage_per_side=
1.5*DEFAULT_SLIPPAGE_PER_SIDE=0.00015, sum=0.000825=0.0825%/side. This
required adding a `fee_rate` parameter to simulate_l()/run_cell_l() (default
= the original module constant FEE_RATE, so every pre-existing call site is
byte-for-byte unaffected) — see cta_l_stage1.py's docstrings on that param
and scripts/cta_l_stage1_selftest{,_t3}.py re-run clean after the change.

Endpoint truncation (G-L5, configs *_ep30/60/90): right end of the window
moves to main_end - {30,60,90} days; left end (2020-09-14) is unchanged.
Truncation is done purely via run_cell_l(..., window=(start, truncated_end))
-- simulate_l() already force-closes any still-open position at the last bar
of whatever slice of `sig` it receives (see cta_l_stage1.py's "force-close at
end" branch), so "窗末強制平倉規則與主窗一致" falls out for free: it is the
SAME code path as the main window's own end-of-window force-close, just
triggered at an earlier bar. No separate end-of-window logic was written.

Read-only: only touches data/cache/cta_proxy/*.parquet (input) and writes
under data/cache/cta_l/ (gitignored, reproducible by re-running this script).
No network calls, no .env* access, no orders.

Usage: .venv/bin/python scripts/cta_l_stage1_runs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_l_stage1 as l1     # noqa: E402
import cta_proxy_lib as lib   # noqa: E402

TF, PCTILE, FUEL_LB, SIDE, CROWD_ON = "4h", 10, 24, "short", True
MAIN_WINDOW = (pd.Timestamp("2020-09-14"), pd.Timestamp("2026-06-30"))
STD_SLIPPAGE = l1.DEFAULT_SLIPPAGE_PER_SIDE          # 1bp
STD_FEE = l1.FEE_RATE                                 # 0.045%
COST15_SLIPPAGE = 1.5 * STD_SLIPPAGE                  # 0.015%
COST15_FEE = 1.5 * STD_FEE                            # 0.0675%  -> sum 0.0825%
OUT_DIR = Path("data/cache/cta_l")

TRADE_COLS = ["coin", "entry_ts", "exit_ts", "side", "notional", "m",
              "pnl", "fees", "reason"]


def ep_window(days_back: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (MAIN_WINDOW[0], MAIN_WINDOW[1] - pd.Timedelta(days=days_back))


def write_run(name: str, frames, m_fn, slippage_per_side, fee_rate, window,
              sigma_params: dict | None, manifest: dict) -> None:
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    r = l1.run_cell_l(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                       stats_start, window=window, m_fn=m_fn,
                       slippage_per_side=slippage_per_side, fee_rate=fee_rate)

    daily_path = OUT_DIR / f"{name}.csv"
    trades_path = OUT_DIR / f"{name}_trades.csv"

    daily = r["daily"].rename("pnl")
    daily.index.name = "date"
    daily.to_csv(daily_path, header=True)

    trows = []
    for t in r["all_trades"]:
        trows.append({
            "coin": t["coin"], "entry_ts": t["entry_time"], "exit_ts": t["exit_time"],
            "side": t["side"], "notional": t["notional"], "m": t["m"],
            "pnl": t["pnl"], "fees": t["fees"], "reason": t["reason"],
        })
    tdf = pd.DataFrame(trows, columns=TRADE_COLS)
    tdf.to_csv(trades_path, index=False)

    manifest[name] = {
        "config": f"{TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}",
        "crowd_on": CROWD_ON,
        "sigma": sigma_params,
        "fee_rate": fee_rate,
        "slippage_per_side": slippage_per_side,
        "cost_per_side_total": fee_rate + slippage_per_side,
        "window_start": window[0].isoformat(),
        "window_end": window[1].isoformat(),
        "daily_csv": str(daily_path),
        "trades_csv": str(trades_path),
        "n_days": int(len(daily)),
        "n_trades": int(len(tdf)),
        "summary": {
            "pnl": r["pnl"], "sharpe": r["sharpe"], "mdd_pct": r["mdd_pct"],
            "trades_post_stats_start": r["trades"],
        },
    }
    print(f"  wrote {name}: n_days={len(daily)} n_trades={len(tdf)} "
          f"pnl={r['pnl']:.6f} sharpe={r['sharpe']:.6f} mdd%={r['mdd_pct']:.4f} "
          f"trades(post stats_start)={r['trades']}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== T4: running all 14 Stage-1 configs ===")
    print(f"config: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}  crowd_on={CROWD_ON}  "
          f"universe={list(lib.SYMBOLS_5.values())}")
    print(f"main window: [{MAIN_WINDOW[0]:%Y-%m-%d} .. {MAIN_WINDOW[1]:%Y-%m-%d}]")
    print(f"standard cost: fee={STD_FEE*100:.4f}%/side + slippage={STD_SLIPPAGE*100:.4f}%/side "
          f"= {(STD_FEE+STD_SLIPPAGE)*100:.4f}%/side")
    print(f"cost x1.5 (G-L4): fee={COST15_FEE*100:.4f}%/side + slippage={COST15_SLIPPAGE*100:.4f}%/side "
          f"= {(COST15_FEE+COST15_SLIPPAGE)*100:.4f}%/side\n")

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage (pre-window-slice): [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]\n")

    manifest: dict[str, dict] = {}

    # ---- main-config V1 sigma/m table (sigma_target=60%, span=180, clip 0.25-1.0)
    print("building main-config (V1) sigma/m table ...")
    _, m_by_coin_v1 = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF)
    m_fn_v1 = l1.make_m_fn(m_by_coin_v1)
    v1_sigma_params = {"sigma_target": l1.SIGMA_TARGET, "span": l1.SIGMA_SPAN,
                        "clip_lo": l1.SIGMA_CLIP_LO, "clip_hi": l1.SIGMA_CLIP_HI}

    # 1. b0 -- m ident 1.0, standard cost, main window
    print("\n[1/14] b0")
    write_run("b0", frames, l1.const_m, STD_SLIPPAGE, STD_FEE, MAIN_WINDOW,
              None, manifest)

    # 2. v1 -- main config, standard cost, main window
    print("[2/14] v1")
    write_run("v1", frames, m_fn_v1, STD_SLIPPAGE, STD_FEE, MAIN_WINDOW,
              v1_sigma_params, manifest)

    # 3-4. sens_st40 / sens_st80 -- sigma_target 40%/80%, span 180 fixed
    for i, st in ((3, 0.40), (4, 0.80)):
        name = f"sens_st{int(st*100)}"
        print(f"[{i}/14] {name}")
        _, m_by_coin = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF, sigma_target=st,
                                         span=l1.SIGMA_SPAN)
        sp = {"sigma_target": st, "span": l1.SIGMA_SPAN,
              "clip_lo": l1.SIGMA_CLIP_LO, "clip_hi": l1.SIGMA_CLIP_HI}
        write_run(name, frames, l1.make_m_fn(m_by_coin), STD_SLIPPAGE, STD_FEE,
                  MAIN_WINDOW, sp, manifest)

    # 5-6. sens_sp90 / sens_sp360 -- span 90/360, sigma_target 60% fixed
    for i, sp_bars in ((5, 90), (6, 360)):
        name = f"sens_sp{sp_bars}"
        print(f"[{i}/14] {name}")
        _, m_by_coin = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF,
                                         sigma_target=l1.SIGMA_TARGET, span=sp_bars)
        sp = {"sigma_target": l1.SIGMA_TARGET, "span": sp_bars,
              "clip_lo": l1.SIGMA_CLIP_LO, "clip_hi": l1.SIGMA_CLIP_HI}
        write_run(name, frames, l1.make_m_fn(m_by_coin), STD_SLIPPAGE, STD_FEE,
                  MAIN_WINDOW, sp, manifest)

    # 7-8. b0_cost15 / v1_cost15 -- cost x1.5, main window
    print("[7/14] b0_cost15")
    write_run("b0_cost15", frames, l1.const_m, COST15_SLIPPAGE, COST15_FEE,
              MAIN_WINDOW, None, manifest)
    print("[8/14] v1_cost15")
    write_run("v1_cost15", frames, m_fn_v1, COST15_SLIPPAGE, COST15_FEE,
              MAIN_WINDOW, v1_sigma_params, manifest)

    # 9-14. b0_ep{30,60,90} / v1_ep{30,60,90} -- truncated right endpoint
    idx = 9
    for days_back in (30, 60, 90):
        w = ep_window(days_back)
        name = f"b0_ep{days_back}"
        print(f"[{idx}/14] {name}  window=[{w[0]:%Y-%m-%d}..{w[1]:%Y-%m-%d}]")
        write_run(name, frames, l1.const_m, STD_SLIPPAGE, STD_FEE, w, None, manifest)
        idx += 1
    for days_back in (30, 60, 90):
        w = ep_window(days_back)
        name = f"v1_ep{days_back}"
        print(f"[{idx}/14] {name}  window=[{w[0]:%Y-%m-%d}..{w[1]:%Y-%m-%d}]")
        write_run(name, frames, m_fn_v1, STD_SLIPPAGE, STD_FEE, w,
                  v1_sigma_params, manifest)
        idx += 1

    manifest_path = OUT_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\nwrote manifest: {manifest_path}  ({len(manifest)} configs)")
    assert len(manifest) == 14, f"expected 14 configs, got {len(manifest)}"
    print("\n=== T4 DONE: 14/14 configs written ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
