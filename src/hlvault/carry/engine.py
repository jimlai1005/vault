"""Pure per-cycle decision function for the carry engine. Returns a SHORT
ordered action list; the live loop executes it and the next cycle re-plans
from fresh exchange state (self-correcting — no local multi-step plans).

Priority order (first match wins the cycle):
  1. funding turned bad -> full unwind sequence
  2. leverage too high (pump) -> sell spot, top up perp margin  [liquidation defense]
  3. leverage too low (dump) -> pull excess margin back to spot
  4. delta drift -> trim the larger leg
  5. flat + funding ok -> enter (margin over, buy spot, open short)
"""
from __future__ import annotations

from dataclasses import dataclass

from .equity import CarrySnapshot


@dataclass(frozen=True)
class Action:
    kind: str            # buy_spot|sell_spot|open_short|close_short|to_perp|to_spot
    size: float = 0.0    # coin units (spot/perp orders)
    amount: float = 0.0  # USDC (transfers)


def plan_actions(s: CarrySnapshot, funding_is_ok: bool, *, deploy_fraction: float,
                 max_short_leverage: float, rebalance_leverage: float,
                 min_short_leverage: float, delta_tolerance: float,
                 min_order_notional: float) -> list[Action]:
    if s.mid <= 0:
        return []
    target_ntl = s.equity * deploy_fraction
    perp_equity = s.perp_margin_used + s.perp_upnl + s.perp_withdrawable
    has_position = s.perp_short_ntl > min_order_notional or s.spot_coin_ntl > min_order_notional

    # 1. funding bad -> unwind everything (close short first: it's the leg
    #    that can be liquidated; spot can wait a cycle if something fails)
    if not funding_is_ok:
        if not has_position:
            return []
        acts = []
        if s.perp_short_size * s.mid > min_order_notional:
            acts.append(Action("close_short", size=s.perp_short_size))
        if s.spot_coin_ntl > min_order_notional:
            acts.append(Action("sell_spot", size=s.spot_coin_size))
        if perp_equity > min_order_notional:
            acts.append(Action("to_spot", amount=perp_equity))
        return acts

    # 2. leverage too high -> liquidation defense: sell spot, move USDC to perp.
    # The raw perp_equity <= 0 check matters: equity.py defines short_leverage
    # as 0.0 when perp equity is non-positive, so a deep-underwater short (an
    # extreme gap move within one poll cycle) would otherwise sail PAST the
    # `> rebalance_leverage` trigger and the engine would plan nothing at the
    # exact moment defense matters most.
    underwater = s.perp_short_ntl > min_order_notional and perp_equity <= 0
    if s.short_leverage > rebalance_leverage or underwater:
        needed_equity = s.perp_short_ntl / max_short_leverage
        shortfall = needed_equity - perp_equity
        sellable_usd = min(shortfall, s.spot_coin_ntl)
        acts = []
        if sellable_usd > min_order_notional:
            acts.append(Action("sell_spot", size=sellable_usd / s.mid))
        transfer = min(shortfall, s.spot_usdc + sellable_usd)
        if transfer > min_order_notional:
            acts.append(Action("to_perp", amount=transfer))
        if acts:
            return acts
        # nothing left to sell/transfer -> shrink the short itself
        excess_ntl = s.perp_short_ntl - perp_equity * max_short_leverage
        if excess_ntl > min_order_notional:
            return [Action("close_short", size=excess_ntl / s.mid)]
        return []

    # 3. leverage far too low with a live position -> recycle idle margin
    if has_position and 0 < s.short_leverage < min_short_leverage:
        excess = perp_equity - s.perp_short_ntl / max_short_leverage
        if excess > min_order_notional:
            return [Action("to_spot", amount=excess)]

    # 4. delta drift -> trim the larger leg toward the smaller
    if has_position:
        tol = max(delta_tolerance * max(target_ntl, 1.0), min_order_notional)
        if s.delta_ntl > tol:
            return [Action("sell_spot", size=s.delta_ntl / s.mid)]
        if -s.delta_ntl > tol:
            return [Action("close_short", size=-s.delta_ntl / s.mid)]

    # 5. flat -> enter. Both legs are sized by what the SPOT side can actually
    # afford this cycle (after any margin transfer out of it): planning a $600
    # buy against $350 of spot cash would get the buy rejected/clipped while
    # the short still opened in full — one cycle of unhedged directional
    # exposure. If cash is parked on the perp side beyond the margin need,
    # recall it first so the affordable size approaches the target.
    if not has_position:
        if target_ntl <= min_order_notional:
            return []
        margin_needed = target_ntl / max_short_leverage
        acts = []
        spot_cash = s.spot_usdc
        if margin_needed - perp_equity > min_order_notional:
            transfer = margin_needed - perp_equity
            acts.append(Action("to_perp", amount=transfer))
            spot_cash -= transfer
        elif perp_equity - margin_needed > min_order_notional:
            recall = min(perp_equity - margin_needed, max(target_ntl - spot_cash, 0.0))
            if recall > min_order_notional:
                acts.append(Action("to_spot", amount=recall))
                spot_cash += recall
        buy_ntl = min(target_ntl, max(spot_cash, 0.0))
        if buy_ntl <= min_order_notional:
            return acts
        size = buy_ntl / s.mid
        acts.append(Action("buy_spot", size=size))
        acts.append(Action("open_short", size=size))
        return acts

    return []
