"""Sub-project L Stage 2 — engine extension (plan T2).

Protocol (sole source of judgment, followed to the formula/number-anchor
level): docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md §3
(multiplier composition), §4 (A1 event-window resize), §5 (A2 same-source
assert), §8 (guards). Plan: docs/superpowers/plans/2026-07-14-cta-l-stage2-plan.md.

This module ADDS to `scripts/cta_l_stage1.py` (`simulate_l`/`run_cell_l`)
without modifying it — `cta_l_stage1.py`'s own functions are only imported
here (plan T2 redline: "不修改 Stage 1 產出腳本的既有函式行為"). Three new
mechanisms, layered on top of Stage 1's sizing-hook engine:

  1. entry veto hook — `veto_fn(coin, entry_ts) -> bool`, default always
     False. Independent of (and additive to) the A1 event-window "禁新倉"
     rule below; either one vetoes an entry signal.
  2. A1 event-window notional resize/restore — protocol §4. A position open
     across the close of the first "in-window" bar has its EFFECTIVE
     notional (not its locked entry notional) scaled to
     `resize_factor * locked_notional` (default 0.5); it is restored to the
     locked notional at the close of the first bar after the window ends.
     Each transition charges a ONE-SIDED cost on |Δnotional| at the prevailing
     `cost_rate` (so a G-A·3 cost-x1.5 run scales resize costs too, for free,
     since it is the same `cost_rate` used for entry/exit).
  3. multiplier composition — protocol §3: `m_total = m_vol * Π m_f`, no
     extra global floor. Implemented as `compose_m_fn()`, a tiny wrapper that
     multiplies factor callables together into the single `m_fn` callable
     `simulate_l2`/`run_cell_l2` already accept (same shape as Stage 1's
     `m_fn` parameter) — the combination logic lives OUTSIDE the per-bar
     loop, not inside it.

Bar-close timing / mtm attribution (protocol §4, "mtm 歸屬（釘死）"), and WHY
the code is structured this way:

  Every exit path (flip/fuel/maxhold/stop) in Stage 1's simulate_l is decided
  from the PREVIOUS bar's shifted signal and executes at THIS bar's OPEN price
  (or intrabar for stops) — i.e. conceptually "before" this bar's close. The
  window resize/restore transition, by contrast, is explicitly a bar-CLOSE
  event ("進入窗的第一根窗內 bar 收盤時..."). Stage 1's branch structure
  already isolates the one case that reaches a bar's close as a still-open
  position — the innermost `else` ("hold: mark to close") branch, the only
  place that does `pos["mark"] = c[i]`. This module's resize/restore check
  therefore lives ONLY inside that branch:
    - bar i's own mtm segment is computed FIRST, using the notional in effect
      BEFORE this bar's transition (protocol: "bar i 自身的 mark-to-market用
      resize前的有效notional") — captured into a local `eff` before any
      mutation.
    - the transition (if the window-membership mask flips relative to the
      position's current `resized` state) is applied AFTER that segment is
      booked: cost charged, `effective_notional` updated for bar i+1 onward.
  Consequence (unforced, falls out of the above): if a position exits on the
  bar that would otherwise be the first out-of-window bar, the restore never
  gets a chance to run (exit branches never touch resize state) — it exits at
  whatever effective notional was already in force. This matches protocol's
  explicit "若部位於窗內觸發出場...不再恢復" for the in-window case, and is
  the internally-consistent extension of the same bar-close-vs-bar-open
  timing model for the symmetric first-bar-out-of-window case (protocol does
  not spell this second case out explicitly; this is the one place T2 makes
  a judgment call beyond the literal text — flagged here for review).

  Entries themselves can never land on an in-window bar (protocol "禁新倉"),
  so a fresh position always starts with `resized=False` and its own entry-
  bar mark can never coincide with a transition — no special-casing needed
  there.

Ledger schema (protocol §4, ledger schema paragraph — dictated verbatim):
  `notional` = entry-locked notional (never rewritten by a resize).
  `m`        = entry-locked m_total (never rewritten).
  `resize_events` = list[dict] (ts, prev_notional, new_effective_notional,
                    cost); ts is the bar-open timestamp of the transition bar
                    (same convention as entry_time/exit_time).
  `fees`     = entry cost + exit cost + Σ resize/restore costs.
  `pnl`      = Σ per-segment mark-to-market − fees, accumulated segment by
               segment (NOT the Stage-1 closed-form telescoped
               `d*(exit-entry)/entry*notional`, which is only valid when
               notional is constant for the trade's whole life). This is
               deliberately NOT required to be bit-identical to Stage 1's
               trade-level `pnl` field in the degenerate case (float
               addition is not associative) — only the identity
               `Σ daily×base == Σ trade.pnl` (protocol §4, 1e-6) and the
               bar-level `daily` Series (guard 1, exact) are load-bearing.

At `event_windows=None`/`[]`, `veto_fn` default, `m_fn` default (≡1.0): every
arithmetic expression below reduces to the EXACT SAME operation sequence as
`cta_l_stage1.simulate_l`/`run_cell_l` (same operands, same order) — bit-
identical `daily` output (guard 1 in scripts/cta_l_stage2_selftest.py).

Not a standalone entrypoint: import `simulate_l2`/`run_cell_l2` from a
runner. Verification lives in scripts/cta_l_stage2_selftest.py.
"""
from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_l_stage1 as l1     # noqa: E402  (sys.path setup must precede this)
import cta_proxy_lib as lib   # noqa: E402

MFn = l1.MFn                                   # Callable[[str, pd.Timestamp], float]
VetoFn = Callable[[str, pd.Timestamp], bool]
EventWindow = tuple[pd.Timestamp, pd.Timestamp]

BAR_WIDTH_4H = pd.Timedelta(hours=4)
A1_RESIZE_FACTOR = 0.5                         # protocol §4 main config


def no_veto(_coin: str, _entry_ts: pd.Timestamp) -> bool:
    """Default entry-veto hook: never vetoes (T2 default; A1's own 禁新倉
    rule is separate and unconditional whenever event_windows is non-empty,
    see compute_in_window_mask() + the entry gate below)."""
    return False


def compose_m_fn(*factor_fns: MFn) -> MFn:
    """Protocol §3: m_total(coin, entry_ts) = m_vol × Π m_f (no extra global
    floor beyond each factor's own clip). Each factor_fn is queried once, at
    entry, exactly like simulate_l2 already queries the single composed
    result once at entry (locked for the trade's life). With zero factor_fns
    the returned callable is the identity 1.0 (same as l1.const_m)."""
    def m_fn(coin: str, entry_ts: pd.Timestamp) -> float:
        p = 1.0
        for f in factor_fns:
            p *= float(f(coin, entry_ts))
        return p
    return m_fn


def compute_in_window_mask(idx: pd.DatetimeIndex,
                            event_windows: Sequence[EventWindow] | None,
                            bar_width: pd.Timedelta = BAR_WIDTH_4H) -> np.ndarray:
    """Protocol §4 bar-alignment: bar i's OPEN time is idx[i]; bar i is
    "in-window" iff its CLOSE time (idx[i] + bar_width) falls in the CLOSED
    interval [start, end] of ANY event window. Testing membership against
    every window's raw interval (rather than pre-merging overlapping/adjacent
    windows into a union first) already IS the union — a bar's in-window
    status is True iff at least one window covers it — so multi-event
    overlap/adjacency (protocol: "多事件窗以閉區間取聯集... 整段只執行一次
    縮放/恢復循環") requires no separate merge step: the resize/restore
    logic in simulate_l2 only fires on a mask VALUE TRANSITION, so a
    continuous True run (however many windows contributed to it) resizes
    once at its first bar and restores once at its first False bar after."""
    if not event_windows:
        return np.zeros(len(idx), dtype=bool)
    close_times = idx + bar_width
    mask = np.zeros(len(idx), dtype=bool)
    for start, end in event_windows:
        mask |= (close_times >= start) & (close_times <= end)
    return mask


def simulate_l2(sig: pd.DataFrame, side: str, coin: str, *,
                 m_fn: MFn = l1.const_m,
                 slippage_per_side: float = l1.DEFAULT_SLIPPAGE_PER_SIDE,
                 fee_rate: float = l1.FEE_RATE,
                 veto_fn: VetoFn = no_veto,
                 event_windows: Sequence[EventWindow] | None = None,
                 resize_enabled: bool = True,
                 resize_factor: float = A1_RESIZE_FACTOR):
    """Stage-1 simulate_l() + entry veto + A1 event-window resize/restore.

    Returns (per-bar $ PnL Series, trade list) like simulate_l(); trade
    dicts additionally carry "resize_events" (list[dict], see module
    docstring "Ledger schema"). `resize_enabled=False` implements protocol
    §4's "只禁新倉、不縮舊倉" sensitivity variant: entries are still vetoed
    on in-window bars (禁新倉 is unconditional whenever event_windows is
    given) but no resize/restore transition ever fires.
    """
    idx = sig.index
    o, h, l, c = (sig[k].to_numpy() for k in ("open", "high", "low", "close"))
    tu, td = sig["trend_up"].to_numpy(), sig["trend_dn"].to_numpy()
    cl, cs = sig["crowd_long"].to_numpy(), sig["crowd_short"].to_numpy()
    fk = sig["fuel_ok"].to_numpy()
    atr = sig["atr"].to_numpy()
    bar_pnl = np.zeros(len(sig))
    trades: list[dict] = []
    pos: dict | None = None
    cost_rate = fee_rate + slippage_per_side
    in_win = compute_in_window_mask(idx, event_windows)

    def close_trade(i: int, exit_px: float, reason: str) -> float:
        d = pos["dir"]
        eff = pos["effective_notional"]
        exit_cost = cost_rate * eff
        seg = d * (exit_px - pos["mark"]) / pos["entry_px"] * eff
        pos["mtm_accum"] += seg
        pos["fees_accum"] += exit_cost
        net = pos["mtm_accum"] - pos["fees_accum"]
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[i],
                       "pnl": net, "reason": reason,
                       "notional": pos["notional"], "m": pos["m"],
                       "fees": pos["fees_accum"],
                       "resize_events": pos["resize_events"]})
        return seg - exit_cost

    for i in range(len(sig)):
        pnl = 0.0
        exited_this_bar = False
        if pos is not None:
            d = pos["dir"]
            flip = (d == 1 and not tu[i]) or (d == -1 and not td[i])
            fuel_fail = not fk[i]
            too_long = idx[i] - pos["t0"] >= l1.MAX_HOLD
            if flip or fuel_fail or too_long:
                reason = "flip" if flip else ("fuel" if fuel_fail else "maxhold")
                pnl += close_trade(i, o[i], reason)
                pos, exited_this_bar = None, True
            else:                                           # intrabar hard stop
                stop_px = None
                if d == -1 and h[i] >= pos["stop"]:
                    stop_px = o[i] if o[i] >= pos["stop"] else pos["stop"]
                elif d == 1 and l[i] <= pos["stop"]:
                    stop_px = o[i] if o[i] <= pos["stop"] else pos["stop"]
                if stop_px is not None:
                    pnl += close_trade(i, stop_px, "stop")
                    pos, exited_this_bar = None, True
                else:                                       # hold: mark to close
                    eff = pos["effective_notional"]
                    seg = d * (c[i] - pos["mark"]) / pos["entry_px"] * eff
                    pnl += seg
                    pos["mtm_accum"] += seg
                    cur_in_win = bool(in_win[i])
                    if resize_enabled and cur_in_win and not pos["resized"]:
                        new_eff = pos["notional"] * resize_factor
                        cost = cost_rate * abs(new_eff - eff)
                        pos["resize_events"].append({
                            "ts": idx[i], "prev_notional": eff,
                            "new_effective_notional": new_eff, "cost": cost})
                        pos["fees_accum"] += cost
                        pnl -= cost
                        pos["effective_notional"] = new_eff
                        pos["resized"] = True
                    elif resize_enabled and (not cur_in_win) and pos["resized"]:
                        new_eff = pos["notional"]
                        cost = cost_rate * abs(new_eff - eff)
                        pos["resize_events"].append({
                            "ts": idx[i], "prev_notional": eff,
                            "new_effective_notional": new_eff, "cost": cost})
                        pos["fees_accum"] += cost
                        pnl -= cost
                        pos["effective_notional"] = new_eff
                        pos["resized"] = False
                    pos["mark"] = c[i]
        if pos is None and not exited_this_bar:             # re-entry next bar min
            want_s = side in ("short", "both") and td[i] and cl[i] and fk[i]
            want_l = side in ("long", "both") and tu[i] and cs[i] and fk[i]
            entry_vetoed = bool(in_win[i]) or bool(veto_fn(coin, idx[i]))
            if (want_s or want_l) and not entry_vetoed and not np.isnan(atr[i]) and atr[i] > 0:
                d = -1 if want_s else 1
                entry_px = o[i]
                stop = entry_px - d * l1.STOP_ATR_MULT * atr[i]
                m = float(m_fn(coin, idx[i]))
                notional = l1.NOTIONAL * m
                entry_cost = cost_rate * notional
                pos = {"dir": d, "entry_px": entry_px, "stop": stop,
                       "t0": idx[i], "mark": entry_px,
                       "notional": notional, "m": m,
                       "effective_notional": notional, "resized": False,
                       "fees_accum": entry_cost, "mtm_accum": 0.0,
                       "resize_events": []}
                pnl -= entry_cost
                hit = (d == -1 and h[i] >= stop) or (d == 1 and l[i] <= stop)
                if hit:                                     # stopped on entry bar
                    pnl += close_trade(i, stop, "stop")
                    pos = None
                else:
                    seg = d * (c[i] - entry_px) / entry_px * notional
                    pnl += seg
                    pos["mtm_accum"] += seg
                    pos["mark"] = c[i]
        bar_pnl[i] = pnl
    if pos is not None:                                     # force-close at end
        eff = pos["effective_notional"]
        exit_cost = cost_rate * eff
        bar_pnl[-1] += -exit_cost
        pos["fees_accum"] += exit_cost
        net = pos["mtm_accum"] - pos["fees_accum"]
        d = pos["dir"]
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[-1],
                       "pnl": net, "reason": "eod",
                       "notional": pos["notional"], "m": pos["m"],
                       "fees": pos["fees_accum"],
                       "resize_events": pos["resize_events"]})
    s = pd.Series(bar_pnl, index=idx)
    tsum = sum(t["pnl"] for t in trades)
    assert abs(s.sum() - tsum) < 1e-6, f"bar/trade pnl mismatch {s.sum()} vs {tsum}"
    return s, trades


def run_cell_l2(frames, symbols, tf, side, crowd_on, p, fuel_lb, stats_start,
                 split_at=None, window=None, *,
                 m_fn: MFn = l1.const_m,
                 slippage_per_side: float = l1.DEFAULT_SLIPPAGE_PER_SIDE,
                 fee_rate: float = l1.FEE_RATE,
                 veto_fn: VetoFn = no_veto,
                 event_windows: Sequence[EventWindow] | None = None,
                 resize_enabled: bool = True,
                 resize_factor: float = A1_RESIZE_FACTOR):
    """Copy of cta_l_stage1.run_cell_l(), threading the T2 hooks through to
    simulate_l2() instead of simulate_l(). Signal construction is reused by
    reference from cta_proxy_lib, exactly like run_cell_l does."""
    port_base = l1.NOTIONAL * len(symbols)
    per_coin_daily = {}
    all_trades = []
    for sym, coin in symbols.items():
        sig = lib.shifted_signals(frames[(coin, tf)], p, fuel_lb)
        if window is not None:
            sig = sig.loc[window[0]:window[1]]
        if not crowd_on:
            sig = lib.crowd_off(sig)
        bar_pnl, trades = simulate_l2(sig, side, coin, m_fn=m_fn,
                                       slippage_per_side=slippage_per_side,
                                       fee_rate=fee_rate, veto_fn=veto_fn,
                                       event_windows=event_windows,
                                       resize_enabled=resize_enabled,
                                       resize_factor=resize_factor)
        per_coin_daily[coin] = bar_pnl.resample("1D").sum()
        for t in trades:
            t["coin"] = coin
        all_trades.extend(trades)
    daily = pd.concat(per_coin_daily.values(), axis=1).fillna(0).sum(axis=1)
    sa = split_at if split_at is not None else stats_start  # noqa: F841 (parity w/ Stage 1)
    d = daily.loc[stats_start:]
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    tstat = mu / sd * math.sqrt(n) if sd > 0 else 0.0
    eq = port_base + d.cumsum()
    mdd = float((eq / eq.cummax() - 1.0).min())
    tr = [t for t in all_trades if t["exit_time"] >= stats_start]
    return {
        "pnl": d.sum(), "ret_pct": d.sum() / port_base * 100.0,
        "sharpe": sharpe, "tstat": tstat, "mdd_pct": mdd * 100.0,
        "trades": len(tr), "pf": lib.profit_factor(tr),
        "win_pct": (np.mean([t["pnl"] > 0 for t in tr]) * 100.0) if tr else 0.0,
        "daily": daily, "n_days": n, "port_base": port_base,
        "all_trades": all_trades,          # UNFILTERED (incl. pre-stats_start)
        "per_coin_daily": per_coin_daily,  # UNFILTERED per-coin daily pnl series
    }
