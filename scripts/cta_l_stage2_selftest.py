"""Sub-project L Stage 2, plan T2 — regression + new-mechanism guards for
scripts/cta_l_stage2.py (simulate_l2 / run_cell_l2 / compose_m_fn /
compute_in_window_mask), per docs/superpowers/plans/2026-07-14-cta-l-stage2-plan.md
T2 and docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md §8.

Six guards (task T2 acceptance list, mapping onto protocol §8 items 1-3):

  1. Degenerate identity  no veto, no event windows, m_f≡1.0: run_cell_l2's
                          `daily` output vs Stage 1 run_cell_l's `daily`,
                          assert_frame_equal(check_exact=True) — same style
                          as cta_l_stage1_selftest.py's own guard 0/1.
  2. Stage 1 regression   re-run BOTH Stage 1 selftest scripts unmodified
                          (subprocess) — proves T2 did not alter
                          cta_l_stage1.py's behavior (T2 only imports it).
  3. New identity         a real-data run WITH event windows active (so
                          resize/restore actually fires): Σ full-window daily
                          $ pnl == Σ all trades' pnl (1e-6) — protocol §4's
                          replacement for Stage 1's single-notional identity.
  4. 2-bar synthetic scenario  hand-built OHLC path, one short trade that
                          enters, holds through a resize AND a restore, then
                          exits on a flip — every bar's bar_pnl, both resize
                          costs, and the final trade record are independently
                          hand-computed and compared bit-for-bit (float
                          tolerance 1e-9) against the engine's output. This
                          is the protocol §8.2 numeric anchor for mtm
                          attribution ("resize bar 用縮放前 notional，次一
                          bar 起用縮放後").
  5. A1 resize cost hand spot-check  same real-data run as guard 3; take one
                          trade with a non-empty resize_events list, hand-
                          recompute each event's cost from its own recorded
                          (prev_notional, new_effective_notional) and cross-
                          check against the engine's cost field AND against
                          fees = entry+exit+Σresize (<1e-9). Uses a synthetic
                          test event calendar (data/events/us_macro_calendar.csv
                          is a separate, not-yet-committed T1 deliverable this
                          guard does not depend on).
  6. A2 same-source assert  real data, all 5 coins: the engine's shifted
                          `crowd_long` boolean == `lpct_raw.shift(1) >= 90`
                          computed independently from the raw frame, entrywise
                          (protocol §5's executable same-source guard for the
                          not-yet-implemented A2 factor — this only checks
                          the DATA SOURCE identity, not any A2 code).

Read-only: only touches data/cache/cta_proxy/*.parquet (local cache). No
network calls, no orders, no .env* access. Writes nothing to
data/cache/cta_l2/ (T2 is engine-only; T3 runs are a separate task).

Usage: .venv/bin/python scripts/cta_l_stage2_selftest.py
"""
from __future__ import annotations

import math
import subprocess
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
WINDOW = (pd.Timestamp("2020-09-14"), pd.Timestamp("2026-06-30"))


def main() -> int:
    print("=== T2 self-test: scripts/cta_l_stage2.py (simulate_l2/run_cell_l2) guards ===")
    print(f"config: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}  crowd_on={CROWD_ON}  "
          f"universe={list(lib.SYMBOLS_5.values())}")
    print(f"window: [{WINDOW[0]:%Y-%m-%d} .. {WINDOW[1]:%Y-%m-%d}]\n")

    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage (pre-window-slice): [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]")
    stats_start = (WINDOW[0] + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    print(f"stats_start: {stats_start:%Y-%m-%d}\n")

    all_pass = True

    # ------------------------------------------------- Guard 1: degenerate identity
    print("--- Guard 1: degenerate identity (no veto, no event windows, m_f=1.0) ---")
    r_stage1 = l1.run_cell_l(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                              FUEL_LB, stats_start, window=WINDOW)
    r_stage2 = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                               FUEL_LB, stats_start, window=WINDOW)
    orig_daily = r_stage1["daily"].rename("ret").to_frame()
    new_daily = r_stage2["daily"].rename("ret").to_frame()
    try:
        pd.testing.assert_frame_equal(orig_daily, new_daily, check_exact=True)
        g1_frame_ok = True
        print(f"assert_frame_equal(check_exact=True): PASS  ({len(orig_daily)} daily rows compared)")
    except AssertionError as e:
        g1_frame_ok = False
        print(f"assert_frame_equal(check_exact=True): FAIL\n{e}")
    g1_scalar_ok = (r_stage1["pnl"] == r_stage2["pnl"]
                    and r_stage1["sharpe"] == r_stage2["sharpe"]
                    and r_stage1["mdd_pct"] == r_stage2["mdd_pct"]
                    and r_stage1["trades"] == r_stage2["trades"])
    print(f"scalar cross-check (pnl/sharpe/mdd/trades all ==): {'PASS' if g1_scalar_ok else 'FAIL'}")
    print(f"  stage1: pnl={r_stage1['pnl']:.6f} sharpe={r_stage1['sharpe']:.6f} "
          f"mdd%={r_stage1['mdd_pct']:.6f} trades={r_stage1['trades']}")
    print(f"  stage2: pnl={r_stage2['pnl']:.6f} sharpe={r_stage2['sharpe']:.6f} "
          f"mdd%={r_stage2['mdd_pct']:.6f} trades={r_stage2['trades']}")
    guard1_ok = g1_frame_ok and g1_scalar_ok
    all_pass = all_pass and guard1_ok
    print(f"Guard 1: {'PASS' if guard1_ok else 'FAIL'}\n")

    # ------------------------------------------------- Guard 2: Stage 1 regression
    print("--- Guard 2: Stage 1 selftests re-run unmodified (subprocess) ---")
    guard2_ok = True
    for name in ("cta_l_stage1_selftest.py", "cta_l_stage1_selftest_t3.py"):
        proc = subprocess.run([sys.executable, str(_SCRIPTS / name)],
                               capture_output=True, text=True)
        ok = proc.returncode == 0
        guard2_ok = guard2_ok and ok
        print(f"  {name}: exit={proc.returncode} {'PASS' if ok else 'FAIL'}")
        if not ok:
            print(f"  --- stdout tail ---\n{proc.stdout[-2000:]}")
            print(f"  --- stderr tail ---\n{proc.stderr[-2000:]}")
    all_pass = all_pass and guard2_ok
    print(f"Guard 2: {'PASS' if guard2_ok else 'FAIL'}\n")

    # ------------------------------------------- shared real-data run for 3 & 5
    print("--- building a synthetic (non-official) test event calendar for guards 3 & 5 ---")
    # A dense, purely-mechanical test calendar (NOT the official FOMC/CPI csv,
    # which is a separate T1 deliverable this script does not depend on):
    # one 30h window [ts-24h, ts+6h] every 10 days across the main window,
    # wide/frequent enough that real trades (avg hold well under MAX_HOLD=14d)
    # are very likely to straddle at least one window.
    anchors = pd.date_range(WINDOW[0] + pd.Timedelta(days=5), WINDOW[1], freq="10D")
    test_windows = [(a - pd.Timedelta(hours=24), a + pd.Timedelta(hours=6)) for a in anchors]
    print(f"  {len(test_windows)} synthetic test windows, 30h each, 10d cadence")

    r_evt = l2.run_cell_l2(frames, lib.SYMBOLS_5, TF, SIDE, CROWD_ON, PCTILE,
                            FUEL_LB, stats_start, window=WINDOW,
                            event_windows=test_windows, resize_enabled=True)
    resized_trades = [t for t in r_evt["all_trades"] if t["resize_events"]]
    print(f"  run: {len(r_evt['all_trades'])} total trades, "
          f"{len(resized_trades)} with >=1 resize_event\n")

    # ------------------------------------------------- Guard 3: new identity
    print("--- Guard 3: new identity (Σ full-window daily $ == Σ all trades' pnl, 1e-6) ---")
    sum_daily = float(r_evt["daily"].sum())
    sum_trades = float(sum(t["pnl"] for t in r_evt["all_trades"]))
    diff = abs(sum_daily - sum_trades)
    guard3_ok = diff < 1e-6
    print(f"  Σ daily $ pnl (full window, unfiltered) = {sum_daily:.8f}")
    print(f"  Σ trade.pnl  (all_trades, unfiltered)    = {sum_trades:.8f}")
    print(f"  |diff| = {diff:.3e}  (tol 1e-6): {'PASS' if guard3_ok else 'FAIL'}")
    all_pass = all_pass and guard3_ok
    print(f"Guard 3: {'PASS' if guard3_ok else 'FAIL'}\n")

    # ------------------------------------------- Guard 4: 2-bar synthetic scenario
    print("--- Guard 4: 2-bar synthetic scenario (hand-computed resize+restore anchor) ---")
    guard4_ok = _guard4_synthetic_scenario()
    all_pass = all_pass and guard4_ok
    print(f"Guard 4: {'PASS' if guard4_ok else 'FAIL'}\n")

    # --------------------------------------- Guard 5: A1 resize cost hand spot-check
    print("--- Guard 5: A1 resize cost hand spot-check (one real resized trade) ---")
    guard5_ok = False
    if not resized_trades:
        print("  FAIL: no resized trades found in the synthetic-calendar run "
              "(cannot spot-check) — widen/densify test_windows")
    else:
        sample = sorted(resized_trades, key=lambda t: (t["coin"], t["entry_time"]))[0]
        cost_rate = l1.FEE_RATE + l1.DEFAULT_SLIPPAGE_PER_SIDE
        print(f"  trade: coin={sample['coin']} entry={sample['entry_time']} "
              f"exit={sample['exit_time']} notional(locked)={sample['notional']:.4f} "
              f"m={sample['m']}  #resize_events={len(sample['resize_events'])}")
        events_ok = True
        manual_resize_cost_total = 0.0
        for ev in sample["resize_events"]:
            manual_cost = cost_rate * abs(ev["new_effective_notional"] - ev["prev_notional"])
            manual_resize_cost_total += manual_cost
            ev_ok = abs(manual_cost - ev["cost"]) < 1e-9
            events_ok = events_ok and ev_ok
            print(f"    ts={ev['ts']} prev={ev['prev_notional']:.6f} "
                  f"new={ev['new_effective_notional']:.6f} "
                  f"engine_cost={ev['cost']:.8f} manual_cost={manual_cost:.8f} "
                  f"{'PASS' if ev_ok else 'FAIL'}")
        manual_entry_cost = cost_rate * sample["notional"]
        # exit cost = fees - entry_cost - Σresize costs (fees is the only field
        # that carries the exit cost directly; recovered here for the spot check)
        implied_exit_cost = sample["fees"] - manual_entry_cost - manual_resize_cost_total
        manual_fees_total = manual_entry_cost + manual_resize_cost_total + implied_exit_cost
        fees_ok = abs(manual_fees_total - sample["fees"]) < 1e-9
        print(f"  manual entry_cost=0.055%*notional(entry) ... "
              f"Σresize_cost={manual_resize_cost_total:.8f}  "
              f"implied_exit_cost(from fees)={implied_exit_cost:.8f}")
        print(f"  engine fees={sample['fees']:.8f}  manual fees "
              f"(entry+Σresize+implied_exit)={manual_fees_total:.8f}  "
              f"match(<1e-9): {'PASS' if fees_ok else 'FAIL'}")
        guard5_ok = events_ok and fees_ok
    all_pass = all_pass and guard5_ok
    print(f"Guard 5: {'PASS' if guard5_ok else 'FAIL'}\n")

    # --------------------------------------------- Guard 6: A2 same-source assert
    print("--- Guard 6: A2 same-source assert (crowd_long == lpct_raw.shift(1)>=90, all coins) ---")
    guard6_ok = True
    for sym, coin in lib.SYMBOLS_5.items():
        raw = frames[(coin, TF)]
        sig = lib.shifted_signals(raw, PCTILE, FUEL_LB)
        expected = (raw["lpct_raw"].shift(1) >= (100 - PCTILE)).fillna(False)
        actual = sig["crowd_long"]
        match = bool((actual == expected).all())
        n_true = int(actual.sum())
        guard6_ok = guard6_ok and match
        print(f"  {coin:5s}: n_bars={len(actual)}  crowd_long_true={n_true}  "
              f"elementwise match: {'PASS' if match else 'FAIL'}")
        if not match:
            mism = actual[actual != expected]
            print(f"    mismatches: {len(mism)}  sample idx: {list(mism.index[:5])}")
    all_pass = all_pass and guard6_ok
    print(f"Guard 6: {'PASS' if guard6_ok else 'FAIL'}\n")

    print("=== SUMMARY ===")
    print(f"Guard 1 (degenerate identity)          : {'PASS' if guard1_ok else 'FAIL'}")
    print(f"Guard 2 (Stage 1 regression)           : {'PASS' if guard2_ok else 'FAIL'}")
    print(f"Guard 3 (new identity, Sigma daily==Sigma trade.pnl) : {'PASS' if guard3_ok else 'FAIL'}")
    print(f"Guard 4 (2-bar synthetic scenario)     : {'PASS' if guard4_ok else 'FAIL'}")
    print(f"Guard 5 (A1 resize cost hand spot-check): {'PASS' if guard5_ok else 'FAIL'}")
    print(f"Guard 6 (A2 same-source assert)        : {'PASS' if guard6_ok else 'FAIL'}")
    print(f"\nALL GUARDS: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


def _guard4_synthetic_scenario() -> bool:
    """Hand-built 6-bar OHLC path, side='short', one trade spanning:
      bar0  entry (short)
      bar1  hold, pre-window
      bar2  hold, FIRST in-window bar  -> resize fires at this bar's close
      bar3  hold, still in-window (no transition; already resized)
      bar4  hold, FIRST out-of-window bar -> restore fires at this bar's close
      bar5  flip exit (open price)
    Every bar_pnl value and the final trade record (resize_events, fees, pnl)
    below are computed by hand in this function's comments and asserted
    against cta_l_stage2.simulate_l2()'s actual output, tol 1e-9.
    """
    T0 = pd.Timestamp("2024-01-01T00:00:00")
    idx = pd.date_range(T0, periods=6, freq="4h")
    # open, high, low, close per bar (short trade: profit as price falls)
    o = [100.0, 99.0, 98.0, 97.0, 96.0, 94.0]
    h = [102.0, 101.0, 99.0, 98.0, 97.0, 96.0]
    lo = [99.0, 97.0, 96.0, 95.0, 94.0, 93.0]
    c = [99.0, 98.0, 97.0, 96.0, 95.0, 93.0]
    trend_dn = [True, True, True, True, True, False]   # flip=True at bar5
    trend_up = [False] * 6
    crowd_long = [True] * 6     # only bar0 matters (want_s requires crowd_long)
    crowd_short = [False] * 6   # unused (side="short" only reads crowd_long)
    fuel_ok = [True] * 6
    atr = [5.0] * 6             # constant; only bar0's value is used (entry stop)

    sig = pd.DataFrame({
        "open": o, "high": h, "low": lo, "close": c,
        "trend_up": trend_up, "trend_dn": trend_dn,
        "crowd_long": crowd_long, "crowd_short": crowd_short,
        "fuel_ok": fuel_ok, "atr": atr,
    }, index=idx)

    # event window covers bar2 & bar3's CLOSE times (T0+12h, T0+16h) but not
    # bar1's (T0+8h) or bar4's (T0+20h) -> in_win = [F, F, T, T, F, F]
    event_windows = [(T0 + pd.Timedelta(hours=10), T0 + pd.Timedelta(hours=18))]

    bar_pnl, trades = l2.simulate_l2(sig, "short", "TEST", event_windows=event_windows)

    cost_rate = l1.FEE_RATE + l1.DEFAULT_SLIPPAGE_PER_SIDE   # 0.045%+0.01% = 0.055%
    notional = l1.NOTIONAL                                    # 100.0 (m_fn default 1.0)
    entry_cost = cost_rate * notional                         # 0.055
    d = -1                                                     # short

    # --- hand-computed segments (d * (px_to - px_from) / entry_px * eff_notional) ---
    seg0 = d * (c[0] - o[0]) / o[0] * notional                # entry bar: 99->100? no: (c0-entry_px)
    # entry_px = o[0] = 100; seg0 uses (c[0]-entry_px)
    seg0 = d * (c[0] - o[0]) / o[0] * notional                 # = -1*(99-100)/100*100 = 1.0
    seg1 = d * (c[1] - c[0]) / o[0] * notional                 # bar1 hold, pre-window, notional=100
    resize_cost = cost_rate * abs(notional * 0.5 - notional)   # |50-100|*cost_rate = 0.0275
    seg2 = d * (c[2] - c[1]) / o[0] * notional                 # bar2's OWN mtm uses PRE-resize (100)
    seg3 = d * (c[3] - c[2]) / o[0] * (notional * 0.5)         # bar3 uses POST-resize (50)
    restore_cost = cost_rate * abs(notional - notional * 0.5)  # 0.0275
    seg4 = d * (c[4] - c[3]) / o[0] * (notional * 0.5)         # bar4's OWN mtm uses PRE-restore (50)
    exit_cost = cost_rate * notional                           # post-restore eff = 100 again
    seg5 = d * (o[5] - c[4]) / o[0] * notional                 # exit segment: open[5] vs mark(=c[4])

    expected_bar_pnl = [
        seg0 - entry_cost,             # bar0
        seg1,                          # bar1
        seg2 - resize_cost,            # bar2 (mtm at old notional, then resize cost)
        seg3,                          # bar3 (mtm at new/resized notional, no transition)
        seg4 - restore_cost,           # bar4 (mtm at old/resized notional, then restore cost)
        seg5 - exit_cost,              # bar5 (exit segment - exit cost)
    ]
    expected_mtm_accum = seg0 + seg1 + seg2 + seg3 + seg4 + seg5
    expected_fees = entry_cost + resize_cost + restore_cost + exit_cost
    expected_trade_pnl = expected_mtm_accum - expected_fees

    ok = True
    engine_bar_pnl = bar_pnl.to_numpy().tolist()
    for i, (exp, got) in enumerate(zip(expected_bar_pnl, engine_bar_pnl)):
        d_ = abs(exp - got)
        bar_ok = d_ < 1e-9
        ok = ok and bar_ok
        print(f"  bar{i}: expected={exp:.8f} engine={got:.8f} |diff|={d_:.2e} "
              f"{'PASS' if bar_ok else 'FAIL'}")

    assert len(trades) == 1, f"expected exactly 1 trade, got {len(trades)}"
    t = trades[0]
    print(f"  trade reason={t['reason']} (expect 'flip')  "
          f"{'PASS' if t['reason'] == 'flip' else 'FAIL'}")
    ok = ok and (t["reason"] == "flip")

    print(f"  #resize_events: engine={len(t['resize_events'])} expected=2  "
          f"{'PASS' if len(t['resize_events']) == 2 else 'FAIL'}")
    ok = ok and (len(t["resize_events"]) == 2)
    if len(t["resize_events"]) == 2:
        ev1, ev2 = t["resize_events"]
        ev1_ok = (abs(ev1["prev_notional"] - notional) < 1e-9
                  and abs(ev1["new_effective_notional"] - notional * 0.5) < 1e-9
                  and abs(ev1["cost"] - resize_cost) < 1e-9)
        ev2_ok = (abs(ev2["prev_notional"] - notional * 0.5) < 1e-9
                  and abs(ev2["new_effective_notional"] - notional) < 1e-9
                  and abs(ev2["cost"] - restore_cost) < 1e-9)
        print(f"  resize_events[0] (resize) : prev={ev1['prev_notional']:.4f} "
              f"new={ev1['new_effective_notional']:.4f} cost={ev1['cost']:.8f} "
              f"{'PASS' if ev1_ok else 'FAIL'}")
        print(f"  resize_events[1] (restore): prev={ev2['prev_notional']:.4f} "
              f"new={ev2['new_effective_notional']:.4f} cost={ev2['cost']:.8f} "
              f"{'PASS' if ev2_ok else 'FAIL'}")
        ok = ok and ev1_ok and ev2_ok

    fees_ok = abs(t["fees"] - expected_fees) < 1e-9
    pnl_ok = abs(t["pnl"] - expected_trade_pnl) < 1e-9
    print(f"  fees: expected={expected_fees:.8f} engine={t['fees']:.8f} "
          f"{'PASS' if fees_ok else 'FAIL'}")
    print(f"  pnl : expected={expected_trade_pnl:.8f} engine={t['pnl']:.8f} "
          f"{'PASS' if pnl_ok else 'FAIL'}")
    ok = ok and fees_ok and pnl_ok

    notional_locked_ok = t["notional"] == notional and t["m"] == 1.0
    print(f"  locked notional/m unchanged by resize: notional={t['notional']} m={t['m']} "
          f"{'PASS' if notional_locked_ok else 'FAIL'}")
    ok = ok and notional_locked_ok

    sum_bar_pnl = float(bar_pnl.sum())
    identity_ok = abs(sum_bar_pnl - t["pnl"]) < 1e-9
    print(f"  bonus: Sigma bar_pnl={sum_bar_pnl:.8f} vs trade.pnl={t['pnl']:.8f} "
          f"{'PASS' if identity_ok else 'FAIL'}")
    ok = ok and identity_ok

    return ok


if __name__ == "__main__":
    sys.exit(main())
