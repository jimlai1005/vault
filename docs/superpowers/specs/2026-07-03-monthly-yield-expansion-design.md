# Sub-project F — Monthly-Yield Expansion Research

**Date:** 2026-07-03 · **Status:** Design approved (Claude as delegated decider)
**Owner ask:** find paths toward 5-10%/month; compare Bitfinex lending; explore
pair trading / regression stat-arb.

## Honest framing (binding)

5-10%/month = 80-215%/yr. Sustained, low-risk versions of this do not exist
in liquid markets. This project treats it as an aspirational target under
hard risk gates (20% MDD breakers), not a promise. Expected honest outcome:
some candidates NO-GO, survivors sized realistically.

## Three parallel tracks

### F1. Passive benchmarks (data pull, no build)
- Bitfinex fUSD lending: public API, 1yr of funding rates -> realized APR
  distribution, drawdown-free but custodial risk (exchange insolvency).
- Hyperliquid HLP vault: vaultDetails API for the protocol vault -> APR
  history + drawdown episodes. Self-custody-adjacent, one-click.
- Output: risk-adjusted comparison table vs live gridbot + carry actuals.
  Decision rule: if a passive benchmark beats an active engine risk-adjusted
  over comparable windows, reallocate that engine's capital.

### F2. Pair trading / cointegration stat-arb (user-requested; main build candidate)
- Universe: 17 HL perps with cached hourly candles (+ fetch more as needed).
- Method: Engle-Granger cointegration test on log prices (train window),
  rolling OLS hedge ratio, z-score of spread; enter |z|>2 long/short the
  pair legs, exit z->0.5, stop at |z|>4 or max-holding 7d. Walk-forward:
  re-select pairs + refit quarterly, trade only next quarter (strict PIT).
- Fees/funding modeled: taker 0.045%/leg + funding differential on both perp legs.
- PRE-DECLARED GATE (all must hold): walk-forward OOS Sharpe > 1.0;
  aggregate MDD <= 15%; >= 3 distinct pairs qualify in the final selection;
  sign stable across z-entry {1.5, 2.0, 2.5} and train windows {60d, 90d}.
  Fail => NO-GO, no tuning, document and stop.
- If GO: build `hlvault.statarb` live engine (new wallet or reallocated
  capital — owner decision at that point), same safety family (MDD breaker,
  dry-run, Telegram, reviews).

### F3. Gridbot capital scaling (no build)
- The 2026-07-15 14-day live review already scheduled. If realized daily
  return >= 0.5%/day with per-coin PnL healthy, scaling capital into gridbot
  is the fastest evidenced path to the monthly target. Data decides.

## Capital note
Both wallets are deployed. Any F2 GO deployment needs fresh capital or
reallocation (owner to decide when presented with the verdict).

## Execution
F1: haiku data-pull script + report. F2: research script (statsmodels
Engle-Granger; sonnet-class for the math core), run on cached data,
verdict report. Reviews per repo convention. All research committed to
reports/.
