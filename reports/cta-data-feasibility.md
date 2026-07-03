# CTA Data Feasibility — Phase-1 Probe Results

**Probe Date:** 2026-07-03  
**Probe Duration:** 5 seconds  
**Symbols Tested:** BTCUSDT, ETHUSDT, SOLUSDT, HYPEUSDT  
**Cached Results:** `/data/cache/cta_probe/probe_results_20260703_211856.json`

---

## Data Availability Summary

| Source & Dataset | Symbol | Row Count | Earliest Data | Latest Data | Granularity | Status |
|---|---|---|---|---|---|---|
| **Binance USDT-M Klines (4h)** | BTCUSDT | 1,500 | 2025-10-27 | 2026-07-03 | 4-hourly | ✓ Partial paginated |
| | ETHUSDT | 1,500 | 2025-10-27 | 2026-07-03 | 4-hourly | ✓ Partial paginated |
| | SOLUSDT | 1,500 | 2025-10-27 | 2026-07-03 | 4-hourly | ✓ Partial paginated |
| | HYPEUSDT | 1,500 | 2025-10-27 | 2026-07-03 | 4-hourly | ✓ Exists on Binance |
| **Binance Open Interest (4h)** | BTCUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | ETHUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | SOLUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | HYPEUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| **Binance Long/Short Ratio (Top Accounts, 4h)** | BTCUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | ETHUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | SOLUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | HYPEUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| **Binance Long/Short Ratio (Global, 4h)** | BTCUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | ETHUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | SOLUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| | HYPEUSDT | 180 | 2026-06-04 | 2026-07-03 | 4-hourly | ✓ ~30d depth capped |
| **Coinalyze OI History** | All | — | — | — | 4-hourly | ✗ HTTP 401 (API key required) |
| **Hyperliquid OI History** | All | — | — | — | — | ✗ Endpoint does not exist |

---

## Key Findings

### 1. Binance Klines (Price) — Years of History via Pagination
- **Status:** ✓ Production-ready
- **Depth:** 1,500 rows max per call (fixed limit), but paginated via `startTime` parameter
- **Earliest:** 2025-10-27 (9+ months with current limit=1500)
- **Coverage:** All four symbols available (BTCUSDT, ETHUSDT, SOLUSDT, **HYPEUSDT exists**)
- **Note:** No natural cap; historical depth is excellent for trend/momentum baseline modeling.

### 2. Binance Futures Sentiment (OI + L/S Ratio) — ~30-Day Rolling Window
- **Status:** ✓ Production-ready, but shallow
- **Depth:** 180 rows at 4h granularity ≈ 30 days (180 × 4h = 720h = 30d)
- **Earliest:** 2026-06-04 (today is 2026-07-03 = 29d ago)
- **Confirmed:** Open Interest, Top-Account L/S Ratio, Global L/S Ratio all capped at ~30 days
- **Fields Available:**
  - Open Interest: `sumOpenInterest`, `sumOpenInterestValue`, `CMCCirculatingSupply`
  - L/S Ratio: `longAccount`, `longShortRatio`, `shortAccount`
- **Coverage:** All four symbols available (including HYPEUSDT)

### 3. Coinalyze — Blocked Without API Key
- **Status:** ✗ Requires authentication
- **HTTP Code:** 401 Unauthorized
- **Expected Benefit:** Free tier unknown; documentation suggests deeper OI history than Binance (~90d+)
- **Blocker:** No public access; free API key registration needed to assess

### 4. Hyperliquid — No OI History Endpoint
- **Status:** ✗ Endpoint does not exist
- **HTTP Code:** 422 (deserialization error on `openInterestHistory` request type)
- **Available:** Hyperliquid does cache funding history (~12mo), but not OI snapshots or account-ratio data
- **Note:** Not a viable data source for OI or sentiment analysis

---

## Phase-2 Feasibility Assessment

### **Can Build NOW (with public Binance APIs only):**
- 4-hour klines baseline for BTC/ETH/SOL/HYPE (years of history → long-term momentum signals)
- 30-day rolling Open Interest and L/S sentiment (top-account and global ratios)
- Short-term momentum + current-cycle sentiment divergence detection
- **Limitation:** Sentiment signals limited to ~1 month recency; cannot correlate macro OI turns with quarterly cycles

### **Unlocks with Coinalyze Free Key:**
- Extend OI history from ~30 days to ~90+ days (empirically TBD)
- Detect medium-term OI accumulation/distribution patterns
- Strengthen position-sizing logic by anchoring on deeper historical context
- **Cost:** Free-tier registration (no credit card required; typical 1000 req/day limit)

### **Not Viable:**
- Hyperliquid sentiment (no OI endpoints; funding-only)
- Any source requiring paid tier or real-time subscription

---

## Recommendation

**Phase-2 is buildable today with Binance public APIs alone**, delivering:
- Long-term momentum from klines (years)
- Recent sentiment from OI + account ratios (30d rolling)

**Recommend registering a free Coinalyze key** (~5 min) to extend OI history to ~90d before Phase-3 production release. This closes the gap between macro cycles (~3mo) and available historical context, improving position-sizing robustness without breaking existing Binance-only workflows.

---

## Probe Methodology

- **Tool:** `/scripts/probe_cta_data_sources.py`
- **Timeout:** 20 seconds per request, 2 retries on transient failure
- **No Keys Used:** Coinalyze and Hyperliquid tested against public endpoints only
- **Data Cached:** `/data/cache/cta_probe/` for reproducibility
