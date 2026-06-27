# OOS Verdict: **NO-GO** — do not deploy capital

**Date:** 2026-06-27 · **Sub-project A (selection research) — go/no-go gate**
**Data:** Hyperliquid official S3 archive `node_fills_by_block`, 2025-07-27 → 2026-06-27 (3,746,771 candidate fills, top-300 leaderboard pre-screen).

## Decision

The walk-forward out-of-sample test gives **no evidence** that "copy the top leaderboard traders" produces persistent positive return, and there are **structural reasons the naive construction is fragile**. Per the project's own criterion #4, the thesis is **not confirmed → NO-GO**. Sub-project B (live execution engine) is gated on GO and is **not** built.

## The numbers (OOS, Jan–May 2026, 150 trading days, 5 rebalances)

| Strategy | OOS Sharpe | OOS total return |
|---|---:|---:|
| **Alpha-filtered HRP vault** (the design) | **−1.42** | **−23.8%** |
| Equal-weight of all qualifying traders | −1.17 | −5.4% |
| BTC buy-and-hold (benchmark) | −1.10 | −28.5% |

- OOS one-sample t-stat on the vault's daily return: **−1.10** (not positive, not significant).
- The alpha-filtered vault did **not** beat BTC risk-adjusted, and it **underperformed even naive equal-weight** — the strict alpha selection added negative value out-of-sample.

## Why — three findings that matter more than the single number

**1. The archive depth is the binding constraint (not fixable).**
Hyperliquid's `node_fills_by_block` archive begins 2025-07-27 (~11 months). With a 6-month track-record gate, **no trader qualifies until ~2026-01-23**, after which all qualify at once. The walk-forward therefore has only **one market regime and 5 rebalances** — far too few for a credible persistence test. A power-adequate walk-forward needs 2–3+ years of history that simply does not exist on-chain yet.

**2. The persistent, copyable universe is tiny — you cannot even fill 30 slots.**
Of the top-300 leaderboard: ~213 have any fills → **99** have a reconstructable equity curve (the rest are vault-scale MMs, blew up, or have unreconstructable deposit/withdrawal-driven equity) → and at any rebalance only **1–4** show statistically significant alpha vs BTC/ETH. The "vault of 30 best traders" **cannot be populated** — the data does not contain 30 simultaneously-persistent alpha traders. The final selection today is **1 trader**.

**3. These traders are net-long crypto beta, not market-neutral alpha.**
The whole window is a BTC bear market, and the selected book tracked it down (−23.8% while BTC −28.5%). They lose less than BTC but provide **no downside protection and no positive risk-adjusted edge** — exactly what a mirror vault would inherit.

## Selection funnel (per rebalance)

| Rebalance | qualifying (≥6mo) | alpha-tstat ≥ 2 | picked |
|---|---:|---:|---:|
| 2025-08 … 2025-12 | 0 | 0 | 0 |
| 2026-01-23 | 99 | 3 | 3 |
| 2026-02-22 | 99 | 2 | 2 |
| 2026-03-24 | 99 | 4 | 4 |
| 2026-04-23 | 99 | 2 | 2 |
| 2026-05-23 | 99 | 1 | 1 |

## Honest caveats (cuts both ways)

- **Underpowered, not definitively falsified.** 5 rebalances in one regime cannot *prove* the thesis wrong; it can only fail to support it. But "we cannot get adequate evidence from available data" is itself a sound reason **not to deploy real capital**.
- **Equity reconstruction is approximate.** No deposit/withdrawal ledger; equity is anchored to current account value with a drawdown-implied floor, and traders with implausible reconstructed daily moves (>±300%) are dropped (48 of 147). This is a research signal, not accounting.
- **Realized-PnL returns** (what a mirror captures), no unrealized MtM for alt-coins.

## Recommendation

**Do not launch the vault as specified.** The rigorous gate did its job: it prevented deploying capital into an unvalidated, likely negative-EV construction. Options to revisit (each its own brainstorm → spec → backtest cycle):

1. **Change the thesis, not the threshold.** Test a *market-neutral* construction (long top traders / short BTC-ETH beta) so the edge isn't just crypto beta. This is the most promising re-frame.
2. **Lower the track-record bar to grow the OOS window** (e.g., 3-month gate) — gains rebalances at the cost of selecting on noisier history; run it as a sensitivity, not a fix.
3. **Wait and accumulate.** Re-run this exact pipeline in 6–12 months when the archive (and these traders' track records) have deepened enough for a real persistence test. The pipeline is built and reproducible.

**Not recommended:** tuning thresholds until a GO appears — that is the selection bias the deflated-Sharpe and OOS test exist to defeat.
