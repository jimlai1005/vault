# Sub-project G — CTA Positioning Strategy Research (OI + crowding + trend)

**Date:** 2026-07-03 · **Status:** research phase approved (Claude as decider)
**Owner ask:** contrarian-retail + trend + OI-momentum CTA; both directions with
per-side enable switches; "fix reasonably if data is ugly"; target 10%+/mo.

## Honest framing (binding)
10%/mo = ~214%/yr. Treated as an aspirational ceiling under hard risk gates,
not a promise. "Reasonable fixing" is implemented as a PRE-DECLARED variant
matrix tested once with multiple-testing correction — never post-hoc tuning.

## Strategy family (hypothesis, pre-declared)
- **Trend layer:** EMA20 vs EMA50 on {4h, 1d}. Direction = sign(EMA20−EMA50).
- **Crowding layer (contrarian):** retail positioning against the trend.
  Sources: long/short account ratio percentile (preferred) or funding-rate
  percentile (proxy; already have 12mo HL funding cached).
  Crowded-against = ratio/funding in its top/bottom {20%, 10%} percentile
  (rolling 90d) OPPOSING the trend direction.
- **Fuel gate:** OI change over {24h, 72h} > 0 (rising interest).
- **Entry:** trend short + retail crowded long + OI rising → SHORT (and mirrored
  for LONG). **Exit:** OI momentum < 0, or trend flips, or hard stop
  (2×ATR(14) on the entry timeframe), or 14d max hold.
- **Side switches:** variants long-only / short-only / both — kept as first-class
  configs per owner's design (asymmetry is real: momentum diagnosis showed
  longs +$1.7k / shorts −$3.2k).
- Universe: BTC, ETH, SOL, HYPE (+DOGE, XRP if data allows).

## Variant matrix (the ONLY knobs; all tested, corrected, once)
trend TF {4h, 1d} × crowding pctile {10, 20} × OI lookback {24h, 72h} ×
side {long, short, both} = 24 configs per coin.

## Pre-declared gate (all must hold for GO)
- Walk-forward OOS (quarterly refit): median-config OOS Sharpe > 1.0 AND the
  BEST config's deflated-Sharpe-style multiple-testing check (against 24
  trials) still > 0.
- Aggregate MDD ≤ 15%; per-side breakdown reported; a side may be disabled
  ONLY if the variant matrix already showed it (declared switch, not tuning).
- ≥ 60% of coins non-negative under the median config.
- Monthly return distribution reported honestly vs the 10%/mo ask.

## Phase 1 — data feasibility (now)
Probe real availability: Binance futures free endpoints (klines: years;
openInterestHist + top/globalLongShortAccountRatio: ~30d only), Coinalyze
(needs free API key — owner asked to register), HL funding (12mo cached).
Decision after probe: full backtest on the longest-history source; Binance
30d used only for signal-shape sanity, never validation.

## Phase 2 — backtest + verdict (after data secured)
Walk-forward engine reusing repo conventions; verdict report with the gate
checklist; GO → live engine build (hlvault.cta) with the standard safety
family; NO-GO → document and stop.

## Capital note
Deployment (if GO) needs fresh capital or reallocation — owner decision at
verdict time.

## Phase 2a amendment (pre-declared 2026-07-03, before any backtest ran)
Probe confirmed Binance OI/ratio history = ~30d only (validation-inadequate);
Coinalyze key pending from owner. Phase 2a therefore tests the strategy family
with declared proxies on 12mo data: crowding = HL funding-rate percentile
(rolling 90d) — funding IS the price of positioning imbalance; fuel gate ∈
{none, volume-change>0 over lookback} replacing OI (volume from klines, years
of depth). Variant matrix stays 24: trend TF {4h,1d} × crowding pctile {10,20}
× fuel {none, volume-24h} × side {long, short, both}. Same gate. When the
Coinalyze key arrives, Phase 2b re-runs the SAME matrix with true OI +
account-ratio data as confirmation — 2a survivors must survive 2b too.
