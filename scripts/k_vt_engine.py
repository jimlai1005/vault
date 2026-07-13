"""Momentum-VT v1 risk-control sizing engine (sub-project K, Task 1).

Pure function library, no main. Protocol (the executable law for this file):
docs/superpowers/specs/2026-07-13-momentum-vt-v1-protocol.md §1. Built on top
of scripts/research_momentum_voltarget.py's verified-no-lookahead vol-target
engine; hlvault.momentum.signals is reused unmodified ("signal 零改動" —
composite_score / daily_log_returns / position_signal are imported, not
re-derived), and hlvault.momentum.risk's risk_budget_per_coin /
target_position_notional supply the base (pre-cap) per-coin dollar target,
same as the existing backtest/live engines (CLAUDE.md #5: one implementation).

Five fixed-order sizing layers, all daily, causal under the STANDARD lag
convention (owner-confirmed 2026-07-13): a position is decided at day t's
close, its inputs (signal and Sigma) may use data through day t's own
close, and it earns day t+1's return — the SAME convention already audited
as no-lookahead in research_momentum_voltarget.py: a day's PnL is booked
using YESTERDAY's target notional against TODAY's return, and only THEN is
a new target computed from data through today's close, to be held starting
tomorrow:

    raw_w -> rc_cap -> cluster_cap -> vol_scale -> dd_ladder

Sigma convention: the rolling SAMPLE COVARIANCE matrix of daily log returns
(ddof=1, lookback = the grid's vol/cov lookback parameter), so `w` in
rc_cap/cluster_cap/vol_scale is always a WEIGHT FRACTION of equity (not a
dollar notional) -- w_i @ Sigma @ w_j has units of daily portfolio-return
variance only when w is in fraction-of-equity units. Callers holding dollar
targets must divide by equity before calling into this module and multiply
back afterward (see `sizing_pipeline` for the reference conversion).

Deliberate deviation from the protocol's literal one-shot cap formula
--------------------------------------------------------------------
The protocol states rc_cap/cluster_cap as: "shrink the violating weight(s)
by sqrt(cap/RC_i), recompute". Implemented literally (and even iterated),
this formula is provably insufficient in exactly the kind of case the unit
tests below construct: shrinking a subset S also shrinks total portfolio
variance (the RC denominator), which partially cancels the numerator's
shrinkage. Worked example (see test_cluster_cap_binds_cluster_to_75pct):
BTC/ETH/SOL start at 90% aggregate RC vs. a 4th coin at 10%, uncorrelated.
The protocol's one-shot k=sqrt(0.75/0.90)=0.9129 only brings the cluster to
~88.2%, still over cap. Repeating the same formula converges asymptotically
toward exactly 75% *from above*, at a fixed rate set by the cap itself
(0.75/step here), and never crosses the boundary in finite iterations —
so neither a single pass nor a bounded repeat of the stated formula can
satisfy the protocol's own stated post-condition ("cap 後 ... ≤75%") for
this (realistic: low correlation between the cluster and the rest of the
book) case. The same failure mode applies to rc_cap's per-asset cap.

Fix used here: `_bisect_scale_to_cap` finds the scale factor for the
violating subset by bisection directly against the true (denominator-aware)
aggregate-RC function, guaranteeing the post-condition exactly rather than
approximately, in the same "iterate a shrink-and-recompute step to
convergence, bounded" architecture the protocol describes for rc_cap. This
preserves every parameter the protocol specifies (cap thresholds, per-round
convergence check, max_iter bound) and changes only the per-round shrink
factor's derivation. Owner reviewed and ACCEPTED this deviation 2026-07-13
(ruling: the protocol's intent is the post-condition, not the literal
formula; protocol text to be amended accordingly).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_CLUSTER = ("BTC", "ETH", "SOL")


# ---------------------------------------------------------------------------
# Shared risk-contribution decomposition
# ---------------------------------------------------------------------------

def risk_contributions(w, cov) -> np.ndarray:
    """Euler/variance decomposition RC_i = w_i*(Sigma @ w)_i / (w^T Sigma w).
    Sums to exactly 1 across all assets whenever portfolio variance > 0 (an
    individual RC_i can be negative for a diversifying/hedging position).
    Returns an all-zero vector when the portfolio has no measurable variance
    (flat book or degenerate Sigma) rather than raising or dividing by zero
    -- a flat book trivially satisfies every cap."""
    w = np.asarray(w, dtype=float)
    cov = np.asarray(cov, dtype=float)
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return np.zeros_like(w)
    return w * (cov @ w) / port_var


def _bisect_scale_to_cap(w: np.ndarray, cov: np.ndarray, idx: list[int], cap: float,
                          tol: float = 1e-10, max_bisect: int = 80) -> tuple[np.ndarray, int]:
    """Largest k in [0, 1] such that scaling w[idx] by k brings
    sum(|RC_i| for i in idx) <= cap, found by bisection against the exact
    (denominator-aware) aggregate risk-contribution function -- see module
    docstring for why the protocol's one-shot sqrt(cap/current) estimate is
    not used directly. agg_rc(k) is continuous, agg_rc(0)=0 <= cap (a flat
    subset trivially satisfies the cap) and by precondition agg_rc(1) > cap,
    so a root exists by the intermediate value theorem; bisection maintains
    the invariant "lo always satisfies the cap, hi always violates it" and
    is robust even where agg_rc isn't strictly monotonic, since it only
    needs *a* feasible k close to the boundary, not the unique one."""
    base = np.array(w, dtype=float)
    idx = list(idx)

    def agg_rc(k: float) -> float:
        trial = base.copy()
        trial[idx] = trial[idx] * k
        rc = risk_contributions(trial, cov)
        return float(np.sum(np.abs(rc[idx])))

    if agg_rc(1.0) <= cap:
        return base, 0
    lo, hi = 0.0, 1.0
    it = 0
    for it in range(1, max_bisect + 1):
        mid = 0.5 * (lo + hi)
        if agg_rc(mid) > cap:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    out = base.copy()
    out[idx] = out[idx] * lo
    return out, it


# ---------------------------------------------------------------------------
# Layer 2: per-asset risk-contribution cap
# ---------------------------------------------------------------------------

def rc_cap(w, cov, cap: float = 0.35, max_iter: int = 10) -> tuple[np.ndarray, int]:
    """Protocol §1 step 2: cap-and-shrink any asset whose |RC_i| exceeds
    `cap`. Released risk is NOT reallocated to other assets ("釋出部分不再
    分配"). Iterates because shrinking one violator can push another asset's
    RC over the cap (through the shared covariance denominator); each round
    re-derives every currently-violating asset's exact required scale via
    `_bisect_scale_to_cap` (see module docstring for why exact, not the
    protocol's one-shot heuristic).

    Returns (w_capped, iterations_used); iterations_used is the number of
    shrink-and-recompute rounds that were actually needed (0 if the input
    already satisfied the cap)."""
    w = np.array(w, dtype=float)
    cov = np.asarray(cov, dtype=float)
    for outer in range(max_iter):
        rc = risk_contributions(w, cov)
        viol = np.where(np.abs(rc) > cap)[0]
        if viol.size == 0:
            return w, outer
        for i in viol:
            w, _ = _bisect_scale_to_cap(w, cov, [int(i)], cap)
    return w, max_iter


# ---------------------------------------------------------------------------
# Layer 3: correlated-cluster cap (BTC/ETH/SOL)
# ---------------------------------------------------------------------------

def cluster_cap(w, cov, coins: list[str], cluster_coins=DEFAULT_CLUSTER,
                cap: float = 0.75, max_iter: int = 5) -> tuple[np.ndarray, int]:
    """Protocol §1 step 3: if the cluster's aggregate |RC| exceeds `cap`,
    shrink every cluster member's weight by the same factor (found via
    `_bisect_scale_to_cap`, exact) so the aggregate lands at or under cap.
    `coins` gives the column order of `w`/`cov`; cluster members not present
    in `coins` (e.g. a universe missing SOL) are simply skipped. A single
    bisection round always solves this exactly (it's one scalar constraint
    on one scalar unknown, unlike rc_cap's potentially-interacting per-asset
    constraints); max_iter=5 is a defensive bound, not an expected budget."""
    w = np.array(w, dtype=float)
    cov = np.asarray(cov, dtype=float)
    idx_s = [i for i, c in enumerate(coins) if c in cluster_coins]
    if not idx_s:
        return w, 0
    for outer in range(max_iter):
        rc = risk_contributions(w, cov)
        agg = float(np.sum(np.abs(rc[idx_s])))
        if agg <= cap:
            return w, outer
        w, _ = _bisect_scale_to_cap(w, cov, idx_s, cap)
    return w, max_iter


# ---------------------------------------------------------------------------
# Layer 4: portfolio vol-target
# ---------------------------------------------------------------------------

def vol_scale(w, cov, target_ann_vol: float, max_gross: float = 3.0) -> np.ndarray:
    """Protocol §1 step 4: k = target / sqrt(w^T Sigma w * 365); w *= k;
    clip gross (sum|w_i|) to max_gross. `cov` is the DAILY return covariance
    (ddof=1), hence the *365 annualization inside the sqrt.

    target_ann_vol <= 0 (used by the drawdown ladder's FLAT state to force
    zero exposure) or an all-flat book (port_var == 0, nothing to scale)
    both return an all-zero weight vector rather than dividing by zero."""
    w = np.array(w, dtype=float)
    cov = np.asarray(cov, dtype=float)
    port_var = float(w @ cov @ w)
    if target_ann_vol <= 0 or port_var <= 0:
        return np.zeros_like(w)
    ann_vol = float(np.sqrt(port_var * 365.0))
    k = target_ann_vol / ann_vol
    w = w * k
    gross = float(np.sum(np.abs(w)))
    if gross > max_gross and gross > 0:
        w = w * (max_gross / gross)
    return w


# ---------------------------------------------------------------------------
# Layer 5: drawdown ladder (state machine, relative to running peak)
# ---------------------------------------------------------------------------

@dataclass
class LadderState:
    """peak_equity: running peak, NEVER reset on a new trough (protocol:
    "peak 不重置"). name: NORMAL | REDUCED | NO_ADD | FLAT | RECOVERY.
    cooldown_remaining: trading days left in a FLAT cooldown (only
    meaningful while name == "FLAT"; the 20-day cooldown is a fixed
    timeout, not reactive to equity recovering mid-cooldown)."""
    peak_equity: float
    name: str = "NORMAL"
    cooldown_remaining: int = 0


def dd_ladder_step(state: LadderState, equity: float, cell_target: float, *,
                    reduced_dd: float = -0.10, no_add_dd: float = -0.15,
                    flat_dd: float = -0.18, reduced_target: float = 0.10,
                    cooldown_days: int = 20) -> tuple[LadderState, float, bool]:
    """One daily transition. Returns (new_state, target_ann_vol_for_today,
    no_add) where no_add=True means the caller must not increase the
    magnitude of any per-asset weight vs. yesterday (see `apply_no_add`).

    Transition rules (protocol §1 step 5, with two judgment calls the
    protocol's prose doesn't pin down, made explicitly here):
      1. A fresh breach of flat_dd re-triggers FLAT from ANY state
         (including mid-REDUCED/NO_ADD/RECOVERY) except while already
         serving an active FLAT cooldown, which runs its fixed 20-day
         timeout regardless of same-period equity moves.
      2. RECOVERY does not get reclassified into REDUCED/NO_ADD merely
         because dd sits in that band; the protocol's own wording ("直到 DD
         回升 >-10% → NORMAL") makes RECOVERY a distinct path-dependent
         state whose only exit is dd > reduced_dd.
    """
    peak = max(state.peak_equity, equity)
    dd = (equity - peak) / peak if peak > 0 else 0.0  # always <= 0

    if state.name == "FLAT" and state.cooldown_remaining > 0:
        remaining = state.cooldown_remaining - 1
        if remaining > 0:
            return LadderState(peak, "FLAT", remaining), 0.0, False
        return LadderState(peak, "RECOVERY", 0), reduced_target, False

    if dd <= flat_dd:
        return LadderState(peak, "FLAT", cooldown_days), 0.0, False

    if state.name == "RECOVERY":
        if dd > reduced_dd:
            return LadderState(peak, "NORMAL", 0), cell_target, False
        return LadderState(peak, "RECOVERY", 0), reduced_target, False

    if dd > reduced_dd:
        return LadderState(peak, "NORMAL", 0), cell_target, False
    if dd > no_add_dd:
        return LadderState(peak, "REDUCED", 0), reduced_target, False
    return LadderState(peak, "NO_ADD", 0), reduced_target, True


def apply_no_add(w_today, w_yesterday) -> np.ndarray:
    """NO_ADD semantics: today's |w_i| must not exceed yesterday's |w_i|,
    per asset (protocol: "今日 |w_i| ≤ 昨日 |w_i|，逐資產"). Direction
    (sign) of today's weight is preserved; only magnitude is clamped down
    toward yesterday's, so a position may still flatten or flip smaller,
    just not grow past yesterday's size."""
    w_today = np.asarray(w_today, dtype=float)
    w_yesterday = np.asarray(w_yesterday, dtype=float)
    mag_cap = np.abs(w_yesterday)
    over = np.abs(w_today) > mag_cap
    out = w_today.copy()
    out[over] = np.sign(w_today[over]) * mag_cap[over]
    return out


# ---------------------------------------------------------------------------
# Composed daily pipeline (all five layers, fixed order)
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    w: np.ndarray
    ladder_state: LadderState
    rc_cap_iters: int
    cluster_cap_iters: int
    target_vol_used: float
    no_add: bool


def sizing_pipeline(raw_w, cov, *, prev_w, ladder_state: LadderState, equity: float,
                     cell_target: float, coins: list[str],
                     rc_cap_pct: float = 0.35, cluster_cap_pct: float = 0.75,
                     cluster_coins=DEFAULT_CLUSTER, max_gross: float = 3.0,
                     reduced_target: float = 0.10, cooldown_days: int = 20,
                     enable_rc_cap: bool = True, enable_cluster_cap: bool = True,
                     enable_ladder: bool = True) -> PipelineResult:
    """Composes the five layers in the protocol's fixed order:
    raw_w -> rc_cap -> cluster_cap -> vol_scale -> dd_ladder.

    Ordering note: dd_ladder is listed last in the protocol's layer diagram,
    but its OUTPUT (today's effective target vol, and the no_add flag) must
    feed vol_scale's `target_ann_vol` parameter and must gate the *result*
    of vol_scale respectively -- there's no way to run vol_scale strictly
    "after" dd_ladder while also having dd_ladder's target used *by*
    vol_scale. This resolution was reviewed and ACCEPTED by owner
    2026-07-13. Resolved as: (1) evaluate dd_ladder_step first to get
    today's target/no_add, using `equity` as the caller passes it (callers
    should pass the equity known at decision time, i.e. as of day t's
    close; the position formed here earns day t+1's return -- see module
    docstring); (2) run
    rc_cap -> cluster_cap -> vol_scale(target=that target); (3) apply the
    no_add clamp as a final post-processing step, and force an all-zero
    weight for FLAT via target_ann_vol=0.0 (vol_scale's own zero-target
    branch), rather than a separate special case.

    `equity` here is a plain float (this is a pure per-day step); the
    caller (e.g. a backtest driver) owns advancing equity/peak day to day.
    """
    w = np.array(raw_w, dtype=float)

    rc_iters = 0
    if enable_rc_cap:
        w, rc_iters = rc_cap(w, cov, cap=rc_cap_pct)

    cl_iters = 0
    if enable_cluster_cap:
        w, cl_iters = cluster_cap(w, cov, coins, cluster_coins=cluster_coins, cap=cluster_cap_pct)

    if enable_ladder:
        new_state, target_vol, no_add = dd_ladder_step(
            ladder_state, equity, cell_target,
            reduced_target=reduced_target, cooldown_days=cooldown_days,
        )
    else:
        new_state, target_vol, no_add = ladder_state, cell_target, False

    w = vol_scale(w, cov, target_vol, max_gross=max_gross)

    if enable_ladder and no_add:
        w = apply_no_add(w, prev_w)

    return PipelineResult(w=w, ladder_state=new_state, rc_cap_iters=rc_iters,
                           cluster_cap_iters=cl_iters, target_vol_used=target_vol,
                           no_add=no_add)


# ---------------------------------------------------------------------------
# Recordkeeping: non-overlapping quarterly OOS blocks
# ---------------------------------------------------------------------------

def quarterly_blocks(daily_returns: pd.Series) -> pd.DataFrame:
    """Non-overlapping calendar-quarter aggregation of a daily strategy
    return series (protocol §3: OOS reported as "非重疊季度塊"). Each
    block's Sharpe/MDD are computed from THAT block's own equity path
    starting at 1.0 -- no drawdown or return history carried across a
    quarter boundary, matching research_momentum_voltarget.py's split-half
    convention (`half_stats`) generalized to quarters."""
    cols = ["quarter", "start", "end", "n_days", "block_return", "block_sharpe", "block_mdd"]
    if daily_returns.empty:
        return pd.DataFrame(columns=cols)
    periods = daily_returns.index.to_period("Q")
    rows = []
    for period in sorted(periods.unique()):
        r = daily_returns[periods == period]
        if r.empty:
            continue
        eq = (1.0 + r).cumprod()
        block_return = float(eq.iloc[-1] - 1.0)
        block_sharpe = 0.0
        if len(r) > 1 and r.std(ddof=1) > 0:
            block_sharpe = float(r.mean() / r.std(ddof=1) * (365 ** 0.5))
        running_max = eq.cummax()
        block_mdd = float(((eq - running_max) / running_max).min())
        rows.append({
            "quarter": str(period), "start": r.index.min(), "end": r.index.max(),
            "n_days": len(r), "block_return": block_return,
            "block_sharpe": block_sharpe, "block_mdd": block_mdd,
        })
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Decision-input construction (signal scores + rolling covariance)
# ---------------------------------------------------------------------------

def causal_scores_and_cov(returns: pd.DataFrame, score_fn, cov_lookback: int):
    """Builds the day-t DECISION inputs (signal scores and rolling
    covariance) under the standard lag convention the reused engine already
    follows: a position is decided at day t's close -- so its inputs may use
    data through day t's own close, rows <= t -- and earns day t+1's return.
    No-lookahead therefore lives in the CALLER's loop ordering (book day-t
    PnL with the position decided at t-1's close BEFORE computing day t's
    new target), exactly as research_momentum_voltarget.py and
    hlvault.momentum.backtest already do; this helper adds NO extra shift.
    (An earlier draft shifted inputs one more day -- decide at t's close
    using <= t-1 only -- which is one day MORE conservative than the audited
    standard; owner ruled 2026-07-13 to standardize on decide-at-t-close,
    and the unit tests' no-lookahead assertions are aligned to it.)

    `score_fn` is typically hlvault.momentum.signals.composite_score,
    called unmodified per coin (protocol: "訊號：零改動").

    Returns (scores, cov_by_date):
      scores: DataFrame aligned to `returns.index`; scores.loc[t] uses <= t.
      cov_by_date: dict[Timestamp, DataFrame]. Day t's value is the rolling
        `cov_lookback`-day sample covariance (daily returns, ddof=1) over
        the SUBSET of coins that have a full lookback window at t -- a coin
        listed mid-panel simply isn't in the matrix until it has
        `cov_lookback` days of history (index/columns name the included
        coins), instead of one late-listing coin (e.g. HYPE) NaN-ing out
        the whole universe's matrix (an earlier draft did exactly that and
        silently sat flat for months; see the Task 1 attribution report).
        Dates where no coin has a full window are absent from the dict."""
    scores = pd.DataFrame(
        {c: score_fn(returns[c].dropna()) for c in returns.columns}
    ).reindex(returns.index)
    cov_frames = returns.rolling(cov_lookback).cov()
    cov_by_date: dict = {}
    for t in returns.index:
        try:
            mat = cov_frames.loc[t]
        except KeyError:
            continue
        mat = mat.reindex(index=returns.columns, columns=returns.columns)
        valid = [c for c in returns.columns if pd.notna(mat.loc[c, c])]
        # Coins sharing the same full trailing window normally have every
        # pairwise entry defined once their variances are; this while loop
        # is a defensive sweep for pathological mid-history gap patterns.
        while valid:
            sub = mat.loc[valid, valid]
            nan_per_coin = sub.isna().sum()
            if int(nan_per_coin.sum()) == 0:
                break
            valid = [c for c in valid if c != nan_per_coin.idxmax()]
        if not valid:
            continue
        cov_by_date[t] = mat.loc[valid, valid]
    return scores, cov_by_date


# ---------------------------------------------------------------------------
# Universe schedule resolution (U-fixed / U-PIT)
# ---------------------------------------------------------------------------

def resolve_universe(schedule, date) -> list[str]:
    """schedule is either a static list/tuple of coins (U-fixed) or a
    dict[date-string -> list[str]] (U-PIT, e.g. loaded from
    data/k_framework/universe_schedule.json), keyed by each quarter's
    PIT-safe effective start date. Returns the membership in effect on
    `date`: the most recent schedule key <= date (no forward-looking --
    a schedule key dated after `date` is never consulted)."""
    if isinstance(schedule, (list, tuple)):
        return list(schedule)
    date_ts = pd.Timestamp(date)
    parsed = sorted(((pd.Timestamp(k), k) for k in schedule.keys()), key=lambda p: p[0])
    eff = [orig_k for ts, orig_k in parsed if ts <= date_ts]
    if not eff:
        return []
    return list(schedule[eff[-1]])
