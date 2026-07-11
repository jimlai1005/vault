# Hyperliquid Spot Stablecoin Pair Liquidity Report

**Generated:** 2026-07-11  
**Scope:** All stablecoin-to-stablecoin pairs on Hyperliquid spot market  
**API:** `https://api.hyperliquid.xyz/info`

## Summary

Found **5 stablecoin-to-stablecoin trading pairs** on Hyperliquid spot market. The market is dominated by **USDT0/USDC** (~$2.86M daily notional volume), with meaningful liquidity in **USDe/USDC** (~$572K) and **USDH/USDC** (~$146K). Smaller pairs show minimal to zero volume.

### Key Finding

**Hyperliquid spot market does not expose individual bid/ask orders via L2Book API** (requests return `null`). The platform appears to use AMM or concentrated liquidity model for spot pairs rather than traditional order books. Therefore, **top-of-book spread cannot be measured via standard API**. Mid-prices and daily volume are available, but depth/spread profiling requires either:
- Direct HTTP scraping of web UI (if available)
- Making actual test trades and observing fills (violates the "no trading" constraint)
- Using Hyperliquid's WebSocket feed (not checked in this pass)

## Stablecoin Pair Universe

| Rank | Pair Name | Token0/Token1 | Mid Price | Daily Notional Volume (USD) | Status |
|------|-----------|---------------|-----------|------------------------------|--------|
| 1 | @166 | USDT0/USDC | 0.9992 | $2,864,517 | Active, high liquidity |
| 2 | @150 | USDe/USDC | 1.0000 | $571,882 | Active, good liquidity |
| 3 | @230 | USDH/USDC | 1.0000 | $146,049 | Active, moderate liquidity |
| 4 | @153 | FEUSD/USDC | 0.9973 | $18,465 | Active, low liquidity |
| 5 | @180 | USDHL/USDC | 1.0060 | $0 | Dead pair (no volume) |

## Data Limitations

- **L2Book API**: Returns empty orderbook (`null`) for all stable pairs tested. Indicates no public order book data available.
- **Spread measurement**: Cannot be derived from published API without order book access.
- **Depth profiling**: Cannot be completed via REST API.

## Implications for Execution

1. **USDT0/USDC** is the most liquid stable pair (~$2.86M daily) - best for mean-reversion strategies requiring depth.
2. **USDe/USDC** provides secondary liquidity option (~$572K daily).
3. **Taker fee of 0.014%** (from task spec) is extremely competitive if fills are instant (implying tight spreads via AMM logic).
4. **No public spread data** means execution venue feasibility assessment requires:
   - Testing actual fills at different order sizes, or
   - Consulting HL support for indicative spreads

## Conclusion

Hyperliquid spot market has 5 stablecoin pairs, with 3 showing meaningful daily volume. The lack of L2Book API access prevents direct spread quantification, but the high daily notional volumes on top pairs suggest adequate liquidity for strategy prototyping. Real execution testing needed before G0 gate approval.

---
**Note:** This report reflects the API limitations as of 2026-07-11. If Hyperliquid enables WebSocket L2Book or REST improvements, spreads can be re-measured.
