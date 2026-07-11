# F2b Maker-Entry Fade Walk-Forward Results (Round 2)

**Hypothesis:** F2 fade signals with maker-entry limit orders (cost structure).
**Two variants:** (A) No vol filter, (B) With vol24h > rolling_median filter.

**Data window:** Pooled across coins
**Configs:** 9 (W ∈ {15,30,60}, K ∈ {3,4,5})


## Variant NoFilter

**OOS trades:** 1910


### NoFilter Pooled Metrics

| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |
|------|------|--------|-------|---------|-------|---------|----------|
| NoFilter-Pooled | 1910 | 0.749 | 38.6% | -7.99 | -15698.1 | -4.25 | 0/0 |
| NoFilter-Sens ×1.5 | 1880 | 0.690 | 38.2% | -10.61 | -20357.3 | -5.50 | 0/0 |

### Exit Reason Distribution

- **Target:** 38.5%
- **Stop:** 60.1%
- **Time:** 1.4%

⚠️ **Divergence-Dominated:** Stop > 50% indicates weak signal fitness.

### Per-Coin Metrics


### NoFilter By Coin

| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |
|------|------|--------|-------|---------|-------|---------|----------|
| LIT | 69 | 0.884 | 36.2% | -4.86 | -1242.0 | -0.45 | 1/2 |
| HYPE | 230 | 0.808 | 44.8% | -6.22 | -2479.0 | -1.07 | 1/2 |
| ZEC | 390 | 0.856 | 46.2% | -6.61 | -3712.1 | -1.20 | 0/2 |
| SOL | 397 | 0.689 | 35.0% | -10.73 | -5118.5 | -2.06 | 0/2 |
| ETH | 428 | 0.745 | 39.5% | -6.57 | -3179.0 | -2.55 | 0/2 |
| BTC | 396 | 0.509 | 30.8% | -9.73 | -4083.2 | -5.49 | 0/2 |

### G1 Gate Checklist (NoFilter)

| Criterion | Threshold | Actual | Status |
|-----------|-----------|--------|--------|
| PF ≥ 1.3 | ≥ 1.30 | 0.749 | ✗ |
| n ≥ 300 | ≥ 300 | 1910 | ✓ |
| Months+ ≥ 60% | ≥ 60% | 0.0% | ✗ |
| MDD ≤ 15% | ≤ 15% | 26.2% | ✗ |

_Capital base for MDD: 6 coins × $1,000 max concurrent book_

| t-stat ≥ 2.0 | ≥ 2.0 | -4.25 | ✗ |
| Sens PF ≥ 1.15 | ≥ 1.15 | 0.690 | ✗ |

**NoFilter G1 Result:** FAIL ✗


## Variant WithFilter

**OOS trades:** 1360


### WithFilter Pooled Metrics

| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |
|------|------|--------|-------|---------|-------|---------|----------|
| WithFilter-Pooled | 1360 | 0.758 | 41.9% | -7.70 | -11159.1 | -3.33 | 0/0 |
| WithFilter-Sens ×1.5 | 1360 | 0.695 | 41.7% | -10.32 | -14380.8 | -4.43 | 0/0 |

### Exit Reason Distribution

- **Target:** 43.4%
- **Stop:** 56.0%
- **Time:** 0.6%

⚠️ **Divergence-Dominated:** Stop > 50% indicates weak signal fitness.

### Per-Coin Metrics


### WithFilter By Coin

| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |
|------|------|--------|-------|---------|-------|---------|----------|
| LIT | 64 | 1.041 | 48.4% | 1.46 | -663.8 | 0.14 | 1/2 |
| HYPE | 113 | 0.741 | 44.2% | -10.45 | -2180.2 | -0.98 | 1/2 |
| ZEC | 164 | 1.132 | 54.9% | 5.49 | -1875.8 | 0.61 | 2/2 |
| SOL | 316 | 0.667 | 38.6% | -12.53 | -4421.5 | -2.06 | 0/2 |
| ETH | 394 | 0.688 | 42.6% | -8.87 | -3546.5 | -2.79 | 0/2 |
| BTC | 309 | 0.567 | 35.3% | -9.16 | -2967.1 | -4.01 | 0/2 |

### G1 Gate Checklist (WithFilter)

| Criterion | Threshold | Actual | Status |
|-----------|-----------|--------|--------|
| PF ≥ 1.3 | ≥ 1.30 | 0.758 | ✗ |
| n ≥ 300 | ≥ 300 | 1360 | ✓ |
| Months+ ≥ 60% | ≥ 60% | 0.0% | ✗ |
| MDD ≤ 15% | ≤ 15% | 18.6% | ✗ |

_Capital base for MDD: 6 coins × $1,000 max concurrent book_

| t-stat ≥ 2.0 | ≥ 2.0 | -3.33 | ✗ |
| Sens PF ≥ 1.15 | ≥ 1.15 | 0.695 | ✗ |

**WithFilter G1 Result:** FAIL ✗
