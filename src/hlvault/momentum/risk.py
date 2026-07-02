"""Position sizing, order reconciliation, and the portfolio MDD circuit
breaker. Current and peak equity always come from the same
get_account_equity call (CLAUDE.md #1) — reused directly from
hlvault.gridbot.exchange_utils, which already fixed a false-positive
drawdown bug there; re-deriving that logic here would risk repeating it."""
from __future__ import annotations

import logging

from hlvault.gridbot.allocator import allocate_capital
from hlvault.gridbot.exchange_utils import get_account_equity

logger = logging.getLogger("momentum")


def risk_budget_per_coin(vol_by_coin: dict, total_capital: float, max_alloc_pct: float) -> dict:
    """Inverse-volatility risk budget, capped per coin — identical algorithm
    to gridbot.allocator.allocate_capital, reused rather than re-implemented."""
    return allocate_capital(vol_by_coin, total_capital, max_alloc_pct)


def target_position_notional(signal: float, risk_budget: float, max_leverage: float) -> float:
    """`signal` in [-1, 1] (from signals.score_to_position). Positive = long,
    negative = short. Bounded by risk_budget * max_leverage so a single
    full-conviction signal can't exceed this asset's allocated risk budget
    times its leverage cap."""
    clipped = max(-1.0, min(1.0, signal))
    return clipped * risk_budget * max_leverage


def compute_order(current_size: float, target_notional: float, price: float,
                  min_order_notional: float) -> dict | None:
    """Pure reconciliation decision: what order (if any) moves `current_size`
    toward `target_notional`. `reduce_only=True` only when the order strictly
    shrinks an existing position toward zero without crossing sides — crossing
    from long to short (or vice versa) is two economically different actions
    and must NOT be marked reduce_only (Hyperliquid would reject/clip it)."""
    if price <= 0:
        return None
    target_size = target_notional / price
    delta = target_size - current_size
    notional = abs(delta) * price
    if notional < min_order_notional:
        return None
    is_buy = delta > 0
    reduce_only = (
        current_size != 0
        and (current_size > 0) != is_buy
        and abs(delta) <= abs(current_size)
    )
    return {"is_buy": is_buy, "size": abs(delta), "reduce_only": reduce_only}


def check_drawdown(info, address: str, state: dict, max_drawdown_pct: float) -> tuple[bool, dict]:
    """Returns (should_halt, updated_state). Once halted, does not touch the
    exchange again — a human must clear `halted` in the state file after
    review (same policy as gridbot)."""
    if state.get("halted"):
        return True, state
    current = get_account_equity(info, address)
    peak = max(state.get("peak_equity", 0.0), current)
    state["peak_equity"] = peak
    drawdown = (peak - current) / peak if peak > 0 else 0.0
    if drawdown >= max_drawdown_pct:
        logger.error(f"MOMENTUM DRAWDOWN CIRCUIT BREAKER: {drawdown:.1%} "
                    f"(peak ${peak:,.2f} -> now ${current:,.2f})")
        state["halted"] = True
        return True, state
    return False, state
