"""Sub-project L Stage 2, plan T3 — A1 (event-calendar de-risking) formal runs.

Protocol (sole source of judgment): docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md
§3 (m composition — A1 carries no extra m_f, only veto+resize), §4 (A1 full
definition: event set, window, bar alignment, resize/restore/mtm, cost, two
"only-report" sensitivities), §7 (G-A·3 cost co-scaling). Plan:
docs/superpowers/plans/2026-07-14-cta-l-stage2-plan.md T3.

Engine: scripts/cta_l_stage2.py (commit 71009d3, six guards PASS) —
run_cell_l2()/simulate_l2(), threaded with `event_windows=` (protocol §4 bar-
close-vs-window-close alignment, computed by l2.compute_in_window_mask) and
`resize_enabled=`/`resize_factor=` (protocol §4 point 2, default 0.5). A1 has
NO independent m_f: the only sizing input is B1's own m_vol table
(l1.build_sigma_m/make_m_fn, identical to Stage 1's v1 config) — A1's effect
on the ledger is entirely through entry veto + notional resize/restore, not
through the multiplier (protocol §3's m_total product for A1 == B1's m_vol).

Baseline (B1) csvs are NOT regenerated here — data/cache/cta_l/v1*.csv (Stage
1 output) are read-only and reused as-is for the anchor spot-check and the
trade-count comparison printed in this script's own report. This script only
ever writes to data/cache/cta_l2/ (plan redline).

PIT guard (protocol §8 point 4): the event calendar's git blob content hash
is asserted against the value recorded at commit 692754e before any run
executes — if the working-tree file has drifted from the frozen PIT csv,
this script refuses to produce numbers.

Seven runs (plan T3): a1, a1_cost15, a1_ep{30,60,90}, a1_sens_noresize,
a1_sens_w48. Each writes a ({name}.csv daily $ pnl, {name}_trades.csv ledger)
pair; the trades csv adds a `resize_events` column (JSON-encoded list, per
protocol §4 ledger schema) on top of Stage 1's TRADE_COLS.

After the 7 runs, two in-script checks (printed, not written as files):
  - degenerate self-check (plan T3 acceptance 4): re-running the `a1` config
    with event_windows=[] must reproduce data/cache/cta_l/v1.csv EXACTLY
    (elementwise), proving A1's entire effect on the ledger flows through the
    event mechanism and nothing else changed vs B1's own v1 run.
  - B1 anchor spot-check (plan T3 acceptance 3): MAR/MDD/Sharpe recomputed
    from data/cache/cta_l/v1.csv via the protocol §1/§2 fixed-basis formula,
    checked against the protocol §1 numeric anchors at relative tolerance
    1e-9.

Read-only except for data/cache/cta_l2/: only touches data/cache/cta_proxy/
(cached parquet input), data/cache/cta_l/ (Stage 1 output, read-only), and
data/events/us_macro_calendar.csv (read-only). No network calls, no .env*
access, no orders.

Usage: .venv/bin/python scripts/cta_l_stage2_runs_a1.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_l_stage1 as l1     # noqa: E402
import cta_l_stage2 as l2     # noqa: E402
import cta_proxy_lib as lib   # noqa: E402

TF, PCTILE, FUEL_LB, SIDE, CROWD_ON = "4h", 10, 24, "short", True
MAIN_WINDOW = (pd.Timestamp("2020-09-14"), pd.Timestamp("2026-06-30"))
STD_SLIPPAGE = l1.DEFAULT_SLIPPAGE_PER_SIDE           # 1bp
STD_FEE = l1.FEE_RATE                                 # 0.045%
COST15_SLIPPAGE = 1.5 * STD_SLIPPAGE                  # 0.015%
COST15_FEE = 1.5 * STD_FEE                            # 0.0675% -> sum 0.0825%
OUT_DIR = Path("data/cache/cta_l2")
B1_DIR = Path("data/cache/cta_l")                     # read-only, Stage 1 output

EVENTS_CSV = Path("data/events/us_macro_calendar.csv")
EVENTS_SHA256_EXPECTED = ("c4e5c2cf685766ce09a4fcb68dbb0f690a41e49"
                           "454606c4ffb238960ca41bbea")
EVENTS_COMMIT = "692754e"
ENGINE_COMMIT = "71009d3"
PROTOCOL_COMMIT = "c329dd2"

# protocol §1 numeric anchors (B1 full window)
ANCHOR_MAR = 0.299355395590
ANCHOR_MDD = -0.152055268750
ANCHOR_SHARPE = 0.499956120997
ANCHOR_TOL_REL = 1e-9

TRADE_COLS = ["coin", "entry_ts", "exit_ts", "side", "notional", "m",
              "pnl", "fees", "reason", "resize_events"]


def ep_window(days_back: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (MAIN_WINDOW[0], MAIN_WINDOW[1] - pd.Timedelta(days=days_back))


def load_event_windows(pre_hours: int, post_hours: int = 6):
    """Protocol §4: window = [T-pre_hours, T+post_hours] per event, built
    from the ET->UTC-converted `ts_utc` column of the frozen calendar csv.
    Returns list[(start, end)] as tz-naive UTC Timestamps (matching the
    tz-naive-UTC convention of frames[(coin, tf)].index / MAIN_WINDOW
    throughout this codebase)."""
    df = pd.read_csv(EVENTS_CSV)
    ts = pd.to_datetime(df["ts_utc"], utc=True).dt.tz_localize(None)
    pre = pd.Timedelta(hours=pre_hours)
    post = pd.Timedelta(hours=post_hours)
    return [(t - pre, t + post) for t in ts]


def assert_events_pit() -> None:
    """Protocol §8 point 4: PIT guard — the working-tree event csv must be
    byte-identical to the frozen commit 692754e content before any run."""
    digest = hashlib.sha256(EVENTS_CSV.read_bytes()).hexdigest()
    assert digest == EVENTS_SHA256_EXPECTED, (
        f"event calendar sha256 mismatch: working tree={digest} "
        f"expected(frozen@{EVENTS_COMMIT})={EVENTS_SHA256_EXPECTED} — "
        "refusing to produce A1 numbers off a drifted PIT input")
    print(f"PIT guard: {EVENTS_CSV} sha256={digest} == frozen@{EVENTS_COMMIT}: PASS")


def write_run(name: str, frames, m_fn, slippage_per_side, fee_rate, window,
              event_windows, resize_enabled, resize_factor,
              event_window_desc: str, manifest: dict) -> dict:
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    r = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                        stats_start, window=window, m_fn=m_fn,
                        slippage_per_side=slippage_per_side, fee_rate=fee_rate,
                        event_windows=event_windows, resize_enabled=resize_enabled,
                        resize_factor=resize_factor)

    daily_path = OUT_DIR / f"{name}.csv"
    trades_path = OUT_DIR / f"{name}_trades.csv"

    daily = r["daily"].rename("pnl")
    daily.index.name = "date"
    daily.to_csv(daily_path, header=True)

    trows = []
    n_resize_events_total = 0
    n_trades_with_resize = 0
    for t in r["all_trades"]:
        rev = t["resize_events"]
        if rev:
            n_trades_with_resize += 1
            n_resize_events_total += len(rev)
        trows.append({
            "coin": t["coin"], "entry_ts": t["entry_time"], "exit_ts": t["exit_time"],
            "side": t["side"], "notional": t["notional"], "m": t["m"],
            "pnl": t["pnl"], "fees": t["fees"], "reason": t["reason"],
            "resize_events": json.dumps(rev, default=str),
        })
    tdf = pd.DataFrame(trows, columns=TRADE_COLS)
    tdf.to_csv(trades_path, index=False)

    manifest[name] = {
        "config": f"{TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}",
        "crowd_on": CROWD_ON,
        "sigma": {"sigma_target": l1.SIGMA_TARGET, "span": l1.SIGMA_SPAN,
                  "clip_lo": l1.SIGMA_CLIP_LO, "clip_hi": l1.SIGMA_CLIP_HI},
        "fee_rate": fee_rate,
        "slippage_per_side": slippage_per_side,
        "cost_per_side_total": fee_rate + slippage_per_side,
        "resize_enabled": resize_enabled,
        "resize_factor": resize_factor,
        "event_window": event_window_desc,
        "n_event_windows": len(event_windows) if event_windows else 0,
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
        "resize_stats": {
            "n_trades_with_resize_events": n_trades_with_resize,
            "n_resize_events_total": n_resize_events_total,
        },
    }
    print(f"  wrote {name}: n_days={len(daily)} n_trades={len(tdf)} "
          f"pnl={r['pnl']:.6f} sharpe={r['sharpe']:.6f} mdd%={r['mdd_pct']:.4f} "
          f"trades(post stats_start)={r['trades']} "
          f"resize: {n_trades_with_resize} trades / {n_resize_events_total} events")
    return r


def degenerate_check(frames, m_fn_v1) -> bool:
    """Plan T3 acceptance 4: `a1` config with event_windows=[] must reproduce
    data/cache/cta_l/v1.csv EXACTLY (elementwise) — proves A1's entire delta
    vs B1 flows through the event mechanism alone."""
    print("\n--- degenerate self-check: a1 config w/ event_windows=[] vs Stage-1 v1.csv ---")
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    r = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                        stats_start, window=MAIN_WINDOW, m_fn=m_fn_v1,
                        slippage_per_side=STD_SLIPPAGE, fee_rate=STD_FEE,
                        event_windows=[], resize_enabled=True, resize_factor=0.5)
    # float_precision="round_trip": pandas' default C float parser (xstrtod)
    # is not always bit-exact on read_csv (observed off-by-1-ULP on this very
    # file, e.g. 2022-09-06: file text "9.011826767002127" parses to
    # ...002129 under the default fast parser) — round_trip uses the
    # standard-library dtoa-equivalent parser so the loaded value matches the
    # CSV text exactly, which this exact-equality check requires.
    v1 = pd.read_csv(B1_DIR / "v1.csv", parse_dates=["date"], index_col="date",
                      float_precision="round_trip")["pnl"]
    got = r["daily"].rename("pnl")
    got.index.name = "date"
    same_index = got.index.equals(v1.index)
    exact_equal = same_index and np.array_equal(got.to_numpy(), v1.to_numpy())
    max_abs_diff = float(np.max(np.abs(got.to_numpy() - v1.to_numpy()))) if same_index else float("nan")
    print(f"  index equal: {same_index}")
    print(f"  elementwise exact equal (np.array_equal): {exact_equal}")
    print(f"  max |diff|: {max_abs_diff:.3e}")
    assert same_index, "degenerate check FAILED: index mismatch vs v1.csv"
    assert exact_equal, f"degenerate check FAILED: values differ, max|diff|={max_abs_diff:.3e}"
    print("degenerate self-check: PASS (a1 w/ event_windows=[] == Stage-1 v1.csv, exact)")
    return True


def anchor_spot_check() -> bool:
    """Plan T3 acceptance 3: recompute B1 full-window MAR/MDD/Sharpe from
    Stage-1's own v1.csv via the protocol §1/§2 fixed-basis formula, and
    check against the protocol §1 numeric anchors (rel tol 1e-9)."""
    print("\n--- B1 anchor spot-check (from data/cache/cta_l/v1.csv, fixed-basis formula) ---")
    df = pd.read_csv(B1_DIR / "v1.csv", parse_dates=["date"], index_col="date",
                      float_precision="round_trip")
    port_base = float(lib.NOTIONAL) * len(lib.SYMBOLS_5)
    r = df["pnl"] / port_base
    n_days = len(r)
    ann = r.sum() * 365 / n_days
    eq = 1 + r.cumsum()
    mdd = float((eq - eq.cummax()).min())
    mar = ann / max(abs(mdd), 0.005)
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(365))

    def rel_err(x, anchor):
        return abs(x - anchor) / abs(anchor)

    checks = [
        ("MAR", mar, ANCHOR_MAR),
        ("MDD", mdd, ANCHOR_MDD),
        ("Sharpe", sharpe, ANCHOR_SHARPE),
    ]
    all_ok = True
    for label, val, anchor in checks:
        err = rel_err(val, anchor)
        ok = err < ANCHOR_TOL_REL
        all_ok = all_ok and ok
        print(f"  {label}: computed={val:.12f} anchor={anchor:.12f} "
              f"rel_err={err:.3e} (tol {ANCHOR_TOL_REL:.0e}): {'PASS' if ok else 'FAIL'}")
    assert all_ok, "B1 anchor spot-check FAILED — see rel_err above"
    print("B1 anchor spot-check: PASS (all three within 1e-9 relative tolerance)")
    return True


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== T3: A1 (event-calendar de-risking) formal runs ===")
    assert_events_pit()

    print(f"\nconfig: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}  crowd_on={CROWD_ON}  "
          f"universe={list(lib.SYMBOLS_5.values())}")
    print(f"main window: [{MAIN_WINDOW[0]:%Y-%m-%d} .. {MAIN_WINDOW[1]:%Y-%m-%d}]")
    print(f"standard cost: fee={STD_FEE*100:.4f}%/side + slippage={STD_SLIPPAGE*100:.4f}%/side "
          f"= {(STD_FEE+STD_SLIPPAGE)*100:.4f}%/side")
    print(f"cost x1.5 (G-A·3): fee={COST15_FEE*100:.4f}%/side + slippage={COST15_SLIPPAGE*100:.4f}%/side "
          f"= {(COST15_FEE+COST15_SLIPPAGE)*100:.4f}%/side")

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage (pre-window-slice): [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]")

    # B1's own m_vol table (protocol §3: A1 carries no extra m_f — m_total==m_vol)
    print("\nbuilding B1 (V1) sigma/m table (reused unmodified for A1) ...")
    _, m_by_coin_v1 = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF)
    m_fn_v1 = l1.make_m_fn(m_by_coin_v1)

    main_windows_24h = load_event_windows(pre_hours=24, post_hours=6)
    sens_windows_48h = load_event_windows(pre_hours=48, post_hours=6)
    print(f"loaded {len(main_windows_24h)} event windows from {EVENTS_CSV} "
          f"(main config [T-24h,T+6h]); {len(sens_windows_48h)} windows for sens_w48 [T-48h,T+6h]")

    manifest: dict[str, dict] = {}

    print("\n[1/7] a1 — main config, standard cost, main window")
    write_run("a1", frames, m_fn_v1, STD_SLIPPAGE, STD_FEE, MAIN_WINDOW,
              main_windows_24h, True, l2.A1_RESIZE_FACTOR, "[T-24h,T+6h]", manifest)

    print("[2/7] a1_cost15 — cost x1.5 (G-A·3), main window")
    write_run("a1_cost15", frames, m_fn_v1, COST15_SLIPPAGE, COST15_FEE, MAIN_WINDOW,
              main_windows_24h, True, l2.A1_RESIZE_FACTOR, "[T-24h,T+6h]", manifest)

    idx = 3
    for days_back in (30, 60, 90):
        w = ep_window(days_back)
        name = f"a1_ep{days_back}"
        print(f"[{idx}/7] {name}  window=[{w[0]:%Y-%m-%d}..{w[1]:%Y-%m-%d}]")
        write_run(name, frames, m_fn_v1, STD_SLIPPAGE, STD_FEE, w,
                  main_windows_24h, True, l2.A1_RESIZE_FACTOR, "[T-24h,T+6h]", manifest)
        idx += 1

    print(f"[{idx}/7] a1_sens_noresize — 只禁新倉、不縮舊倉 (main window)")
    write_run("a1_sens_noresize", frames, m_fn_v1, STD_SLIPPAGE, STD_FEE, MAIN_WINDOW,
              main_windows_24h, False, l2.A1_RESIZE_FACTOR, "[T-24h,T+6h] (resize disabled)", manifest)
    idx += 1

    print(f"[{idx}/7] a1_sens_w48 — 窗改 [T-48h,T+6h] (main window)")
    write_run("a1_sens_w48", frames, m_fn_v1, STD_SLIPPAGE, STD_FEE, MAIN_WINDOW,
              sens_windows_48h, True, l2.A1_RESIZE_FACTOR, "[T-48h,T+6h]", manifest)

    # ---- trade-count comparison vs B1's own v1_trades.csv (禁新倉 sanity)
    b1_trades = pd.read_csv(B1_DIR / "v1_trades.csv")
    a1_trades = pd.read_csv(OUT_DIR / "a1_trades.csv")
    print(f"\ntrade count: B1 v1 = {len(b1_trades)}, A1 a1 = {len(a1_trades)} "
          f"(delta = {len(a1_trades) - len(b1_trades)}; expect <= 0, 禁新倉 vetoes entries)")

    out_manifest = {
        "protocol_commit": PROTOCOL_COMMIT,
        "engine_commit": ENGINE_COMMIT,
        "engine_file": "scripts/cta_l_stage2.py",
        "event_calendar_csv": str(EVENTS_CSV),
        "event_calendar_commit": EVENTS_COMMIT,
        "event_calendar_sha256": EVENTS_SHA256_EXPECTED,
        "baseline_note": ("B1 csvs reused read-only from data/cache/cta_l/ "
                           "(v1.csv, v1_cost15.csv, v1_ep{30,60,90}.csv) — "
                           "not regenerated by this script"),
        "b1_v1_trade_count": int(len(b1_trades)),
        "runs": manifest,
    }
    manifest_path = OUT_DIR / "manifest_a1.json"
    with open(manifest_path, "w") as f:
        json.dump(out_manifest, f, indent=2, default=str)
    print(f"\nwrote manifest: {manifest_path} ({len(manifest)} runs)")
    assert len(manifest) == 7, f"expected 7 A1 runs, got {len(manifest)}"

    ok1 = degenerate_check(frames, m_fn_v1)
    ok2 = anchor_spot_check()

    print("\n=== T3 DONE: 7/7 A1 runs written, degenerate check PASS, anchor spot-check PASS ==="
          if ok1 and ok2 else "\n=== T3 FAILED: see checks above ===")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
