# Momentum Backtest Verdict: NO-GO

**Universe:** BTC, ETH, SOL, HYPE
**Window:** 2024-07-02 -> 2026-07-02 (731 days)
**Capital (hypothetical):** $10,000 · **Leverage cap:** 3.0x · **Entry threshold:** 0.5

| Metric | Value |
|---|---:|
| Total return | -24.0% |
| Sharpe (ann.) | 0.28 |
| Max drawdown | -65.1% |

**Verdict logic:** GO iff Sharpe > 0.5 AND total return > 0 AND max drawdown stays inside the
live circuit-breaker budget (20%). This is a backtest sanity gate, not a
substitute for the circuit breaker itself, which remains enforced live regardless of this verdict.

**Recommendation:** Do not enable LIVE_TRADING yet — revisit universe/parameters or gather more history before going live.
