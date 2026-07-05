# Overnight execution state — recovery doc

## FINAL STATUS 04:15 — BUILD COMPLETE, DAEMON LIVE
All packages done. 53 tests green. Review findings F2/F3/F5/F6/F7/F8 fixed;
F1 (orphan-offer adoption) + F4 (fill-misattribution reconciliation) + candle
local cache deferred to pre-scale-up (documented in morning report §7).
Live churn bug found in live test and fixed (strategy sizes on deployable).
Live daemon running (pid in `pgrep -f run_engine`), 2 probe offers active.
Deliverables: reports/morning_report.md (user-facing), README.md,
docs/deploy-lightsail.md, reports/backtest_verdict.md (causal p30 numbers:
train 12.5%, OOS 9.7%). User decisions pending: migration ladder (report §6).

Updated 2026-07-05 ~00:35. If the session dies, resume from here.
API session limit hit ~00:30, resets 03:20 Asia/Taipei. No subagents until then.

## Done
- Skeleton, venv (py3.9), pytest green (9 tests: rates/config).
- docs/architecture.md (incl. coexistence: engine owns only its offer ids, NEVER
  cancel-all; capital_budget=328). docs/backtest-design.md (fill model honesty rules).
- docs/bitfinex-api-reference.md — complete, live-verified. KEY FACTS: auth =
  HMAC-SHA384 of `/api/v2/{endpoint}{nonce}{rawBody}` hex, headers bfx-nonce/apikey/
  signature, nonce microseconds monotonic; rates everywhere are DAILY decimals except
  funding-stats FRR = FRR/365; book: amount>0 = lender ask; min offer 150 USD;
  period 2..120 int; fee 15% (hidden 18%); submit uses fUSD, cancel-all/ledgers use
  USD; don't branch on notification TYPE, use STATUS field.
- docs/strategy-research.md — complete. KEY: ladder 3-7 rungs anchored to FRR/book;
  term thresholds (30d ≈ +2.2pp median premium; spikes: crash-day avg 153% APR decays
  to 46% next day → must pre-place high-rate long-period offers); pure FRR earns only
  6-8% recently; no daily predictability vs BTC returns (corr≈0), only tail events;
  12% is conditionally feasible, stress-test on 2024-2026 not 2020-2021.
- data/ ALL FETCHED: candles_1D_p2.csv (3618 rows, 2016-07-31→2026-07-04),
  candles_1D_p30.csv, candles_1h_p2.csv (48235 rows, 2021→now), funding_stats.csv
  (83910 rows), book+ticker snapshots. scripts/fetch_history.py works.
- .env in place; key VERIFIED read-only (wallets ok). funding USD total 4340.85,
  available 328.68 — delta ≈4012 is legacy-bot money, DO NOT TOUCH.
- User authorization: live test ≤300 USD/offer, period 2d, ≤2 concurrent; max period
  120d when rates high; 250k migration decision reserved for user.

## In progress
- src/compound/bfx/models.py exists from killed agent — VERIFY before trusting.

## DONE before reset (main loop, ~01:30)
- Backtest COMPLETE: src/compound/backtest/{data,sim,strategies}.py, 18 tests green.
  Dual-market fill model (2d offers fill vs hourly p2; 30/120d offers fill vs daily
  p30 broadcast to hours). Metrics on EQUITY basis (initial-capital denominator bug
  found & fixed — compounding inflated old numbers).
- Grid run: scripts/run_backtest.py → reports/backtest_verdict.md.
  WINNER params: short=[(q0.3,w2),(q0.6,w1)] period2; term=[(q0.5,w3),(q0.8,w2)]
  period30 priced off p30 highs, floor 7% APR; spike=fixed APR rungs
  [20%,40%,80%] each w1.0, period 120. rebalance 4h.
  Numbers: full-history base 12.5-13.1%, OOS 2025-26 ~10.1%, pessimistic full ~10.6%.
  Baseline always-close = 4.8%. Term premium (p30-p2 close) 2024+: median +2.8pp.
  12% verdict: conditional — needs spike years or unmodeled taker/FRR upside.

## TODO after 03:20 reset (re-dispatch agents)
1. Package A finish: bfx transport/boundary/public/private + tests + smoke
   (models.py DONE & reviewed). Agent must read docs/bitfinex-api-reference.md +
   architecture.md; original full prompt spec is in the killed agent's task, rewrite
   from those docs. Python 3.9. requests only in transport.py.
2. Package C: engine. Key specs: strategy/ladder.py = production port of
   backtest ladder3 with winner params (from MarketState rolling window of
   recent rates — engine journals hourly highs itself or refetches candles);
   engine/{state,reconcile,loop,journal}. Reconcile: engine owns ONLY offer ids
   it placed (journal), never cancel-all; tolerance band (skip re-place if rate
   within 5%); mutation cap per tick; capital_budget enforcement; identity check
   wallet vs available+own_offers(+own credits) alert >$1 discrepancy.
   live_test_mode SPECIAL: strategy replaced by two-offer probe (one at short
   q0.3 to verify fill path, one at q0.9 to verify management), period clamp 2d,
   amount ≤300, ≤2 concurrent. run_engine.py --dry-run|--live --once|--daemon.
3. Live validation: read-only reconcile → ≥2 dry-run ticks sane → live probe.
4. Fresh review (independent agent) of bfx+engine before --live. Then live test.
5. Deliverables: README, Lightsail deploy notes, reports/morning_report.md (zh-TW):
   backtest verdict incl. honest 12% assessment, live test evidence, 250k migration
   plan (gradual: 328 → 5k → 25k → full, gated on realized-vs-model tracking),
   next-phase roadmap (taker module for rich long bids, FRR-delta offers, alerting).

## Notes
- Timezone: user sleeps ~00:00-08:00 Asia/Taipei. Morning report by ~07:30.
- Main-loop may hand-write light modules but should re-delegate heavy work post-reset.
