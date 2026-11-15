# gridbot — independent grid-trading engine (design)

Goal: replicate the *mechanic* found in `target-strategy-analysis.md` (dense percentage grid,
spread capture, long-biased on trending alts) as an **independent strategy** — no copytrade
dependency, no mirroring of the target's orders — with risk controls the target does not
appear to have. Pilot risk budget (per user decision): **$1,000 USDC, 20% max drawdown**,
separate agent wallet/capital from the existing `hl-copytrader` deployment.

## Core mechanic per coin

A ladder of paired orders around the current mid price:

- `N` **buy rungs** below mid at geometric spacing `step_pct`: `rung_i = mid * (1 - step_pct)^i`
- Each filled buy immediately gets a **paired reduce-only sell** at `fill_px * (1 + step_pct)`
  (take the spread, not a directional bet).
- The ladder **trails upward**: when the top TP fills and price makes a new high beyond the
  current top rung, add a new rung at the top and retire the deepest rung (bounded by
  `max_position_notional`) — this reproduces the target's observed behavior of trailing HYPE
  from $21 to $75 rather than sitting in a fixed range.

## Improvements over the observed target

1. **Volatility-adaptive spacing** (target uses a fixed % per coin; no evidence of adaptation):
   `step_pct = clip(VOL_K * atr_pct_1h, MIN_STEP, MAX_STEP)`, recalibrated once per day per
   coin from the last 14d of 1h candles. Widens the grid automatically in high-vol regimes
   (fewer, larger, safer fills) instead of the same tight spacing regardless of regime.
2. **Hard per-coin stop-loss** (target shows none): if price trades below
   `lowest_active_rung * (1 - STOP_BUFFER_PCT)`, flatten that coin's position with a
   reduce-only market order and pause new rungs on it for `COOLDOWN_HOURS`. Per CLAUDE.md #3,
   this is a safety-critical action — failure to flatten must alert, not silently retry-loop.
3. **Portfolio drawdown circuit breaker**: equity vs the same allocated-capital baseline
   (CLAUDE.md #1 — one source, one basis: both read from the account's own clearinghouseState,
   never mixed with an external snapshot). At `MAX_DRAWDOWN_PCT = 0.20` of allocated capital:
   cancel all resting orders, switch every coin to reduce-only, alert, and require a manual
   re-arm — never auto-resume.

   **Exit semantics as implemented (2026-11-14, plan `docs/plans/gridbot-position-truth.md`).**
   The 2026-11-05 incident showed the two exits above followed the bot's own books
   (`state.open_lots`) and never read the exchange: ~6% of buy fills were never recorded, the
   circuit breaker closed only the lots it knew about, and nobody looked at positions after the
   halt (20% drawdown became 40%). Now:
   - **Position truth gate.** Every "what do we hold" question goes through
     `exchange_utils.read_positions` (exchange `szi`). "Could not read" raises; it never reads
     as "no position".
   - **Flat means verified.** Both the circuit breaker (all of `COIN_UNIVERSE`) and the
     per-coin stop-loss (one coin) run the same routine: cancel every resting order of the
     coin(s) on the exchange, market-close the exchange `szi` (reduce-only), wait, read orders
     then positions back, and only call it flat when there are no orders and `szi == 0`.
     Not verified -> books kept, `flatten_pending` / `stop_pending` persisted, retried every
     cycle regardless of price, one Telegram on failure and one on verified completion.
     Spot holdings and non-universe perps are never touched.
   - **Buys cannot be forgotten.** An armed buy leaves the books only after its final state is
     read back by oid (`orderStatus`): filled quantity (`origSz - sz`, partial fills included)
     becomes a lot + TP, zero fill on a dead order is dropped, anything unreadable is kept and
     re-checked next cycle. A cancel is always followed by that read-back.
   - **Cap on the exchange position, resting buys included.** Per coin,
     `abs(szi) * mid + resting buy notional <= max_position_notional`; the deepest buys are
     cancelled first. (Before: the cap ignored resting buys, so a fast drop could fill ~2x the
     budget — live diverged from the backtest, which caps at fill time.)
   - **Reconcile every cycle.** `szi` vs the books; a gap for 2 cycles alerts once and pauses
     new buys for that coin. Untracked size is never traded automatically (owner decision).
     A coin whose cycle keeps failing (unreadable orders/price/positions) alerts after 5 cycles.
   - **Re-arm.** A service restart is the owner's re-arm request: it resumes only if the
     drawdown has recovered, and first completes any flatten still pending. While halted with
     no flatten pending the bot does not touch the exchange.
4. **Systematic capital allocation** (target put 74% into one coin, seemingly ad hoc): split
   allocated capital across a fixed coin universe by a liquidity/inverse-volatility weight,
   capped at `MAX_COIN_ALLOCATION_PCT` per coin (default 40%) so no single market can sink the
   whole pilot.
5. **Leverage by tier, not per-asset guesswork**: conservative fixed tiers
   (majors 5x / mid-liquidity alts 3x / everything else 2x), derived once from the coin's
   volatility bucket rather than chosen per-market as the target's fills suggest.

## Order management

Reuse the proven pattern from `hl-copytrader/src/orders.py` (diff current resting orders vs
desired rungs; `modify` in place where price/size drifted; cancel+place only when necessary) —
don't reinvent order reconciliation. Every exchange call goes through one resilience boundary
(CLAUDE.md #5): classify transient-vs-semantic and retryable-vs-not at the call site; only
place/modify calls are safely retried when they are idempotent-by-clientOrderId, never blind-
retried when a fill may have already landed unconfirmed (CLAUDE.md #2).

## Backtest plan

Replay 1h/5m historical candles (Hyperliquid `candleSnapshot`) through the same rung-fill logic
used live (shared code path, not a re-implementation) to get an apples-to-apples Sharpe/drawdown
against the target's own reconstructed realized PnL from `target-strategy-analysis.md`.

## What's still blocked on the user

Live order placement needs a **new Hyperliquid agent wallet** (Hyperliquid → More → API),
funded with the $1,000 pilot capital, kept separate from `hl-copytrader`'s existing wallet per
your decision to run in parallel. Everything up to "ready to go live, `LIVE_TRADING=false` by
default" can be built and tested without it.
