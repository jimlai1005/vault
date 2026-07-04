"""Position sizing, the strategy-level 2xATR hard stop, and the portfolio MDD
circuit breaker for the CTA engine.

Equity basis (CLAUDE.md #1): the MDD breaker's current and peak equity both
come from ONE call to gridbot.exchange_utils.get_account_equity (spot USDC +
sum(marginUsed + unrealizedPnl) across perp positions). This wallet holds only
USDC + HL perp positions (no spot-coin leg), so that basis is exactly right —
this is deliberately NOT carry's spot-coin-inclusive basis, and it does NOT add
`withdrawable` (adding withdrawable + margin + upnl is precisely the carry
double-count bug fixed 2026-07-04). Reuse get_account_equity; do not hand-roll.

ATR entry gate (CLAUDE.md, and a hard requirement): signals.atr() returns NaN
during the warmup window and can only be non-negative. Sizing/stop math that
consumed a NaN or <= 0 ATR would emit garbage (a NaN stop the engine cannot
compare, or a zero-width stop that trips instantly). `atr_gate_ok` is the single
predicate the entry path must clear before an ATR-derived stop is computed, and
`stop_level` itself returns NaN for a bad ATR so a bypassed gate still cannot
manufacture a tradeable stop level."""
from __future__ import annotations

import logging

from hlvault.gridbot.exchange_utils import get_account_equity

logger = logging.getLogger("cta")


def position_size(notional: float, price: float) -> float:
    """Coin units for a fixed-notional entry. Non-positive price -> 0 (no
    order), NaN-safe via `not (price > 0)` (nan > 0 is False, so NaN is
    rejected too)."""
    if not (price > 0):
        return 0.0
    return notional / price


def atr_gate_ok(atr: float) -> bool:
    """Entry gate: an ATR-derived stop is only meaningful when ATR is a finite
    positive number. During signals.atr()'s warmup window ATR is NaN; a
    zero/negative ATR is degenerate. Either case must block a NEW entry rather
    than let NaN/zero flow into stop_level / position math. NaN-safe via
    `not (atr > 0)`."""
    if atr is None or not (atr > 0):
        return False
    return True


def stop_level(direction: int, entry_px: float, atr: float, mult: float) -> float:
    """2xATR hard-stop price. SHORT (dir -1): stop ABOVE entry (entry + mult*atr).
    LONG (dir 1): stop BELOW entry (entry - mult*atr). Matches the backtest's
    `entry_px - dir * STOP_ATR_MULT * atr`.

    Guard (CLAUDE.md): a NaN or non-positive ATR (warmup / degenerate) yields
    NaN, never a bogus stop level. The entry path should have already refused
    the trade via atr_gate_ok; returning NaN here is the structural backstop so
    a bypassed gate cannot produce a stop the engine would act on."""
    if not (atr > 0):
        return float("nan")
    return entry_px - direction * mult * atr


def stop_hit(direction: int, stop: float, price: float) -> bool:
    """True when the live price has reached/breached the stop. SHORT stops out
    when price rises to/above stop; LONG stops out when price falls to/below.
    A NaN stop (never armed) or NaN price can never trigger (all comparisons
    with NaN are False), so a warmup/garbage stop stays inert."""
    if direction == -1:
        return price >= stop
    if direction == 1:
        return price <= stop
    return False


def account_equity(info, address: str) -> float:
    """Single equity basis for this wallet — see module docstring. Reused
    verbatim from gridbot (spot USDC + Σ marginUsed+upnl); no `withdrawable`."""
    return get_account_equity(info, address)


def check_drawdown(info, address: str, state: dict, max_drawdown_pct: float):
    """Returns (should_halt, updated_state). Pure w.r.t. persistence: does NOT
    write state (kept testable) — the caller MUST persist immediately, ideally
    before any flatten, so a crash mid-flatten cannot lose the halt flag (same
    caller obligation as momentum.risk.check_drawdown). Current and peak equity
    come from the SAME account_equity call (CLAUDE.md #1) — never mixing two
    sources, which is what caused carry's phantom drawdown."""
    if state.get("halted"):
        return True, state
    current = account_equity(info, address)
    peak = max(state.get("peak_equity", 0.0), current)
    state["peak_equity"] = peak
    drawdown = (peak - current) / peak if peak > 0 else 0.0
    if drawdown >= max_drawdown_pct:
        logger.error(f"CTA DRAWDOWN CIRCUIT BREAKER: {drawdown:.1%} "
                    f"(peak ${peak:,.2f} -> now ${current:,.2f})")
        state["halted"] = True
        return True, state
    return False, state
