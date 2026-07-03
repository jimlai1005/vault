"""Pure per-cycle decision function for the carry engine. Returns a SHORT
ordered action list; the live loop executes it and the next cycle re-plans
from fresh exchange state (self-correcting — no local multi-step plans).

TRANSFER-FREE by design (discovered live 2026-07-03): Hyperliquid agent/API
keys CANNOT perform usdClassTransfer (spot<->perp USDC moves) — that is a
user-signed action only the master wallet key can sign; attempting it with
the agent key fails with "Must deposit before performing actions". So the
engine never plans to_perp/to_spot. All rebalancing goes through the four
order kinds; delta neutrality is preserved by moving BOTH legs together
(paired unwind / paired grow). If the perp side holds no margin, no order
can fix it — only a manual master-key transfer — so the planner returns []
and live.py alerts the operator.

Priority order (first match wins the cycle):
  1. funding turned bad -> full unwind (close short, sell spot)
  2. leverage too high (pump) or underwater -> PAIRED UNWIND: close a short
     slice FIRST (it's the leg at liquidation risk), sell the matching spot
     slice second to restore delta  [liquidation defense]
  3. leverage too low with a live position -> GROW both legs from spot cash
     back toward target (idle perp margin can't be recycled without a
     transfer; it's a harmless safety buffer)
  4. delta drift -> trim the larger leg
  5. flat + funding ok -> enter, sized by BOTH sides: spot cash AND the
     margin already sitting on the perp side
"""
from __future__ import annotations

from dataclasses import dataclass

from .equity import CarrySnapshot


@dataclass(frozen=True)
class Action:
    kind: str            # buy_spot|sell_spot|open_short|close_short
    size: float = 0.0    # coin units (spot/perp orders)
    amount: float = 0.0  # USDC (unused since the transfer-free redesign;
                         # kept so the Action shape stays stable)


def plan_actions(s: CarrySnapshot, funding_is_ok: bool, *, deploy_fraction: float,
                 max_short_leverage: float, rebalance_leverage: float,
                 min_short_leverage: float, delta_tolerance: float,
                 min_order_notional: float) -> list[Action]:
    if s.mid <= 0:
        return []
    target_ntl = s.equity * deploy_fraction
    # margin_used + withdrawable only -- see equity.py: `withdrawable` already
    # bakes in unrealized pnl, so adding perp_upnl here double-counts it.
    perp_equity = s.perp_margin_used + s.perp_withdrawable
    has_position = s.perp_short_ntl > min_order_notional or s.spot_coin_ntl > min_order_notional

    # 1. funding bad -> unwind everything (close short first: it's the leg
    #    that can be liquidated; spot can wait a cycle if something fails).
    #    Any USDC left stranded on the perp side stays there — transfers are
    #    impossible with an agent key, and idle margin is harmless.
    if not funding_is_ok:
        if not has_position:
            return []
        acts = []
        if s.perp_short_size * s.mid > min_order_notional:
            acts.append(Action("close_short", size=s.perp_short_size))
        if s.spot_coin_ntl > min_order_notional:
            acts.append(Action("sell_spot", size=s.spot_coin_size))
        return acts

    # 2. leverage too high -> liquidation defense: PAIRED UNWIND. Without
    # transfers, margin cannot be topped up — the only way to cut leverage is
    # to shrink the short itself: close the slice that restores
    # (short_ntl - Δ) / perp_equity <= max_short_leverage, and sell the same
    # spot slice to stay delta-neutral. close_short goes FIRST: it's the leg
    # at liquidation risk; if the spot sale fails, the delta guard trims the
    # remainder next cycle.
    # The raw perp_equity <= 0 check matters: equity.py defines short_leverage
    # as 0.0 when perp equity is non-positive, so a deep-underwater short (an
    # extreme gap move within one poll cycle) would otherwise sail PAST the
    # `> rebalance_leverage` trigger and the engine would plan nothing at the
    # exact moment defense matters most. max(perp_equity, 0) makes the
    # underwater Δ equal to the FULL short — close everything.
    underwater = s.perp_short_ntl > min_order_notional and perp_equity <= 0
    if s.short_leverage > rebalance_leverage or underwater:
        excess_ntl = s.perp_short_ntl - max(perp_equity, 0.0) * max_short_leverage
        acts = []
        if excess_ntl > min_order_notional:
            acts.append(Action("close_short", size=excess_ntl / s.mid))
            # sell what exists if spot holds less than the slice; the delta
            # guard trims the rest next cycle
            sell_size = min(excess_ntl / s.mid, s.spot_coin_size)
            if sell_size * s.mid > min_order_notional:
                acts.append(Action("sell_spot", size=sell_size))
        return acts

    # 3. leverage far too low with a live position -> idle perp margin cannot
    # be recycled to spot (no transfers), so GROW both legs back toward the
    # target instead, bounded by what BOTH sides can afford: remaining target,
    # spot cash for the buy, and perp margin headroom for the short.
    # funding_is_ok is structurally True here (priority 1 returned otherwise)
    # but is kept explicit so a future reorder can't silently grow into bad
    # funding.
    if funding_is_ok and has_position and 0 < s.short_leverage < min_short_leverage:
        grow_ntl = min(target_ntl - s.perp_short_ntl, s.spot_usdc,
                       perp_equity * max_short_leverage - s.perp_short_ntl)
        if grow_ntl > min_order_notional:
            size = grow_ntl / s.mid
            return [Action("buy_spot", size=size), Action("open_short", size=size)]
        # else: nothing affordable to grow — idle margin is a harmless safety
        # buffer; fall through so the delta guard still runs.

    # 4. delta drift -> trim the larger leg toward the smaller
    if has_position:
        tol = max(delta_tolerance * max(target_ntl, 1.0), min_order_notional)
        if s.delta_ntl > tol:
            return [Action("sell_spot", size=s.delta_ntl / s.mid)]
        if -s.delta_ntl > tol:
            return [Action("close_short", size=-s.delta_ntl / s.mid)]

    # 5. flat -> enter. No transfer planning is possible, so BOTH constraints
    # size the trade: the spot buy is limited by spot cash, the short by the
    # margin already on the perp side (perp_equity * max_short_leverage).
    # Legs are always equal — planning a $600 buy against $350 of cash (or a
    # $600 short against $200 of margin capacity) would leave one cycle of
    # unhedged directional exposure. If the perp side holds no margin at all,
    # return [] — only a manual master-key transfer can fix that, and live.py
    # surfaces it with an operator alert.
    if not has_position:
        if target_ntl <= min_order_notional:
            return []
        affordable_ntl = min(target_ntl, s.spot_usdc, perp_equity * max_short_leverage)
        if affordable_ntl <= min_order_notional:
            return []
        size = affordable_ntl / s.mid
        return [Action("buy_spot", size=size), Action("open_short", size=size)]

    return []
