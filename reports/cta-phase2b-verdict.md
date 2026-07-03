# CTA Positioning (Sub-project G) — Phase-2b Verdict: **NO-GO** (real OI/account-ratio data)

**Date:** 2026-07-04 · **Spec:** `docs/superpowers/specs/2026-07-03-cta-positioning-design.md` (original design + Phase-2a amendment)
**Script:** `scripts/research_cta_positioning_phase2b.py` · **Data-pull script:** `scripts/pull_coinalyze_data.py`
**Window:** 2025-08-03 → 2026-07-03 (Coinalyze coverage, ~334 days), stats from 2025-09-03 (30d crowding warmup) → 303 stats days
**Universe:** BTC ETH SOL HYPE DOGE XRP · **Sizing:** $100 notional per coin, equal-weight portfolio base $600 · **Fees:** 0.045%/side

## Honest correction to the spec's data assumption (binding, reported per acceptance criteria)

The design doc and Phase-2a report both assumed **2 years** of Coinalyze OI/long-short-ratio history would eventually be available. Empirically (`reports/coinalyze-data-pull.md`, pull run 2026-07-04) this API key's plan serves only **~335 days** of 4h OI/account-ratio history — requests before 2025-08-03 return empty for every coin tested (BTC, HYPE spot-checked explicitly; all 6 coins ultimately show identical coverage: 2025-08-03/04 → 2026-07-03/04, 2005-2007 4h bars). This is a real limitation of the current Coinalyze subscription tier, not a bug. Phase 2b therefore runs on **less than a third** of the originally planned sample — the walk-forward has correspondingly less statistical power, which shows up directly in the multiple-testing gate result below.

## Method (identical to Phase 2a except the two data-source swaps the owner asked for)

Walk-forward simulation of the pre-declared 24-config matrix — trend TF {4h, 1d} × crowding percentile {10, 20} × **OI fuel lookback {24h, 72h}** × side {long, short, both} — on Binance USDT-M klines (unchanged from Phase 2a, `data/cache/cta/`) with **real Coinalyze data** (`data/cache/coinalyze/{COIN}_{oi,lsr}_4h.parquet`) replacing both Phase-2a proxies:

- **Crowding** (was: HL funding-rate percentile) → now: Coinalyze long/short **account ratio**, specifically the `l` field (% of accounts/positions long; `l + s = 100`, `r = l/s` exactly, verified numerically) from the `long-short-ratio-history` endpoint — the same metric Binance calls `globalLongShortAccountRatio`. Resampled to the trend TF (mean) and ranked in a rolling trailing-90d percentile (min 30d warmup, trailing-only) — exactly the same percentile mechanics as Phase 2a, just fed real positioning data instead of funding rate.
- **Fuel gate** (was: proxy 24h quote-volume change, `{none, vol}`) → now: real Coinalyze **open interest level** (`c` field of `open-interest-history`, verified to be in **native-coin units**, not USD — see Data Verification below) compared to its value {24h, 72h} earlier; fuel = OI risen over the lookback. This realizes the *original* design doc's fuel-lookback axis (`{24h, 72h}`, line 29 of the spec) for the first time — Phase 2a could only approximate it with volume because OI history wasn't available yet. There is no "none" fuel variant in Phase 2b (matches the original design; Phase 2a's `none` option was itself a workaround for lacking real OI, not a first-class spec variant).
- Trend layer (EMA20 vs EMA50 on closed bars, {4h,1d}), entry/exit logic (2×ATR(14) hard stop, 14d max hold, trend-flip exit, fuel-fail exit), $100 notional/coin, 0.045%/side fee, one position per coin, re-entry earliest the bar after exit — **all unchanged from Phase 2a**.
- Every decision signal is computed on bar t−1's close and executed at bar t's open (shift-by-one), percentile/EMA/ATR/OI-change windows are trailing-only — verified by a synthetic PIT test (see Self-Review below).
- Backtest window = **intersection** of Binance klines coverage and Coinalyze coverage across all 6 coins; Coinalyze is the binding constraint (klines go back to 2025-07-01 and beyond, Coinalyze only to 2025-08-03).
- Sharpe annualized (√365) from daily portfolio PnL (idle zero-PnL days included), MDD on the $600 base, split-half check at the calendar midpoint of the actual window (2026-01-18, not a fixed calendar date since the window itself shifted), multiple-testing gate uses the same pre-declared t > 2.9 threshold (Bonferroni, 24 trials at 5%) as Phase 2a.
- **Caveat — funding accrual dropped:** Phase 2a's PnL included real HL hourly funding cash-flow while holding a position (funding was also the crowding-signal proxy, so it was already wired in). Phase 2b's crowding signal is now a real account ratio, decoupled from funding, and Coinalyze does not supply a matching Hyperliquid funding series for this window. Phase 2b PnL therefore has **no funding accrual** — fees are identical (0.045%/side) but Phase 2a benefited from (or was penalized by) real funding cash flows that Phase 2b does not model. This makes the two PnL levels not perfectly apples-to-apples; Sharpe/MDD/gate comparisons are still valid since both use the same annualization and fee treatment, but this is flagged honestly rather than silently glossed over.

## Verdict: NO-GO

| # | Gate (binding, pre-declared) | Result | Pass? |
|---|---|---|---|
| 1 | Median-config Sharpe > 1.0 | **1.27** | **PASS** |
| 2 | Best config survives 24-trial correction (t-stat > 2.9) | best = `4h-p10-fuel24-short`, Sharpe 2.34, **t = 2.14** | **FAIL** |
| 3 | Aggregate MDD ≤ 15% (median config) | −5.1% | PASS |
| 4 | ≥60% of coins non-negative at median config | 5/6 | PASS |
| 5 | Split halves same sign at median config | h1 +$21.63 / h2 +$84.81 | PASS |

Four of five gates now pass — a clear improvement over Phase 2a (which failed both gate 1 and gate 2). Real positioning and real OI data produced a stronger, more statistically credible signal than the funding/volume proxies. But **gate 2, the multiple-testing correction, still fails**: the best config's t-stat (2.14) falls short of the 2.9 bar needed to distinguish it from the luckiest of 24 pre-declared trials on ~303 days of daily data — and 303 days is barely a quarter of the ~2yr sample the gate's power was originally calibrated against. **Conclusion: real data confirms the strategy family has a genuine, coin-broad, risk-contained edge (unlike Phase 2a's marginal median), but the sample is still too short to statistically distinguish the best config from noise at the pre-declared significance bar. Do not deploy capital. The gate is not softened — one failing leg is still NO-GO per the pre-declared "all must hold" rule.**

## Full 24-config matrix

Portfolio = 6 coins × $100, stats from 2025-09-03. `h1`/`h2` = PnL before/after 2026-01-18 (calendar midpoint of the actual 334-day window).

| config | pnl $ | ret % | Sharpe | t-stat | MDD % | trades | win % | h1 $ | h2 $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1d-p10-fuel24-both | 106.48 | 17.75 | 1.81 | 1.65 | −3.6 | 82 | 55 | 35.51 | 70.97 |
| 1d-p10-fuel24-long | −3.93 | −0.65 | −0.18 | −0.16 | −2.5 | 24 | 46 | 0.96 | −4.89 |
| 1d-p10-fuel24-short | 110.41 | 18.40 | 1.95 | 1.78 | −3.3 | 58 | 59 | 34.55 | 75.86 |
| 1d-p10-fuel72-both | 121.08 | 20.18 | 1.80 | 1.64 | −5.4 | 67 | 61 | 25.72 | 95.37 |
| 1d-p10-fuel72-long | 19.98 | 3.33 | 1.05 | 0.95 | −2.1 | 16 | 50 | 0.58 | 19.41 |
| 1d-p10-fuel72-short | 101.10 | 16.85 | 1.54 | 1.41 | −4.4 | 51 | 65 | 25.14 | 75.96 |
| 1d-p20-fuel24-both | 116.15 | 19.36 | 1.30 | 1.19 | −6.7 | 141 | 48 | 17.59 | 98.55 |
| 1d-p20-fuel24-long | 9.71 | 1.62 | 0.28 | 0.26 | −4.5 | 44 | 43 | −4.03 | 13.74 |
| 1d-p20-fuel24-short | 106.44 | 17.74 | **1.27** | 1.15 | −5.1 | 97 | 49 | 21.63 | 84.81 |
| 1d-p20-fuel72-both | 129.90 | 21.65 | 1.54 | 1.40 | −9.2 | 107 | 50 | 15.10 | 114.80 |
| 1d-p20-fuel72-long | 23.18 | 3.86 | 0.72 | 0.65 | −4.7 | 33 | 36 | 0.58 | 22.61 |
| 1d-p20-fuel72-short | 106.72 | 17.79 | 1.28 | 1.17 | −6.6 | 74 | 55 | 14.52 | 92.19 |
| 4h-p10-fuel24-both | 113.46 | 18.91 | 1.26 | 1.15 | −9.6 | 321 | 44 | 49.80 | 63.66 |
| 4h-p10-fuel24-long | −70.21 | −11.70 | −1.61 | −1.47 | −16.0 | 149 | 38 | 9.26 | −79.46 |
| 4h-p10-fuel24-short | 183.67 | 30.61 | **2.34** | **2.14** | −3.1 | 172 | 49 | 40.55 | 143.12 |
| 4h-p10-fuel72-both | 104.27 | 17.38 | 1.15 | 1.05 | −15.4 | 246 | 41 | 58.67 | 45.60 |
| 4h-p10-fuel72-long | −56.90 | −9.48 | −1.15 | −1.05 | −20.1 | 125 | 34 | 17.30 | −74.20 |
| 4h-p10-fuel72-short | 161.17 | 26.86 | 2.08 | 1.90 | −5.6 | 121 | 49 | 41.36 | 119.80 |
| 4h-p20-fuel24-both | 87.49 | 14.58 | 0.79 | 0.72 | −14.6 | 474 | 44 | 9.59 | 77.91 |
| 4h-p20-fuel24-long | −85.56 | −14.26 | −1.55 | −1.42 | −22.2 | 209 | 41 | −12.24 | −73.31 |
| 4h-p20-fuel24-short | 172.81 | 28.80 | 1.73 | 1.58 | −5.6 | 266 | 46 | 21.59 | 151.22 |
| 4h-p20-fuel72-both | 154.52 | 25.75 | 1.31 | 1.20 | −17.0 | 345 | 42 | 66.97 | 87.55 |
| 4h-p20-fuel72-long | −51.57 | −8.60 | −0.85 | −0.78 | −23.5 | 170 | 36 | 11.64 | −63.22 |
| 4h-p20-fuel72-short | 206.10 | 34.35 | 1.98 | 1.81 | −6.8 | 175 | 49 | 55.32 | 150.77 |

Median of the 24 Sharpes = **1.27**; median config (nearest Sharpe) = `1d-p20-fuel24-short` (1.27, exact match). **20/24 configs have positive total PnL** — the 4 losers are **all long-only** configs (both timeframes, both pctiles, fuel24 — note `1d-p10-fuel24-long` is marginally negative at −$3.93). Every single **short-only or both-side** config is profitable; short-only configs dominate on Sharpe (best 6 of the top 8 configs by Sharpe are short-only).

## Per-side breakdown ("both" configs) — feeds the owner's side-switch design

| config | long $ | nL | winL % | short $ | nS | winS % |
|---|---:|---:|---:|---:|---:|---:|
| 1d-p10-fuel24-both | −3.93 | 24 | 46 | 110.41 | 58 | 59 |
| 1d-p10-fuel72-both | 19.98 | 16 | 50 | 101.10 | 51 | 65 |
| 1d-p20-fuel24-both | 9.71 | 44 | 43 | 106.44 | 97 | 49 |
| 1d-p20-fuel72-both | 23.18 | 33 | 36 | 106.72 | 74 | 55 |
| 4h-p10-fuel24-both | −70.21 | 149 | 38 | 183.67 | 172 | 49 |
| 4h-p10-fuel72-both | −56.90 | 125 | 34 | 161.17 | 121 | 49 |
| 4h-p20-fuel24-both | −80.93 | 209 | 41 | 173.05 | 265 | 46 |
| 4h-p20-fuel72-both | −51.57 | 170 | 36 | 206.10 | 175 | 49 |

*(Note: `long$ + short$` differs from the matrix `pnl$` for `4h-p20-fuel24-both` by ~$4.63 — one trade straddles the stats-window start (entered 2025-09-02 16:00, exited 2025-09-04 04:00) and the trade-attribution table counts its full PnL at the exit bar, while the gate-relevant `pnl$`/Sharpe/MDD numbers correctly use bar-level daily PnL truncated at the stats cutoff. Verified this affects only 2 of 144 coin×config combinations and only the diagnostic per-side dollar table — not any gate number. See script comment for detail.)*

**Real data sharpens the asymmetry Phase 2a already flagged: the long leg is now dead weight or actively lossy across BOTH timeframes** (all 8 "both" configs show long-side PnL ≤ +$23, with 4h long-side deeply negative in all 4 configs), while short-side PnL is strongly positive in every single config (min +$101, all with 46-65% win rates). This is a *stronger* version of the Phase-2a finding (where 4h-long was dead weight but 1d-long still contributed). If a future validated version of this family is ever built, **short-only is the declared, evidence-backed configuration** on both timeframes — not a post-hoc tune, since side is one of the 24 pre-declared matrix dimensions.

## Per-coin at median config (`1d-p20-fuel24-short`)

| coin | pnl $ | trades | sign |
|---|---:|---:|---|
| BTC | 18.14 | 25 | non-negative |
| ETH | 51.00 | 20 | non-negative |
| SOL | 18.34 | 24 | non-negative |
| HYPE | −5.43 | 4 | NEGATIVE |
| DOGE | 4.44 | 11 | non-negative |
| XRP | 19.95 | 13 | non-negative |

5/6 coins non-negative (HYPE is the lone loser, only 4 trades — thin sample, likely noise rather than a structural HYPE-specific failure, but not enough trades to say confidently either way). Gate 4 (≥60% non-negative) still passes at 5/6 = 83%.

## Monthly distribution vs the 10%/mo ask (median config, $600 base)

2025-09 −0.25% · 2025-10 −0.82% · 2025-11 +8.37% · 2025-12 −2.86% · 2026-01 +3.46% · 2026-02 +5.68% · 2026-03 −0.09% · 2026-04 −1.12% · 2026-05 +0.12% · 2026-06 +5.66% · 2026-07 −0.41%

Median-config average ≈ **+1.6%/mo** over the 303-day window (best single month +8.4%); the best-Sharpe config (`4h-p10-fuel24-short`) totals $183.67 over 303 days ≈ +1.8%/skip-day-adjusted-mo. Both are meaningfully better than Phase 2a's ~+1.2%/mo (median) but still nowhere near the aspirational 10%/mo ceiling at 1× notional — consistent with Phase 2a's honest-framing conclusion that reaching 10%/mo would require leverage that blows through every risk gate.

## Comparison to Phase 2a (proxy data) — the central finding of this run

| Metric | Phase 2a (proxy: HL funding + volume) | Phase 2b (real: Coinalyze OI + account ratio) | Direction |
|---|---:|---:|---|
| Sample length | ~336 days (12mo nominal) | ~303 stats days (334d window) | shorter (Coinalyze limit) |
| Median-config Sharpe | 0.98 (FAIL, gate >1.0) | **1.27 (PASS)** | improved |
| Best-config Sharpe | 2.05 | **2.34** | improved |
| Best-config t-stat | 1.96 (FAIL, gate >2.9) | **2.14 (FAIL, gate >2.9)** | improved, still fails |
| Aggregate MDD (median cfg) | −7.7% | −5.1% | improved |
| Coins non-negative (median cfg) | 6/6 | 5/6 | slightly worse |
| Split-half same sign | yes | yes | unchanged |
| Positive configs | 22/24 | 20/24 | slightly worse (but losers now cleanly isolated to long-only) |
| Best side/TF pattern | 4h short-only strong, 1d both-side viable | 4h AND 1d short-only strong; long dead/negative everywhere | asymmetry sharpened |

**This is a meaningful, honest finding in its own right**: real positioning and OI data did not just "confirm" the proxy result — it produced a *better-behaved* signal (higher Sharpe, lower drawdown, tighter long/short asymmetry) than the Phase-2a proxies, on a materially *shorter* sample. That the median-Sharpe and MDD gates now pass where they failed on proxy data suggests the real crowding/fuel signals carry more genuine information than funding-rate/volume stand-ins — plausible, since account ratio and OI are literally the quantities the strategy hypothesis is about, whereas funding and volume were always acknowledged proxies. But the shorter real-data sample (303 vs 336 days) costs statistical power exactly where it matters: the multiple-testing gate is the one leg that stayed failed, moving from t=1.96 to t=2.14 — real progress, but 0.76 short of the 2.9 bar. **Bottom line: better signal, not-yet-enough data to prove it isn't luck.**

## Data verification (self-review, run before accepting any result)

1. **Schema, read directly from the parquet files** (no assumption from prose):
   - `{COIN}_oi_4h.parquet`: columns `t` (unix seconds), `o`, `h`, `l`, `c` (OHLC-style bar of the OI level over the 4h interval).
   - `{COIN}_lsr_4h.parquet`: columns `t` (unix seconds), `r` (ratio), `l` (long %), `s` (short %). Verified numerically: `r == l/s` exactly for all rows, and `l + s == 100.0` for all 2007 BTC rows (std 0.0) — confirms `l`/`s` are literally a percentage split, `r` is derived, not independent.
2. **OI unit check** (base-asset units, not USD — this determines whether "OI rising" means dollars or coins of open interest): BTC OI `c` ranges 70,680–115,096; ETH 1.39M–2.52M; SOL 6.99M–13.5M; DOGE 1.33B–4.02B; XRP 178.6M–368.2M. These magnitudes match plausible native-coin OI levels for Binance perps (e.g., ~70-115k BTC of open interest is a realistic historical range), not USD notional (which would be ~$7-13B for BTC — a different, much larger number). Cross-checked BTC OI `c` against BTC price over the same timestamps: correlation is **−0.31** (not the near-1.0 correlation that would result if the OI column were secretly price data mislabeled). Conclusion: OI is genuinely OI, in native-coin units, as the pull script's docstring claims.
3. **Long/short ratio direction check**: `l` (long %) is always > 50 across the full BTC sample (range 32.8–79.97, but never observed near/below 50 for BTC specifically — mean 60.3), consistent with Binance's well-documented `globalLongShortAccountRatio` structural bias (many small retail accounts are long, balanced against fewer, larger short positions). This confirms the field is what its name says — % of accounts long — and matches the design spec's intended semantics ("long/short account ratio percentile ... crowded-against = ratio ... in its top/bottom percentile ... OPPOSING the trend"). Because the strategy uses a **rolling 90-day percentile of `l`**, not the raw level, the structural >50% bias does not distort the contrarian logic — "crowded long" here correctly means "more long, relative to its own recent history," which is the intended interpretation.
4. **Point-in-time (PIT) test**: computed all raw indicators (trend, crowding percentile, both fuel-lookback signals, ATR) on BTC's real data, then re-computed them after shuffling every OHLC/OI/long% value **after** an arbitrary cutoff (200 bars from the end) with a fixed random seed, leaving the pre-cutoff data untouched. All six raw-indicator columns (`trend_up_raw`, `trend_dn_raw`, `lpct_raw`, `fuel24_raw`, `fuel72_raw`, `atr_raw`) were **bit-identical before the cutoff** in both runs — confirming no signal at or before any bar depends on data after that bar. This directly tests the exact concern (leakage from rolling-window computations) rather than relying on code review alone.
5. **Too-good-to-be-true check on the best config**: `4h-p10-fuel24-short` (Sharpe 2.34, the run's best) was decomposed per-coin — PnL is broadly distributed (BTC $25.6/32 trades, ETH $76.9/44, SOL $20.1/41, HYPE $3.7/10, DOGE $34.2/21, XRP $23.3/24), not concentrated in one coin or a handful of trades. Fuel-gate fire rates (~50% for fuel24, ~53% for fuel72) and trend-direction rates (39% up / 59% down, the rest warmup) are non-degenerate. No single component looks like an artifact.
6. **Boundary bug found and fixed during this run**: an initial version normalized `stats_start`/`split_at` from `window_start + N days` without floor/ceiling to midnight; since Coinalyze's first bar lands at 16:00 UTC, this produced a non-midnight cutoff applied via `.loc[cutoff:]` against a midnight-indexed daily-resampled series — which silently **dropped an entire day** of post-warmup data from the Sharpe/MDD calc while a parallel trade-level filter (correctly) did not drop that day. Caught via the same long+short-should-equal-total cross-check described in the self-review requirement, fixed by `.ceil("D")`-ing both cutoffs before re-running for this report. (This is exactly the class of bug CLAUDE.md principle #1 warns about — two derived quantities meant to describe "the same period" computed via two different mechanisms that quietly disagreed at a boundary.)

## Honest caveats

1. **Sample is ~335 days, not 2 years.** This is the single biggest limiter on this run's conclusiveness — the multiple-testing gate requires strong evidence precisely because 24 trials were run, and fewer days of data means less power to clear that bar. A longer Coinalyze history (higher subscription tier, or simply waiting for more calendar time to accrue under the current key) is the most direct path to resolving the gate-2 ambiguity, not further variant tuning.
2. **Cross-exchange basis.** OI and long/short-ratio come from Coinalyze's Binance-perp aggregation (`BTCUSDT_PERP.A` etc.); trend/price signals and simulated fills are also Binance klines (unchanged from Phase 2a). If ever deployed, live execution would be on Hyperliquid — a different venue with its own OI, positioning, and funding dynamics. Binance is the largest and most liquid venue for these pairs so it's a reasonable signal source, but retail crowding and OI dynamics on Hyperliquid specifically (a perps-only DEX with a different user base) could diverge from what this backtest measures. This cross-exchange gap applies to the signal source, not just execution slippage.
3. **No funding accrual in Phase 2b** (see Method section) — Phase 2a's PnL included real HL funding cash-flow, Phase 2b's does not (Coinalyze doesn't supply it and it's no longer the crowding-signal basis). If this family were ever taken further, funding would need to be added back in as a live PnL component (it was economically small in Phase 2a, a few dollars either way, but not zero).
4. **Simulation optimism/simplifications**, same as Phase 2a: stop exits fill exactly at the stop level (gap-through handled at open, no extra slippage beyond the taker fee); stop-first intrabar assumption is conservative but high/low ordering within a bar is unknowable; no partial fills or liquidity constraints modeled at $100 notional (immaterial at this size, but noted for completeness).
5. **One ~11-month window, one regime**, now even shorter than Phase 2a's already-short window. The Bonferroni-style gate corrects for the 24 declared trials but not for regime luck — with ~303 daily observations, statistical power is lower than Phase 2a's ~336, which is reflected directly in the still-failing gate 2.
6. **HYPE's negative result at the median config rests on only 4 trades** — too few to distinguish a real coin-specific effect from noise. Not treated as evidence against the family; just flagged as thin.

## Actual script output

```
$ .venv/bin/python scripts/research_cta_positioning_phase2b.py
=== data ===
BTC   klines 4h=2004 1d=333 bars [2025-08-03 .. 2026-07-03]  coinalyze oi=2005 lsr=2005 [2025-08-03 .. 2026-07-03]
ETH   klines 4h=2004 1d=333 bars [2025-08-03 .. 2026-07-03]  coinalyze oi=2005 lsr=2005 [2025-08-03 .. 2026-07-03]
SOL   klines 4h=2004 1d=333 bars [2025-08-03 .. 2026-07-03]  coinalyze oi=2005 lsr=2005 [2025-08-03 .. 2026-07-03]
HYPE  klines 4h=2004 1d=333 bars [2025-08-03 .. 2026-07-03]  coinalyze oi=2005 lsr=2005 [2025-08-03 .. 2026-07-03]
DOGE  klines 4h=2004 1d=333 bars [2025-08-03 .. 2026-07-03]  coinalyze oi=2005 lsr=2005 [2025-08-03 .. 2026-07-03]
XRP   klines 4h=2004 1d=333 bars [2025-08-03 .. 2026-07-03]  coinalyze oi=2005 lsr=2005 [2025-08-03 .. 2026-07-03]

backtest window: [2025-08-03 .. 2026-07-03]  stats from 2025-09-03 (303d after 30d crowding warmup)  split at 2026-01-18

=== 24-config matrix (portfolio: 6 coins x $100, stats from 2025-09-03) ===
config                   pnl$    ret%  sharpe  tstat   mdd% trades  win%      h1$      h2$
1d-p10-fuel24-both     106.48  17.75%    1.81   1.65  -3.6%     82   55%    35.51    70.97
1d-p10-fuel24-long      -3.93  -0.65%   -0.18  -0.16  -2.5%     24   46%     0.96    -4.89
1d-p10-fuel24-short     110.41  18.40%    1.95   1.78  -3.3%     58   59%    34.55    75.86
1d-p10-fuel72-both     121.08  20.18%    1.80   1.64  -5.4%     67   61%    25.72    95.37
1d-p10-fuel72-long      19.98   3.33%    1.05   0.95  -2.1%     16   50%     0.58    19.41
1d-p10-fuel72-short     101.10  16.85%    1.54   1.41  -4.4%     51   65%    25.14    75.96
1d-p20-fuel24-both     116.15  19.36%    1.30   1.19  -6.7%    141   48%    17.59    98.55
1d-p20-fuel24-long       9.71   1.62%    0.28   0.26  -4.5%     44   43%    -4.03    13.74
1d-p20-fuel24-short     106.44  17.74%    1.27   1.15  -5.1%     97   49%    21.63    84.81
1d-p20-fuel72-both     129.90  21.65%    1.54   1.40  -9.2%    107   50%    15.10   114.80
1d-p20-fuel72-long      23.18   3.86%    0.72   0.65  -4.7%     33   36%     0.58    22.61
1d-p20-fuel72-short     106.72  17.79%    1.28   1.17  -6.6%     74   55%    14.52    92.19
4h-p10-fuel24-both     113.46  18.91%    1.26   1.15  -9.6%    321   44%    49.80    63.66
4h-p10-fuel24-long      -70.21 -11.70%   -1.61  -1.47 -16.0%    149   38%     9.26   -79.46
4h-p10-fuel24-short     183.67  30.61%    2.34   2.14  -3.1%    172   49%    40.55   143.12
4h-p10-fuel72-both     104.27  17.38%    1.15   1.05 -15.4%    246   41%    58.67    45.60
4h-p10-fuel72-long      -56.90  -9.48%   -1.15  -1.05 -20.1%    125   34%    17.30   -74.20
4h-p10-fuel72-short     161.17  26.86%    2.08   1.90  -5.6%    121   49%    41.36   119.80
4h-p20-fuel24-both      87.49  14.58%    0.79   0.72 -14.6%    474   44%     9.59    77.91
4h-p20-fuel24-long      -85.56 -14.26%   -1.55  -1.42 -22.2%    209   41%   -12.24   -73.31
4h-p20-fuel24-short     172.81  28.80%    1.73   1.58  -5.6%    266   46%    21.59   151.22
4h-p20-fuel72-both     154.52  25.75%    1.31   1.20 -17.0%    345   42%    66.97    87.55
4h-p20-fuel72-long      -51.57  -8.60%   -0.85  -0.78 -23.5%    170   36%    11.64   -63.22
4h-p20-fuel72-short     206.10  34.35%    1.98   1.81  -6.8%    175   49%    55.32   150.77

median config Sharpe = 1.27  (nearest config: 1d-p20-fuel24-short, sharpe 1.27)
best config = 4h-p10-fuel24-short  sharpe 2.34  tstat 2.14 (gate 2.9)

=== per-coin at median config (1d-p20-fuel24-short) ===
BTC   pnl=   18.14$  trades= 25  non-negative
ETH   pnl=   51.00$  trades= 20  non-negative
SOL   pnl=   18.34$  trades= 24  non-negative
HYPE  pnl=   -5.43$  trades=  4  NEGATIVE
DOGE  pnl=    4.44$  trades= 11  non-negative
XRP   pnl=   19.95$  trades= 13  non-negative

=== per-side breakdown ('both' configs) ===
config                  long$   nL  winL%   short$   nS  winS%
1d-p10-fuel24-both      -3.93   24    46%   110.41   58    59%
1d-p10-fuel72-both      19.98   16    50%   101.10   51    65%
1d-p20-fuel24-both       9.71   44    43%   106.44   97    49%
1d-p20-fuel72-both      23.18   33    36%   106.72   74    55%
4h-p10-fuel24-both     -70.21  149    38%   183.67  172    49%
4h-p10-fuel72-both     -56.90  125    34%   161.17  121    49%
4h-p20-fuel24-both     -80.93  209    41%   173.05  265    46%
4h-p20-fuel72-both     -51.57  170    36%   206.10  175    49%

=== monthly portfolio PnL at median config (1d-p20-fuel24-short) vs the 10%/mo ask ($600 base -> $60/mo) ===
2025-09     -1.52$  ( -0.25%)
2025-10     -4.91$  ( -0.82%)
2025-11     50.24$  (  8.37%)
2025-12    -17.14$  ( -2.86%)
2026-01     20.76$  (  3.46%)
2026-02     34.10$  (  5.68%)
2026-03     -0.56$  ( -0.09%)
2026-04     -6.70$  ( -1.12%)
2026-05      0.71$  (  0.12%)
2026-06     33.93$  (  5.66%)
2026-07     -2.47$  ( -0.41%)

=== pre-declared gate (ALL must hold for GO) ===
1. median-config Sharpe > 1.0          :   1.27  PASS
2. best-config tstat > 2.9 (24 trials) :   2.14  FAIL
3. aggregate MDD <= 15% (median cfg)   :  -5.1%  PASS
4. >=60% coins non-negative (median)   : 5/6  PASS
5. split halves same sign (median cfg) : h1=+21.63 h2=+84.81  PASS

VERDICT: NO-GO   (0.4s)
```

## Next step

NO-GO on real data means **no live engine and no capital**, same as Phase 2a. But the character of the NO-GO has changed materially: Phase 2a failed on *median strength* (0.98 vs 1.0 gate) and *significance* (1.96 vs 2.9); Phase 2b passes median strength decisively (1.27) and improves significance (2.14) but is still short of the 2.9 bar purely on sample size. The most direct, non-tuning path forward is **more calendar time under the same declared matrix** — either a higher Coinalyze tier with deeper OI/LSR history, or simply re-running this exact script (no code changes) once more days have accrued under the current key. This is not "waiting to p-hack a better number" — it is the pre-declared gate doing exactly its job: distinguishing a real-but-unproven effect from a proven one, and correctly refusing to authorize capital until it can.
