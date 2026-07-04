# Sub-project G (cont.) — CTA Live Engine (`hlvault.cta`)

**Date:** 2026-07-04 · **Status:** design approved (Claude as delegated decider;
owner gave explicit directive to implement + pre-authorized repurposing the
carry wallet after tomorrow's carry health check)
**Depends on:** `reports/cta-phase2b-verdict.md` (the research this operationalizes)

## Honest framing (binding — this is NOT a passed gate)

Phase 2b was **NO-GO** on the pre-declared multiple-testing bar (best config
`4h-p10-fuel24-short` Sharpe 2.34, t=2.14 < the ~2.9 Bonferroni threshold for
24 trials). The ONLY reason for a live deployment is the owner's explicit
decision: run **small ($1,000)** to accumulate genuine out-of-sample live
evidence over ~6 months, then re-evaluate scaling. This is forward-testing
an in-sample-best config with real skin — a legitimate way to resolve a
"not enough data" verdict, but it must be labeled as such everywhere. It is
NOT a validated edge. Capital at risk is capped by the 20% MDD breaker and
the small book.

## Strategy (operationalizes the phase-2b family)

Per coin, each rebalance:
- **Trend:** EMA20 vs EMA50 on 4h closed bars (Binance klines — same source
  as the backtest, so the live signal matches what was validated). Down-trend
  = EMA50 > EMA20; up = EMA20 > EMA50.
- **Crowding (contrarian):** Binance long/short account ratio (via Coinalyze,
  `.A` symbols), rolling trailing-90d percentile (min 30d warmup, PIT). Retail
  crowded-long = ratio percentile >= 90 (i.e. p10 config, top decile). Mirror
  for crowded-short.
- **Fuel:** Coinalyze OI rose over the trailing 24h.
- **SHORT entry:** down-trend AND retail-crowded-long AND OI-rising.
  **LONG entry:** up-trend AND retail-crowded-short AND OI-rising (mirrored).
- **Exit:** OI fuel fails (OI not rising) OR trend flips OR hard stop
  2×ATR(14, 4h) from entry OR 14-day max hold.
- One position per coin; sized `NOTIONAL_PER_TRADE` (default $100) so the
  $1,000 book runs ~5-8 concurrent max across the universe.
- Universe: BTC, ETH, SOL, HYPE, DOGE, XRP (the six with Coinalyze data).

## Per-side switches (owner's explicit design requirement)

`ENABLE_LONG` / `ENABLE_SHORT` env booleans. **Live default: LONG disabled,
SHORT enabled** — phase-2b evidence: the long leg is deeply negative on 4h
(−$51 to −$81 across all configs) and flat-to-weak on 1d; shorts carry the
entire edge on both timeframes. Running longs live would knowingly burn
capital to re-confirm a rejected sub-hypothesis. The switch (which the owner
asked for precisely to disable a losing side) is set to honor the evidence.
The full both-sides logic is still built and tested so the switch is a real,
reversible config — if live shorts confirm and the owner later wants to
gather long-side evidence, it flips with one env change.

## Data architecture (the new hard part vs carry/momentum)

Signals come from **Binance-venue data** (Coinalyze OI + LSR, Binance klines);
execution is on **Hyperliquid perps**. This cross-venue signal→execution gap
is a real, documented risk (the crowding/OI that drives the signal is Binance
retail, not HL's; liquid majors correlate but it is not identical). The live
engine:
- Fetches Coinalyze OI + LSR each rebalance via `.env.research` key (header
  `api_key`, 40 req/min → throttle 1.6s), through the shared resilience
  boundary. Caches to avoid re-pull within a cycle.
- Fetches Binance 4h klines for trend (paginated, cached).
- Places orders on HL via the same `ResilientExchange` + IoC-limit +
  round_price/round_size path proven in momentum/carry.
- Rebalance cadence: every 4h (aligned to bar close); drawdown breaker checked
  every SYNC_INTERVAL_SECONDS (default 300s) independent of rebalance.

## Architecture (mirror momentum's proven layout)

```
src/hlvault/cta/
  __init__.py
  config.py     # .env.cta via dotenv_values (isolated dict; NEVER os.environ)
  state.py      # halted/peak_equity/_alerted_this_halt/_flatten_complete
                #   /last_rebalance_ms  (same schema family)
  signals.py    # pure: EMA trend, rolling-percentile crowding, OI-fuel gate,
                #   score->{long,short,flat} per coin (side switches applied here)
  data.py       # Coinalyze OI+LSR fetch + Binance klines fetch, both cached,
                #   both through io.source.resilient_read
  risk.py       # position sizing, ATR stop, MDD circuit breaker (reuse
                #   gridbot.get_account_equity — this wallet is USDC+perp,
                #   gridbot's basis is correct here, NOT carry's)
  live.py       # CtaEngine: cycle loop, entry/exit/stop, reconciliation
scripts/setup_cta_wallet.py  # (thin) verify wallet is pure-USDC perp-funded
deploy/hl-cta.service, deploy/setup-cta.sh
```

Reuse (import, do not reimplement): `gridbot.exchange_utils`
(`get_account_equity`, `get_mid_price`, `get_sz_decimals`, `round_price`,
`round_size`), `gridbot.resilience.ResilientExchange`, `notify.telegram`,
`io.source.resilient_read`.

**Equity basis (CLAUDE.md #1):** this wallet holds USDC + HL perp positions
(no spot leg), so `gridbot.exchange_utils.get_account_equity` (spot USDC +
Σ perp marginUsed+upnl) is the correct basis — deliberately NOT carry's
spot-coin-inclusive basis. Documented in risk.py. (Note the carry
double-count bug fixed 2026-07-04: do NOT add withdrawable+upnl+margin here;
gridbot's helper already avoids that. Reuse it, don't hand-roll.)

## Risk policy (same family)

- 20% MDD hard stop from post-launch peak → flatten all positions, halt,
  Telegram alert, persist-halt-before-flatten, retry-flatten-until-complete,
  re-arm on healthy cycle (momentum's proven pattern).
- Per-position 2×ATR(14) hard stop (strategy-level, separate from the
  portfolio breaker).
- All exchange writes dry-run gated; non-idempotent opens reconcile next
  cycle; reduce-only closes retry.
- Cross-venue data staleness guard: if Coinalyze/Binance fetch fails or
  returns stale data (last point older than N hours), skip NEW entries that
  cycle (do not trade on stale signals) but still run the drawdown breaker
  and manage exits/stops on existing positions from HL state.

## Go-live gate (execution-correctness, mirrors carry)

Not a PnL gate (that was phase-2b, already NO-GO but owner-overridden for
small forward-test). Gate = correctness: full test suite green; a
signal-reproduction test (given fixed OI/LSR/kline fixtures, the live signal
matches the backtest's signal for the same bar); dry-run against the real
wallet showing sane intended orders; then LIVE_TRADING=true with short-only.

## Wallet (tomorrow, post carry health check — owner pre-authorized)

Carry wallet (`0xbAC6…3662`) repurposed: stop carry → flatten carry to USDC
→ (spot USDC may need class-transfer to perp for margin — but that requires
the master key, same limit hit before; if agent-key-only, keep USDC where
flatten leaves it and sic the CTA engine on whatever account holds it, sizing
to available margin) → `.env.cta` with the wallet creds → dry-run → live.
Exact transfer mechanics decided at execution time based on where flatten
leaves the funds. Carry code stays in the repo (dormant), not deleted.

## Out of scope
Multi-timeframe blend, the 1d configs, long-side live trading (switch off),
capital scaling (owner revisits in ~6 months per the forward-test plan).
