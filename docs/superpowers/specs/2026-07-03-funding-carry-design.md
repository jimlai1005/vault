# Sub-project E — Delta-Neutral Funding-Carry Engine (`hlvault.carry`)

**Date:** 2026-07-03
**Status:** Design approved (decision delegated to Claude as project decider)
**Wallet:** the ex-momentum wallet (`.env.momentum`'s credentials move to
`.env.carry`), ~$1,000 USDC currently in its perp account.
**Supersedes:** sub-project D (gridbot 2nd instance) — cancelled at its own
coin-selection gate (`reports/gridbot2-coin-selection.md`, NO-GO) and its
trend-filtered variant (`reports/trend-filtered-grid-verdict.md`, NO-GO).

## Why this, why now

Four directional/mechanic hypotheses have now been tested with real data and
rejected (copy-trading, time-series momentum, multi-alt grid, trend-filtered
grid). What survives scrutiny:

- **Funding carry is real and persistent on Hyperliquid** (12mo hourly scan,
  `scripts/research_funding_carry.py`): HYPE funding annualized **+12.1%**
  with **92% of hours positive**; BTC +7.2%/82%, ETH +7.5%/83%. Naive
  daily rotation dies to fees (−0.3%/yr), so the design below holds
  positions and minimizes turnover instead of chasing.
- **It complements the live gridbot instead of stacking risk on it**: carry
  = long spot + short perp. When HYPE crashes, gridbot (instance 1)
  stop-losses out with bounded loss while carry is unaffected; when HYPE
  pumps, gridbot prints and funding typically spikes higher. The two wallets
  end up one-long-inventory, one-neutral — portfolio risk goes down, not up.

**Honest expectation:** ~7–9%/yr on the wallet at conservative leverage —
the *stable ballast* leg. The *fast* leg remains gridbot instance 1
(+1.6% in its first 2 days) plus future capital scaling; this is stated
plainly rather than oversold.

## The strategy

**v1 = HYPE-only carry** (deepest HL spot liquidity, highest/steadiest
funding). Universe expansion (UBTC/UETH) is future work once v1 is boring.

- **Position:** hold `X` notional of spot HYPE and short `X` notional of
  HYPE perp. Delta ≈ 0; PnL = funding received − fees − basis noise.
- **Sizing:** `X = capital × DEPLOY_FRACTION` (default 0.60). Perp margin =
  remaining USDC in the perp account; effective short leverage ≤ 2x
  (`X / perp_margin ≤ MAX_SHORT_LEVERAGE`).
- **Entry/exit rule (low turnover by design):** enter/hold while trailing
  7-day mean funding > 0; unwind to full USDC when trailing 7-day funding
  < `EXIT_FUNDING_APR` (default 0, i.e. only exit when carry actually turns
  negative on a weekly basis). Hysteresis prevents flip-flopping.
- **The core engineering — liquidation defense:** spot HYPE cannot
  collateralize the perp short on Hyperliquid, so a fast HYPE pump bleeds
  the short's margin while the spot gain sits unrealized. The engine
  monitors margin ratio every cycle; if short-leg leverage drifts above
  `REBALANCE_LEVERAGE` (default 2.5x), it sells enough spot HYPE and
  class-transfers the USDC to the perp account to restore ≤2x. Symmetrically,
  if leverage drifts far below (price fell), it can move excess perp USDC
  back to spot and top the position back up (keeps delta ≈ 0 and capital
  working). Both legs of a rebalance shrink/grow *together* so delta stays
  ~0 at all times.
- **Delta guard:** |spot notional − perp short notional| / X >
  `DELTA_TOLERANCE` (default 2%) → trim the larger leg. This is checked from
  live exchange state each cycle (exchange is the source of truth), not from
  local bookkeeping.

## Architecture (mirrors the proven momentum/gridbot layout)

```
src/hlvault/carry/
  __init__.py
  config.py      # .env.carry via dotenv_values (isolated; no os.environ)
  state.py       # halted / peak_equity / _alerted_this_halt / _flatten_complete
                 #   / last_rebalance_ms  (same schema family as momentum)
  funding.py     # fundingHistory fetch + trailing-mean signal (pure)
  engine.py      # sizing/rebalance/delta-guard decision functions (pure)
  live.py        # CarryEngine: cycle loop, class transfers, order placement
scripts/fund_carry_spot.py   # one-time perp->spot USDC class transfer helper
deploy/hl-carry.service, deploy/setup-carry.sh
```

Reuse, not reimplementation: `gridbot.exchange_utils.get_account_equity`
(equity basis **must** additionally count spot HYPE at mark — see below),
`round_price/round_size/get_sz_decimals`, `ResilientExchange`,
`notify.telegram.send_alert`, `io.source.resilient_read`.

**Equity for the MDD breaker (CLAUDE.md #1 — one source, one basis):**
carry equity = spot USDC + spot HYPE × mid + Σ(perp marginUsed +
unrealizedPnl) + perp withdrawable-free USDC, all read in one cycle from the
same Info client. A dedicated `carry_equity()` lives in `hlvault/carry/`
(gridbot's spot-USDC-only basis is wrong for a wallet whose value is mostly
spot HYPE; this is a deliberate, documented divergence, tested against a
fake Info).

## Risk policy (unchanged family)

- 20% MDD hard stop from post-launch peak → unwind both legs to USDC, halt,
  Telegram alert, retry-until-flat (momentum's proven pattern; both the
  spot sell and the perp buy-to-close are reduce-only-in-spirit and
  idempotent to retry against live position reads).
- Given delta-neutrality, hitting 20% would itself signal something deeply
  wrong (basis blowout, failed rebalance loop) — the breaker is a backstop,
  not an expected path.
- All order placement via `ResilientExchange`; non-idempotent opens
  reconcile next cycle; dry-run gates every write including flatten
  (momentum's convention).
- Cycle cadence: `SYNC_INTERVAL_SECONDS=300`; funding signal refresh hourly.

## Go/no-go gate before LIVE_TRADING=true

Backtest is *not* the bottleneck here (the income stream is directly
observable in 12 months of funding prints; strategy PnL ≈ funding × deployed
notional − turnover fees, already computed in the research scan). The gate
is instead **execution correctness**:

1. Full test suite green (same no-network discipline).
2. Dry-run against the real wallet: two consecutive cycles produce sane
   `[DRY RUN]` orders and a correct equity/leverage readout.
3. A liquidation-defense simulation test: feed a synthetic 2x pump and
   assert the rebalance path sells spot and tops up margin before modeled
   liquidation price is reached.
4. Then flip live. Expected steady state: 1 entry, then near-zero turnover
   for weeks at a time.

## Open items

- HYPE spot market symbol/decimals on HL (spot pair id for the SDK) —
  resolve during implementation from the live spot meta endpoint.
- Funding-flip regime (trailing 7d < 0 for long stretches): engine just
  sits in USDC; capital idles rather than forcing trades. Accepted.
