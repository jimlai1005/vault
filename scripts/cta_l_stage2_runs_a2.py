"""Sub-project L Stage 2, plan T5 — A2 (crowd-percentile signal-strength
scaling) formal runs.

Protocol (sole source of judgment): docs/superpowers/specs/2026-07-14-cta-l-
stage2-protocol.md §3 (m composition — A2 IS an m_f, composed with B1's own
m_vol: `m_total = m_vol * m_A2`, no extra global floor), §5 (A2 full
definition: pct source, same-source guard, formula, defense clause, two
"only-report" ramp sensitivities), §7 (G-A·3 cost co-scaling). Plan:
docs/superpowers/plans/2026-07-14-cta-l-stage2-plan.md T5-T6.

Baseline for A2 is B1 (Stage 1 V1), NOT B1+A1: A1's own T4 gate table
(data/cache/cta_l2/a1_gates.md) shows G-A·1 (DSR, N=11) = 0.4941 < 0.95 ->
FAIL, so per protocol §7's judgment semantics ("任一不過 -> 該因子收檔、不
重試變體、繼續下一個 ablation") A1 was NOT merged into baseline. A2 is
therefore judged against B1 directly, reusing data/cache/cta_l/v1*.csv
read-only exactly like T3 did for A1 (this script never touches
data/cache/cta_l/ or data/cache/cta_l2/a1*).

Engine: scripts/cta_l_stage2.py (commit 71009d3, six guards PASS, including
Guard 6's A2 same-source assert: `crowd_long == (lpct_raw.shift(1) >= 90)`
elementwise on all 5 coins). A2 has NO event window and NO veto (protocol
§5's factor is purely a multiplicative m_f) — every write_run() call below
passes event_windows=None (compute_in_window_mask degenerates to an
all-False mask, matching l2's own "at event_windows=None ... every
arithmetic expression reduces to the EXACT SAME operation sequence as
Stage 1" docstring guarantee) and the default veto_fn (l2.no_veto).

pct source (protocol §5, "顯式" clause): `frames[(coin, tf)]["lpct_raw"]`
(the UNSHIFTED raw column produced by cta_proxy_lib.raw_indicators) shifted
by ONE bar — `.shift(1)` — the identical shift applied to the boolean
`crowd_long` gate inside cta_proxy_lib.shifted_signals(). This script never
recomputes a second percentile: build_pct_lookup() reads the exact same
`lpct_raw` column selftest Guard 6 already proved is elementwise identical,
in source, to the boolean gate's underlying data (`raw["lpct_raw"].shift(1)
>= (100-PCTILE)` == `sig["crowd_long"]`, PCTILE=10 => threshold 90).

Formula (protocol §5, short side): for the entry bar's `pct = lpct_raw.shift(1)`
value, `m_A2 = 0.5 + 0.5 * min(1, (pct-90)/(ramp_upper-90))`, ramp_upper=97
in the main config (90..97 ramp), 95/99 in the two only-report sensitivities
(§5's "ramp 上端 97 改 95／99"). Defense clause: an entry with pct<90 (or
NaN) is "理論不發生" per protocol (crowd_long, the entry gate, already
requires lpct_raw.shift(1)>=90 from the identical source) — if it ever
fires, it is logged to DEFENSE_LOG and forced to m_A2=0.5 rather than
raising, and the count is reported in the manifest and printed summary.

Seven runs (plan T5, matching a1's T3 shape): a2, a2_cost15, a2_ep{30,60,90},
a2_sens_p95, a2_sens_p99. Each writes a ({name}.csv daily $ pnl,
{name}_trades.csv ledger) pair; the trades csv carries the same base columns
as Stage 1's ledger PLUS `resize_events` (always `[]` here, kept only for
schema uniformity with the a1/a1_gates tooling) and two A2-specific
diagnostic columns, `m_a2`/`pct_a2` (the entry-locked A2 factor and its
underlying pct, recomputed post-hoc from the same pct lookup used inside the
run's own composed m_fn — NOT re-derived by any second formula) so the T6
gate/verdict step can build the m_A2 distribution (plan T5-T6 acceptance 4)
without re-running the engine.

After the 7 runs, four in-script checks (printed, not written as files):
  - ledger identity (T5 acceptance 2, A2-specific — A2 only scales size, it
    never touches entries/exits/veto): the (coin, entry_ts, exit_ts) SET of
    the `a2` run's trades must equal the SET of Stage 1 v1_trades.csv's
    trades exactly (symmetric difference == 0).
  - m_A2 distribution summary over the `a2` run's own trades (T5 acceptance
    4): min/median/max, and the =0.5 / =1.0 fraction.
  - degenerate self-check (T5 acceptance 6): re-running the `a2` config with
    the A2 factor forced to the constant 1.0 (m_fn = compose_m_fn(m_vol_fn,
    lambda *_: 1.0)) must reproduce data/cache/cta_l/v1.csv EXACTLY
    (elementwise) — proves the wiring (compose_m_fn, run_cell_l2 threading)
    introduces no drift of its own, isolating any real a2/v1 delta to the
    A2 factor's actual (non-degenerate) values.
  - B1 anchor spot-check (T5 acceptance 5, copied verbatim from T3's version):
    MAR/MDD/Sharpe recomputed from data/cache/cta_l/v1.csv via the protocol
    §1/§2 fixed-basis formula, checked against the protocol §1 numeric
    anchors at relative tolerance 1e-9.

Read-only except for data/cache/cta_l2/: only touches data/cache/cta_proxy/
(cached parquet input) and data/cache/cta_l/ (Stage 1 output, read-only).
No network calls, no .env* access, no orders. Does not import or modify
data/cache/cta_l2/a1* (A1's own outputs, untouched).

Usage: .venv/bin/python scripts/cta_l_stage2_runs_a2.py
"""
from __future__ import annotations

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

ENGINE_COMMIT = "71009d3"
PROTOCOL_COMMIT = "c329dd2"
A1_GATES_MD = "data/cache/cta_l2/a1_gates.md"
A1_STATUS = "NOT MERGED (G-A.1 DSR FAIL, see a1_gates.md) — A2 baseline = B1"

# protocol §1 numeric anchors (B1 full window)
ANCHOR_MAR = 0.299355395590
ANCHOR_MDD = -0.152055268750
ANCHOR_SHARPE = 0.499956120997
ANCHOR_TOL_REL = 1e-9

RAMP_LOW = 90.0
RAMP_UPPER_MAIN = 97.0

TRADE_COLS = ["coin", "entry_ts", "exit_ts", "side", "notional", "m", "m_a2",
              "pct_a2", "pnl", "fees", "reason", "resize_events"]

DEFENSE_LOG: list[dict] = []   # protocol §5 defense clause: pct<90 (or NaN) at an entry


def ep_window(days_back: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (MAIN_WINDOW[0], MAIN_WINDOW[1] - pd.Timedelta(days=days_back))


def build_pct_lookup(frames, symbols, tf) -> dict[str, dict]:
    """protocol §5 pct source: `frames[(coin, tf)]["lpct_raw"].shift(1)`
    (raw, UNSHIFTED lpct_raw column, then one bar shift) — the identical
    source+shift cta_l_stage2_selftest.py Guard 6 already proved elementwise
    equal to `sig["crowd_long"]`'s underlying `(lpct_raw>=90)` boolean on
    this exact data. Returns dict[coin] -> {timestamp: pct} for O(1) per-
    trade lookup, exactly like l1.make_m_fn()'s own lookup-dict pattern."""
    out: dict[str, dict] = {}
    for sym, coin in symbols.items():
        raw = frames[(coin, tf)]
        out[coin] = raw["lpct_raw"].shift(1).to_dict()
    return out


def m_a2_value(pct: float, ramp_upper: float) -> tuple[float, bool]:
    """protocol §5 formula, single source of truth for both the live m_fn
    used inside the engine and the post-hoc CSV annotation columns. Returns
    (m_a2, defense_triggered)."""
    if not (pct >= RAMP_LOW):                # covers pct<90 AND NaN
        return 0.5, True
    denom = ramp_upper - RAMP_LOW
    return 0.5 + 0.5 * min(1.0, (pct - RAMP_LOW) / denom), False


def make_m_a2_fn(pct_lookup: dict[str, dict], ramp_upper: float, run_name: str):
    def m_fn(coin: str, entry_ts: pd.Timestamp) -> float:
        pct = pct_lookup[coin].get(entry_ts, float("nan"))
        m_a2, defended = m_a2_value(pct, ramp_upper)
        if defended:
            DEFENSE_LOG.append({"run": run_name, "coin": coin,
                                 "entry_ts": str(entry_ts), "pct": pct})
        return m_a2
    return m_fn


def write_run(name: str, frames, m_vol_fn, ramp_upper: float, pct_lookup,
              slippage_per_side: float, fee_rate: float, window, manifest: dict) -> tuple[dict, pd.DataFrame]:
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    m_a2_fn = make_m_a2_fn(pct_lookup, ramp_upper, name)
    m_fn = l2.compose_m_fn(m_vol_fn, m_a2_fn)
    r = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                        stats_start, window=window, m_fn=m_fn,
                        slippage_per_side=slippage_per_side, fee_rate=fee_rate,
                        event_windows=None, resize_enabled=False,
                        resize_factor=l2.A1_RESIZE_FACTOR)

    daily_path = OUT_DIR / f"{name}.csv"
    trades_path = OUT_DIR / f"{name}_trades.csv"

    daily = r["daily"].rename("pnl")
    daily.index.name = "date"
    daily.to_csv(daily_path, header=True)

    trows = []
    for t in r["all_trades"]:
        coin, ets = t["coin"], t["entry_time"]
        pct = pct_lookup[coin].get(ets, float("nan"))
        m_a2, _ = m_a2_value(pct, ramp_upper)   # post-hoc annotation only; not re-appended to DEFENSE_LOG
        trows.append({
            "coin": coin, "entry_ts": t["entry_time"], "exit_ts": t["exit_time"],
            "side": t["side"], "notional": t["notional"], "m": t["m"],
            "m_a2": m_a2, "pct_a2": pct,
            "pnl": t["pnl"], "fees": t["fees"], "reason": t["reason"],
            "resize_events": json.dumps(t["resize_events"], default=str),
        })
    tdf = pd.DataFrame(trows, columns=TRADE_COLS)
    tdf.to_csv(trades_path, index=False)

    manifest[name] = {
        "config": f"{TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}",
        "crowd_on": CROWD_ON,
        "sigma": {"sigma_target": l1.SIGMA_TARGET, "span": l1.SIGMA_SPAN,
                  "clip_lo": l1.SIGMA_CLIP_LO, "clip_hi": l1.SIGMA_CLIP_HI},
        "a2": {"ramp_low": RAMP_LOW, "ramp_upper": ramp_upper},
        "fee_rate": fee_rate,
        "slippage_per_side": slippage_per_side,
        "cost_per_side_total": fee_rate + slippage_per_side,
        "event_windows": None,
        "veto": "none (l2.no_veto default)",
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
          f"trades(post stats_start)={r['trades']} ramp_upper={ramp_upper}")
    return r, tdf


def ledger_identity_check(a2_tdf: pd.DataFrame) -> bool:
    """T5 acceptance 2: A2 only scales notional — it never touches entries,
    exits, or veto (no event_windows, no veto_fn beyond the default no-op).
    The (coin, entry_ts, exit_ts) trade SET of `a2` must therefore equal the
    SET of Stage 1's own v1_trades.csv exactly (symmetric difference == 0).
    (A1's analogous T3 script has no such check because A1's own 禁新倉 rule
    deliberately removes entries — that check doesn't apply here.)"""
    print("\n--- ledger identity: a2 vs Stage-1 v1_trades.csv, (coin, entry_ts, exit_ts) set ---")
    v1 = pd.read_csv(B1_DIR / "v1_trades.csv", parse_dates=["entry_ts", "exit_ts"])
    a2 = a2_tdf.copy()
    a2["entry_ts"] = pd.to_datetime(a2["entry_ts"])
    a2["exit_ts"] = pd.to_datetime(a2["exit_ts"])
    set_v1 = set(zip(v1["coin"], v1["entry_ts"], v1["exit_ts"]))
    set_a2 = set(zip(a2["coin"], a2["entry_ts"], a2["exit_ts"]))
    sym_diff = set_v1 ^ set_a2
    print(f"  |v1|={len(set_v1)}  |a2|={len(set_a2)}  |symmetric difference|={len(sym_diff)}")
    if sym_diff:
        print(f"  sample diffs (up to 10): {list(sym_diff)[:10]}")
    ok = len(sym_diff) == 0
    print(f"ledger identity check: {'PASS' if ok else 'FAIL'}")
    return ok


def m_a2_distribution_summary(a2_tdf: pd.DataFrame) -> dict:
    """T5 acceptance 4: distribution of the entry-locked m_A2 over the `a2`
    run's own trades."""
    print("\n--- m_A2 distribution summary (a2 run, entry-locked) ---")
    s = a2_tdf["m_a2"]
    n = len(s)
    at_lo = int((np.isclose(s, 0.5)).sum())
    at_hi = int((np.isclose(s, 1.0)).sum())
    summary = {
        "n_trades": int(n),
        "min": float(s.min()), "median": float(s.median()), "max": float(s.max()),
        "n_eq_0.5": at_lo, "frac_eq_0.5": at_lo / n if n else float("nan"),
        "n_eq_1.0": at_hi, "frac_eq_1.0": at_hi / n if n else float("nan"),
    }
    print(f"  n_trades={n}  min={summary['min']:.6f}  median={summary['median']:.6f}  max={summary['max']:.6f}")
    print(f"  m_a2==0.5: {at_lo}/{n} ({summary['frac_eq_0.5']:.4%})")
    print(f"  m_a2==1.0: {at_hi}/{n} ({summary['frac_eq_1.0']:.4%})")
    return summary


def degenerate_check(frames, m_vol_fn) -> bool:
    """T5 acceptance 6: `a2` config wiring, with the A2 factor forced to the
    constant 1.0 (compose_m_fn(m_vol_fn, lambda *_: 1.0)), must reproduce
    data/cache/cta_l/v1.csv EXACTLY (elementwise) — isolates any real a2/v1
    delta to the A2 factor's actual (non-degenerate) values, not to the
    compose_m_fn/run_cell_l2 threading added in this script."""
    print("\n--- degenerate self-check: a2 wiring w/ m_A2 forced to 1.0 vs Stage-1 v1.csv ---")
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    m_fn = l2.compose_m_fn(m_vol_fn, lambda _coin, _ts: 1.0)
    r = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                        stats_start, window=MAIN_WINDOW, m_fn=m_fn,
                        slippage_per_side=STD_SLIPPAGE, fee_rate=STD_FEE,
                        event_windows=None, resize_enabled=False,
                        resize_factor=l2.A1_RESIZE_FACTOR)
    # float_precision="round_trip": see cta_l_stage2_runs_a1.py's identical
    # comment — pandas' default C float parser is not always bit-exact.
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
    print("degenerate self-check: PASS (a2 wiring w/ m_A2==1.0 == Stage-1 v1.csv, exact)")
    return True


def anchor_spot_check() -> bool:
    """T5 acceptance 5 (copied verbatim from T3's version): recompute B1
    full-window MAR/MDD/Sharpe from Stage-1's own v1.csv via the protocol
    §1/§2 fixed-basis formula, checked against the protocol §1 numeric
    anchors (rel tol 1e-9)."""
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
    print("=== T5: A2 (crowd-percentile signal-strength scaling) formal runs ===")
    print(f"A1 status: {A1_STATUS}")

    print(f"\nconfig: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}  crowd_on={CROWD_ON}  "
          f"universe={list(lib.SYMBOLS_5.values())}")
    print(f"main window: [{MAIN_WINDOW[0]:%Y-%m-%d} .. {MAIN_WINDOW[1]:%Y-%m-%d}]")
    print(f"standard cost: fee={STD_FEE*100:.4f}%/side + slippage={STD_SLIPPAGE*100:.4f}%/side "
          f"= {(STD_FEE+STD_SLIPPAGE)*100:.4f}%/side")
    print(f"cost x1.5 (G-A·3): fee={COST15_FEE*100:.4f}%/side + slippage={COST15_SLIPPAGE*100:.4f}%/side "
          f"= {(COST15_FEE+COST15_SLIPPAGE)*100:.4f}%/side")

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage (pre-window-slice): [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]")

    # B1's own m_vol table (protocol §3: m_total = m_vol * m_A2)
    print("\nbuilding B1 (V1) sigma/m table (reused unmodified for A2) ...")
    _, m_by_coin_v1 = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF)
    m_fn_v1 = l1.make_m_fn(m_by_coin_v1)

    print("building A2 pct lookup (frames[(coin,tf)]['lpct_raw'].shift(1)) ...")
    pct_lookup = build_pct_lookup(frames, lib.SYMBOLS_5, TF)

    manifest: dict[str, dict] = {}
    a2_tdf = None

    print("\n[1/7] a2 — main config (ramp 90..97), standard cost, main window, no events/veto")
    _, a2_tdf = write_run("a2", frames, m_fn_v1, RAMP_UPPER_MAIN, pct_lookup,
                           STD_SLIPPAGE, STD_FEE, MAIN_WINDOW, manifest)

    print("[2/7] a2_cost15 — cost x1.5 (G-A·3), main window")
    write_run("a2_cost15", frames, m_fn_v1, RAMP_UPPER_MAIN, pct_lookup,
              COST15_SLIPPAGE, COST15_FEE, MAIN_WINDOW, manifest)

    idx = 3
    for days_back in (30, 60, 90):
        w = ep_window(days_back)
        name = f"a2_ep{days_back}"
        print(f"[{idx}/7] {name}  window=[{w[0]:%Y-%m-%d}..{w[1]:%Y-%m-%d}]")
        write_run(name, frames, m_fn_v1, RAMP_UPPER_MAIN, pct_lookup,
                  STD_SLIPPAGE, STD_FEE, w, manifest)
        idx += 1

    print(f"[{idx}/7] a2_sens_p95 — ramp upper 97 -> 95 (only-report), main window")
    write_run("a2_sens_p95", frames, m_fn_v1, 95.0, pct_lookup,
              STD_SLIPPAGE, STD_FEE, MAIN_WINDOW, manifest)
    idx += 1

    print(f"[{idx}/7] a2_sens_p99 — ramp upper 97 -> 99 (only-report), main window")
    write_run("a2_sens_p99", frames, m_fn_v1, 99.0, pct_lookup,
              STD_SLIPPAGE, STD_FEE, MAIN_WINDOW, manifest)

    # ---- T5-specific in-script checks ----
    ok_ledger = ledger_identity_check(a2_tdf)
    dist = m_a2_distribution_summary(a2_tdf)
    ok_degen = degenerate_check(frames, m_fn_v1)
    ok_anchor = anchor_spot_check()

    print(f"\n--- pct<90 defense clause: {len(DEFENSE_LOG)} trigger(s) across all 7 runs "
          f"(expected 0) ---")
    if DEFENSE_LOG:
        for e in DEFENSE_LOG:
            print(f"  {e}")

    out_manifest = {
        "protocol_commit": PROTOCOL_COMMIT,
        "engine_commit": ENGINE_COMMIT,
        "engine_file": "scripts/cta_l_stage2.py",
        "a1_status": A1_STATUS,
        "a1_gates_md": A1_GATES_MD,
        "baseline_note": ("B1 csvs reused read-only from data/cache/cta_l/ "
                           "(v1.csv, v1_cost15.csv, v1_ep{30,60,90}.csv) — "
                           "not regenerated by this script; A1 NOT merged so "
                           "A2 baseline == B1 (not B1+A1)"),
        "a2_formula": "m_A2 = 0.5 + 0.5*min(1, (pct-90)/(ramp_upper-90)), pct = lpct_raw.shift(1) at entry",
        "runs": manifest,
        "checks": {
            "ledger_identity_a2_vs_v1": ok_ledger,
            "m_a2_distribution_a2": dist,
            "degenerate_self_check": ok_degen,
            "b1_anchor_spot_check": ok_anchor,
            "defense_clause_triggers": len(DEFENSE_LOG),
            "defense_clause_detail": DEFENSE_LOG,
        },
    }
    manifest_path = OUT_DIR / "manifest_a2.json"
    with open(manifest_path, "w") as f:
        json.dump(out_manifest, f, indent=2, default=str)
    print(f"\nwrote manifest: {manifest_path} ({len(manifest)} runs)")
    assert len(manifest) == 7, f"expected 7 A2 runs, got {len(manifest)}"

    all_ok = ok_ledger and ok_degen and ok_anchor
    print("\n=== T5 DONE: 7/7 A2 runs written, all in-script checks PASS ==="
          if all_ok else "\n=== T5 FAILED: see checks above ===")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
