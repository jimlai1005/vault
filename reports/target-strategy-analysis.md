# Target Wallet Strategy Analysis

**Address:** `0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1`
**Data:** Hyperliquid public `userFillsByTime` API, 2025-09-01 → 2026-07-01 (32,460 fills; earlier fills 2024-06-12 → 2025-08-31 are outside both the public API's and the S3 archive's retention window and are not recoverable at fill granularity — only the coarse portfolio equity curve exists that far back).

## Verdict: dense percentage grid, long-biased, multi-asset, HYPE-concentrated

This is **not discretionary trading** — it is an automated market-making grid:

- **1,408 unique order IDs produced 21,750 HYPE fills** (avg 15.4 fills/order) — orders rest at fixed price levels and get repeatedly (partially) hit as price oscillates.
- **484 distinct HYPE entry price levels**, median spacing **0.05%** between adjacent levels (some levels reused up to 525 times). Same signature confirmed on every other liquid coin traded: BTC (0.01% median spacing, 117 levels), BNB (0.003%), ETH (0.59%), XRP (0.22%).
- **Close-heavy**: "Close Long" fills outnumber "Open Long" ~2.25:1 on HYPE — the grid is realizing many small take-profits continuously while occasionally adding on dips.
- **80% of fills cluster in same-millisecond batches** (up to 226 fills at once) — consistent with resting limit ladders being swept by incoming taker flow, not manual clicking.
- **Directionally long-biased, not symmetric**: Open Long 6,452 vs Open Short 404 on HYPE (16:1). This is a "buy-the-dip grid riding an uptrend," not a range-bound neutral grid — HYPE's price moved $21 → $75 over the window and the grid's bound clearly trailed/expanded upward with it rather than staying fixed.
- **No visible stop-loss / circuit breaker** in the fill pattern — risk management (if any) is via leverage choice and grid spacing, not hard exits.

## Capital allocation & profitability (realized PnL, net of fees)

| Coin | Fills | Net PnL | Win rate (closes) |
|---|---:|---:|---:|
| HYPE | 21,750 | **+$432,347** (74% of total) | 80% |
| xyz:CL | 2,079 | +$70,289 | 60% |
| ZEC | 1,029 | +$66,448 | 70% |
| BTC | 770 | +$44,022 | 80% |
| BNB | 381 | +$24,960 | 70% |
| ETH | 243 | +$24,761 | 90% |
| ~20 more coins (crypto + xyz-dex tokenized US equities + spot) | — | mostly small positive; XRP/xyz:NVDA/xyz:INTC/XMR mildly negative | — |
| **Total realized** | 28,745 perp fills | **≈ $584,900** | — |

Current leverage snapshot (per-coin, cross): ETH 10x, BNB 10x, XRP 20x, HYPE 5x — leverage is set per-market, not a single global rule; HYPE (the largest allocation) runs the *lowest* leverage, which is what lets a grid that dense survive its own drawdowns without liquidation.

## What this means for replication

The edge is **not alpha from picking direction** — it's bid-ask/spread capture from resting liquidity across many coins simultaneously, with HYPE as the flagship allocation (likely also collecting Hyperliquid's maker rebates/points). It is replicable without copying trades 1:1: implement a parametrized grid engine (spacing, levels, leverage, capital-per-coin) and run it directly. See `reports/gridbot-design.md` for the proposed implementation, which keeps this core mechanic but adds risk controls the target does not appear to have (volatility-scaled spacing, hard per-coin stop/max-position, portfolio drawdown circuit breaker).
