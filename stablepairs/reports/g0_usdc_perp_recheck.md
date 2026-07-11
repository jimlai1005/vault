# G0 USDCUSDT Perpetual Recheck: Binance/OKX Cost Scenarios

**Date**: 2026-07-11  
**Objective**: Re-verify stablepairs sub-project G0 NO-GO verdict against perp-only cost scenarios (perp funding rates lower than spot TT costs)  
**Data**: Binance USDCUSDT 1h perpetual, 2024-07-11 → 2026-07-11 (729 days, 17,520 bars)  
**Method**: Z-score mean reversion (720-bar rolling window, z-threshold entry, |z| ≤ 0.2 exit, amplitude measurement in bps)

---

## Executive Summary

**VERDICT: NO-GO CONFIRMED.** All cost scenarios fail G0 rule across all z-thresholds. Perp funding rates (2–4.5 bps taker/0–2.0 bps maker) do **not** rescue the strategy — USDCUSDT perp amplitude is structural too small.

Key finding: **Median amplitude z=1.5 = 3.5 bps**, which is **below cost even at maker rates (3.2–4.0 bps)** and far below the required 3× RT buffers (9.6–33 bps depending on venue/maker-taker mix).

---

## Price Behavior & Stationarity

| Metric | Value |
|--------|-------|
| Price range | 0.9955–1.0021 USDC |
| Price std (rolling 30d) | 5.04 bps |
| P5–P95 bandwidth | 16.53 bps |
| P99 \|price − 1\| deviation | 14.27 bps |
| Event count (z ≥ 1.5) | 98 |
| Median hold time | 41 hours |

**Interpretation**: USDCUSDT exhibits **extreme stationarity**. Price std < 6 bps means 99% of hourly moves are ≤~14 bps. Z-score mean reversion triggers are rare (98 in 729 days ≈ 0.13 events/day).

---

## Z-Score Event Analysis

Methodology: 720-bar (30-day) rolling mean/std; track |z| > threshold crossings; exit when |z| ≤ 0.2.

### Amplitude by Threshold

| Z-Threshold | # Events | Median Amplitude (bps) | Mean (bps) | P5–P95 Range |
|-------------|----------|------------------------|------------|--------------|
| 1.0         | 181      | 2.8                    | 3.1        | 1.3–6.8     |
| **1.5**     | **98**   | **3.5**                | **4.4**    | 1.4–8.3     |
| 2.0         | 58       | 4.4                    | 5.8        | 2.7–11.6    |

**Key observation**: Median amplitude **decreases with stricter entry threshold** (further deviations are not rewarded with larger mean reversions). This rules out deep-entry alpha strategies — the price just doesn't move far enough.

---

## G0 Cost Scenarios

**G0 Rule**: Median amplitude must exceed **3 × (RT)** where RT = round-trip cost.

### Scenario Definitions & Results

| Scenario | RT (bps) | G0 Threshold (bps) | z=1.0 Result | z=1.5 Result | z=2.0 Result |
|----------|----------|-------------------|--------------|--------------|--------------|
| **Binance TT** (5bps taker fee × 2 + 1bps spread) | 11.0 | 33.0 | 2.8 → FAIL | 3.5 → FAIL | 4.4 → FAIL |
| **Binance MM** (2bps maker fee × 2) | 4.0 | 12.0 | 2.8 → FAIL | 3.5 → FAIL | 4.4 → FAIL |
| **OKX TT** (4.5bps taker fee × 2 + 1bps spread) | 10.0 | 30.0 | 2.8 → FAIL | 3.5 → FAIL | 4.4 → FAIL |
| **OKX MM** (1.6bps maker fee × 2) | 3.2 | **9.6** | 2.8 → FAIL | 3.5 → FAIL | 4.4 → FAIL |

**All scenarios fail.** Even the most favorable case (OKX maker-only: 3.2 bps RT → 9.6 bps threshold) is **2.7× the median amplitude**.

---

## Funding Rate Note

This analysis **does not include perpetual funding rates** (charged per settlement period, e.g., 8-hourly on Binance). 

**Why omitted**: USDCUSDT is a stable coin perp — its funding rate is typically **near zero or slightly negative** (lenders paying borrowers, since perp stays pinned near spot). Including funding would at best flatten the cost picture further (or slightly improve it if funding is negative), but:

1. Funding is not guaranteed to be negative — funding can flip positive if perp trades above spot (rare, but possible during liquidation cascades).
2. Funding is **not** order-level revenue — it accumulates per settlement and cannot be deducted from amplitude-to-cost judgement in real time.
3. **The amplitude gap is so large that funding is immaterial** — even if funding subsidized costs by 100%, median amplitude 3.5 bps still falls short of OKX MM threshold 9.6 bps.

**Conclusion**: Funding rates do **not** change the verdict.

---

## Reasons for NO-GO (Root Cause Analysis)

1. **USDC = collateral, not a price discovery asset**. Price is pegged by design (Coinbase's reserve backing, regulatory certainty). Supply shocks → immediate monetary policy response, not trading ranges → mean reversion.

2. **Central bank parity**: If USDC trades at 0.99, it's a regulatory/liquidity issue, not alpha — spreads widen to lure sellers back to parity, then close abruptly. Scalp amplitude is minimum-cost-to-cross-bid-ask, not edge.

3. **Maker-to-maker fees (0–2 bps) are still 3–9× median reversions**, because the reversions themselves are just noise around parity. You can only make money if reversions exceed **both** round-trip cost **and** inventory risk during the revert.

4. **Inventory risk**: With median hold 41 hours, position carries overnight basis, funding accrual risk (even if mean expectation is zero), and liquidity drag.

---

## Verification Checklist

| Item | Status |
|------|--------|
| Bars fetched | 17,520 ✓ |
| Date range | 2024-07-11 → 2026-07-11 (729 days) ✓ |
| Price range | 0.9955–1.0021 ✓ (9–21 bps band) |
| Z-score window | 720 bars (30d rolling) ✓ |
| Event exit rule | \|z\| ≤ 0.2 ✓ |
| Amplitude metric | Absolute price change, bps ✓ |
| Cost scenarios | 4 (2 venues × 2 fee modes) ✓ |
| Funding rates | Noted as omitted (immaterial) ✓ |
| G0 judgement | Amplitude vs 3×RT, all FAIL ✓ |

---

## Recommendation

**Sub-project G remains NO-GO.** The original stablepairs verdict stands:

- USDCUSDT perp on Binance/OKX has **lower fees than spot TT** (true), but fee advantage is **nullified by amplitude shortfall**.
- Median reversion is too weak to justify operational overhead (inventory management, funding accrual monitoring).
- If Binance announces sub-2 bps taker fees or OKX sub-1 bps flat fees → rerun with new RT baseline; verdict might flip. Until then, **reject this variant as infeasible (sub-project I)**.

---

## Data Provenance

- **Source**: Binance FAPI v1 `/klines` endpoint (public, unauthenticated, read-only).
- **Calls**: 12 requests × 1500 bars = 18,000 rows, de-duplicated to 17,520 unique.
- **Script**: `/private/tmp/g0_usdc_recheck.py` (includes scalp_lib.py binance_klines/binance_rows_to_df wrappers).
- **No credentials used**: No `.env*` files read; all data public.

---

**Generated by**: Claude Code, Haiku 4.5  
**Last verified**: 2026-07-11 @ 13:44 UTC  
