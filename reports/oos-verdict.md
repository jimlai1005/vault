# OOS Verdict: **NO-GO** — do not deploy capital

**Date:** 2026-06-27 · **Sub-project A (selection research) — go/no-go gate**
**Data:** Hyperliquid official S3 archive `node_fills_by_block`, 2025-07-27 → 2026-06-27 (3,746,771 candidate fills, top-300 leaderboard pre-screen, 99 with reconstructable equity).

## Decision

No configuration tested shows positive out-of-sample risk-adjusted return. Per criterion #4, the thesis is **not confirmed → NO-GO**. Sub-project B (live execution engine) is gated on GO and is **not** built.

## Robustness — NO-GO across every construction and threshold

| Construction | Gate | Rebalances | OOS Sharpe | OOS total | t-stat | Verdict |
|---|---|---:|---:|---:|---:|---|
| Long-only HRP vault | 6mo | 5 | −1.42 | −23.8% | −1.10 | NO-GO |
| Long-only HRP vault | 3mo | 8 | −1.02 | −22.2% | −1.00 | NO-GO |
| **Market-neutral** (beta-hedged) | 6mo | 5 | −1.53 | −25.5% | −1.18 | NO-GO |
| **Market-neutral** (beta-hedged) | 3mo | 8 | −1.11 | −23.8% | −1.08 | NO-GO |
| BTC buy-hold (benchmark) | — | — | −1.10 to −1.30 | −28.5% | — | — |

Hedging out BTC/ETH beta made results **worse**, not better — there is no hidden alpha to uncover; the selected traders' residual return is itself negative OOS. The result is stable whether we select long-only or market-neutral, at a 6- or 3-month track-record gate.

## Why — three structural findings

**1. Archive depth is the binding constraint (not fixable).**
The archive begins 2025-07-27 (~11 months). A 6-month track-record gate leaves only one regime and 5 rebalances (8 at a 3-month gate). Far too few for a credible persistence test; needs 2–3+ years that don't exist on-chain yet.

**2. The persistent, copyable universe is tiny — you cannot fill 30 slots.**
top-300 → 213 with fills → **99** reconstructable → only **1–4** with significant alpha at any rebalance. Today's final selection is **1 trader**. A "vault of 30" is unpopulatable from this data.

**3. These traders are net-long crypto beta, not market-neutral alpha.**
They tracked the BTC bear market down with no downside protection and no positive risk-adjusted edge — and removing the beta leaves a negative residual.

## Selection funnel (6-month gate)

| Rebalance | qualifying (≥6mo) | alpha-tstat ≥ 2 | picked |
|---|---:|---:|---:|
| 2025-08 … 2025-12 | 0 | 0 | 0 |
| 2026-01-23 | 99 | 3 | 3 |
| 2026-02-22 | 99 | 2 | 2 |
| 2026-03-24 | 99 | 4 | 4 |
| 2026-04-23 | 99 | 2 | 2 |
| 2026-05-23 | 99 | 1 | 1 |

## Honest caveats (cut both ways)

- **Underpowered, not definitively falsified.** A handful of rebalances in one regime cannot *prove* the thesis wrong — but "we cannot obtain adequate evidence from available data" is itself a sound reason **not to deploy capital**.
- **Equity reconstruction is approximate** — anchored to current account value + drawdown-implied floor (no deposit/withdrawal ledger); traders with implausible reconstructed daily moves (>±300%) dropped (48 of 147). Research signal, not accounting.
- **Realized-PnL returns** (what a mirror captures); no unrealized MtM for alt-coins.

## Recommendation

**Do not launch.** The two most natural re-frames were tested:
- Market-neutral (long traders / short BTC-ETH beta): **also NO-GO** (worse).
- Lower track-record bar to 3 months for more rebalances: **also NO-GO**.

Realistic remaining paths: **(a) wait 6–12 months** for the archive and these traders' track records to deepen, then re-run this exact (reproducible) pipeline for a power-adequate test; or **(b) stop**. Tuning thresholds until a GO appears is the selection bias the deflated-Sharpe / OOS test exist to defeat — not recommended.
