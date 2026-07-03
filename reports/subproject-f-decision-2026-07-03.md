# Sub-project F Decision — 2026-07-03

Three tracks, all resolved with real data (details in linked reports):

| Track | Result | Decision |
|---|---|---|
| F1 Bitfinex USD lending | 6.4%/yr realized (12mo), custodial risk | **Stay** — carry (~10%, self-custody) beats it on both axes |
| F1 HLP vault | −3.9% this week; drawdowns real | Not a "safe" upgrade; monitor only |
| F2 Pair trading (cointegration) | **NO-GO** — median OOS Sharpe −1.63, all 6 configs negative, 60% of exits are hard stops: train-window cointegration does not persist OOS on this universe/regime | **Do not build.** No tuning past the pre-declared configs |
| F3 Gridbot scaling | Pending 14-day live review (2026-07-15) | The realistic path to the 5-10%/mo target if confirmed |

## Bottom line for the monthly-yield goal

The 5-10%/mo target currently has exactly one evidenced candidate: scaling
capital into gridbot IF its 14-day review (7/15) confirms ≥0.5%/day with
healthy per-coin PnL. Passive alternatives are strictly worse than what is
already deployed; stat-arb on HL hourly data fails its gate decisively.
Running total of honestly rejected hypotheses this week: copy-trading,
momentum, multi-alt grid, trend-filtered grid, naive funding rotation,
pair trading (6). Deployed and alive: gridbot (fast leg), carry (steady leg).

Verdicts: `reports/passive-benchmarks-2026-07-03.md`, `reports/pair-trading-verdict.md`.
