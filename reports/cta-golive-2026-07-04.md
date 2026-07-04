# CTA Forward-Test Go-Live — 2026-07-04 17:41

**Wallet:** ex-carry `0xbAC6...3662`, equity $998.30 at bootstrap.
**Config:** short-only (ENABLE_LONG=false per phase-2b evidence), 4h-p10-fuel24,
$100/trade, 6-coin universe, 20% MDD breaker, 5-min breaker cadence, 4h rebalance.

**Carry retirement (same wallet, 22.5h live):** entered 07-03 15:52 @ $999.35
(post-fix basis), funding received +$0.179 (≈10.9% APR — matches research),
delta never exceeded -$0.45, zero halts. Teardown via the engine's own tested
flatten: $999.51 → $998.57 (cost $0.94). Residual $0.27 HYPE dust (sub-min,
untradeable, excluded from CTA equity basis — conservative direction).
Carry code stays dormant in-repo; this 22.5h run validates the mechanism for
future scaled redeployment.

**Go-live gates passed:** 215 tests; signal-parity suite (live==backtest per
bar on 4 fixtures + 6-way mutation-injection audit all caught + config pinned
to backtested values); opus holistic review incl. independent on-chain equity
verification (identity exact to the cent); wallet verified pure-USDC (F2);
state cleared between dry-run and live (F3); first live cycle observable and
hand-verified correct (all flat; DOGE closest to a short setup — downtrend +
fuel, crowd 71.9 < 90 threshold).

**Honest status:** this deploys an in-sample-best config that FAILED its
multiple-testing gate (t=2.14 < 2.9) — a deliberate owner decision to buy
~6 months of true out-of-sample evidence with a $1,000 cap and hard breakers,
NOT a validated edge. Verdict reference: reports/cta-phase2b-verdict.md.

**Portfolio now:** gridbot $1,018.91 (restarted 17:36 after silent process
death ~17:25 — cause unknown, exchange-side orders were resting unattended
~10min; state reconciliation clean) + CTA $998.30. Both on 20% breakers.
