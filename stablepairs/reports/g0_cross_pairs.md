# G0 Cost Feasibility: HL Stablecoin CROSS Pairs

## Summary
Analysis of synthetic cross spreads (long one stable pair, short another) on HL.
- Pairs: USDT0/USDC (@166), USDe/USDC (@150), USDH/USDC (@230)
- Strategy: Synthetic spread = log(close_A) - log(close_B), mean reversion
- Fee structure: Taker 1.4 bps/side per leg (double-leg trade)
- G0 threshold: median amplitude >= 3× round-trip cost

## Cross Pair Analysis

| Combination | Bars | Days | Spread A (bps) | Spread B (bps) | RT_cross (bps) | 3×RT (bps) |
|---|---|---|---|---|---|---|
| USDT0-USDe | 5001 | 208.3 | 2.5 | 0.1 | 8.2 | 24.6 |
| USDT0-USDH | 5002 | 208.4 | 2.5 | 0.5 | 8.6 | 25.8 |
| USDe-USDH | 5002 | 208.4 | 0.1 | 0.5 | 6.2 | 18.6 |

## Event Statistics & G0 Judgment

### USDT0-USDe

**Data:** 5001 bars, 208.3 days | **Cost:** RT_cross=8.2 bps, 3×RT=24.6 bps

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | Passes G0 | Status |
|---|---|---|---|---|---|---|
| 1.0 | 145 | 4.0 | 4.3 | 7.0 | ❌ | ❌ FAIL |
| 1.5 | 68 | 5.4 | 6.1 | 12.0 | ❌ | ❌ FAIL |
| 2.0 | 36 | 7.4 | 8.6 | 20.0 | ❌ | ❌ FAIL |

### USDT0-USDH

**Data:** 5002 bars, 208.4 days | **Cost:** RT_cross=8.6 bps, 3×RT=25.8 bps

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | Passes G0 | Status |
|---|---|---|---|---|---|---|
| 1.0 | 95 | 3.7 | 4.0 | 14.0 | ❌ | ❌ FAIL |
| 1.5 | 57 | 4.9 | 5.3 | 20.0 | ❌ | ❌ FAIL |
| 2.0 | 31 | 5.8 | 6.5 | 31.0 | ❌ | ❌ FAIL |

### USDe-USDH

**Data:** 5002 bars, 208.4 days | **Cost:** RT_cross=6.2 bps, 3×RT=18.6 bps

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | Passes G0 | Status |
|---|---|---|---|---|---|---|
| 1.0 | 70 | 4.5 | 4.7 | 21.0 | ❌ | ❌ FAIL |
| 1.5 | 37 | 6.8 | 7.3 | 49.0 | ❌ | ❌ FAIL |
| 2.0 | 22 | 8.3 | 9.6 | 52.0 | ❌ | ❌ FAIL |

## G0 Verdict

❌ **G0 FAIL**: No cross combinations meet median amplitude >= 3× round-trip cost threshold.
