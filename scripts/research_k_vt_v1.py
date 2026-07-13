"""Momentum-VT v1 formal 8-cell grid runner (sub-project K, Task 3).

Protocol (the executable law for this file):
docs/superpowers/specs/2026-07-13-momentum-vt-v1-protocol.md §2 (8-cell
table), §3 (windows), §4b (implementation adjudications). Engine: called,
never modified: scripts/k_vt_engine.py (12 unit tests green; lag convention
already standardized there). Signal reused unmodified from
hlvault.momentum.signals; sizing base (pre-cap) reused unmodified from
hlvault.momentum.risk (CLAUDE.md #5: one implementation, not re-derived).

Daily loop ordering (mirrors k_vt_engine.sizing_pipeline's own contract):
for date t, in this order --
  1. Book today's PnL using YESTERDAY's target notional (prev_notional,
     decided at t-1's close) against TODAY's return/funding -- this yields
     `equity_t_close`, the mark-to-market equity AS OF today's close,
     BEFORE today's rebalance cost.
  2. Decide TODAY's new target using data through t's own close (causal)
     and `equity_t_close` as the ladder/vol-scale/no-add basis -- this is
     the "equity known at decision time, i.e. as of day t's close" that
     scripts/k_vt_engine.py's sizing_pipeline docstring calls for.
     `prev_w` (yesterday's weight, for the no-add clamp) is ALSO expressed
     as a fraction of this SAME `equity_t_close` -- not of yesterday's
     equity -- so the no-add comparison and the new weight it's clamped
     against share one source/one basis (CLAUDE.md engineering principle
     #1: never compare values computed on different bases).
  3. Subtract today's rebalance cost from `equity_t_close` to get the
     final, post-cost equity carried into tomorrow's iteration.
This differs from scripts/research_momentum_voltarget.py's vol_target_backtest
(which sizes off equity BEFORE today's own pnl, since it has no drawdown
ladder to react to today's own close) -- the difference is required here
because the ladder must see today's actual drawdown, not yesterday's.

Universe handling: U-fixed is BTC/ETH/SOL (+HYPE from its actual Binance
listing 2025-05-30, protocol §4b.3) -- HYPE's absence before that date is
already handled by data absence (NaN scores/cov), same mechanism used for
any coin's listing. U-PIT reads data/k_framework/universe_schedule.json
(Binance symbols) through k_vt_engine.resolve_universe, converted to this
engine's short coin codes via `binance_to_engine_coin` below. On any day a
previously-held coin drops out of the day's resolved membership (quarterly
U-PIT rebalance, or simply running out of data), its target is forced to 0
and the turnover cost of closing it is charged that same day (protocol
§2: "移出者平倉計成本") -- see the `affected` set in `simulate_cell`.

Funding: Binance funding rate history (data/k_framework/funding/), daily-
summed (3 x 8h samples/day). A coin economically "affected" that day (held
or being closed) with no funding sample that day is counted as a gap and
charged $0 funding PnL for it (protocol §1: "缺洞計 0 並統計") -- gaps are
tallied and printed, never silently absorbed.

KNOWN DATA LIMITATION (not this file's bug, flagged for the record): as of
this writing, data/k_framework/funding/*.csv.gz only holds each symbol's
most recent ~500 rows (~5.5 months) rather than full history back to 2019 --
scripts/k_data_layer.py's fetch_funding_history pagination has a latent bug
(see its own comment at that function). For the "formal" window (2020-2025)
this means the overwhelming majority of days will report as funding gaps
(booked $0). This is real and should be fixed at the data layer before the
formal G-K1..K6 numbers are treated as final; it does not block writing or
smoke-testing this runner, since the gap-accounting path is exactly the
protocol's documented contingency for exactly this situation.

Window locks (both mechanical, both enforced inside simulate_cell itself so
EVERY caller -- this CLI, k_gates_eval.py's cost-x1.5 leg, anything else
importing this module -- passes through the same gate, protocol §4b-7):
  - formal:  refuses unless data/k_framework/FORMAL_UNLOCKED exists (created
    by the main conversation only at official-run time; remediation added
    after a smoke test executed one formal-window leg -- that output is
    voided and quarantined per §4b-7, and the DSR declared trial count was
    raised 16 -> 17 as the snooping penalty).
  - holdout: refuses unless data/k_framework/HOLDOUT_UNLOCKED exists (only
    after G-K1..K5 all pass).

Run:
    .venv/bin/python scripts/research_k_vt_v1.py --cell 2 --window dev
    .venv/bin/python scripts/research_k_vt_v1.py --cell 2 --window formal
        (refuses unless data/k_framework/FORMAL_UNLOCKED exists)
    .venv/bin/python scripts/research_k_vt_v1.py --cell 2 --window holdout
        (refuses unless data/k_framework/HOLDOUT_UNLOCKED exists)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # hlvault package (mirrors research_momentum_voltarget.py)

from k_vt_engine import (  # noqa: E402
    LadderState,
    causal_scores_and_cov,
    quarterly_blocks,
    resolve_universe,
    sizing_pipeline,
)
from hlvault.momentum.risk import risk_budget_per_coin, target_position_notional  # noqa: E402
from hlvault.momentum.signals import composite_score, daily_log_returns, position_signal  # noqa: E402
from scalp_lib import BINANCE_SYMBOL_OVERRIDES  # noqa: E402

DATA_DIR = ROOT / "data" / "k_framework"
KLINES_DIR = DATA_DIR / "klines"
FUNDING_DIR = DATA_DIR / "funding"
UNIVERSE_SCHEDULE_PATH = DATA_DIR / "universe_schedule.json"
RUNS_DIR = DATA_DIR / "runs"
HOLDOUT_UNLOCK_FLAG = DATA_DIR / "HOLDOUT_UNLOCKED"
FORMAL_UNLOCK_FLAG = DATA_DIR / "FORMAL_UNLOCKED"  # protocol §4b-7 remediation (b)

# ---------------------------------------------------------------------------
# Fixed engine parameters -- NOT part of the 8-cell grid (signal/sizing-base
# "零改動": same defaults as hlvault.momentum.config's ENTRY_THRESHOLD /
# MAX_COIN_ALLOCATION_PCT, hardcoded here instead of imported from that
# module so this research script never loads .env.momentum (the live
# wallet's real key file) -- see vault CLAUDE.md's 實盤紅線.
# ---------------------------------------------------------------------------
CAPITAL = 10_000.0
ENTRY_THRESHOLD = 0.5
MAX_COIN_ALLOCATION_PCT = 0.40
BASE_LEVERAGE = 1.0  # raw (pre-cap) target uses leverage=1; vol_scale does the real scaling
                      # (matches research_momentum_voltarget.py's run_vt convention)
FEE_RATE = 0.0005    # 5bps/side
SLIP_RATE = 0.0001   # 1bp/side
MAX_GROSS = 3.0
RC_CAP_PCT = 0.35
CLUSTER_CAP_PCT = 0.75
CLUSTER_COINS = ("BTC", "ETH", "SOL")
REDUCED_TARGET = 0.10
COOLDOWN_DAYS = 20
ANN_FACTOR = 365 ** 0.5

HYPE_LISTING = pd.Timestamp("2025-05-30")  # protocol §4b.3: actual Binance HYPEUSDT listing
FIXED_UNIVERSE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "HYPE": "HYPEUSDT"}

# ---------------------------------------------------------------------------
# Protocol §2: the 8 pre-registered cells. Not to be extended/altered.
# ---------------------------------------------------------------------------
CELLS = {
    1: {"target_vol": 0.15, "lookback": 20, "universe": "U-fixed"},
    2: {"target_vol": 0.15, "lookback": 40, "universe": "U-fixed"},
    3: {"target_vol": 0.20, "lookback": 20, "universe": "U-fixed"},
    4: {"target_vol": 0.20, "lookback": 40, "universe": "U-fixed"},
    5: {"target_vol": 0.15, "lookback": 20, "universe": "U-PIT"},
    6: {"target_vol": 0.15, "lookback": 40, "universe": "U-PIT"},
    7: {"target_vol": 0.20, "lookback": 40, "universe": "U-PIT"},
    8: {"target_vol": 0.20, "lookback": 20, "universe": "U-PIT"},
}
PRIMARY_CELL = 2  # 15%/40d/U-fixed

# ---------------------------------------------------------------------------
# Protocol §3: windows (hardcoded timestamps, not derived from "now" --
# same reproducibility discipline as research_momentum_voltarget.py).
# ---------------------------------------------------------------------------
WINDOWS = {
    "dev": ("2024-07-02", "2026-07-02"),
    "formal": ("2020-01-01", "2025-12-31"),
    "holdout": ("2026-01-01", "2026-07-02"),
}
FORMAL_OOS_START = "2020-07-01"  # 6-month warmup carve-out, protocol §3

# Protocol §4/G-K3: 5 calendar market phases, hardcoded per Task 3 spec.
ERAS = [
    ("2020-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2025-06-30"),
    ("2025-07-01", "2025-12-31"),
]
ERA_LABELS = ["2020-01~2021-12 (牛)", "2022 全年 (熊)", "2023 全年 (震盪)",
              "2024-01~2025-06 (牛尾)", "2025-07~2025-12 (熊)"]
# Protocol §3: "2020-Q3->2024-Q2 段（乾淨...）承重". Eras 1-3 (0-indexed 0,1,2)
# fall inside that window; era 4 straddles the clean/dirty boundary
# (2024-06-30) and era 5 is entirely past it -- classified dirty rather than
# partially-clean to keep the classification binary and conservative.
CLEAN_ERA_INDEXES = {0, 1, 2}


# ---------------------------------------------------------------------------
# Binance symbol -> engine coin code
# ---------------------------------------------------------------------------
_REVERSE_BINANCE_OVERRIDES = {v: k for k, v in BINANCE_SYMBOL_OVERRIDES.items()}


def binance_to_engine_coin(symbol: str) -> str:
    """Binance USDT-perp symbol -> this engine's internal coin code.

    Reverses scalp_lib.BINANCE_SYMBOL_OVERRIDES for the 5 coins Hyperliquid
    lists with a 'k' prefix (kPEPE/kBONK/kSHIB/kFLOKI/kLUNC); every other
    symbol is normalized by stripping the 'USDT' suffix and, if still
    present, a leading '1000' quantity-multiplier prefix (HL does not
    k-prefix those, e.g. 1000SATSUSDT has no HL 'k' listing, only Binance's
    quantity convention). '1000000...' (the 1e6-multiplier coins) is left
    untouched -- stripping only 4 digits from it would produce a bogus code.

    >>> binance_to_engine_coin("BTCUSDT")
    'BTC'
    >>> binance_to_engine_coin("1000PEPEUSDT")
    'kPEPE'
    >>> binance_to_engine_coin("1000SHIBUSDT")
    'kSHIB'
    >>> binance_to_engine_coin("1000BONKUSDT")
    'kBONK'
    >>> binance_to_engine_coin("1000SATSUSDT")
    'SATS'
    >>> binance_to_engine_coin("DOGEUSDT")
    'DOGE'
    >>> binance_to_engine_coin("1MBABYDOGEUSDT")
    '1MBABYDOGE'
    >>> binance_to_engine_coin("1000000MOGUSDT")
    '1000000MOG'
    """
    if symbol in _REVERSE_BINANCE_OVERRIDES:
        return _REVERSE_BINANCE_OVERRIDES[symbol]
    core = symbol[:-4] if symbol.endswith("USDT") else symbol
    if core.startswith("1000") and not core.startswith("1000000"):
        core = core[4:]
    return core


def pit_symbol_maps() -> dict:
    """engine_code -> binance_symbol for every symbol that ever appears in
    universe_schedule.json. Raises on a genuine engine-code collision
    between two different Binance symbols (rather than silently letting one
    shadow the other) -- that would be a real ambiguity bug, not a thing to
    paper over."""
    raw = json.loads(UNIVERSE_SCHEDULE_PATH.read_text())
    all_symbols = sorted({s for syms in raw.values() for s in syms})
    engine_to_symbol: dict = {}
    for sym in all_symbols:
        code = binance_to_engine_coin(sym)
        if code in engine_to_symbol and engine_to_symbol[code] != sym:
            raise ValueError(
                f"engine-code collision: {sym!r} and {engine_to_symbol[code]!r} "
                f"both map to {code!r}"
            )
        engine_to_symbol[code] = sym
    return engine_to_symbol


def load_universe_schedule_engine_codes() -> dict:
    raw = json.loads(UNIVERSE_SCHEDULE_PATH.read_text())
    return {date: [binance_to_engine_coin(s) for s in syms] for date, syms in raw.items()}


def ufixed_membership(date) -> list:
    coins = ["BTC", "ETH", "SOL"]
    if pd.Timestamp(date) >= HYPE_LISTING:
        coins.append("HYPE")
    return coins


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_close_series(binance_symbol: str) -> pd.Series:
    path = KLINES_DIR / f"{binance_symbol}_1d.csv.gz"
    if not path.exists():
        raise FileNotFoundError(f"no klines for {binance_symbol}: {path}")
    df = pd.read_csv(path)
    idx = pd.to_datetime(df["ts"], utc=True, format="ISO8601").dt.tz_localize(None).dt.normalize()
    s = pd.Series(df["c"].astype(float).values, index=idx, name=binance_symbol).sort_index()
    return s[~s.index.duplicated(keep="last")]


def load_funding_daily(binance_symbol: str) -> pd.Series:
    """Daily-summed Binance fundingRate (3 x 8h samples -> 1 daily total),
    or an empty Series if this symbol has no funding file at all (protocol:
    gap days counted as 0 and tallied by the caller, not silently dropped)."""
    path = FUNDING_DIR / f"{binance_symbol}_funding.csv.gz"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    idx = pd.to_datetime(df["fundingTime"], utc=True, format="ISO8601").dt.tz_localize(None).dt.normalize()
    daily = pd.Series(df["fundingRate"].astype(float).values, index=idx).groupby(level=0).sum()
    return daily.sort_index()


def load_panel_for_universe(universe_kind: str, window_end: str) -> tuple:
    """Returns (closes panel, engine_code->binance_symbol map), truncated to
    <= window_end (no leakage possible even before the causal computation
    below gets a chance to look at it)."""
    if universe_kind == "U-fixed":
        symbol_map = dict(FIXED_UNIVERSE_SYMBOLS)
    elif universe_kind == "U-PIT":
        symbol_map = pit_symbol_maps()
    else:
        raise ValueError(f"unknown universe kind {universe_kind!r}")
    closes = {}
    for code, sym in symbol_map.items():
        s = load_close_series(sym)
        s = s[s.index <= pd.Timestamp(window_end)]
        if len(s) == 0:
            continue
        closes[code] = s
    panel = pd.DataFrame(closes).sort_index()
    return panel, symbol_map


# ---------------------------------------------------------------------------
# Stats helpers (shared with k_gates_eval.py -- CLAUDE.md #5: one implementation)
# ---------------------------------------------------------------------------

def compute_stats(returns: pd.Series) -> dict:
    """Own-compounding stats for an arbitrary return slice (matches the
    "each half/quarter computed from its own equity path starting at 1.0"
    convention already used by k_vt_engine.quarterly_blocks and
    research_momentum_voltarget.py's half_stats)."""
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"sharpe": 0.0, "total_return": 0.0, "mdd": 0.0, "n": 0}
    eq = (1.0 + r).cumprod()
    total_return = float(eq.iloc[-1] - 1.0)
    sharpe = 0.0
    if n > 1 and r.std(ddof=1) > 0:
        sharpe = float(r.mean() / r.std(ddof=1) * ANN_FACTOR)
    running_max = eq.cummax()
    mdd = float(((eq - running_max) / running_max).min())
    return {"sharpe": sharpe, "total_return": total_return, "mdd": mdd, "n": n}


def daily_sr(returns: pd.Series) -> float:
    """Unannualized daily Sharpe: mean(r)/std(r, ddof=1). Same formula as
    research_momentum_voltarget.py's daily_sr (DSR trial-pool convention)."""
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1))


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

@dataclass
class CellRunResult:
    cell: int
    window: str
    detail: pd.DataFrame          # full simulated window, columns per spec
    oos_returns: pd.Series        # date-indexed 'ret' slice used for gate stats
    funding_gap_days: int
    funding_gap_by_coin: dict
    coins_ever_seen: list


def simulate_cell(cell: int, window: str, *, window_end_override: str | None = None,
                   oos_start_override: str | None = None,
                   cost_multiplier: float = 1.0) -> CellRunResult:
    """Runs one (cell, window) combination end to end. `window_end_override`
    and `oos_start_override` exist for G-K5's endpoint-sensitivity check in
    k_gates_eval.py; `window_end_override` is guarded so it can never read
    into the locked holdout range (protocol: holdout may only be touched
    once all of G-K1..K5 pass, and the guard here makes that structural
    rather than a thing a caller has to remember -- CLAUDE.md engineering
    principle #5)."""
    if cell not in CELLS:
        raise ValueError(f"unknown cell {cell}; must be one of {sorted(CELLS)}")
    if window not in WINDOWS:
        raise ValueError(f"unknown window {window!r}; must be one of {sorted(WINDOWS)}")

    if window == "holdout" and not HOLDOUT_UNLOCK_FLAG.exists():
        raise RuntimeError(
            "holdout locked pending G-K1..5 -- data/k_framework/HOLDOUT_UNLOCKED absent"
        )
    if window == "formal" and not FORMAL_UNLOCK_FLAG.exists():
        # Protocol §4b-7: the formal window carries the same mechanical lock
        # as holdout. Enforced HERE (not only in the CLI) so k_gates_eval.py's
        # cost-x1.5 leg and any other simulate_cell caller hit the same gate.
        raise RuntimeError(
            "formal locked pending official run -- data/k_framework/FORMAL_UNLOCKED absent"
        )

    params = CELLS[cell]
    window_start, window_end = WINDOWS[window]
    if window_end_override is not None:
        if pd.Timestamp(window_end_override) >= pd.Timestamp(WINDOWS["holdout"][0]):
            raise RuntimeError(
                "window_end_override would read into the locked holdout range "
                f"({WINDOWS['holdout'][0]}) -- refusing"
            )
        window_end = window_end_override

    oos_start = FORMAL_OOS_START if window == "formal" else window_start
    if oos_start_override is not None:
        oos_start = oos_start_override

    universe_kind = params["universe"]
    lookback = params["lookback"]
    target_vol = params["target_vol"]

    panel, symbol_map = load_panel_for_universe(universe_kind, window_end)
    panel = panel[panel.index <= pd.Timestamp(window_end)]
    coins_all = list(panel.columns)
    if not coins_all:
        raise RuntimeError(f"empty panel for cell {cell} ({universe_kind}) window_end={window_end}")

    returns = pd.DataFrame(
        {c: daily_log_returns(panel[c]) for c in coins_all}
    ).reindex(panel.index)
    scores = pd.DataFrame(
        {c: composite_score(returns[c].dropna()) for c in coins_all}
    ).reindex(panel.index)
    signals = pd.DataFrame(
        {c: position_signal(scores[c], ENTRY_THRESHOLD) for c in coins_all}
    ).reindex(panel.index)
    _, cov_by_date = causal_scores_and_cov(returns, composite_score, lookback)

    funding_raw = {c: load_funding_daily(symbol_map[c]) for c in coins_all}
    funding_sets = {c: set(funding_raw[c].index) for c in coins_all}
    funding_panel = pd.DataFrame(funding_raw).reindex(panel.index).fillna(0.0)

    if universe_kind == "U-fixed":
        def membership_fn(d):
            return ufixed_membership(d)
    else:
        schedule_engine = load_universe_schedule_engine_codes()

        def membership_fn(d):
            return resolve_universe(schedule_engine, d)

    sim_dates = panel.index[
        (panel.index >= pd.Timestamp(window_start)) & (panel.index <= pd.Timestamp(window_end))
    ]
    if len(sim_dates) == 0:
        raise RuntimeError(f"no trading days in {window_start}..{window_end} for cell {cell}")

    cost_rate = (FEE_RATE + SLIP_RATE) * cost_multiplier

    equity = CAPITAL
    ladder_state = LadderState(peak_equity=CAPITAL)
    prev_notional: dict = {}
    funding_gap_days = 0
    funding_gap_by_coin = {c: 0 for c in coins_all}
    rows = []

    for t in sim_dates:
        # Step 1: book today's PnL using YESTERDAY's targets against
        # TODAY's return/funding (see module docstring for why equity_t_close
        # -- post-pnl, pre-cost -- is the correct decision basis).
        u_members = set(membership_fn(t))
        cov_t = cov_by_date.get(t)
        if cov_t is not None:
            coins_today = [c for c in cov_t.columns if c in u_members]
            cov_mat = cov_t.loc[coins_today, coins_today].values
        else:
            coins_today = []
            cov_mat = np.zeros((0, 0))

        affected = set(coins_today) | {c for c, v in prev_notional.items() if v != 0.0}
        gross_pnl = 0.0
        funding_pnl = 0.0
        for c in affected:
            ret = float(returns.loc[t, c]) if (c in returns.columns and pd.notna(returns.loc[t, c])) else 0.0
            prev_n = prev_notional.get(c, 0.0)
            gross_pnl += prev_n * ret
            frate = float(funding_panel.loc[t, c]) if c in funding_panel.columns else 0.0
            funding_pnl -= prev_n * frate  # HL/Binance convention: positive rate -> longs pay shorts
            if t not in funding_sets.get(c, set()):
                funding_gap_days += 1
                funding_gap_by_coin[c] = funding_gap_by_coin.get(c, 0) + 1

        equity_t_close = equity + gross_pnl + funding_pnl
        if equity_t_close <= 0:
            print(f"WARNING: equity <=0 at {t.date()} ({equity_t_close:.2f}); "
                  "clamping to 1e-6 for numerical safety", file=sys.stderr)
            equity_t_close = 1e-6

        # Step 2: decide today's new target using data through t's own
        # close, sized/laddered off equity_t_close (same basis for prev_w
        # and the raw target below -- CLAUDE.md engineering principle #1).
        vol_by_coin = {}
        for i, c in enumerate(coins_today):
            v = float(np.sqrt(max(cov_mat[i, i], 0.0)))
            if v > 0:
                vol_by_coin[c] = v
        budgets = risk_budget_per_coin(vol_by_coin, equity_t_close, MAX_COIN_ALLOCATION_PCT) if vol_by_coin else {}
        raw_target = {}
        for c in coins_today:
            if c not in vol_by_coin:
                raw_target[c] = 0.0
                continue
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            raw_target[c] = target_position_notional(sig, budgets.get(c, 0.0), BASE_LEVERAGE)

        raw_w = np.array([raw_target.get(c, 0.0) / equity_t_close for c in coins_today])
        prev_w = np.array([prev_notional.get(c, 0.0) / equity_t_close for c in coins_today])

        result = sizing_pipeline(
            raw_w, cov_mat, prev_w=prev_w, ladder_state=ladder_state, equity=equity_t_close,
            cell_target=target_vol, coins=coins_today,
            rc_cap_pct=RC_CAP_PCT, cluster_cap_pct=CLUSTER_CAP_PCT, cluster_coins=CLUSTER_COINS,
            max_gross=MAX_GROSS, reduced_target=REDUCED_TARGET, cooldown_days=COOLDOWN_DAYS,
        )
        target_notional_today = {c: float(result.w[i]) * equity_t_close for i, c in enumerate(coins_today)}

        # Step 3: charge today's rebalance cost (includes flattening any
        # coin dropped from today's membership, protocol §2 "移出者平倉計成本" --
        # target defaults to 0 for anything not in coins_today via .get above).
        cost = 0.0
        for c in affected:
            target = target_notional_today.get(c, 0.0)
            cost += abs(target - prev_notional.get(c, 0.0)) * cost_rate
            prev_notional[c] = target

        equity_final = equity_t_close - cost
        day_pnl = gross_pnl + funding_pnl - cost
        day_ret = day_pnl / equity if equity else 0.0
        gross_frac = sum(abs(v) for v in target_notional_today.values()) / equity_t_close if equity_t_close else 0.0
        peak = result.ladder_state.peak_equity
        dd = (equity_t_close - peak) / peak if peak > 0 else 0.0

        rows.append({
            "date": t, "ret": day_ret, "equity": equity_final, "gross": gross_frac,
            "target_now": result.target_vol_used, "dd": dd, "ladder_state": result.ladder_state.name,
            "funding_pnl": funding_pnl, "cost": cost, "universe_size": len(coins_today),
        })

        equity = equity_final
        ladder_state = result.ladder_state

    detail = pd.DataFrame(rows, columns=[
        "date", "ret", "equity", "gross", "target_now", "dd", "ladder_state",
        "funding_pnl", "cost", "universe_size",
    ])
    oos_mask = detail["date"] >= pd.Timestamp(oos_start)
    oos_returns = detail.loc[oos_mask].set_index("date")["ret"]

    return CellRunResult(
        cell=cell, window=window, detail=detail, oos_returns=oos_returns,
        funding_gap_days=funding_gap_days, funding_gap_by_coin=funding_gap_by_coin,
        coins_ever_seen=coins_all,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(result: CellRunResult) -> None:
    stats = compute_stats(result.oos_returns)
    print(f"  OOS n_days={stats['n']}  Sharpe(ann)={stats['sharpe']:.4f}  "
          f"total_ret={stats['total_return']:.2%}  MDD={stats['mdd']:.2%}  "
          f"daily_SR(unann)={daily_sr(result.oos_returns):.6f}")

    # RC-cap diagnostic: rc_cap's exact bisection cannot satisfy a 35%
    # single-asset cap with fewer than ceil(1/0.35)=3 simultaneously
    # nonzero-weight coins (RC_i is scale-invariant for a single dominant
    # asset, so no rescale of it alone ever reduces its RC below 100%; with
    # exactly 2 nonzero coins, RC0+RC1==1 forces at least one > 35% no
    # matter the split). On U-fixed's 3-coin pre-HYPE stretch this makes a
    # concentrated-signal day (fewer than 3 coins simultaneously past the
    # entry threshold) mechanically zero out, not a runner bug -- flagged
    # here since it can dominate a whole cell's day count (see report).
    det = result.detail
    if len(det):
        zero_all = float((det["gross"] == 0).mean())
        print(f"  zero-gross-exposure days (RC-cap concentration, whole sim window): "
              f"{(det['gross'] == 0).sum()}/{len(det)} ({zero_all:.1%})")
        by_us = det.groupby("universe_size")["gross"].apply(lambda g: float((g == 0).mean()))
        for us, frac in by_us.items():
            n = int((det["universe_size"] == us).sum())
            print(f"    universe_size={us}: {frac:.1%} zero-gross (n={n})")

    q = quarterly_blocks(result.oos_returns)
    print("\n  quarterly blocks (OOS, non-overlapping, each own-compounding):")
    if q.empty:
        print("    (no full quarter in this window's OOS slice)")
    else:
        for _, row in q.iterrows():
            print(f"    {row['quarter']}  n={row['n_days']:>3}  "
                  f"ret={row['block_return']:+.2%}  sharpe={row['block_sharpe']:+.3f}  "
                  f"mdd={row['block_mdd']:.2%}")

    print("\n  calendar eras (OOS-restricted, own-compounding):")
    for (start, end), label in zip(ERAS, ERA_LABELS):
        era_r = result.oos_returns[(result.oos_returns.index >= start) & (result.oos_returns.index <= end)]
        if len(era_r) == 0:
            print(f"    {label}: no data in this window")
            continue
        net = float((1.0 + era_r).prod() - 1.0)
        print(f"    {label}: n={len(era_r)}  net_ret={net:+.2%}")

    total_gap = result.funding_gap_days
    print(f"\n  funding gap days (affected-coin-days with no Binance funding sample, booked $0): "
          f"{total_gap}")
    nonzero_gaps = {c: g for c, g in result.funding_gap_by_coin.items() if g > 0}
    if nonzero_gaps:
        print(f"    by coin: {nonzero_gaps}")


def main():
    ap = argparse.ArgumentParser(description="Momentum-VT v1 formal 8-cell grid runner")
    ap.add_argument("--cell", type=int, required=True, choices=sorted(CELLS))
    ap.add_argument("--window", required=True, choices=sorted(WINDOWS))
    args = ap.parse_args()

    if args.window == "holdout" and not HOLDOUT_UNLOCK_FLAG.exists():
        print("holdout locked pending G-K1..5")
        sys.exit(1)
    if args.window == "formal" and not FORMAL_UNLOCK_FLAG.exists():
        print("formal locked pending official run")
        sys.exit(1)

    params = CELLS[args.cell]
    print(f"cell {args.cell}: target_vol={params['target_vol']:.0%} "
          f"lookback={params['lookback']}d universe={params['universe']}"
          f"{'  (PRIMARY)' if args.cell == PRIMARY_CELL else ''}")
    print(f"window={args.window} ({WINDOWS[args.window][0]} -> {WINDOWS[args.window][1]})")

    result = simulate_cell(args.cell, args.window)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_DIR / f"cell{args.cell}_{args.window}_daily.csv"
    out = result.detail.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(out_path, index=False)
    print(f"\ncsv: {out_path} ({len(out)} rows)")

    _print_summary(result)


if __name__ == "__main__":
    main()
