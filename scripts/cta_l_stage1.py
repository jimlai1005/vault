"""Sub-project L Stage 1 — sizing-hook engine (plan T2).

This module is a COPY of two functions, not a modification of either source:
  - research_cta_positioning_phase2b.simulate()   -> simulate_l()
  - cta_proxy_lib.run_cell()                       -> run_cell_l()
Neither `scripts/cta_proxy_lib.py` nor `scripts/research_cta_positioning_phase2b.py`
is touched (live-engine freeze + phase-2b result comparability; see
docs/superpowers/plans/2026-07-13-cta-staged-sizing-plan.md T2 and
docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md §3).

Why a copy, not a hook into the original: `cta_proxy_lib.run_cell()` calls
`p2b.simulate(sig, side)` — `simulate()` never receives `coin` (run_cell only
stamps `t["coin"] = coin` onto each trade dict AFTER simulate() returns). A
sizing multiplier keyed on (coin, entry_ts) therefore cannot be injected into
the original call graph without editing p2b.simulate()'s signature, which is
off-limits. Copying preserves the audited original untouched and lets the new
engine be verified BIT-IDENTICAL against it (guard 0 below) instead of trusted.

Two additive parameters over the original simulate()/run_cell():
  m_fn(coin, entry_ts) -> float   entry-notional multiplier, locked for the
                                   life of the trade. Default `const_m` = 1.0
                                   everywhere (baseline / anchor behavior).
  slippage_per_side                fraction of notional, charged on entry AND
                                    exit in addition to the p2b fee rate.
                                    Default 1bp (0.0001); 0 disables it.

Every dollar computation that used the module constant NOTIONAL in
p2b.simulate() now uses `notional = NOTIONAL * m_fn(coin, entry_ts)`, locked
at entry (spec §3: "m 在部位存續期間鎖定於進場值"). Every fee computation that
used the fixed p2b.FEE_SIDE now uses `(FEE_RATE + slippage_per_side) *
notional` — cost is proportional to the ACTUAL (scaled) notional, not the
$100 baseline (spec §3 "成本掛載": fee 與 slippage 皆按實際 notional 計).
At m_fn≡const_m and slippage_per_side=0, notional≡NOTIONAL and cost_rate≡
FEE_RATE, so every arithmetic path reduces byte-for-byte to p2b.simulate()'s
(guard 0 in scripts/cta_l_stage1_selftest.py).

Config note: this module is NOT tied to any single (tf, pctile, fuel_lb, side)
— run_cell_l takes the same config args as cta_proxy_lib.run_cell. Stage 1's
actual runs (T4) all pin phase-2b's production config "4h-p10-fuel24-short"
(short-only; see reports/cta-golive-2026-07-04.md and
src/hlvault/cta/config.py ENABLE_LONG=false). The self-test below also uses
this pinned config, on the 5-coin universe (lib.SYMBOLS_5) and the spec's
hardcoded main window 2020-09-14T00:00Z -> 2026-06-30T00:00Z.

Not a standalone entrypoint: import `run_cell_l` / `simulate_l` from T4's
runner. Verification lives in scripts/cta_l_stage1_selftest.py.
"""
from __future__ import annotations

import math
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_proxy_lib as lib  # noqa: E402  (sys.path setup must precede this)

NOTIONAL = lib.NOTIONAL                    # $100/coin, identical to p2b
FEE_RATE = 0.00045                         # 0.045%/side — literal, matches p2b.py:61
                                            # `FEE_SIDE = 0.00045 * NOTIONAL` verbatim
STOP_ATR_MULT = lib.p2b.STOP_ATR_MULT
MAX_HOLD = lib.p2b.MAX_HOLD
DEFAULT_SLIPPAGE_PER_SIDE = 0.0001         # 1bp; spec §3 成本掛載 = 0.045% fee + 1bp
                                            # slippage = 0.055%/side

assert abs(FEE_RATE * NOTIONAL - lib.FEE_SIDE) < 1e-12, (
    "FEE_RATE literal has drifted from p2b.FEE_SIDE / p2b.NOTIONAL — "
    "guard-0 engine anchor would silently stop matching. Do not edit "
    "research_cta_positioning_phase2b.py; fix the literal here instead.")

MFn = Callable[[str, pd.Timestamp], float]


def const_m(_coin: str, _entry_ts: pd.Timestamp) -> float:
    """Default multiplier: always 1.0 (baseline notional; guard-0 anchor)."""
    return 1.0


def simulate_l(sig: pd.DataFrame, side: str, coin: str, m_fn: MFn = const_m,
                slippage_per_side: float = DEFAULT_SLIPPAGE_PER_SIDE,
                fee_rate: float = FEE_RATE):
    """Copy of p2b.simulate() with an entry-notional sizing hook.

    Returns (per-bar $ PnL Series, trade list) exactly like p2b.simulate();
    each trade dict additionally carries "notional", "m", "fees" (total
    entry+exit fee+slippage $, for the guard-4 hand-calc spot check).

    `fee_rate` (T4 addition, plan T4 / spec §3 G-L4): taker-fee-per-side
    fraction, additive with `slippage_per_side` into `cost_rate` exactly like
    before. Defaults to the module constant FEE_RATE, so every existing call
    site (T2/T3 selftests, guard 0 anchor, etc.) is byte-for-byte unaffected —
    this parameter exists ONLY so T4's cost-x1.5 runs (G-L4) can scale the fee
    component proportionally alongside slippage_per_side, instead of dumping
    the entire x1.5 delta onto slippage alone. Re-run both selftests after
    this change (T4 guard-0..4 regression) to confirm identical behavior at
    the default.
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

    def close_trade(i: int, exit_px: float, reason: str) -> float:
        d = pos["dir"]
        notional = pos["notional"]
        exit_cost = cost_rate * notional
        pnl = d * (exit_px - pos["mark"]) / pos["entry_px"] * notional - exit_cost
        net = (d * (exit_px - pos["entry_px"]) / pos["entry_px"] * notional
               - pos["entry_cost"] - exit_cost)
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[i],
                       "pnl": net, "reason": reason,
                       "notional": notional, "m": pos["m"],
                       "fees": pos["entry_cost"] + exit_cost})
        return pnl

    for i in range(len(sig)):
        pnl = 0.0
        exited_this_bar = False
        if pos is not None:
            d = pos["dir"]
            flip = (d == 1 and not tu[i]) or (d == -1 and not td[i])
            fuel_fail = not fk[i]
            too_long = idx[i] - pos["t0"] >= MAX_HOLD
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
                    pnl += d * (c[i] - pos["mark"]) / pos["entry_px"] * pos["notional"]
                    pos["mark"] = c[i]
        if pos is None and not exited_this_bar:             # re-entry next bar min
            want_s = side in ("short", "both") and td[i] and cl[i] and fk[i]
            want_l = side in ("long", "both") and tu[i] and cs[i] and fk[i]
            if (want_s or want_l) and not np.isnan(atr[i]) and atr[i] > 0:
                d = -1 if want_s else 1
                entry_px = o[i]
                stop = entry_px - d * STOP_ATR_MULT * atr[i]
                m = float(m_fn(coin, idx[i]))
                notional = NOTIONAL * m
                entry_cost = cost_rate * notional
                pos = {"dir": d, "entry_px": entry_px, "stop": stop,
                       "t0": idx[i], "mark": entry_px,
                       "notional": notional, "m": m, "entry_cost": entry_cost}
                pnl -= entry_cost
                hit = (d == -1 and h[i] >= stop) or (d == 1 and l[i] <= stop)
                if hit:                                     # stopped on entry bar
                    pnl += close_trade(i, stop, "stop")
                    pos = None
                else:
                    pnl += d * (c[i] - entry_px) / entry_px * notional
                    pos["mark"] = c[i]
        bar_pnl[i] = pnl
    if pos is not None:                                     # force-close at end
        exit_cost = cost_rate * pos["notional"]
        bar_pnl[-1] += -exit_cost
        d = pos["dir"]
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[-1],
                       "pnl": d * (c[-1] - pos["entry_px"]) / pos["entry_px"]
                              * pos["notional"] - pos["entry_cost"] - exit_cost,
                       "reason": "eod",
                       "notional": pos["notional"], "m": pos["m"],
                       "fees": pos["entry_cost"] + exit_cost})
    s = pd.Series(bar_pnl, index=idx)
    tsum = sum(t["pnl"] for t in trades)
    assert abs(s.sum() - tsum) < 1e-6, f"bar/trade pnl mismatch {s.sum()} vs {tsum}"
    return s, trades


def run_cell_l(frames, symbols, tf, side, crowd_on, p, fuel_lb, stats_start,
               split_at=None, window=None, m_fn: MFn = const_m,
               slippage_per_side: float = DEFAULT_SLIPPAGE_PER_SIDE,
               fee_rate: float = FEE_RATE):
    """Copy of cta_proxy_lib.run_cell(), threading `coin` + the sizing hook
    through to simulate_l() instead of calling p2b.simulate() directly.
    Signal construction (shifted_signals / crowd_off) is REUSED by reference
    from cta_proxy_lib — those functions have nothing to do with sizing/cost
    and copying them too would only add drift risk for zero benefit.

    `fee_rate`: see simulate_l() docstring (T4 addition); defaults to FEE_RATE
    so all pre-T4 callers are unaffected."""
    port_base = NOTIONAL * len(symbols)
    per_coin_daily = {}
    all_trades = []
    for sym, coin in symbols.items():
        sig = lib.shifted_signals(frames[(coin, tf)], p, fuel_lb)
        if window is not None:
            sig = sig.loc[window[0]:window[1]]
        if not crowd_on:
            sig = lib.crowd_off(sig)
        bar_pnl, trades = simulate_l(sig, side, coin, m_fn=m_fn,
                                      slippage_per_side=slippage_per_side,
                                      fee_rate=fee_rate)
        per_coin_daily[coin] = bar_pnl.resample("1D").sum()
        for t in trades:
            t["coin"] = coin
        all_trades.extend(trades)
    daily = pd.concat(per_coin_daily.values(), axis=1).fillna(0).sum(axis=1)
    sa = split_at if split_at is not None else stats_start  # noqa: F841 (kept for parity with cta_proxy_lib.run_cell, which also leaves this unused)
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


# ---------------------------------------------------------------------------
# T3: per-position vol-target sigma / multiplier (plan T3; spec §2-§3)
# ---------------------------------------------------------------------------
# Builds the m_fn(coin, entry_ts) table consumed by simulate_l()/run_cell_l()
# above. This section only ADDS new functions — simulate_l/run_cell_l/const_m
# above are untouched (T2's guard-0/1/2/3 regression is re-run unmodified by
# scripts/cta_l_stage1_selftest.py as T3's guard 4; see
# scripts/cta_l_stage1_selftest_t3.py).

BARS_PER_YEAR_4H = 2190.0                  # 365 * 24 / 4 — spec §3 "年化 ×√2190"
SIGMA_TARGET = 0.60                        # spec §3 main config (60% annualized)
SIGMA_SPAN = 180                           # bars (~30 days of 4h bars)
SIGMA_CLIP_LO = 0.25
SIGMA_CLIP_HI = 1.0


def _ewma_log_return_vol(close: pd.Series, span: int,
                          bars_per_year: float) -> pd.Series:
    """Zero-mean EWMA volatility of closed-bar log returns, explicit
    recursion — deliberately NOT pandas `.ewm().std()`. pandas' EWM std
    mean-centers the series (tracks an EWM mean of returns, then an EWM
    variance around that moving mean) AND applies an internal small-sample
    bias-correction factor (a running sum-of-weights adjustment) whose
    per-step formula is opaque without reading pandas' Cython source — that
    would make an independent hand/spot check meaningless (any bug would
    reproduce identically if "independent" verification just re-derives the
    same opaque formula). This function instead uses the standard
    RiskMetrics-style ZERO-MEAN EWMA variance estimator — appropriate for
    short-horizon (4h) returns whose mean is negligible next to their
    variance, and trivial to reimplement independently for T3 guard 1:

        alpha  = 2 / (span + 1)                       (pandas' own span<->alpha
                                                         mapping, adjust=False)
        r_i    = ln(close_i / close_{i-1})             bar i's log return —
                                                         known at the CLOSE of
                                                         bar i (uses close_i
                                                         and close_{i-1} only)
        var_1  = r_1^2                                  seed: first return
        var_i  = (1-alpha)*var_{i-1} + alpha*r_i^2      i >= 2
        sigma_raw_i = sqrt(var_i) * sqrt(bars_per_year)

    Returns sigma_raw indexed exactly like `close`. Position i's value
    already incorporates bar i's OWN close/return (r_i) — the closed-bar /
    shift-by-one discipline that excludes the entry bar's own data from ITS
    OWN sizing decision is applied by the caller via `.shift(1)`, identical
    to how cta_proxy_lib.shifted_signals() shifts trend_up/crowd_long/atr
    one bar before they're usable at a decision point.
    """
    alpha = 2.0 / (span + 1)
    px = close.to_numpy(dtype=float)
    n = len(px)
    log_ret = np.full(n, np.nan)
    log_ret[1:] = np.log(px[1:] / px[:-1])
    var_raw = np.full(n, np.nan)
    for i in range(1, n):
        r2 = log_ret[i] * log_ret[i]
        prev = var_raw[i - 1]
        var_raw[i] = r2 if np.isnan(prev) else (1 - alpha) * prev + alpha * r2
    sigma_raw = np.sqrt(var_raw) * math.sqrt(bars_per_year)
    return pd.Series(sigma_raw, index=close.index)


def build_sigma_m(frames: dict, symbols: dict[str, str], tf: str = "4h", *,
                   sigma_target: float = SIGMA_TARGET, span: int = SIGMA_SPAN,
                   clip_lo: float = SIGMA_CLIP_LO, clip_hi: float = SIGMA_CLIP_HI,
                   warmup_bars: int | None = None,
                   bars_per_year: float = BARS_PER_YEAR_4H,
                   ) -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
    """Spec §3 V1 sizing: per-coin sigma_i,t and entry-notional multiplier
    m_i,t = clip(sigma_target / sigma_i,t, clip_lo, clip_hi).

    closed-bar + shift-by-one (spec §3 "closed-bar、shift-by-one（進場當 bar
    不含自身）"): the sigma value USED for a decision AT bar i is the EWMA
    computed through bar i-1's close only, i.e.
    `_ewma_log_return_vol(close, span, bars_per_year).shift(1)` — the same
    one-bar-shift convention cta_proxy_lib.shifted_signals() applies to
    trend_up/crowd_long/fuel_ok/atr. The entry bar's own close therefore
    never feeds its own sizing decision (T3 guard 2 spot-checks this).

    warmup (spec §3 "warmup 前 180 bars m=1.0"): the first `warmup_bars` bars
    BY POSITION in the coin's full frame (frames[(coin, tf)] — i.e. counted
    from the start of the cached history, the same convention
    cta_proxy_lib.py uses for TREND_WARMUP_BARS) get m=1.0 regardless of the
    EWMA value. warmup_bars defaults to `span` when not given: that's the
    natural "not enough history yet" boundary for a span-N EWMA, and matches
    spec's literal numbers (180/180) for the main config; sensitivity configs
    (span=90/360) scale warmup with them unless a caller overrides.

    Returns (sigma_by_coin, m_by_coin): dict[coin] -> pd.Series, each indexed
    exactly like frames[(coin, tf)].index — the coin's FULL, unsliced frame.
    Callers that window-slice a run (e.g. run_cell_l's `window=` arg) look
    values up by timestamp via make_m_fn(), exactly like every other signal
    column in this codebase; slicing rows afterward does not change values.
    sigma_by_coin carries the POST-shift ("as used") sigma — NaN for the
    first 2 bars (no prior return exists yet) and the real EWMA value
    thereafter, UNAFFECTED by the warmup override (which only clamps m, not
    sigma itself). This is what T3 guard 1/2 check and what the guard-3
    distribution summary is built from (via m_by_coin).
    """
    if warmup_bars is None:
        warmup_bars = span
    sigma_by_coin: dict[str, pd.Series] = {}
    m_by_coin: dict[str, pd.Series] = {}
    for sym, coin in symbols.items():
        close = frames[(coin, tf)]["close"]
        sigma_raw = _ewma_log_return_vol(close, span, bars_per_year)
        sigma_used = sigma_raw.shift(1)
        m_used = (sigma_target / sigma_used).clip(lower=clip_lo, upper=clip_hi)
        m_arr = m_used.to_numpy(dtype=float)
        warmup_mask = np.arange(len(close)) < warmup_bars
        m_arr[warmup_mask] = 1.0
        sigma_by_coin[coin] = sigma_used
        m_by_coin[coin] = pd.Series(m_arr, index=close.index)
    return sigma_by_coin, m_by_coin


def make_m_fn(m_by_coin: dict[str, pd.Series]) -> MFn:
    """Wrap a build_sigma_m() m table as an m_fn(coin, entry_ts) -> float for
    simulate_l()/run_cell_l(). "m 在部位存續期間鎖定於進場值" (spec §3) falls
    out for free from simulate_l()'s own call pattern: it calls m_fn exactly
    once per trade, at the entry bar (`m = float(m_fn(coin, idx[i]))`), and
    stores the result in pos["m"] for the rest of the trade's life — this
    closure is never re-queried mid-trade."""
    lookup = {coin: s.to_dict() for coin, s in m_by_coin.items()}

    def m_fn(coin: str, entry_ts: pd.Timestamp) -> float:
        return float(lookup[coin][entry_ts])

    return m_fn
