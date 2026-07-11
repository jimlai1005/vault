# G0 Cost Feasibility Analysis: HL Stable Pairs

## Summary
Analysis of three HL stable coin pairs for mean-reversion scalping strategy around peg.
- Pairs: USDT0/USDC (@166), USDe/USDC (@150), USDH/USDC (@230)
- Fee structure: Taker 1.4 bps/side
- G0 threshold: median amplitude >= 3× round-trip cost

## Candle Data & Spread Samples

| Pair | Index | Bars | Days | Spread (bps) | Std (bps) | P5-P95 (bps) | Mean Dev from 1 (bps) |
|------|-------|------|------|--------------|-----------|--------------|----------------------|
| USDT0 | @166 | 5001 | 208.3 | 2.50 | 5.18 | 16.91 | -4.21 |
| USDe | @150 | 5002 | 208.4 | 0.10 | 5.24 | 17.41 | -8.31 |
| USDH | @230 | 5004 | 208.5 | 0.50 | 1.11 | 3.00 | 0.33 |

## Event Analysis & G0 Viability

### Cost Structure (bps)

| Scenario | Cost |
|----------|------|
| Taker RT (fees only) | 2.80 |
| USDT0 Taker RT (fees + spread) | 5.30 |
| USDe Taker RT (fees + spread) | 2.90 |
| USDH Taker RT (fees + spread) | 3.30 |

### Amplitude Statistics & G0 Judgment

**USDT0** (@166, 5001 bars, 208.3 days)

##### USDT0 - z_peg (anchored to 1.0)

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |
|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|
| 1.0 | 61 | 3.1 | 3.7 | 7.0 | 15.91 | ❌ | ❌ FAIL |
| 1.5 | 30 | 4.3 | 5.1 | 9.0 | 15.91 | ❌ | ❌ FAIL |
| 2.0 | 17 | 6.0 | 7.2 | 33.0 | 15.91 | ❌ | ❌ FAIL |

##### USDT0 - z_roll (rolling mean basis)

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |
|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|
| 1.0 | 87 | 3.8 | 4.0 | 10.0 | 15.91 | ❌ | ❌ FAIL |
| 1.5 | 47 | 4.4 | 5.1 | 17.0 | 15.91 | ❌ | ❌ FAIL |
| 2.0 | 24 | 5.7 | 6.7 | 30.5 | 15.91 | ❌ | ❌ FAIL |

**USDe** (@150, 5002 bars, 208.4 days)

##### USDe - z_peg (anchored to 1.0)

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |
|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|
| 1.0 | 18 | 2.6 | 2.6 | 14.0 | 8.70 | ❌ | ❌ FAIL |
| 1.5 | 10 | 3.9 | 4.4 | 81.0 | 8.70 | ❌ | ❌ FAIL |
| 2.0 | 10 | 3.9 | 5.3 | 81.0 | 8.70 | ❌ | ❌ FAIL |

##### USDe - z_roll (rolling mean basis)

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |
|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|
| 1.0 | 37 | 4.1 | 4.3 | 38.0 | 8.70 | ❌ | ❌ FAIL |
| 1.5 | 24 | 5.9 | 6.1 | 80.0 | 8.70 | ❌ | ❌ FAIL |
| 2.0 | 16 | 7.4 | 8.2 | 108.5 | 8.70 | ❌ | ❌ FAIL |

**USDH** (@230, 5004 bars, 208.5 days)

##### USDH - z_peg (anchored to 1.0)

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |
|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|
| 1.0 | 341 | 1.0 | 1.2 | 3.0 | 9.90 | ❌ | ❌ FAIL |
| 1.5 | 103 | 2.0 | 1.8 | 4.0 | 9.90 | ❌ | ❌ FAIL |
| 2.0 | 18 | 2.7 | 2.5 | 14.0 | 9.90 | ❌ | ❌ FAIL |

##### USDH - z_roll (rolling mean basis)

| Entry Z | Events | Median Amp (bps) | Mean Amp (bps) | Median Hold (h) | 3×RT Cost (bps) | G0 Pass | Status |
|---------|--------|-----------------|----------------|-----------------|-----------------|---------|--------|
| 1.0 | 233 | 1.0 | 1.2 | 2.0 | 9.90 | ❌ | ❌ FAIL |
| 1.5 | 40 | 1.9 | 2.1 | 9.0 | 9.90 | ❌ | ❌ FAIL |
| 2.0 | 18 | 2.0 | 2.9 | 16.5 | 9.90 | ❌ | ❌ FAIL |


## G0 Verdict

❌ **G0 FAIL**: No combinations meet median amplitude >= 3× round-trip cost threshold
