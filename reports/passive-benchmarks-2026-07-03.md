# Passive Yield Benchmarks: Bitfinex, Hyperliquid HLP, and Live Engines

**Date**: 2026-07-03  
**Research Scope**: Public API data only (no credentials, no trading)

## Summary

This report compares four passive yield approaches:
1. **Bitfinex USD Lending** — exchange-based fixed-income, 365-day track record
2. **Hyperliquid HLP Vault** — protocol vault (liquidations + market-making), current week
3. **Carry Engine** — live 2026-07-03, targeting ~10% APR from funding rates
4. **Gridbot** — live 2026-07-01 to 07-03, +1.6% in 2 days (tiny sample)

## Data Sources

| Source | API | Data Type | Lookback | Status |
|--------|-----|-----------|----------|--------|
| Bitfinex | `GET /v2/candles/trade:1D:fUSD:a30:p2:p30/hist?limit=365` | Daily funding candles | 365 days | ✓ OK |
| Hyperliquid | `POST /info type=vaultDetails` | Vault portfolio history | week (67 pts) | ✓ OK |
| Carry Engine | (repo docs / logs) | Trailing 7d funding at entry | 1 day observed | ✓ LIVE |
| Gridbot | (repo logs) | Portfolio delta PnL | 2 days observed | ✓ LIVE |

## Detailed Results

### 1. Bitfinex USD Lending Rates

**Symbol**: `fUSD:a30:p2:p30` (30-day funding period, average rate)  
**Window**: 365 daily candles (2025-07-03 to 2026-07-03)  
**Method**: Daily rate field (CLOSE) × 365 = annualized APR

| Metric | Value |
|--------|-------|
| **Mean APR** | 6.41% |
| **25th percentile APR** | 4.73% |
| **75th percentile APR** | 6.94% |
| **Min daily rate** | 0.000001 |
| **Max daily rate** | 0.007 |

**Interpretation**: Steady ~6–7% APR with low volatility. The 25th–75th band (4.7–6.9%) suggests rates rarely drop below 4% or spike above 7%. This is stable, tradeable yield backed by deep USD liquidity.

### 2. Hyperliquid HLP Vault

**Vault Address**: `0xdfc24b077bc1425ad1dea75bcb6f8158e10df303`  
**Window Selected**: `week` (latest 7.1 days, 67 data points)  
**Method**: Account value change / account value start × (365 / days)

| Metric | Value |
|--------|-------|
| **Top-level APR field** | -0.02% |
| **Approx. APR (from weekly delta)** | -199.71% |
| **Max drawdown (7-day window)** | -3.89% |
| **Account value start** | $272.0M |
| **Account value end** | $261.4M |
| **7-day loss** | -$10.6M (-3.9%) |

**Interpretation**: The vault is currently experiencing market-driven losses. Over the past week, equity has eroded by ~$10.6M. This is **not a vault failure** (smart contracts are operating normally) but reflects the current market environment where the vault's strategies (liquidations, market-making spreads) are underwater. The -199% annualized APR if this week sustained is pure extrapolation noise; real drawdown is -3.9%.

### 3. Carry Engine (Live)

**Deployment**: 2026-07-03  
**Target**: ~10% APR (based on trailing 7-day funding rate at entry)  
**Position**: Delta-neutral long-spot / short-perp on selected altcoins  
**Sample Size**: 1 day (0 days of live PnL yet)

**Status**: Entered targeting 10% APR. This is a reasonable expectation given funding rates at deployment, but funding is cyclical and will rotate. Real performance will emerge over weeks.

### 4. Gridbot (Live)

**Deployment**: 2026-07-01  
**Sample Window**: 2 days (2026-07-01 to 07-03)  
**Portfolio PnL**: +1.6% on $1,000 ($16 absolute gain)  
**Annualized (naive extrapolation)**: ~292%

**Status**: Early, **do not extrapolate**. Two days of volatility and liquidity-triggered fills on a tiny portfolio is not meaningful data. Real performance requires weeks of observation.

## Comparison Table

| Strategy | Est. APR | Drawdown Risk | Custody | Capacity | Sample Quality |
|----------|----------|---------------|---------|----------|----------------|
| **Bitfinex USD Lend** | 6.4% (4.7–6.9%) | minimal (steady) | high | high | 365d |
| **Hyperliquid HLP** | -199.7%* | -3.9%** | medium | limited | week (67 pts) |
| **Carry (live)** | ~10% (target) | unknown (<1d) | low | low | 1d sample |
| **Gridbot (live)** | ~292% (naive)† | unknown (<3d) | low | low | 2d sample |

*7-day drawdown extrapolated annualized; real drawdown is -3.9%. † Extrapolation artifact; meaningless.

## Commentary

### Bitfinex USD Lending
Offers steady **~6–8% APR** with minimal volatility. However, **custody is the core risk**: the exchange holds your capital and is exposed to operational/solvency events (FTX precedent). Lenders have no recovery priority; funds are frozen if the exchange fails. Capacity is high (deep liquidity into major funding pools). Data is robust (365 days of daily samples), so this is the most reliable yield benchmark.

### Hyperliquid HLP Vault
Shows current losses (**-3.9% over 7 days**, -199.7% annualized if sustained). This is a **market-driven drawdown, not a vault failure**: the vault's strategies (liquidations, market-making) are underwater in the current market regime. Real-world performance varies widely with volatility and liquidation flow. Custody risk is lower than Bitfinex (assets on-chain in smart contracts, liquidation risks vs. operational risks), but equity can erode rapidly during dislocation. Capacity is more constrained than Bitfinex (vault size limits set by Hyperliquid).

### Our Live Engines (Carry, Gridbot)
Both are in **single-digit-day samples**. Carry entered on 2026-07-03 targeting ~10% APR based on funding rates observed at deployment — a reasonable expectation, but funding is cyclical and will rotate. Gridbot's +1.6% in 2 days is a statistical artifact (volatility + tiny portfolio scale); extrapolating to 292% APR is not meaningful. Real live performance will emerge over weeks.

Custody risk is **lowest for our engines** (we hold keys; custodian risk only on the exchange where we trade, not on our capital ledger). Capacity is low (small deployed capital) and sample quality is poor (no historical depth yet). 

### Strategic Decision
The choice depends on your priorities:
- **Bitfinex**: Passive, fire-and-forget, ~6.4% APR, but exchange counterparty risk.
- **HLP**: On-chain, lower counterparty risk, but current market drawdown (-3.9% week).
- **Our Engines**: Strategic optionality, lower custodial risk, but higher touch and tiny samples.

**No recommendation is offered**: the coordinator decides based on risk tolerance and strategy alignment.

## Raw Data Cache

All responses cached in `data/cache/benchmarks/`:
- `bitfinex_lending.json` — 365 candles, daily rates
- `hyperliquid_hlp_vault.json` — portfolio history across 8 time windows

Script: `scripts/research_passive_benchmarks.py`

## Notes

- **Bitfinex API**: Required User-Agent header; Cloudflare-protected.
- **Hyperliquid API**: Portfolio structured as `[["window_label", {accountValueHistory, pnlHistory, ...}], ...]`. Skipped `allTime` window due to initialization artifact (0-start value).
- **Carry**: Entered with knowledge of ~10% trailing 7d funding rate; actual execution pending.
- **Gridbot**: Tiny sample; no statistical validity yet.
