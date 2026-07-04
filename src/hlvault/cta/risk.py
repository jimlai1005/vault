"""Position sizing, the strategy-level 2xATR hard stop, and the portfolio MDD
circuit breaker for the CTA engine.

Equity basis (CLAUDE.md #1 — wallet-shape-specific, three incidents deep; see
account_equity's docstring for the full history): the MDD breaker's current and
peak equity both come from ONE function, account_equity (spot USDC + perp
totalMarginUsed + perp withdrawable). This is deliberately NOT gridbot's basis
(blind to perp free collateral, which this wallet holds) and NOT carry's basis
(which adds a spot-coin leg this wallet does not have), and it adds NO separate
upnl term (withdrawable already contains it — the carry double-count bug).

ATR entry gate (CLAUDE.md, and a hard requirement): signals.atr() returns NaN
during the warmup window and can only be non-negative. Sizing/stop math that
consumed a NaN or <= 0 ATR would emit garbage (a NaN stop the engine cannot
compare, or a zero-width stop that trips instantly). `atr_gate_ok` is the single
predicate the entry path must clear before an ATR-derived stop is computed, and
`stop_level` itself returns NaN for a bad ATR so a bypassed gate still cannot
manufacture a tradeable stop level."""
from __future__ import annotations

import logging

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
    """CTA-wallet equity: spot USDC + perp totalMarginUsed + perp withdrawable.

    The equity basis is WALLET-SHAPE-SPECIFIC (engineering principle #1: the
    MDD breaker compares current against peak, so both must come from this one
    function, AND the basis must count every bucket this wallet's value lives
    in exactly once). Three equity-basis incidents shaped this formula:

    1. carry's phantom 41.9% drawdown (mixed sources): current equity and peak
       equity were assembled from different endpoints with different bases.
       Fix here: current and peak both flow from this single function.
    2. carry's double-count (2026-07-04): `withdrawable` ALREADY includes
       unrealizedPnl — verified on-chain (carry wallet: accountValue 281.13 ==
       totalMarginUsed 63.34 + withdrawable 217.79, with upnl -28.41 already
       inside withdrawable). So this formula adds NO separate upnl term;
       adding one counts floating pnl twice.
    3. gridbot's phantom 23.6% drawdown (resting orders): with resting orders,
       accountValue swings with order-margin reservations and the identity
       accountValue == totalMarginUsed + withdrawable BREAKS (resting-order
       margin sits in neither bucket). That forced gridbot to hand-roll
       spot USDC + Σ per-position (marginUsed + upnl) — a basis that is BLIND
       to perp free collateral. This wallet parks part of its idle USDC as
       perp free collateral (measured ~$281 = 28% of the account), so reusing
       gridbot's basis here understated equity by 28% and anchored the MDD
       peak too low: the third incident, fixed by this function.

    Precondition (why the formula is safe HERE): this engine trades IoC-only
    and never rests orders, so the no-resting-orders identity holds and
    spot USDC + totalMarginUsed + withdrawable == spot USDC + accountValue —
    assembled from the two fields whose semantics were verified on-chain
    rather than from accountValue directly. If an operator manually rests an
    order on this wallet, that order's margin drops out of BOTH fields and
    equity is understated — the breaker would trip early (conservative, not
    dangerous, but be aware).

    No spot-coin leg: this wallet holds no spot coins (counting them is
    carry's basis, not ours). Strict key access on marginSummary/withdrawable
    is deliberate: a missing bucket must fail loudly (principle #3), because a
    silent 0.0 default IS this incident class."""
    perp = info.user_state(address)
    margin_used = float(perp["marginSummary"]["totalMarginUsed"])
    withdrawable = float(perp["withdrawable"])
    spot = info.spot_user_state(address)
    spot_usdc = 0.0
    for bal in spot.get("balances", []):
        if bal.get("coin") == "USDC":
            spot_usdc = float(bal.get("total", 0.0))
            break
    return spot_usdc + margin_used + withdrawable


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
