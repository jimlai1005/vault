"""Deterministic percentage-grid state machine.

The grid is an infinite geometric ladder anchored at a fixed reference price:
    level_price(k) = anchor * (1 + step_pct) ** k

At any time only the `num_levels` rungs just below the current price are
"armed" (candidate buy levels). A filled buy becomes an open lot paired with
a reduce-only take-profit one rung up — the spread-capture mechanic found in
target-strategy-analysis.md. On top of that mechanic this module adds what
the target does not appear to have: a hard stop-loss below the armed window
and a position-notional cap that skips new fills once breached.

This same `step()` function drives both the backtest (fed historical
candles) and the live engine (fed the latest mid price each sync cycle) so
there is exactly one implementation of "what should the grid be doing right
now" — see CLAUDE.md #5 (one boundary, not scattered logic).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class GridConfig:
    coin: str
    step_pct: float                 # rung spacing, e.g. 0.002 = 0.2%
    num_levels: int                 # active buy rungs maintained below price
    notional_per_level: float       # USDC notional per rung
    max_position_notional: float    # hard cap on total open-lot notional
    stop_buffer_pct: float          # stop-loss trigger below the armed window
    cooldown_candles: int           # candles to stay stopped-out before re-arming
    fee_rate: float = 0.0003        # taker/maker blended estimate for backtest


@dataclass(frozen=True)
class OpenLot:
    level: int
    entry_price: float
    size: float
    tp_price: float


@dataclass(frozen=True)
class GridState:
    anchor: float
    open_lots: dict = field(default_factory=dict)   # level -> OpenLot
    armed: frozenset = field(default_factory=frozenset)  # levels with a resting buy
    stopped_for: int = 0             # candles remaining in stop-loss cooldown


@dataclass(frozen=True)
class Event:
    kind: str            # "fill" | "tp" | "stop"
    level: int | None
    price: float
    size: float
    pnl: float = 0.0


def level_price(anchor: float, step_pct: float, k: int) -> float:
    return anchor * (1 + step_pct) ** k


def level_index(anchor: float, step_pct: float, price: float) -> int:
    """Nearest integer rung index for `price` (used to find the center)."""
    return round(math.log(price / anchor) / math.log(1 + step_pct))


def _open_notional(open_lots: dict) -> float:
    return sum(lot.entry_price * lot.size for lot in open_lots.values())


def desired_armed_levels(center_k: int, cfg: GridConfig) -> list[int]:
    """The num_levels rungs immediately below the current price."""
    return list(range(center_k - cfg.num_levels, center_k))


def step(state: GridState, candle: dict, cfg: GridConfig) -> tuple[GridState, list[Event]]:
    """Advance the grid by one candle ({'h':..,'l':..,'c':..}). Pure function.

    Order within a candle (backtest approximation — live fills are event-driven,
    not candle-driven): stop-loss check first, then TP closes (price rose into
    them), then new fills (price dipped into them), then re-arm.
    """
    events: list[Event] = []
    open_lots = dict(state.open_lots)
    armed = set(state.armed)
    stopped_for = state.stopped_for

    low, high, close = candle["l"], candle["h"], candle["c"]

    # 1. stop-loss: price fell stop_buffer_pct below the deepest FILLED entry.
    # Deliberately anchored to open_lots (actual capital at risk), not the
    # armed window — the armed window keeps re-arming lower as price trails
    # down, which would push a window-relative stop further away over time
    # and defeat its purpose.
    stop_px = None
    if open_lots:
        bottom_k = min(open_lots)
        stop_px = level_price(state.anchor, cfg.step_pct, bottom_k) * (1 - cfg.stop_buffer_pct)

    if stop_px is not None and low <= stop_px:
        flatten_size = sum(lot.size for lot in open_lots.values())
        flatten_notional_cost = sum(lot.size * stop_px for lot in open_lots.values())
        entry_notional = _open_notional(open_lots)
        pnl = flatten_notional_cost - entry_notional - flatten_notional_cost * cfg.fee_rate
        events.append(Event("stop", None, stop_px, flatten_size, pnl))
        open_lots = {}
        armed = set()
        stopped_for = cfg.cooldown_candles
        return GridState(state.anchor, open_lots, frozenset(armed), stopped_for), events

    # 2. take-profits: price rose through an open lot's tp
    for lvl, lot in list(open_lots.items()):
        if high >= lot.tp_price:
            notional_in = lot.entry_price * lot.size
            notional_out = lot.tp_price * lot.size
            pnl = (notional_out - notional_in) - notional_out * cfg.fee_rate
            events.append(Event("tp", lvl, lot.tp_price, lot.size, pnl))
            del open_lots[lvl]

    if stopped_for > 0:
        stopped_for -= 1
        if stopped_for > 0:
            return GridState(state.anchor, open_lots, frozenset(), stopped_for), events
        # cooldown just expired this candle — fall through and resume below

    # 3. fills: price dipped through an armed buy level
    center_k = level_index(state.anchor, cfg.step_pct, close)
    for lvl in sorted(armed):
        px = level_price(state.anchor, cfg.step_pct, lvl)
        if low <= px:
            projected = _open_notional(open_lots) + cfg.notional_per_level
            if projected > cfg.max_position_notional:
                continue  # capped — skip this fill, leave level un-armed this candle
            size = cfg.notional_per_level / px
            tp_px = level_price(state.anchor, cfg.step_pct, lvl + 1)
            open_lots[lvl] = OpenLot(lvl, px, size, tp_px)
            events.append(Event("fill", lvl, px, size))
            armed.discard(lvl)

    # 4. re-arm the window around the current center
    desired = set(desired_armed_levels(center_k, cfg))
    armed = {lvl for lvl in armed if lvl in desired or lvl not in open_lots}
    for lvl in desired:
        if lvl not in open_lots:
            projected = _open_notional(open_lots) + cfg.notional_per_level
            if projected <= cfg.max_position_notional:
                armed.add(lvl)

    return GridState(state.anchor, open_lots, frozenset(armed), 0), events


def init_state(anchor_price: float) -> GridState:
    return GridState(anchor=anchor_price)
