# Backtest verdict — Bitfinex fUSD lending ladder

Generated 2026-07-04 20:12 UTC by scripts/run_backtest.py. Fill model & honesty rules:
docs/backtest-design.md. Data: 1h p2 candles 2021→now + daily p30 candles
(term/spike tranches price AND fill against the 30d-period market).

## Winner: `T-A/S-02-04-08/l7`

Short tranche [(0.3, 2), (0.6, 1)] (2d) / term [(0.5, 3), (0.8, 2)] (30d) / spike S-02-04-08 @120d, lock30 floor 0.07 APR.

| metric | pessimistic | base | optimistic |
|---|---|---|---|
| net APR (full 2021-now) | 10.76% | 11.68% | 12.98% |
| utilization | 77.56% | 82.72% | 89.08% |
| worst rolling 90d | 2.19% | 4.67% | 6.46% |
| avg lock (amount-wtd) | 12d | 11d | 11d |

Yearly net APR (base fill): {2021: 13.6, 2022: 11.2, 2023: 15.3, 2024: 10.3, 2025: 10.8, 2026: 8.8}
Yearly net APR (pessimistic): {2021: 11.6, 2022: 10.1, 2023: 14.7, 2024: 9.2, 2025: 10.5, 2026: 7.7}

Baseline B1 (always lend at close, 2d): net APR 4.82% — the ladder's edge is +6.9pp.

## Train (2021-2024) vs OOS (2025-now), base fill, all combos

| combo | train | OOS |
|---|---|---|
| T-C/S-02-04-08/l7 | 12.61% | 9.31% |
| T-C/S-02-04-08/l5 | 12.56% | 9.31% |
| T-A/S-02-04-08/l7 | 12.50% | 9.72% | ← winner
| T-A/S-02-04-08/l5 | 12.34% | 9.72% |
| T-A/S-025-05-10/l7 | 12.23% | 9.45% |
| T-A/S-025-05-10/l5 | 12.06% | 9.45% |
| T-A/S-03-06/l7 | 11.97% | 9.50% |
| T-A/S-03-06/l5 | 11.82% | 9.50% |
| T-C/S-03-06/l7 | 11.71% | 9.22% |
| T-C/S-03-06/l5 | 11.66% | 9.22% |
| T-B/S-02-04-08/l7 | 11.64% | 9.66% |
| T-B/S-02-04-08/l5 | 11.59% | 9.65% |
| T-C/S-025-05-10/l7 | 11.56% | 8.98% |
| T-C/S-025-05-10/l5 | 11.48% | 8.97% |
| T-A/S-none/l7 | 11.26% | 9.59% |
| T-B/S-025-05-10/l7 | 11.21% | 9.71% |
| T-B/S-025-05-10/l5 | 11.18% | 9.71% |
| T-A/S-none/l5 | 11.10% | 9.58% |
| T-B/S-03-06/l7 | 11.09% | 9.74% |
| T-B/S-03-06/l5 | 11.05% | 9.73% |
| T-B/S-none/l7 | 10.82% | 9.84% |
| T-B/S-none/l5 | 10.79% | 9.84% |
| T-C/S-none/l7 | 10.38% | 9.19% |
| T-C/S-none/l5 | 10.36% | 9.18% |

## Assumptions that matter (do not hide these)

- Fill model is bar-based (high must clear quote by eps, volume gate);
  real queue position is unknowable from candles. Pessimistic regime uses
  eps=10%, 5x volume, 50% early-repayment on >7d locks.
- Early repayment: filled >7d loans assumed to survive only 75% (base) /
  50% (pessimistic) of nominal period. No public dataset exists for this.
- Interest compounds continuously in-sim; Bitfinex actually pays daily.
- 30d/120d offers fill against DAILY p30 candles broadcast to hours —
  coarser than the 2d market's hourly resolution.
- Fee 15% flat. FRR-pegged and hidden offers not modeled.
- Taker opportunities (hitting rich long-period bids, e.g. live 2026-07-04
  book showed 120d bids at ~11% APR gross) are NOT modeled — no historical
  book data. This is upside not captured here, to be measured live.

## Verdict on the 12% target

- Full-history base fill: 11.68% → target NOT met.
- Recent regime (2024-now) base fill avg: 9.96% → the 12% floor is NOT
  guaranteed in a low-rate regime; it requires spike years or the
  unmodeled taker/FRR upside. This is a model estimate with limited
  confidence, not a promise.