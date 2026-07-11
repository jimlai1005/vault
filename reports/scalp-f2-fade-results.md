# F2 Overshoot-Fade Walk-Forward Results

**Data window:** Pooled across 6 coins
**Configs:** 9 (W ∈ {15,30,60}, K ∈ {3,4,5})
**OOS trades:** 1894

## Summary Metrics (Pooled OOS)


### Pooled Metrics

| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |
|------|------|--------|-------|---------|-------|---------|----------|
| POOLED | 1894 | 0.754 | 41.9% | -8.12 | -15637.3 | -4.16 | 0/0 |
| POOLED (sens ×1.5) | 1825 | 0.638 | 40.8% | -13.35 | -24535.1 | -6.56 | 0/0 |

### Exit Reason Distribution

- **Target:** 43.1%
- **Stop:** 55.4%
- **Time:** 1.5%

⚠️ **Divergence-Dominated:** Stop > 50% indicates weak signal fitness.

## Per-Coin Metrics


### By Coin (Pooled OOS)

| Coin | n | PF | Win% | Avg PnL | MDD | t-stat | Months+ |
|------|------|--------|-------|---------|-------|---------|----------|
| LIT | 83 | 0.791 | 44.6% | -9.04 | -1512.7 | -0.94 | 1/2 |
| ZEC | 414 | 0.985 | 48.6% | -0.62 | -2199.3 | -0.11 | 1/2 |
| HYPE | 231 | 0.772 | 47.2% | -7.78 | -2643.1 | -1.29 | 1/2 |
| SOL | 416 | 0.676 | 39.9% | -11.50 | -5955.3 | -2.30 | 0/2 |
| ETH | 408 | 0.677 | 40.9% | -9.30 | -3966.3 | -3.38 | 0/2 |
| BTC | 342 | 0.460 | 33.3% | -11.72 | -4219.7 | -5.98 | 0/2 |

## G1 Gate Checklist

| Criterion | Threshold | Actual | Status |
|-----------|-----------|--------|--------|
| PF ≥ 1.3 | ≥ 1.30 | 0.754 | ✗ |
| n ≥ 300 | ≥ 300 | 1894 | ✓ |
| Months+ ≥ 60% | ≥ 60% | 0.0% | ✗ |
| MDD ≤ 15% | ≤ 15% | 26.1% | ✗ |

_Capital base for MDD: 6 coins × $1,000 max concurrent book_
_MDD% = 26.1%, MDD bps (raw) = -15637.3_

| t-stat ≥ 2.0 | ≥ 2.0 | -4.16 | ✗ |
| Sens PF ≥ 1.15 | ≥ 1.15 | 0.638 | ✗ |

**Overall G1 Result:** FAIL ✗
