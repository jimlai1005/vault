# Sub-project C — Systematic Trend/Momentum Strategy (`hlvault.momentum`)

**Date:** 2026-07-02
**Status:** Design approved (decision delegated to Claude as project decider; user is observer)
**Repo:** `hl-vault` (this repo) — new subpackage, independent of `hlvault.gridbot`

## Executive summary

Add a third, independent trading engine to the vault: a systematic trend/momentum
strategy on Hyperliquid perps. It runs on its own wallet, its own capital, and its
own risk budget — it does not read, write, or depend on `hlvault.gridbot` in any way.

**Why this strategy, and not the alternatives already considered:**
- **Copying a basket of top traders** (HRP-weighted vault) was already tested
  rigorously in sub-project A (`reports/oos-verdict.md`) with a walk-forward OOS
  backtest and deflated-Sharpe selection-bias correction: **NO-GO**. The
  persistent-alpha universe is too small (1–4 traders at any rebalance), hedging
  out BTC/ETH beta made results worse, and the residual is not significantly
  positive OOS. This path is not being retried.
- **Copying one specific wallet's mechanic** was investigated in
  `reports/target-strategy-analysis.md`: the target address turned out to be a
  dense percentage grid / automated market-maker, not a discretionary trader.
  That mechanic is already implemented and live as `hlvault.gridbot`.
- Trend/momentum is chosen because it is (a) uncorrelated with gridbot's
  mean-reversion/liquidity-capture edge — gridbot profits in chop and is exposed
  to large directional moves; momentum profits from exactly those moves — and
  (b) testable with public price data at scale, avoiding the "borrowed alpha"
  failure mode that sank sub-project A.
- A social-media / narrative-momentum signal (text analytics on X/Twitter,
  KOL activity) was discussed and deliberately deferred: there is no historical
  dataset to backtest it against yet, so validating it before risking capital is
  not currently possible. It is noted as future work (see below), potentially as
  a position-sizing overlay on top of the price-based momentum signal once this
  system has a live track record.

**Future direction (explicitly out of scope for this spec, noted for continuity):**
once both `hlvault.gridbot` and `hlvault.momentum` have live track records, a
portfolio-level rebalancer could allocate capital between the two strategies
based on realized regime (trending vs. chop) — at that point the two engines plus
the rebalancer constitute a self-contained multi-strategy vault. Not built now
(YAGNI) — flagged here so the independent-engine design below doesn't
accidentally foreclose it (each engine already reports equity/drawdown in a
uniform way that a future rebalancer could consume).

## Goals / Non-goals

**Goals**
- A systematic, price-data-driven trend-following engine, independently
  backtestable with walk-forward OOS methodology before/alongside going live.
- Hard, structural drawdown control: 20% MDD from post-launch peak equity
  triggers automatic full flatten + trading halt + loud alert. This is enforced
  inside the always-on live process, not dependent on any chat session or human
  polling.
- Reuse this repo's existing resilience boundary (`hlvault/io`) and CLAUDE.md
  discipline (single source of truth for compared values, transient-vs-semantic
  error handling, idempotent-only retries, no-network tests).
- Telegram alerting for critical events (circuit breaker trip, unhandled
  exception, exchange rejection on a safety-critical action).

**Non-goals (this spec)**
- No changes to `hlvault.gridbot` — read-only reference for conventions only.
- No social-media/NLP signal in v1 (see Future direction above).
- No cross-strategy rebalancer in v1.
- No UI beyond extending the existing local dashboard with a momentum tab/section.

## Risk parameters (user-approved, hardcoded — not tunable via a "just this once" override)

- **Capital:** entire balance of a dedicated new Hyperliquid wallet (separate
  from gridbot's and copytrader's wallets — no shared-wallet accounting risk).
- **MDD hard stop:** 20%, measured from the highest equity observed *since this
  engine's own launch*, computed from a single equity source (CLAUDE.md #1).
  On breach: cancel all resting orders, market-flatten all positions, set
  `LIVE_TRADING=false` in persisted state (requires explicit manual re-enable),
  send a Telegram alert. This is a safety-critical action per CLAUDE.md #3: if
  the flatten call itself fails, retry (flatten/reduce-only close is idempotent)
  and alert loudly — never log-and-continue.
- **Autonomy boundary:** live trading may start automatically once (a) the new
  wallet is funded and its key is in `.env.momentum`, and (b) the walk-forward
  backtest in this spec has been run and reviewed (by Claude, autonomously —
  this is due diligence, not a user-approval gate; the user has pre-authorized
  going live directly). No further per-trade or per-day confirmation is
  required from the user unless the circuit breaker trips.

## Architecture

New subpackage mirroring `hlvault/gridbot/`'s layout:

```
src/hlvault/momentum/
  __init__.py
  config.py        # pydantic-settings, loads .env.momentum
  signals.py        # multi-timeframe momentum/breakout score per asset
  risk.py            # vol-scaled sizing, exposure caps, MDD circuit breaker
  backtest.py        # walk-forward OOS harness + go/no-go verdict (reuses the
                      # point-in-time discipline from sub-project A's backtest stage)
  live.py            # live engine entrypoint (order placement, reconciliation)
  state.py            # persisted equity peak, halt flag, open positions
  resilience.py       # thin wrapper delegating to hlvault/io/source.py boundary
src/hlvault/notify/
  __init__.py
  telegram.py         # shared Telegram notifier (new — usable by momentum and,
                       # later, gridbot if desired; gridbot is not modified now)
```

### Data flow

```
hlvault/io (existing HL API + cache) ──▶ signals.py (per-asset momentum score)
                                              │
                                              ▼
                                       risk.py (position sizing, exposure caps)
                                              │
                                              ▼
                                       live.py (order placement via hlvault/io)
                                              │
                                              ▼
                                 state.py (equity, peak, halt flag — single
                                 source of truth read by both live.py's trading
                                 loop and risk.py's MDD check)
                                              │
                              on breach ──▶ notify/telegram.py (alert) +
                                             live.py forces flatten + halts
```

### Backtest (due-diligence gate, run by Claude before flipping `LIVE_TRADING=true`)

- Walk-forward OOS, same discipline as sub-project A: as-of clock so no
  lookahead, parameter grid (lookback windows, breakout thresholds) evaluated
  with a multiple-testing correction analogous to DSR, verdict reports OOS
  Sharpe/Calmar/max-drawdown honestly.
- Universe: Hyperliquid's liquid perp markets (liquidity-filtered, not just
  BTC/ETH, to get diversification across uncorrelated trend signals — this is
  the mechanism that lets the strategy chase big absolute returns without
  concentrating drawdown risk in one asset).
- Verdict is a report artifact under `reports/`, same pattern as
  `oos-verdict.md`. If it comes back NO-GO, momentum does not go live and this
  is reported to the user rather than iterated into a GO by parameter search
  (same anti-p-hacking stance as sub-project A).

### Error handling (CLAUDE.md #2 / #5)

- All exchange/API calls go through the existing `hlvault/io/source.py`
  boundary. Transient errors (timeouts, 5xx, connection reset) retry with
  backoff. Semantic errors (rejected order, insufficient margin) surface, no
  retry. Order placement (non-idempotent) reconciles against exchange state
  next cycle rather than blind-retrying; flatten/reduce-only closes (idempotent)
  retry safely.

### Telegram notifier

- `hlvault/notify/telegram.py`: single function `send_alert(message, level)`
  reading `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from `.env.momentum`.
  Network call goes through the same resilience boundary (transient retry,
  never blocks the flatten action on notification failure — alerting failure
  must not prevent the safety action itself).

## Testing strategy

- Autouse fixture mutes real network + real Telegram send for the whole suite
  (CLAUDE.md #4) — a present `.env.momentum` must not cause live calls in tests.
- Synthetic-data tests for `signals.py` (known trend → known signal sign) and
  `risk.py` (known equity path → circuit breaker fires at exactly 20% from
  peak, computed from one series — a direct test of CLAUDE.md #1).
- No-lookahead test for `backtest.py` (same pattern as sub-project A).
- Idempotency test: simulated dropped response on a flatten call asserts a
  retry does not double-close.

## Deployment

- `deploy/hl-momentum.service` (systemd unit), mirroring
  `deploy/hl-gridbot.service`, running as its own process — independent of any
  Claude Code session. `pyproject.toml` gets a new script entry
  `hl-momentum = "hlvault.momentum.live:main"`.

## Open items (not blocking spec approval, tracked for follow-up)

- New Hyperliquid wallet address/private key — user is provisioning this now;
  `.env.momentum` has placeholders (`WALLET_ADDRESS`, `WALLET_PRIVATE_KEY`,
  `ALLOCATED_CAPITAL`, `LEVERAGE`) to fill in once available. `LIVE_TRADING`
  defaults to `false` until then.
- Exact leverage cap and per-asset exposure cap are implementation-plan-level
  parameters, not re-litigated here; they must jointly guarantee the 20% MDD
  budget is structurally hard to blow through even under a single-asset gap
  move (worst-case sizing math belongs in the implementation plan / `risk.py`).
