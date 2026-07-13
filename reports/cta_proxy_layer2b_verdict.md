# CTA Positioning (Sub-project G) — Layer-2b: Binance-only Proxy Regime Study

**Date:** 2026-07-06 · **Status: PROXY RESEARCH, not a GO/NO-GO input.** This layer exists to
probe **regime robustness** of the strategy *structure* (trend + crowd-fade + fuel) across
multiple BTC cycles, using a free, Binance-only, no-key, live-computable crowd/fuel proxy that
stands in for the real ~11-month Coinalyze crowd signal (`reports/cta-phase2b-verdict.md`), which
is structurally too short to see more than one regime. **It does not validate the live crowd
signal itself** — Phase 2b (real data, NO-GO) remains the binding verdict on that question.

**Scripts:** `scripts/cta_proxy_pull_data.py` (data), `scripts/cta_proxy_lib.py` (shared engine,
reuses `research_cta_positioning_phase2b.py`'s `simulate()`/exit logic unchanged),
`scripts/cta_proxy_validate.py` (Part 1 gate), `scripts/cta_proxy_multiyear.py` (Part 2 study).
**Cache:** `data/cache/cta_proxy/` (Binance public endpoints only, no key, no `.env` touched).

## Method

Same simulation core as Phase 2b: EMA20/50 trend on closed bars, 2×ATR(14) hard stop, 14-day
max hold, trend-flip/fuel-fail exits, $100 notional/coin, 0.045%/side fee, one position per
coin, shift-by-one-bar point-in-time discipline (re-verified here with a fresh synthetic-shuffle
test — perturbing all data after an arbitrary cutoff left every raw indicator bit-identical
before the cutoff, same method Phase 2b used). Two inputs are swapped for **Binance-only, free,
no-key proxies**:

- **Crowd** (was: Coinalyze account-ratio `l`) → **Binance perpetual funding rate**
  (`fapi/v1/fundingRate`), mean-resampled to the trend TF, rolling trailing-90d percentile
  (30d warmup) — identical percentile mechanics, different source. This is a re-test of
  Phase-2a's own funding-proxy hypothesis, but sourced from **Binance** funding (public, no key)
  rather than Phase-2a's Hyperliquid funding.
- **Fuel** (was: Coinalyze real open interest) → **Binance quote-volume, 24h-sum vs prior 24h**
  — Phase-2a's already-declared "vol" fuel proxy. Binance's own OI history endpoint
  (`futures/data/openInterestHist`) is **hard-capped to ~30 days regardless of `startTime`**
  (re-confirmed empirically for all 6 symbols by `cta_proxy_pull_data.py`, matching
  `reports/cta-data-feasibility.md`), so it cannot serve a multi-year study — volume is the only
  Binance series with genuine multi-year depth.

## Part 1 — Overlap validation gate: **PASS**

Ran the production-equivalent config (4h, crowd-percentile 10, fuel 24h) on the proxy engine,
restricted to the **exact same window** Phase 2b used (`[2025-08-03 .. 2026-07-03]`, re-derived
from the live Coinalyze cache, not hardcoded), and compared direction against the published
real-crowd result (`reports/cta-phase2b-verdict.md`, `scripts/research_cta_crowd_ablation.py`).

| cell | proxy Sharpe | real Sharpe (cited) | proxy MDD | real MDD (cited) |
|---|---:|---:|---:|---:|
| short/crowd-ON | 1.25 | 2.34 | −9.2% | −3.1% |
| short/crowd-OFF | 0.35 | n/a | −22.1% | −14.4% |
| long/crowd-ON | −1.69 | −1.61 | −10.1% | −16.0% |
| long/crowd-OFF | −0.74 | n/a | −19.9% | −26.0% |

Pre-declared directional gates (all three had to hold):

1. Proxy short/crowd-ON profitable (Sharpe > 0): **1.25 — PASS**
2. Proxy short/crowd-ON beats long/crowd-ON (Sharpe and MDD): 1.25 vs −1.69 Sharpe, −9.2% vs
   −10.1% MDD — **PASS**
3. Crowd-OFF MDD meaningfully worse than crowd-ON on the short side (≥1.5× bar, pre-declared
   before running; real data showed ~4.6×): ratio **2.40× — PASS**

All weaker in magnitude than the real signal (expected — funding is a noisier proxy for
positioning than an actual account-ratio), but every direction matches. **Gate: PASS → proceed
to the multi-year run.** Full 4h/1d × p10/p20 × fuel24/72 sweep: `/private/tmp/claude-501/-Users-jim-projects-vault/0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/cta_proxy_validate_full_sweep.txt`.

**Caveat on this gate itself:** the proxy's crowd percentile draws on Binance funding history
going back to each coin's 2019/2020 listing, i.e. a far longer warmup runway than the real LSR
signal ever had (Coinalyze only existed for this key from 2025-08). This is flagged, not hidden
— it's a genuine structural advantage a live proxy deployment could also exploit, but it means
the two signals are not on a perfectly level footing even within the "same window."

## Part 2 — Multi-year cross-cycle study

**Universe:** BTC, ETH, SOL, DOGE, XRP (5 coins). **HYPE excluded** — Binance HYPEUSDT perp only
listed 2025-05-30 (~13 months), too short for any cross-cycle claim.
**Window:** `[2020-09-14 .. 2026-07-05]` (SOL's Binance listing is the binding constraint across
the 5 coins), stats from 2020-10-15 after 30d crowd warmup — **≈5.7 years**, spanning the 2020-21
bull, 2022 bear, 2023 recovery, 2024 bull, and 2025-26 (the real-crowd window).
Full table: `/private/tmp/claude-501/-Users-jim-projects-vault/0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/cta_proxy_multiyear_full.txt`.

### Headline full-period cells (4h-p10-fuel24)

| cell | Sharpe | MDD | PnL $ | trades | win% |
|---|---:|---:|---:|---:|---:|
| short/crowd-ON | 0.35 | **−32.2%** | 119.84 | 762 | 48% |
| short/crowd-OFF | −0.62 | −148.2%¹ | −645.94 | 3014 | 43% |
| long/crowd-ON | 0.62 | −11.4% | 206.99 | 343 | 49% |
| long/crowd-OFF | 0.90 | −25.9% | 1008.09 | 2920 | 45% |

¹ Below −100% because this engine uses **fixed $100/coin notional, not compounding equity** — a
real leveraged account would be liquidated well before a nominal drawdown reaches −100%; treat
this number as "catastrophically worse," not a literally realizable percentage. This artifact
only becomes visible over the long window (the ~11-month real-crowd sample never crossed −100%,
its worst crowd-off MDD was −26.0%).

**Full-period worst MDD, deployed-equivalent config (short/crowd-ON): −32.2%.** This is roughly
**10× worse** than the −3.1% the ~11-month real-crowd sample showed — the single most important
honest finding of this layer: an 11-month sample structurally cannot see the drawdown a 5.7-year
sample reveals. **−32.2% (or −148.2% if the crowd filter were ever dropped) is the leverage
anchor this layer supports, not −3.1%.**

### Does the edge hold across cycles? No — it is regime-conditional, not persistent

| year | short/ON Sharpe | long/ON Sharpe | which side wins | BTC regime that year |
|---|---:|---:|---|---|
| 2020 | −1.07 | **4.40** | long | recovery → bull |
| 2021 | −1.98 | 0.42 | long (short loses badly) | bull |
| 2022 | **1.27** | −0.23 | short | bear |
| 2023 | −0.08 | **1.67** | long | recovery |
| 2024 | −0.35 | **1.25** | long | bull |
| 2025 | **1.97** | 0.99 | short | (real-crowd window) |
| 2026 (partial) | **1.24** | −1.86 | short | (real-crowd window) |

The short-crowd-fade dominance that Phase 2b's ~11-month real-crowd sample showed so cleanly
(short Sharpe 2.34, long dead/negative) **only shows up as a persistent pattern in 2025-26 —
the exact window that sample covers.** Across the full cycle, the winning side flips: long wins
2020/2021/2023/2024 (bull/recovery years), short wins 2022/2025/2026 (bear/choppy years). The
"long is dead weight" finding from Phase 2a/2b is **not** a cross-cycle property of this proxy
structure — it is specific to the regime the real-crowd data happened to be sampled in. This is
the central, honest counter-evidence this layer was built to surface.

### Does the crowd filter's value hold across cycles? Partially — robust for MDD, not for Sharpe/PnL

Crowd filter **reduced MDD in 7/7 years (100%) on the short side**, and (checked in the full
table) in all 7 years on the long side too — this part **is** a robust, cross-cycle property:
the filter is a genuine risk-reducer regardless of side or regime.

```
2020: ON  -6.9%  OFF -12.5%   2021: ON -22.2%  OFF -99.8%   2022: ON  -8.4%  OFF -31.9%
2023: ON  -9.7%  OFF -13.8%   2024: ON  -8.2%  OFF -39.4%   2025: ON  -2.4%  OFF -22.1%
2026: ON  -2.0%  OFF -27.1%
```

But the filter's effect on **return** is side-dependent: on the short side it also improves
Sharpe in 5/7 years (2022/2023/2024/2025/2026) — a genuine value-add, not just risk reduction.
On the **long side**, the filter consistently **cuts participation and gives up large upside**
in bull years (e.g. 2020: ON $38.86 vs OFF $168.08; 2024: ON $58.03 vs OFF $381.76) — there, the
filter trades return for lower risk rather than adding value outright. Phase 2b's ~11-month
window never surfaced this trade-off because the long side was net-negative in that window
either way.

### Regime decomposition (BTC 200DMA risk-on/off, 30-day realized-vol tercile)

Trade-level only (non-contiguous buckets — valid for PnL/PF, not MDD):

- **Short/crowd-ON**: profitable in risk-off (PF 1.48, PnL +$183.69) but a small loser in
  risk-on (PF 0.87, PnL −$63.85) — consistent with a bear/chop-favoring signal.
- **Long/crowd-ON**: the mirror image — profitable in risk-on (PF 1.72, PnL +$217.98), a small
  loser in risk-off (PF 0.93, PnL −$10.99).
- By volatility tercile, **crowd-ON short's edge is concentrated in low/mid vol** (PF 1.33/1.71)
  and **inverts in high vol** (PF 0.60, PnL −$136.49) — the crowd-fade thesis breaks down exactly
  when volatility (and presumably crowding itself) is most extreme, an honest limitation worth
  flagging for any future sizing logic.

Full regime tables: same scratchpad file as above.

## Honest limits of this proxy layer (read before using any number above for a leverage or sizing decision)

1. **Funding ≠ positioning.** Funding is the *price* of a positioning imbalance, not a headcount
   of accounts; it can diverge from true crowding (whale-driven funding without retail crowding),
   same caveat Phase 2a already carried. This layer's PASS in Part 1 shows the funding proxy is
   *directionally* informative in the one window we can check against real data — it is not
   proof the proxy tracks true crowding well in years we cannot check.
2. **Volume ≠ open interest.** Volume rises during both accumulation and liquidation cascades;
   real OI would separate them. Binance's own OI history is capped at ~30 days for everyone,
   confirmed here again — there is no way to check the volume-fuel proxy against real OI outside
   the ~11-month Coinalyze window either.
3. **HYPE excluded from the multi-year study entirely** (listed 2025-05-30) — all multi-year
   conclusions are BTC/ETH/SOL/DOGE/XRP only.
4. **Fixed-notional, non-compounding engine.** Inherited from Phase 2a/2b unchanged; produces the
   −148.2% "MDD" artifact noted above. A compounding/leverage-aware engine would show a smaller
   nominal number but the qualitative message (crowd-off is far worse, deployed-equivalent MDD
   is far worse than the 11-month sample suggested) would not change.
5. **This is not a re-validation of the live crowd signal.** Phase 2b (real Coinalyze data,
   NO-GO, `reports/cta-phase2b-verdict.md`) remains the binding verdict on whether to deploy
   capital. This layer's contribution is purely about regime context: the short-side dominance
   Phase 2b measured is regime-specific (2025-26), not a persistent cross-cycle property, and the
   honest full-period MDD anchor for any future leverage conversation is ~−32%, not ~−3-5%.
6. **One proxy engine, one specification.** Only the production-equivalent config
   (4h-p10-fuel24) was run for the multi-year study (Part 1's sweep covered more cells in the
   overlap window only) — this is a single-configuration cross-cycle probe, not a re-run of the
   full 24-config multiple-testing matrix over multi-year data.

## Files

- `scripts/cta_proxy_pull_data.py` — Binance-only data puller (klines, funding, OI-diagnostic).
- `scripts/cta_proxy_lib.py` — shared engine (funding-percentile crowd + volume fuel; reuses
  `research_cta_positioning_phase2b.py`'s `simulate()` unmodified).
- `scripts/cta_proxy_validate.py` — Part 1 overlap gate (PASS).
- `scripts/cta_proxy_multiyear.py` — Part 2 multi-year study.
- `data/cache/cta_proxy/` — cached klines/funding/OI-diagnostic parquet (Binance, no key).
- Scratchpad detail tables: `cta_proxy_validate_full_sweep.txt`,
  `cta_proxy_multiyear_full.txt`, `cta_proxy_multiyear_summary.json` (all under
  `/private/tmp/claude-501/-Users-jim-projects-vault/0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad/`).
