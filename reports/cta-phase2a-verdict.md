# CTA Positioning (Sub-project G) — Phase-2a Verdict: **NO-GO** (proxy data)

**Date:** 2026-07-03 · **Spec:** `docs/superpowers/specs/2026-07-03-cta-positioning-design.md` (Phase-2a amendment, pre-declared 2026-07-03 before any backtest ran)
**Script:** `scripts/research_cta_positioning.py` · **Window:** 2025-07-01 → 2026-07-02 (12mo), stats from 2025-08-01 (30d crowding warmup)
**Universe:** BTC ETH SOL HYPE DOGE XRP · **Sizing:** $100 notional per coin, equal-weight portfolio base $600 · **Fees:** 0.045%/side · **Funding:** actual HL hourly accrual

## Method

Walk-forward simulation of the pre-declared 24-config matrix — trend TF {4h, 1d} × crowding percentile {10, 20} × fuel {none, 24h quote-volume increase} × side {long, short, both} — on Binance USDT-M klines with HL hourly funding. Trend is EMA20 vs EMA50 on closed bars; crowding is the HL funding rate resampled to the trend TF (mean) and ranked in a rolling trailing 90d percentile (min 30d warmup) — a **proxy** for retail positioning, since real account-ratio/OI history is only ~30d deep on Binance (Phase-1 probe); the fuel gate's 24h volume change is likewise a **proxy** for OI momentum. Every decision signal is computed on bar t−1's close and executed at bar t's open (percentile/EMA/ATR windows trailing-only, verified by synthetic point-in-time tests); shorts enter on down-trend + crowded-long + fuel, longs mirrored; exits are fuel-fail (vol variant), trend flip, 2×ATR(14) hard stop (checked intrabar, stop-first, gap-through at open), or 14d max hold; one position per coin, re-entry earliest the bar after exit, funding accrued at −direction × rate × $100 (short receives positive funding). Signals are PIT by construction (rolling windows, no fitted parameters), so the walk-forward is a single continuous simulation plus a split-half stability check at the calendar midpoint (2026-01-01); Sharpe is annualized (√365) from daily portfolio PnL including idle zero-PnL days, MDD on the $600 base, and the multiple-testing check uses the pre-declared t > 2.9 threshold (one-sided Bonferroni, 24 trials at 5%).

## Verdict: NO-GO

| # | Gate (binding, pre-declared) | Result | Pass? |
|---|---|---|---|
| 1 | Median-config Sharpe > 1.0 | **0.98** | **FAIL** |
| 2 | Best config survives 24-trial correction (t-stat > 2.9) | best = `1d-p20-vol-both`, Sharpe 2.05, **t = 1.96** | **FAIL** |
| 3 | Aggregate MDD ≤ 15% (median config) | −7.7% | PASS |
| 4 | ≥60% of coins non-negative at median config | 6/6 | PASS |
| 5 | Split halves same sign at median config | h1 +$47.00 / h2 +$29.99 | PASS |

Two of five legs fail, and they are the two that matter for statistical validity. The median-config Sharpe (0.98) misses the gate by a hair — reported as-is, not rounded up. The sharper failure is leg 2: the best config's t-stat (1.96) is nowhere near the 2.9 needed to distinguish it from the luckiest of 24 trials on ~11 months of daily data; a config would need Sharpe ≈ 3 on this window to survive. **Conclusion: the family looks promising (22/24 configs profitable, risk well-contained, both halves positive) but is statistically unproven. Do not deploy capital. Hold for Phase-2b with real OI/account-ratio data.**

## Full 24-config matrix

Portfolio = 6 coins × $100, stats from 2025-08-01. `h1`/`h2` = PnL before/after 2026-01-01.

| config | pnl $ | ret % | Sharpe | t-stat | MDD % | trades | win % | h1 $ | h2 $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1d-p10-none-both | 182.79 | 30.47 | 1.81 | 1.74 | −7.5 | 52 | 52 | 66.48 | 116.32 |
| 1d-p10-none-long | 105.81 | 17.63 | 1.41 | 1.35 | −7.1 | 18 | 56 | 19.48 | 86.33 |
| 1d-p10-none-short | 76.99 | 12.83 | 1.01 | 0.97 | −7.7 | 34 | 50 | 47.00 | 29.99 |
| 1d-p10-vol-both | 70.25 | 11.71 | 1.73 | 1.66 | −3.3 | 63 | 60 | 5.39 | 64.86 |
| 1d-p10-vol-long | 15.21 | 2.54 | 0.54 | 0.51 | −4.4 | 29 | 52 | −5.29 | 20.50 |
| 1d-p10-vol-short | 55.04 | 9.17 | 1.82 | 1.74 | −2.5 | 34 | 68 | 10.68 | 44.36 |
| 1d-p20-none-both | 176.95 | 29.49 | 1.26 | 1.21 | −10.7 | 81 | 52 | 129.01 | 47.94 |
| 1d-p20-none-long | 94.31 | 15.72 | 0.93 | 0.89 | −6.4 | 31 | 55 | 46.19 | 48.12 |
| 1d-p20-none-short | 83.33 | 13.89 | 0.76 | 0.73 | −12.5 | 51 | 51 | 82.82 | 0.50 |
| 1d-p20-vol-both | 108.07 | 18.01 | **2.05** | 1.96 | −3.5 | 115 | 57 | 63.65 | 44.42 |
| 1d-p20-vol-long | 26.05 | 4.34 | 0.73 | 0.70 | −3.3 | 49 | 53 | 7.91 | 18.14 |
| 1d-p20-vol-short | 82.02 | 13.67 | 1.79 | 1.72 | −4.4 | 66 | 59 | 55.73 | 26.28 |
| 4h-p10-none-both | 122.57 | 20.43 | 0.81 | 0.78 | −16.7 | 167 | 35 | 31.07 | 91.51 |
| 4h-p10-none-long | −9.79 | −1.63 | −0.12 | −0.12 | −16.4 | 68 | 31 | −22.24 | 12.45 |
| 4h-p10-none-short | 133.95 | 22.33 | 0.95 | 0.91 | −14.4 | 100 | 38 | 55.81 | 78.14 |
| 4h-p10-vol-both | 80.76 | 13.46 | 1.04 | 1.00 | −5.7 | 241 | 48 | 37.89 | 42.88 |
| 4h-p10-vol-long | 17.32 | 2.89 | 0.56 | 0.54 | −5.0 | 82 | 44 | 5.38 | 11.94 |
| 4h-p10-vol-short | 77.18 | 12.86 | 1.06 | 1.01 | −6.2 | 160 | 51 | 32.50 | 44.68 |
| 4h-p20-none-both | 131.42 | 21.90 | 0.67 | 0.64 | −18.7 | 227 | 32 | 68.13 | 63.29 |
| 4h-p20-none-long | −29.50 | −4.92 | −0.28 | −0.27 | −25.3 | 96 | 25 | −48.26 | 18.76 |
| 4h-p20-none-short | 154.08 | 25.68 | 0.85 | 0.82 | −14.5 | 133 | 37 | 108.58 | 45.50 |
| 4h-p20-vol-both | 114.46 | 19.08 | 1.15 | 1.10 | −5.1 | 393 | 48 | 57.37 | 57.09 |
| 4h-p20-vol-long | 26.06 | 4.34 | 0.63 | 0.61 | −3.6 | 147 | 43 | −4.45 | 30.51 |
| 4h-p20-vol-short | 103.29 | 17.21 | 1.10 | 1.05 | −5.7 | 248 | 52 | 62.88 | 40.41 |

Median of the 24 Sharpes = 0.98; median config (nearest Sharpe) = `1d-p10-none-short` (1.01). 22/24 configs have positive total PnL (the two losers are both 4h long-only); the fuel gate is the family's best risk tool (vol-variant MDDs −2.5%…−6.2% vs up to −25.3% without it).

## Per-side breakdown ("both" configs) — feeds the owner's side-switch design

| config | long $ | nL | winL % | short $ | nS | winS % |
|---|---:|---:|---:|---:|---:|---:|
| 1d-p10-none-both | 105.81 | 18 | 56 | 76.99 | 34 | 50 |
| 1d-p10-vol-both | 15.21 | 29 | 52 | 55.04 | 34 | 68 |
| 1d-p20-none-both | 93.63 | 30 | 53 | 83.33 | 51 | 51 |
| 1d-p20-vol-both | 26.05 | 49 | 53 | 82.02 | 66 | 59 |
| 4h-p10-none-both | −7.84 | 67 | 31 | 130.41 | 100 | 38 |
| 4h-p10-vol-both | 3.58 | 81 | 43 | 77.18 | 160 | 51 |
| 4h-p20-none-both | −24.19 | 94 | 26 | 155.61 | 133 | 37 |
| 4h-p20-vol-both | 11.94 | 145 | 42 | 102.52 | 248 | 52 |

The asymmetry is timeframe-dependent: on **4h the long leg is dead weight** (negative or near-zero in all four configs; shorts carry all the PnL), while on **1d both sides contribute** (longs actually led in the p10-none cell). If Phase-2b confirms, the declared side-switch would justify short-only on 4h; 1d supports both sides. This is an observation from the declared matrix, not a new tuned config.

## Per-coin at median config (`1d-p10-none-short`)

| coin | pnl $ | trades | sign |
|---|---:|---:|---|
| BTC | 10.67 | 5 | non-negative |
| ETH | 24.10 | 6 | non-negative |
| SOL | 1.85 | 9 | non-negative |
| HYPE | 4.94 | 2 | non-negative |
| DOGE | 18.74 | 5 | non-negative |
| XRP | 16.68 | 7 | non-negative |

## Monthly distribution vs the 10%/mo ask (median config, $600 base)

2025-08 0.00% · 2025-09 0.00% · 2025-10 +0.67% · 2025-11 +4.84% · 2025-12 +2.32% · 2026-01 −0.09% · 2026-02 −0.02% · 2026-03 +1.96% · 2026-04 −3.78% · 2026-05 −2.13% · 2026-06 +9.92% · 2026-07 −0.87%

The honest read vs the aspirational 10%/mo: the median config averages **≈ +1.2%/mo** (best single month +9.9%); even the best config (`1d-p20-vol-both`) averages ≈ +1.6%/mo. The 10%/mo ceiling is not remotely supported by this evidence at 1× notional — reaching it would require ~6–8× leverage, which would scale the −3.5% MDD to ~25% and breach every risk gate. Reported per the spec's honest-framing requirement.

## Honest caveats

1. **Crowding is a proxy.** HL funding percentile stands in for retail long/short positioning. Funding is the *price* of positioning imbalance, not a head-count; the two can diverge (e.g., whale-driven funding without retail crowding). Phase-2b must re-run the same matrix with true account-ratio/OI data (Coinalyze key pending) — **2a survivors must survive 2b**, and this run produced no statistically-validated survivor to carry forward.
2. **Fuel is a proxy.** 24h quote-volume change stands in for OI momentum. Volume rises during both accumulation (OI up) and liquidation cascades (OI down); true OI separates them. The vol-gate's strong MDD reduction here may partly reflect this conflation.
3. **Venue mismatch.** Signals and fills are simulated on Binance USDT-M klines; live execution would be on Hyperliquid. Prices track closely for these liquid names, but basis, fill quality, and wick structure differ; funding accrual is HL-real.
4. **Simulation optimism/simplifications.** Stop exits fill exactly at the stop level (gap-through handled at open, but no slippage beyond the taker fee); funding accrues on entry notional ($100) rather than marked notional; no funding on the partial exit bar; stop-first intrabar assumption is conservative but high/low ordering within a bar is unknowable.
5. **One 12-month window, one regime.** The Bonferroni-style gate corrects for the 24 declared trials, but not for regime luck; ~336 daily observations give little power (hence the t = 2.9 bar being so demanding — that is the point of the gate).
6. **Marginal median.** 0.98 vs 1.0 is inside estimation noise; the gate is applied literally per the spec ("do not soften"). The correct response to marginality is more/better data (Phase-2b), not gate adjustment.

## Actual script output

```
$ .venv/bin/python scripts/research_cta_positioning.py
=== data ===
BTC   klines 4h=2200 1d=366 bars [2025-07-01 .. 2026-07-02]  funding hours=8760 [2025-07-02 .. 2026-07-02]
ETH   klines 4h=2200 1d=366 bars [2025-07-01 .. 2026-07-02]  funding hours=8760 [2025-07-02 .. 2026-07-02]
SOL   klines 4h=2200 1d=366 bars [2025-07-01 .. 2026-07-02]  funding hours=8760 [2025-07-02 .. 2026-07-02]
HYPE  klines 4h=2200 1d=366 bars [2025-07-01 .. 2026-07-02]  funding hours=8760 [2025-07-02 .. 2026-07-02]
DOGE  klines 4h=2200 1d=366 bars [2025-07-01 .. 2026-07-02]  funding hours=8760 [2025-07-02 .. 2026-07-02]
XRP   klines 4h=2200 1d=366 bars [2025-07-01 .. 2026-07-02]  funding hours=8760 [2025-07-02 .. 2026-07-02]

=== 24-config matrix (portfolio: 6 coins x $100, stats from 2025-08-01) ===
config                 pnl$    ret%  sharpe  tstat   mdd% trades  win%      h1$      h2$
1d-p10-none-both     182.79  30.47%    1.81   1.74  -7.5%     52   52%    66.48   116.32
1d-p10-none-long     105.81  17.63%    1.41   1.35  -7.1%     18   56%    19.48    86.33
1d-p10-none-short     76.99  12.83%    1.01   0.97  -7.7%     34   50%    47.00    29.99
1d-p10-vol-both       70.25  11.71%    1.73   1.66  -3.3%     63   60%     5.39    64.86
1d-p10-vol-long       15.21   2.54%    0.54   0.51  -4.4%     29   52%    -5.29    20.50
1d-p10-vol-short      55.04   9.17%    1.82   1.74  -2.5%     34   68%    10.68    44.36
1d-p20-none-both     176.95  29.49%    1.26   1.21 -10.7%     81   52%   129.01    47.94
1d-p20-none-long      94.31  15.72%    0.93   0.89  -6.4%     31   55%    46.19    48.12
1d-p20-none-short     83.33  13.89%    0.76   0.73 -12.5%     51   51%    82.82     0.50
1d-p20-vol-both      108.07  18.01%    2.05   1.96  -3.5%    115   57%    63.65    44.42
1d-p20-vol-long       26.05   4.34%    0.73   0.70  -3.3%     49   53%     7.91    18.14
1d-p20-vol-short      82.02  13.67%    1.79   1.72  -4.4%     66   59%    55.73    26.28
4h-p10-none-both     122.57  20.43%    0.81   0.78 -16.7%    167   35%    31.07    91.51
4h-p10-none-long      -9.79  -1.63%   -0.12  -0.12 -16.4%     68   31%   -22.24    12.45
4h-p10-none-short    133.95  22.33%    0.95   0.91 -14.4%    100   38%    55.81    78.14
4h-p10-vol-both       80.76  13.46%    1.04   1.00  -5.7%    241   48%    37.89    42.88
4h-p10-vol-long       17.32   2.89%    0.56   0.54  -5.0%     82   44%     5.38    11.94
4h-p10-vol-short      77.18  12.86%    1.06   1.01  -6.2%    160   51%    32.50    44.68
4h-p20-none-both     131.42  21.90%    0.67   0.64 -18.7%    227   32%    68.13    63.29
4h-p20-none-long     -29.50  -4.92%   -0.28  -0.27 -25.3%     96   25%   -48.26    18.76
4h-p20-none-short    154.08  25.68%    0.85   0.82 -14.5%    133   37%   108.58    45.50
4h-p20-vol-both      114.46  19.08%    1.15   1.10  -5.1%    393   48%    57.37    57.09
4h-p20-vol-long       26.06   4.34%    0.63   0.61  -3.6%    147   43%    -4.45    30.51
4h-p20-vol-short     103.29  17.21%    1.10   1.05  -5.7%    248   52%    62.88    40.41

median config Sharpe = 0.98  (nearest config: 1d-p10-none-short, sharpe 1.01)
best config = 1d-p20-vol-both  sharpe 2.05  tstat 1.96 (gate 2.9)

=== per-coin at median config (1d-p10-none-short) ===
BTC   pnl=   10.67$  trades=  5  non-negative
ETH   pnl=   24.10$  trades=  6  non-negative
SOL   pnl=    1.85$  trades=  9  non-negative
HYPE  pnl=    4.94$  trades=  2  non-negative
DOGE  pnl=   18.74$  trades=  5  non-negative
XRP   pnl=   16.68$  trades=  7  non-negative

=== per-side breakdown ('both' configs) ===
config                long$   nL  winL%   short$   nS  winS%
1d-p10-none-both     105.81   18    56%    76.99   34    50%
1d-p10-vol-both       15.21   29    52%    55.04   34    68%
1d-p20-none-both      93.63   30    53%    83.33   51    51%
1d-p20-vol-both       26.05   49    53%    82.02   66    59%
4h-p10-none-both      -7.84   67    31%   130.41  100    38%
4h-p10-vol-both        3.58   81    43%    77.18  160    51%
4h-p20-none-both     -24.19   94    26%   155.61  133    37%
4h-p20-vol-both       11.94  145    42%   102.52  248    52%

=== monthly portfolio PnL at median config (1d-p10-none-short) vs the 10%/mo ask ($600 base -> $60/mo) ===
2025-08      0.00$  (  0.00%)
2025-09      0.00$  (  0.00%)
2025-10      4.03$  (  0.67%)
2025-11     29.05$  (  4.84%)
2025-12     13.92$  (  2.32%)
2026-01     -0.52$  ( -0.09%)
2026-02     -0.11$  ( -0.02%)
2026-03     11.79$  (  1.96%)
2026-04    -22.69$  ( -3.78%)
2026-05    -12.76$  ( -2.13%)
2026-06     59.50$  (  9.92%)
2026-07     -5.22$  ( -0.87%)

=== pre-declared gate (ALL must hold for GO) ===
1. median-config Sharpe > 1.0          :   0.98  FAIL
2. best-config tstat > 2.9 (24 trials) :   1.96  FAIL
3. aggregate MDD <= 15% (median cfg)   :  -7.7%  PASS
4. >=60% coins non-negative (median)   : 6/6  PASS
5. split halves same sign (median cfg) : h1=+47.00 h2=+29.99  PASS

VERDICT: NO-GO   (4.3s)
```

## Next step

NO-GO on proxy data means **no live engine and no capital**. The pre-declared path remains open: when the owner's Coinalyze key arrives, Phase-2b re-runs the *same* 24-config matrix with true OI and account-ratio data. Given 3/5 gate legs passed and the family's risk profile is clean, Phase-2b is worth running — but nothing here authorizes deployment.
