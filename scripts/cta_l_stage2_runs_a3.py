"""Sub-project L Stage 2, plan T7 — A3 (BTC-200SMA regime downsizing) formal
runs.

Protocol (sole source of judgment): docs/superpowers/specs/2026-07-14-cta-l-
stage2-protocol.md §3 (m composition — A3 IS an m_f, composed with B1's own
m_vol: `m_total = m_vol * m_A3`, no extra global floor), §6 (A3 full
definition: BTC SMA regime signal, warmup clause, single BTC-derived signal
applied to every coin's entries, two "only-report" SMA-window sensitivities,
乘數 0.75 sensitivity CANCELLED — not run), §7 (G-A·3 cost co-scaling). Plan:
docs/superpowers/plans/2026-07-14-cta-l-stage2-plan.md T7-T8.

Baseline for A3 is B1 (Stage 1 V1), NOT B1+A1 and NOT B1+A2:
  - A1's own T4 gate table (data/cache/cta_l2/a1_gates.md): G-A·1 (DSR,
    N=11) = 0.4941 < 0.95 -> FAIL -> A1 not merged.
  - A2's own T6 gate table (data/cache/cta_l2/a2_gates.md): G-A·1 (DSR,
    N=14) = 0.0124 < 0.95 -> FAIL, G-A·2 = 1/6 folds < 4 -> FAIL -> A2 not
    merged.
Per protocol §7's judgment semantics ("任一不過 -> 該因子收檔、不重試變體、
繼續下一個 ablation"), the survivor baseline handed to A3 is therefore
still plain B1. A3 is judged against B1 directly, reusing
data/cache/cta_l/v1*.csv read-only exactly like T3/T5 did for A1/A2 (this
script never touches data/cache/cta_l/ or data/cache/cta_l2/a1*/a2*).

Engine: scripts/cta_l_stage2.py (commit 71009d3, six guards PASS). A3 has NO
event window and NO veto (protocol §6's factor is purely a multiplicative
m_f, exactly like A2) — every write_run() call below passes
event_windows=None (compute_in_window_mask degenerates to an all-False mask)
and the default veto_fn (l2.no_veto). resize_enabled is irrelevant with
event_windows=None but is passed False for clarity, matching a2's pattern.

Regime signal (protocol §6, "顯字" clause): BTC 4h close vs SMA(1200 bars =
200d), closed-bar, shift-by-one. SMA is computed on `frames[("BTC","4h")]`
BEFORE any window slicing — the FULL cached BTC frame (2019-09-08 start,
confirmed by build_frames()) — so the main window's start (2020-09-14) sees
a fully-warmed SMA (2228 bars of BTC history precede 2020-09-14, comfortably
> 1200 and > 1800 for the 300d sensitivity). Formula: at bar t, using
`close_{t-1}` and `SMA_{t-1}` (both evaluated one bar before t, i.e. the
regime state is a PIT-safe .shift(1) of a same-bar close-vs-SMA comparison —
identical shift convention to A2's `lpct_raw.shift(1)`):
  close_{t-1} > SMA_{t-1}  ->  m_A3 = 0.5  (risk-on, downsize)
  otherwise                ->  m_A3 = 1.0
  SMA_{t-1} undefined (warmup, <1200 bars of history at t-1) -> m_A3 = 1.0
Applied IDENTICALLY to every coin's entries — this is a single BTC-derived
regime signal, not a per-coin one (protocol §6: "所有幣的進場都用 BTC 的
regime 值"). The lookup dict is therefore built ONCE per SMA-bars config and
shared across all 5 coins' m_fn calls (coin argument ignored inside the A3
factor).

Sensitivities (protocol §6, "只呈報", exactly 2 — 乘數 0.75 sensitivity is
explicitly CANCELLED to hold each ablation's trial count at exactly 3, per
protocol §10's "不跑任何額外配置"): 100d = 600 bars, 300d = 1800 bars
(4h bars, 6/day).

Seven runs (plan T7, matching a1/a2's T3/T5 shape): a3, a3_cost15,
a3_ep{30,60,90} (all at the MAIN 1200-bar SMA config), a3_sens_sma100,
a3_sens_sma300 (main window, standard cost, SMA bars swapped to 600/1800).
Each writes a ({name}.csv daily $ pnl, {name}_trades.csv ledger) pair; the
trades csv carries the same base columns as Stage 1's ledger PLUS
`resize_events` (always `[]`, kept only for schema uniformity with the
a1/a2 tooling) and two A3-specific diagnostic columns, `m_a3`/`warmup_a3`
(the entry-locked A3 factor and whether it was assigned via the warmup
clause, recomputed post-hoc from the SAME regime lookup used inside the
run's own composed m_fn) so the T8 gate/verdict step can build the m_A3
distribution (plan T7-T8 acceptance 3) and warmup-trigger count (acceptance
4) without re-running the engine.

After the 7 runs, five in-script checks (printed, not written as files):
  - ledger identity (T7 acceptance 2, A3-specific — like A2, A3 only scales
    size, it never touches entries/exits/veto): the (coin, entry_ts,
    exit_ts) SET of the `a3` run's trades must equal the SET of Stage 1
    v1_trades.csv's trades exactly (symmetric difference == 0).
  - regime distribution (T7 acceptance 3): (a) BAR-level — fraction of main-
    window BTC bars whose (shift-locked) regime state is above-SMA
    (m_A3=0.5) vs at/below (m_A3=1.0, non-warmup) vs warmup, from the raw
    main-config (1200-bar) regime lookup restricted to the main window's
    index; (b) TRADE-level — fraction of the `a3` run's own entries whose
    locked m_a3 == 0.5 vs == 1.0.
  - warmup-trigger counts (T7 acceptance 4): reported separately for the
    main (1200-bar) config and each of the two sensitivity configs
    (600/1800-bar), counted over each config's own entries actually placed
    in a run using that config (expected 0 for all three, per the module
    docstring's warmup-clause note).
  - degenerate self-check (T7 acceptance 6): re-running the `a3` config with
    the A3 factor forced to the constant 1.0 (m_fn = compose_m_fn(m_vol_fn,
    lambda *_: 1.0)) must reproduce data/cache/cta_l/v1.csv EXACTLY
    (elementwise) — proves the wiring introduces no drift of its own.
  - B1 anchor spot-check (T7 acceptance 5, copied verbatim from T3/T5's
    version): MAR/MDD/Sharpe recomputed from data/cache/cta_l/v1.csv via the
    protocol §1/§2 fixed-basis formula, checked against the protocol §1
    numeric anchors at relative tolerance 1e-9.

Read-only except for data/cache/cta_l2/: only touches data/cache/cta_proxy/
(cached parquet input) and data/cache/cta_l/ (Stage 1 output, read-only).
No network calls, no .env* access, no orders. Does not import or modify
data/cache/cta_l2/a1*/a2* (A1/A2's own outputs, untouched).

Usage: .venv/bin/python scripts/cta_l_stage2_runs_a3.py
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
BTC_COIN = "BTC"
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
A2_GATES_MD = "data/cache/cta_l2/a2_gates.md"
A1_STATUS = "NOT MERGED (G-A.1 DSR FAIL, see a1_gates.md)"
A2_STATUS = "NOT MERGED (G-A.1 DSR FAIL + G-A.2 1/6 folds FAIL, see a2_gates.md)"
A3_BASELINE_NOTE = "A1 and A2 both failed to merge -> A3 baseline = B1 (not B1+A1, not B1+A2)"

# protocol §1 numeric anchors (B1 full window)
ANCHOR_MAR = 0.299355395590
ANCHOR_MDD = -0.152055268750
ANCHOR_SHARPE = 0.499956120997
ANCHOR_TOL_REL = 1e-9

SMA_BARS_MAIN = 1200     # 200d @ 4h x 6/day
SMA_BARS_100D = 600      # only-report sensitivity
SMA_BARS_300D = 1800     # only-report sensitivity

TRADE_COLS = ["coin", "entry_ts", "exit_ts", "side", "notional", "m", "m_a3",
              "warmup_a3", "pnl", "fees", "reason", "resize_events"]

WARMUP_LOG: list[dict] = []   # protocol §6 warmup clause: SMA_{t-1} undefined at an entry


def ep_window(days_back: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (MAIN_WINDOW[0], MAIN_WINDOW[1] - pd.Timedelta(days=days_back))


def build_regime_lookup(frames, sma_bars: int) -> dict[pd.Timestamp, tuple[float, bool]]:
    """protocol §6 regime source: BTC 4h close vs SMA(sma_bars), computed on
    the FULL cached BTC frame (frames[("BTC","4h")], pre-window-slice —
    2019-09-08 start, PIT-safe, all past data), then close_{t-1} > SMA_{t-1}
    (closed-bar, shift-by-one). Returns dict[bar-open ts] -> (m_a3, warmup),
    keyed by the SAME bar-open timestamp convention l1.make_m_fn()'s own
    per-coin lookup dicts use, so `pct_lookup[coin].get(entry_ts, ...)`-style
    access with entry_ts=idx[i] retrieves the value one bar prior — mirrors
    A2's build_pct_lookup() `.shift(1)` pattern exactly."""
    btc = frames[(BTC_COIN, TF)]
    close = btc["close"]
    sma = close.rolling(sma_bars, min_periods=sma_bars).mean()
    close_lag1 = close.shift(1)
    sma_lag1 = sma.shift(1)
    warmup = sma_lag1.isna()
    above = (~warmup) & (close_lag1 > sma_lag1)
    m = pd.Series(1.0, index=close.index)
    m[above] = 0.5
    return {ts: (float(mv), bool(wu)) for ts, mv, wu in
            zip(close.index, m.to_numpy(), warmup.to_numpy())}


def m_a3_value(regime_lookup: dict, entry_ts: pd.Timestamp) -> tuple[float, bool, bool]:
    """Single source of truth for both the live m_fn used inside the engine
    and the post-hoc CSV annotation columns. Returns (m_a3, warmup, missing).
    `missing` (entry_ts not in the BTC lookup at all) is a defensive branch
    only — BTC's frame comfortably covers the full main+ep window range with
    ~2228 bars of pre-window margin; if it ever fires it forces m_a3=1.0 and
    is logged exactly like a warmup trigger."""
    val = regime_lookup.get(entry_ts)
    if val is None:
        return 1.0, True, True
    m_a3, warmup = val
    return m_a3, warmup, False


def make_m_a3_fn(regime_lookup: dict, run_name: str):
    def m_fn(_coin: str, entry_ts: pd.Timestamp) -> float:
        # protocol §6: "所有幣的進場都用 BTC 的 regime 值" -- coin ignored,
        # single shared BTC-derived lookup for every coin's entries.
        m_a3, warmup, missing = m_a3_value(regime_lookup, entry_ts)
        if warmup or missing:
            WARMUP_LOG.append({"run": run_name, "coin": _coin,
                                "entry_ts": str(entry_ts), "missing": missing})
        return m_a3
    return m_fn


def write_run(name: str, frames, m_vol_fn, regime_lookup: dict,
              slippage_per_side: float, fee_rate: float, window, manifest: dict) -> tuple[dict, pd.DataFrame]:
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    m_a3_fn = make_m_a3_fn(regime_lookup, name)
    m_fn = l2.compose_m_fn(m_vol_fn, m_a3_fn)
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
        m_a3, warmup, _missing = m_a3_value(regime_lookup, ets)   # post-hoc annotation only
        trows.append({
            "coin": coin, "entry_ts": t["entry_time"], "exit_ts": t["exit_time"],
            "side": t["side"], "notional": t["notional"], "m": t["m"],
            "m_a3": m_a3, "warmup_a3": warmup,
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
          f"trades(post stats_start)={r['trades']}")
    return r, tdf


def ledger_identity_check(a3_tdf: pd.DataFrame) -> bool:
    """T7 acceptance 2: A3 only scales notional — it never touches entries,
    exits, or veto (no event_windows, no veto_fn beyond the default no-op,
    exactly like A2). The (coin, entry_ts, exit_ts) trade SET of the `a3`
    run must therefore equal the SET of Stage 1's own v1_trades.csv exactly
    (symmetric difference == 0)."""
    print("\n--- ledger identity: a3 vs Stage-1 v1_trades.csv, (coin, entry_ts, exit_ts) set ---")
    v1 = pd.read_csv(B1_DIR / "v1_trades.csv", parse_dates=["entry_ts", "exit_ts"])
    a3 = a3_tdf.copy()
    a3["entry_ts"] = pd.to_datetime(a3["entry_ts"])
    a3["exit_ts"] = pd.to_datetime(a3["exit_ts"])
    set_v1 = set(zip(v1["coin"], v1["entry_ts"], v1["exit_ts"]))
    set_a3 = set(zip(a3["coin"], a3["entry_ts"], a3["exit_ts"]))
    sym_diff = set_v1 ^ set_a3
    print(f"  |v1|={len(set_v1)}  |a3|={len(set_a3)}  |symmetric difference|={len(sym_diff)}")
    if sym_diff:
        print(f"  sample diffs (up to 10): {list(sym_diff)[:10]}")
    ok = len(sym_diff) == 0
    print(f"ledger identity check: {'PASS' if ok else 'FAIL'}")
    return ok


def regime_distribution_summary(regime_lookup_main: dict, a3_tdf: pd.DataFrame) -> dict:
    """T7 acceptance 3: (a) BAR-level distribution of the main-config
    (1200-bar) regime state, restricted to bars whose OWN timestamp falls
    inside the main window (i.e. the state that WOULD be assigned to an
    entry at that bar); (b) TRADE-level distribution of the `a3` run's own
    entry-locked m_a3 column."""
    print("\n--- regime distribution (main config, 1200-bar SMA) ---")
    bar_ts = np.array(list(regime_lookup_main.keys()))
    in_window = (bar_ts >= MAIN_WINDOW[0]) & (bar_ts <= MAIN_WINDOW[1])
    vals = np.array([regime_lookup_main[t] for t in bar_ts[in_window]], dtype=object)
    n_bar = len(vals)
    warmup_bar = sum(1 for _, w in vals if w)
    above_bar = sum(1 for m, w in vals if (not w) and np.isclose(m, 0.5))
    below_bar = n_bar - warmup_bar - above_bar
    print(f"  bar-level (main window, n={n_bar}): above-SMA(m=0.5)={above_bar} "
          f"({above_bar/n_bar:.4%})  at/below(m=1.0)={below_bar} ({below_bar/n_bar:.4%})  "
          f"warmup={warmup_bar} ({warmup_bar/n_bar:.4%})")

    s = a3_tdf["m_a3"]
    n_tr = len(s)
    at_lo = int((np.isclose(s, 0.5)).sum())
    at_hi = int((np.isclose(s, 1.0)).sum())
    print(f"  trade-level (a3 run entries, n={n_tr}): m_a3==0.5: {at_lo} ({at_lo/n_tr:.4%})  "
          f"m_a3==1.0: {at_hi} ({at_hi/n_tr:.4%})")

    return {
        "bar_level_main_window": {
            "n_bars": int(n_bar), "n_above_sma": int(above_bar),
            "frac_above_sma": above_bar / n_bar if n_bar else float("nan"),
            "n_at_or_below_sma": int(below_bar),
            "frac_at_or_below_sma": below_bar / n_bar if n_bar else float("nan"),
            "n_warmup": int(warmup_bar),
            "frac_warmup": warmup_bar / n_bar if n_bar else float("nan"),
        },
        "trade_level_a3_run": {
            "n_trades": int(n_tr),
            "n_eq_0.5": at_lo, "frac_eq_0.5": at_lo / n_tr if n_tr else float("nan"),
            "n_eq_1.0": at_hi, "frac_eq_1.0": at_hi / n_tr if n_tr else float("nan"),
        },
    }


def degenerate_check(frames, m_vol_fn) -> bool:
    """T7 acceptance 6: `a3` config wiring, with the A3 factor forced to the
    constant 1.0 (compose_m_fn(m_vol_fn, lambda *_: 1.0)), must reproduce
    data/cache/cta_l/v1.csv EXACTLY (elementwise) — isolates any real a3/v1
    delta to the A3 factor's actual (non-degenerate) values, not to the
    compose_m_fn/run_cell_l2 threading."""
    print("\n--- degenerate self-check: a3 wiring w/ m_A3 forced to 1.0 vs Stage-1 v1.csv ---")
    stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    m_fn = l2.compose_m_fn(m_vol_fn, lambda _coin, _ts: 1.0)
    r = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                        stats_start, window=MAIN_WINDOW, m_fn=m_fn,
                        slippage_per_side=STD_SLIPPAGE, fee_rate=STD_FEE,
                        event_windows=None, resize_enabled=False,
                        resize_factor=l2.A1_RESIZE_FACTOR)
    # float_precision="round_trip": pandas' default C float parser is not
    # always bit-exact (see cta_l_stage2_runs_a1.py's identical comment).
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
    print("degenerate self-check: PASS (a3 wiring w/ m_A3==1.0 == Stage-1 v1.csv, exact)")
    return True


def anchor_spot_check() -> bool:
    """T7 acceptance 5 (copied verbatim from T3/T5's version): recompute B1
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


def warmup_summary_by_config() -> dict:
    print(f"\n--- warmup/missing-lookup trigger counts by SMA config (expected 0 for all) ---")
    by_cfg: dict[str, int] = {}
    for e in WARMUP_LOG:
        cfg = e["run"]
        by_cfg[cfg] = by_cfg.get(cfg, 0) + 1
    # collapse per-run counts into the 3 distinct SMA configs used
    main_cfg_runs = {"a3", "a3_cost15", "a3_ep30", "a3_ep60", "a3_ep90"}
    n_main = sum(v for k, v in by_cfg.items() if k in main_cfg_runs)
    n_100d = by_cfg.get("a3_sens_sma100", 0)
    n_300d = by_cfg.get("a3_sens_sma300", 0)
    print(f"  main config (1200-bar, runs a3/a3_cost15/a3_ep30/60/90): {n_main} triggers")
    print(f"  sens 100d (600-bar, a3_sens_sma100): {n_100d} triggers")
    print(f"  sens 300d (1800-bar, a3_sens_sma300): {n_300d} triggers")
    if WARMUP_LOG:
        print(f"  detail (up to 20): {WARMUP_LOG[:20]}")
    return {"main_1200bar": n_main, "sens_100d_600bar": n_100d, "sens_300d_1800bar": n_300d,
            "by_run_raw": by_cfg}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== T7: A3 (BTC-200SMA regime downsizing) formal runs ===")
    print(f"A1 status: {A1_STATUS}")
    print(f"A2 status: {A2_STATUS}")
    print(f"A3 baseline: {A3_BASELINE_NOTE}")

    print(f"\nconfig: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}  crowd_on={CROWD_ON}  "
          f"universe={list(lib.SYMBOLS_5.values())}")
    print(f"main window: [{MAIN_WINDOW[0]:%Y-%m-%d} .. {MAIN_WINDOW[1]:%Y-%m-%d}]")
    print(f"standard cost: fee={STD_FEE*100:.4f}%/side + slippage={STD_SLIPPAGE*100:.4f}%/side "
          f"= {(STD_FEE+STD_SLIPPAGE)*100:.4f}%/side")
    print(f"cost x1.5 (G-A·3): fee={COST15_FEE*100:.4f}%/side + slippage={COST15_SLIPPAGE*100:.4f}%/side "
          f"= {(COST15_FEE+COST15_SLIPPAGE)*100:.4f}%/side")

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage (pre-window-slice): [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]")
    btc_full = frames[(BTC_COIN, TF)]
    print(f"BTC full cached frame: [{btc_full.index.min():%Y-%m-%d %H:%M} .. "
          f"{btc_full.index.max():%Y-%m-%d %H:%M}]  n={len(btc_full)}  "
          f"bars before main window start: {(btc_full.index < MAIN_WINDOW[0]).sum()}")

    # B1's own m_vol table (protocol §3: m_total = m_vol * m_A3)
    print("\nbuilding B1 (V1) sigma/m table (reused unmodified for A3) ...")
    _, m_by_coin_v1 = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF)
    m_fn_v1 = l1.make_m_fn(m_by_coin_v1)

    print(f"building A3 regime lookups: main={SMA_BARS_MAIN}bars(200d), "
          f"sens={SMA_BARS_100D}bars(100d)/{SMA_BARS_300D}bars(300d) ...")
    regime_main = build_regime_lookup(frames, SMA_BARS_MAIN)
    regime_100d = build_regime_lookup(frames, SMA_BARS_100D)
    regime_300d = build_regime_lookup(frames, SMA_BARS_300D)

    manifest: dict[str, dict] = {}
    a3_tdf = None

    print("\n[1/7] a3 — main config (SMA 1200 bars / 200d), standard cost, main window, no events/veto")
    _, a3_tdf = write_run("a3", frames, m_fn_v1, regime_main,
                           STD_SLIPPAGE, STD_FEE, MAIN_WINDOW, manifest)

    print("[2/7] a3_cost15 — cost x1.5 (G-A·3), main window, main SMA config")
    write_run("a3_cost15", frames, m_fn_v1, regime_main,
              COST15_SLIPPAGE, COST15_FEE, MAIN_WINDOW, manifest)

    idx = 3
    for days_back in (30, 60, 90):
        w = ep_window(days_back)
        name = f"a3_ep{days_back}"
        print(f"[{idx}/7] {name}  window=[{w[0]:%Y-%m-%d}..{w[1]:%Y-%m-%d}]  main SMA config")
        write_run(name, frames, m_fn_v1, regime_main,
                  STD_SLIPPAGE, STD_FEE, w, manifest)
        idx += 1

    print(f"[{idx}/7] a3_sens_sma100 — SMA 1200 -> 600 bars (100d, only-report), main window")
    write_run("a3_sens_sma100", frames, m_fn_v1, regime_100d,
              STD_SLIPPAGE, STD_FEE, MAIN_WINDOW, manifest)
    idx += 1

    print(f"[{idx}/7] a3_sens_sma300 — SMA 1200 -> 1800 bars (300d, only-report), main window")
    write_run("a3_sens_sma300", frames, m_fn_v1, regime_300d,
              STD_SLIPPAGE, STD_FEE, MAIN_WINDOW, manifest)

    # ---- T7-specific in-script checks ----
    ok_ledger = ledger_identity_check(a3_tdf)
    dist = regime_distribution_summary(regime_main, a3_tdf)
    ok_degen = degenerate_check(frames, m_fn_v1)
    ok_anchor = anchor_spot_check()
    warmup = warmup_summary_by_config()

    out_manifest = {
        "protocol_commit": PROTOCOL_COMMIT,
        "engine_commit": ENGINE_COMMIT,
        "engine_file": "scripts/cta_l_stage2.py",
        "a1_status": A1_STATUS,
        "a1_gates_md": A1_GATES_MD,
        "a2_status": A2_STATUS,
        "a2_gates_md": A2_GATES_MD,
        "baseline_note": ("B1 csvs reused read-only from data/cache/cta_l/ "
                           "(v1.csv, v1_cost15.csv, v1_ep{30,60,90}.csv) — "
                           "not regenerated by this script; " + A3_BASELINE_NOTE),
        "a3_formula": ("m_A3 = 0.5 if close_{t-1} > SMA_{t-1} (BTC 4h, SMA bars per "
                        "config) else 1.0; SMA_{t-1} undefined (warmup) -> m_A3 = 1.0; "
                        "single BTC-derived regime value applied to every coin's entries"),
        "sma_bars": {"main_200d": SMA_BARS_MAIN, "sens_100d": SMA_BARS_100D,
                     "sens_300d": SMA_BARS_300D},
        "runs": manifest,
        "checks": {
            "ledger_identity_a3_vs_v1": ok_ledger,
            "regime_distribution": dist,
            "degenerate_self_check": ok_degen,
            "b1_anchor_spot_check": ok_anchor,
            "warmup_trigger_counts": warmup,
        },
    }
    manifest_path = OUT_DIR / "manifest_a3.json"
    with open(manifest_path, "w") as f:
        json.dump(out_manifest, f, indent=2, default=str)
    print(f"\nwrote manifest: {manifest_path} ({len(manifest)} runs)")
    assert len(manifest) == 7, f"expected 7 A3 runs, got {len(manifest)}"

    all_ok = ok_ledger and ok_degen and ok_anchor
    print("\n=== T7 DONE: 7/7 A3 runs written, all in-script checks PASS ==="
          if all_ok else "\n=== T7 FAILED: see checks above ===")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
