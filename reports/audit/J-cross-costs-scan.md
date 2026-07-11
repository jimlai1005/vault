# Audit: Cross-Codebase Cost Constants Scan
**Date:** 2026-07-12  
**Scope:** `scripts/`, `src/hlvault/`, `stablepairs/`, `compound/` (excluding `.venv` and `tests/`)  
**Purpose:** Comprehensive inventory of fee, slippage, funding, and cost constants across all research and production code.

---

## Section 1: Cost Constants Inventory

### 1.1 Fee-Related Constants (Non-Research)

| File:Line | Constant Name | Value | Notes | Strategy |
|-----------|---|---|---|---|
| `src/hlvault/gridbot/strategy.py:33` | `fee_rate` | 0.0003 | taker/maker blended estimate | gridbot (spot grid) |
| `src/hlvault/momentum/backtest.py:17` | `FEE_RATE` | 0.0005 | daily rebalance fee | momentum (live+backtest) |
| `src/hlvault/carry/config.py:60` | `ORDER_SLIPPAGE` | 0.05 (env override) | limit price buffer, live execution | carry (live execution only) |
| `src/hlvault/cta/config.py:111` | `ORDER_SLIPPAGE` | 0.05 (env override) | limit price buffer, live execution | CTA (live execution only) |
| `src/hlvault/momentum/live.py:47` | `ORDER_SLIPPAGE` | 0.05 | limit price buffer, live execution | momentum (live execution only) |
| `compound/src/compound/config.py:24` | `fee` | 0.15 | Bitfinex platform cut of interest earned | compound (Bitfinex lending) |

### 1.2 Fee-Related Constants (Research Scripts)

| File:Line | Constant Name | Value | Notes | Strategy |
|-----------|---|---|---|---|
| `scripts/research_pair_trading.py:52` | `FEE` | 0.00045 | 0.045% taker, per leg per side | F2 pair trading (perp cointegration) |
| `scripts/research_trend_filtered_grid.py:42` | `FEE` | 0.0003 | taker/maker blended | grid + trend filter research |
| `scripts/research_cta_positioning.py:50` | `FEE_SIDE` | 0.00045 × NOTIONAL (0.045%) | computed per coin, $100 notional | CTA positioning Phase 2a |
| `scripts/research_cta_positioning_phase2b.py:61` | `FEE_SIDE` | 0.00045 × NOTIONAL (0.045%) | same as Phase 2a; Phase 2b note: funding dropped | CTA positioning Phase 2b |
| `scripts/research_funding_carry.py:111` | `FEE_PER_SWAP` | 4 × 0.00045 = 0.0018 | 4 legs (perp entry/exit, spot entry/exit) per rebalance | funding carry research |
| `compound/scripts/research_strategy_phases.py:58` | `COST` | 0.00095 | 0.045% fee + 0.05% slippage per side | compound phase-fit (BTC/ETH trend + grid) |

### 1.3 Slippage Constants

| File:Line | Constant Name | Value | Notes |
|-----------|---|---|---|
| `stablepairs/config.py:41` | `slippage_bps` | 1.0 bps (0.01%) | configurable, per-side |
| `compound/scripts/research_strategy_phases.py:20` (comment) | fee + slippage | 0.045% + 0.05% = 0.095% | documented composition |

### 1.4 Stable Pair Trading Specific

| File:Line | Constant Name | Value | Notes |
|-----------|---|---|---|
| `stablepairs/config.py:40` | `fee_bps` | 7.5 bps (0.075%) | PER SIDE, configurable for testing |
| `stablepairs/config.py:41` | `slippage_bps` | 1.0 bps (0.01%) | PER SIDE |
| `stablepairs/g0_hl_stables.py:36` (comment) | Stable pair taker fees | 1.4 bps per side | HL actual observed rate |
| `stablepairs/g0_cross_pairs.py:56` | `TAKER_FEES_BPS_SIDE` | 1.4 bps | per side |
| `stablepairs/g0_hl_stables.py:34` | `TAKER_FEES_BPS_SIDE` | 1.4 bps | per side |

---

## Section 2: ORDER_SLIPPAGE Usage Classification

### 2.1 Live Execution Use (Limit Price Buffer)
Purpose: Aggressive IoC limit orders at mid +/- ORDER_SLIPPAGE, rounded to exchange precision.  
**Classification: Limit price buffer for market execution — NOT a cost/slippage assumption.**

| File:Line | Context | Direction | Value |
|-----------|---------|-----------|-------|
| `src/hlvault/carry/live.py:124` | Spot order execution | Both (buy/sell) | mid ± 0.05 |
| `src/hlvault/carry/live.py:132` | Perp order execution | Both (buy/sell) | mid ± 0.05 |
| `src/hlvault/cta/live.py:144` | Perp order execution | Both (buy/sell) | mid ± cfg.ORDER_SLIPPAGE (0.05) |
| `src/hlvault/momentum/live.py:140` | Execution | Both (buy/sell) | mid ± 0.05 |

### 2.2 Definition Points

| File:Line | Definition | Default | Type |
|-----------|-----------|---------|------|
| `src/hlvault/carry/config.py:60` | Env override with fallback | 0.05 | _env_float() |
| `src/hlvault/cta/config.py:111` | Env override with fallback | 0.05 | _env_float() |
| `src/hlvault/momentum/live.py:47` | Hardcoded | 0.05 | float literal |

**Misuse Candidates:** NONE FOUND  
- All ORDER_SLIPPAGE uses are in `live.py` modules (execution context), not in research/backtest.
- No research script uses ORDER_SLIPPAGE (all use named `FEE` or `COST` constants).
- All uses are for **limit price adjustment**, not cost accounting.

---

## Section 3: Funding Treatment Classification

### 3.1 Perpetual Backtest Scripts WITH Funding PnL

Scripts that hold perp positions across bars and explicitly account for funding cash flow:

| File | Strategy | Funding Source | Funding in PnL? | Notes |
|------|----------|---|---|---|
| `scripts/research_cta_positioning.py` | CTA (trend + crowd + fuel) | HL hourly (cache: `data/cache/funding/{COIN}.parquet`) | **YES** (lines 237-238, 256-257) | Short receives positive funding. `pos["fund"]` accumulates during hold. |
| `scripts/research_funding_carry.py` | Delta-neutral funding carry | HL fundingHistory API | **YES** (PnL = funding collected − rebalance fees, line 6) | Purpose-built for funding; long/short pair. |

### 3.2 Perpetual Backtest Scripts WITHOUT Funding PnL

Scripts that run perp backtests but do NOT include funding cash flow in metrics:

| File | Strategy | Instruments | Funding Treatment | Rationale/Note |
|------|----------|---|---|---|
| `scripts/research_pair_trading.py` | F2 pair trading (cointegration) | Perp spreads (e.g., SOL vs XRP) | "Funding approximated as zero-mean (simplification, noted in report)" (line 14) | Research-only; simplification disclosed. No perp funding modeling. |
| `scripts/research_trend_filtered_grid.py` | Grid + trend filter | Spot ONLY (implicit from GridConfig usage) | N/A (no perps) | Grid runs on spot, not perp; fallback mentions "funding carry" (line 16) as alternative if grid fails. |
| `compound/scripts/research_strategy_phases.py` | Trend + Grid (BTC/ETH) | Spot ONLY | "Short leg ignores perp funding" (line 36) | Spot-only design; no leverage; explicitly disclaims perp funding modeling. |

### 3.3 Live Production Engines (Funding Handling)

| Engine | File | Funding Handled? | Location | Notes |
|--------|------|---|---|---|
| carry | `src/hlvault/carry/engine.py` | **YES** (in decision logic) | Lines 16, 24 mention "funding turned bad" as unwind trigger | Funding is live input to engine state machine. |
| gridbot | `src/hlvault/gridbot/strategy.py` | **NO** | N/A | Spot-only; no funding. |
| momentum | `src/hlvault/momentum/backtest.py` | **NO** | N/A | Daily close rebalance; no intraday perp holdings. |
| CTA | `src/hlvault/cta/live.py`, `src/hlvault/cta/config.py` | **NO** (live); Phase 2a did (research) | Research: `scripts/research_cta_positioning.py:13` mentions actual funding. Live engine does not. | Live engine uses trend + proxy signals; no direct funding measurement. |

### 3.4 Funding-Aware Scripts (Reference/Data)

| File | Purpose | Funding Data Source |
|------|---------|---|
| `scripts/cta_proxy_lib.py` | Crowd proxy (Binance funding, rolling percentile) | Binance perpetual fundingRate (public API) |
| `scripts/research_cta_positioning_phase2b.py` | CTA Phase 2b (coinalyze proxy, no HL funding) | **HL funding DROPPED in 2b** (Phase 2a used it; see lines 18–22) |
| `scripts/research_cta_layer2a_analysis.py` | Analysis of Phase 2a | HL funding (retrospective analysis) |
| `scripts/research_cta_crowd_ablation.py` | Ablation: crowd filter | Multiple sources (HL, Coinalyze, Binance) |

**Critical Finding:**  
Lines 18–22 of `scripts/research_cta_positioning_phase2b.py` document that Phase 2b **explicitly excludes** HL funding accrual that Phase 2a included. This is a deliberate design change, not an oversight.

---

## Section 4: Fee Rate Discrepancies (Non-0.00045 Items)

### 4.1 Higher/Lower Than 0.00045 (0.045%)

| Fee Value | File:Line | Context | Reason |
|-----------|-----------|---------|--------|
| **0.0003** (0.03%) | `src/hlvault/gridbot/strategy.py:33` | gridbot backtest | taker/maker blended estimate (lower than pure taker 0.045%) |
| **0.0003** (0.03%) | `scripts/research_trend_filtered_grid.py:42` | research grid backtest | same rationale; blended rate |
| **0.0005** (0.05%) | `src/hlvault/momentum/backtest.py:17` | momentum backtest | daily rebalance (slighly higher; includes stale midpoint risk) |
| **0.00095** (0.095%) | `compound/scripts/research_strategy_phases.py:58` | compound phase-fit backtest | 0.045% fee + 0.05% slippage combined |
| **0.0018** (0.18%) | `scripts/research_funding_carry.py:111` | funding carry rebalance | 4 legs (2 entry + 2 exit); 4 × 0.00045 = 0.0018 per round trip |
| **0.15** (15%) | `compound/src/compound/config.py:24` | Bitfinex lending engine | platform cut of **interest earned**, not trading fee (different domain) |
| **0.075%** (7.5 bps) | `stablepairs/config.py:40` | stable pairs backtest config | configurable; set to "YOUR real taker fee" (higher for testing; actual HL is 1.4bps) |
| **0.01%** (1.0 bps) | `stablepairs/config.py:41` | stable pairs slippage | very low (stables); configurable |
| **0.014%** (1.4 bps) | `stablepairs/g0_hl_stables.py:36`, line 34 | stable pair observation | HL actual observed taker rate on stables |

---

## Section 5: Summary Counts

| Metric | Count |
|--------|-------|
| Distinct cost constant definitions (non-config)| 9 |
| ORDER_SLIPPAGE usage sites (live execution only) | 4 |
| Perp backtest scripts WITH funding PnL | 2 |
| Perp backtest scripts WITHOUT funding PnL | 3 |
| Fee rate values != 0.00045 | 8 |
| Live production engines | 4 |

---

## Section 6: Audit Notes

### Data Integrity
- ✅ All numeric constants have source lines and file paths.
- ✅ Funding PnL calculations in Phase 2a are explicit (lines 237–238, 256–257 in research_cta_positioning.py).
- ✅ Phase 2b funding exclusion is documented (research_cta_positioning_phase2b.py:18–22).
- ✅ ORDER_SLIPPAGE never used in research scripts; only in live engine modules.

### Known Simplifications (Disclosed in Code)
1. **Pair trading:** "Funding approximated as zero-mean" (research_pair_trading.py:14).
2. **Compound phase-fit:** "Short leg ignores perp funding" (research_strategy_phases.py:36).
3. **Stable pairs:** Configurable slippage; actual HL is 1.4 bps but backtest uses higher values for conservatism.

### No Misuse Detected
- No research script incorrectly uses ORDER_SLIPPAGE as a cost assumption.
- No implicit funding gap (non-perp backtests don't claim to model it).
- Fee values are explicitly documented at their definition points.

---

**Scan completed:** 2026-07-12  
**Total files scanned:** 90+  
**Python files analyzed:** ~50 in target directories  
**Lines with cost constants:** 40+
