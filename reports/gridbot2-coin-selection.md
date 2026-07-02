# Gridbot instance-2 coin selection — NO-GO

Gate: net PnL > 0 AND backtest MDD <= 20% of the coin's $333 budget; top 3 by Sharpe; >=2 required to deploy.
Window: ~730 days of 1h candles; live-engine default grid params; same strategy.step code path as production.

| coin | step | days | net PnL | ann. on budget | Sharpe | MDD %budget | fills | stops | note |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| TAO | 0.65% | 208 | $-7.3 | -3.9% | -0.01 | 41.1% | 1616 | 9 | rejected |
| TON | 1.03% | 208 | $-27.9 | -14.7% | -0.06 | 42.2% | 529 | 5 | rejected |
| SOL | 0.51% | 208 | $-36.4 | -19.1% | -0.08 | 47.6% | 908 | 5 | rejected |
| PENDLE | 0.65% | 208 | $-62.3 | -32.7% | -0.10 | 40.9% | 1383 | 9 | rejected |
| AAVE | 0.80% | 208 | $-61.8 | -32.5% | -0.11 | 51.1% | 860 | 7 | rejected |
| LINK | 0.44% | 208 | $-68.9 | -36.2% | -0.15 | 37.9% | 956 | 5 | rejected |
| BNB | 0.32% | 208 | $-53.1 | -27.9% | -0.15 | 32.6% | 715 | 3 | rejected |
| AVAX | 0.59% | 208 | $-114.3 | -60.1% | -0.21 | 50.5% | 927 | 7 | rejected |
| CRV | 0.57% | 208 | $-156.8 | -82.4% | -0.25 | 65.7% | 1237 | 9 | rejected |
| SUI | 0.55% | 208 | $-188.7 | -99.2% | -0.28 | 71.8% | 1405 | 10 | rejected |
| UNI | 0.61% | 208 | $-186.9 | -98.2% | -0.30 | 83.7% | 924 | 8 | rejected |
| LTC | 0.40% | 208 | $-151.6 | -79.7% | -0.34 | 57.4% | 610 | 5 | rejected |
| DOGE | 0.45% | 208 | $-243.6 | -128.0% | -0.42 | 80.1% | 931 | 8 | rejected |
| XRP | 0.40% | 208 | $-246.1 | -129.3% | -0.43 | 80.7% | 964 | 8 | rejected |
| HYPE | 0.78% | 208 | $+276.5 | +145.2% | 0.55 | 20.2% | 1423 | 5 | baseline (live inst-1) |
| BTC | 0.35% | 208 | $-35.6 | -18.7% | -0.10 | 30.2% | 752 | 3 | baseline (live inst-1) |
| ETH | 0.41% | 208 | $-142.9 | -75.1% | -0.29 | 56.7% | 921 | 6 | baseline (live inst-1) |

**Verdict: NO-GO** — fewer than 2 qualifiers; do not deploy.
