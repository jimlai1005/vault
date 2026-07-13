"""Sub-project L Stage 1, plan T3 — regression-guard self-test for the
sigma/multiplier builder in scripts/cta_l_stage1.py (build_sigma_m /
make_m_fn), per docs/superpowers/plans/2026-07-13-cta-staged-sizing-plan.md
T3 and docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md §2/§3.

Guard 1  Hand-calc match     3 (coin, position) points (>=2 coins, all past
                              warmup), independently recomputed with a
                              from-scratch, plain-Python recursion (NOT
                              calling build_sigma_m()/_ewma_log_return_vol()
                              again, NOT calling pandas .ewm()) — abs diff
                              from the engine's sigma must be < 1e-9.
Guard 2  No-lookahead         for one arbitrary t past warmup: blank every
                              bar strictly AFTER t to NaN and rebuild sigma/m
                              from scratch — the value AT t must be
                              bit-identical to the unblanked run.
Guard 3  m distribution       per-coin + pooled min/median/max, %m==1.0,
                              %m==0.25 (clip-floor) over the spec §2 main
                              window — reporting only, not a gate (verdict
                              input, per plan T3 驗收 3).
Guard 4  T2 regression         re-run scripts/cta_l_stage1_selftest.py (the
                              T2 sizing-hook engine guards) unmodified, to
                              demonstrate T3 did not alter simulate_l /
                              run_cell_l / const_m behavior.

Read-only: only touches data/cache/cta_proxy/*.parquet (local cache). No
network calls, no orders, no .env* access.

Usage: .venv/bin/python scripts/cta_l_stage1_selftest_t3.py
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
import cta_proxy_lib as lib   # noqa: E402

TF, FUEL_LB = "4h", 24
WINDOW = (pd.Timestamp("2020-09-14"), pd.Timestamp("2026-06-30"))


def hand_calc_sigma(closes: pd.Series, span: int, bars_per_year: float,
                     t_pos: int) -> float:
    """From-scratch, pure-Python (no numpy vectorization, no pandas .ewm(),
    no call into cta_l_stage1._ewma_log_return_vol) recursion implementing
    ONLY the spec §2/§3 formula, to compute the shift-by-one sigma value
    seen by a decision AT bar position `t_pos` — i.e. the EWMA accumulated
    through bar (t_pos - 1)'s close (bar t_pos's own close excluded)."""
    alpha = 2.0 / (span + 1)
    px = closes.to_numpy(dtype=float).tolist()
    upto = t_pos - 1                      # last raw index whose return feeds this value
    var = None
    for i in range(1, upto + 1):
        r = math.log(px[i] / px[i - 1])
        r2 = r * r
        var = r2 if var is None else (1 - alpha) * var + alpha * r2
    if var is None:
        return float("nan")
    return math.sqrt(var) * math.sqrt(bars_per_year)


def _print_m_summary(label: str, m: pd.Series) -> None:
    m = m.dropna()
    n = len(m)
    at_1 = float((m >= 1.0 - 1e-12).mean() * 100.0) if n else float("nan")
    at_floor = float((m <= 0.25 + 1e-12).mean() * 100.0) if n else float("nan")
    print(f"  {label:14s} n={n:6d}  min={m.min():.4f}  median={m.median():.4f}  "
          f"max={m.max():.4f}  %m==1.0={at_1:6.2f}%  %m==0.25={at_floor:6.2f}%")


def main() -> int:
    print("=== T3 self-test: build_sigma_m / make_m_fn (scripts/cta_l_stage1.py) ===")
    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    print(f"raw frame coverage: [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]")
    print(f"main config: sigma_target={l1.SIGMA_TARGET} span={l1.SIGMA_SPAN} "
          f"clip=[{l1.SIGMA_CLIP_LO},{l1.SIGMA_CLIP_HI}] "
          f"bars_per_year={l1.BARS_PER_YEAR_4H}\n")

    sigma_by_coin, m_by_coin = l1.build_sigma_m(frames, lib.SYMBOLS_5, TF)
    all_pass = True

    # --------------------------------------------------- Guard 1: hand-calc
    print("--- Guard 1: hand-calc EWMA sigma match (3 points, independent recursion) ---")
    coins = list(lib.SYMBOLS_5.values())
    close_by_coin = {c: frames[(c, TF)]["close"] for c in coins}
    # NOTE: per-coin frame lengths differ (each coin's frame spans ITS OWN
    # full available history, e.g. BTC's Binance listing predates DOGE/XRP's
    # by years — build_frames() does not crop individual frames to the
    # cross-coin intersection, only w_start/w_end report that intersection).
    # Every position below is therefore computed from that COIN's own length,
    # and anchored to spec §2's actual Stage-1 window start so the 3 spot
    # checks land where m_fn() is actually queried during a real run (not
    # somewhere in a coin's pre-window history that a windowed run never
    # touches).
    n_by_coin = {c: len(close_by_coin[c]) for c in coins}
    win_start_pos = {c: int(close_by_coin[c].index.searchsorted(WINDOW[0]))
                      for c in coins}
    check_points = [
        (coins[0], win_start_pos[coins[0]] + l1.SIGMA_SPAN + 50),  # just past warmup, in-window
        (coins[1], (win_start_pos[coins[1]] + n_by_coin[coins[1]]) // 2),  # mid-window
        (coins[2], n_by_coin[coins[2]] - 100),                     # near the end (in-window)
    ]
    rows = []
    for coin, pos in check_points:
        ts = close_by_coin[coin].index[pos]
        engine_sigma = float(sigma_by_coin[coin].iloc[pos])
        hand_sigma = hand_calc_sigma(close_by_coin[coin], l1.SIGMA_SPAN,
                                      l1.BARS_PER_YEAR_4H, pos)
        diff = abs(engine_sigma - hand_sigma)
        ok = diff < 1e-9
        rows.append(ok)
        print(f"  coin={coin:4s} pos={pos:5d} ts={ts}  engine_sigma={engine_sigma:.12f}  "
              f"hand_sigma={hand_sigma:.12f}  |diff|={diff:.3e}  {'PASS' if ok else 'FAIL'}")
    guard1_ok = all(rows)
    all_pass = all_pass and guard1_ok
    print(f"Guard 1: {'PASS' if guard1_ok else 'FAIL'}\n")

    # ------------------------------------------------ Guard 2: no-lookahead
    print("--- Guard 2: no-lookahead spot check (blank all bars after t, recompute) ---")
    coin_g2 = coins[0]
    n_g2 = n_by_coin[coin_g2]
    t_pos = n_g2 // 3
    close_orig = close_by_coin[coin_g2]
    ts_t = close_orig.index[t_pos]
    sigma_before = float(sigma_by_coin[coin_g2].loc[ts_t])
    m_before = float(m_by_coin[coin_g2].loc[ts_t])

    blanked = close_orig.copy()
    blanked.iloc[t_pos + 1:] = np.nan
    blanked_frame = frames[(coin_g2, TF)].copy()
    blanked_frame["close"] = blanked
    frames_blanked = dict(frames)                      # shallow copy of outer dict
    frames_blanked[(coin_g2, TF)] = blanked_frame       # only this coin's frame mutated
    sigma_by_coin_b, m_by_coin_b = l1.build_sigma_m(frames_blanked, {"X": coin_g2}, TF)
    sigma_after = float(sigma_by_coin_b[coin_g2].loc[ts_t])
    m_after = float(m_by_coin_b[coin_g2].loc[ts_t])

    sigma_match = (sigma_before == sigma_after) or (math.isnan(sigma_before) and math.isnan(sigma_after))
    m_match = m_before == m_after
    guard2_ok = sigma_match and m_match
    all_pass = all_pass and guard2_ok
    print(f"  coin={coin_g2} t_pos={t_pos} ts={ts_t}  (n_bars_blanked_after_t={n_g2 - 1 - t_pos})")
    print(f"  sigma: before={sigma_before!r} after={sigma_after!r} match={sigma_match}")
    print(f"  m    : before={m_before!r} after={m_after!r} match={m_match}")
    print(f"Guard 2: {'PASS' if guard2_ok else 'FAIL'}\n")

    # -------------------------------------------- Guard 3: m distribution
    print("--- Guard 3: full-window m distribution (reporting only, not a gate) ---")
    pooled = []
    for coin in coins:
        m_win = m_by_coin[coin].loc[WINDOW[0]:WINDOW[1]]
        pooled.append(m_win)
        _print_m_summary(coin, m_win)
    pooled_all = pd.concat(pooled)
    _print_m_summary("ALL (pooled)", pooled_all)
    print()

    # ------------------------------------------------- Guard 4: regression
    print("--- Guard 4: T2 regression (re-run cta_l_stage1_selftest.py unmodified) ---")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "cta_l_stage1_selftest.py")],
        capture_output=True, text=True)
    print(proc.stdout[-2500:])
    if proc.stderr:
        print("--- stderr (tail) ---")
        print(proc.stderr[-2000:])
    guard4_ok = proc.returncode == 0
    all_pass = all_pass and guard4_ok
    print(f"Guard 4: {'PASS' if guard4_ok else 'FAIL'} (T2 selftest exit code {proc.returncode})\n")

    print("=== SUMMARY ===")
    print(f"Guard 1 (hand-calc sigma match)   : {'PASS' if guard1_ok else 'FAIL'}")
    print(f"Guard 2 (no-lookahead spot check) : {'PASS' if guard2_ok else 'FAIL'}")
    print(f"Guard 3 (m distribution)          : reported above (not a gate)")
    print(f"Guard 4 (T2 regression)           : {'PASS' if guard4_ok else 'FAIL'}")
    print(f"\nALL GATED GUARDS (1,2,4): {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
