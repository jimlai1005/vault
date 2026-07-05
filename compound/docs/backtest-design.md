# Backtest design — fill model and honesty rules

Written 2026-07-04. The backtest's job is to pick strategy parameters and produce an
*honest* APR estimate. Its biggest lie-risk is the fill model, so that is pinned here.

## Data available

- 1h + 1D funding candles for fUSD (executed-rate OHLCV), period-2 aggregate; longer
  daily history 2021→now.
- funding stats history (FRR proxy, total funding amount / used).
- NO historical order book, NO per-period trade tape (candles aggregate periods unless
  the a/p key syntax lets us split — check api reference doc).

## Fill model (maker offers)

An offer at daily rate `r` placed at time t fills in a later 1h bar B if:

1. `B.high >= r * (1 + eps)` — rate must clear our quote by a margin, because
   high >= r only proves *someone* traded at >= r, not that our queue position filled.
2. `B.volume >= q_mult * amount` — the bar must have enough traded volume to
   plausibly absorb us.

Run the whole grid under three fill regimes:
- pessimistic: eps=0.10, q_mult=5
- base:        eps=0.05, q_mult=2
- optimistic:  eps=0.00, q_mult=1  (upper bound, reporting only — never used to pick params)

Params are picked on the **base** regime; the report shows all three. If a strategy only
beats 12% under optimistic fills, it does NOT pass.

## Term locking & early repayment

- A filled offer locks `amount` for `period` days earning `r` daily (simple interest,
  credited daily to cash, re-lendable → compounding happens via re-offering).
- Borrowers may repay early, especially spike-driven borrowing. We have no dataset of
  realized loan lifetimes, so run survival-fraction sensitivity: filled loans live
  `min(period, period * s)` with s ∈ {0.5, 0.75, 1.0}. Base = 0.75 for period > 7d;
  2d loans always live full term. Label this assumption in every report.

## Baselines (must appear in every report)

- B0 "ideal FRR": 100% utilization earning the daily FRR series (from funding stats /
  1D close as proxy) — optimistic upper bound of the naive strategy.
- B1 "always-fill": lend everything daily at that day's close rate, 2d rolling —
  realistic floor for "just stay lent".
- Target check: strategy net APR ≥ 12% AND ≥ B0 net (otherwise the complexity isn't
  paying for itself).

## Fees & units

- Interest netted at `(1 - fee)`, fee=0.15 default (verify from research doc; if FRR
  offers or hidden offers carry different fee, model per-offer-type).
- All internal math in daily-rate decimals; APR only in reports: `apr = daily * 365`.
  Realized APR of a run = total_net_interest / time_weighted_capital / years_elapsed.

## Overfitting guard

- Parameter grid selected on 2021-01 → 2024-12 ("train"). 2025-01 → now is
  out-of-sample; reported separately. Params that win train but fall >30% relative in
  OOS are rejected as regime-fit.
- Report worst rolling 90-day net APR, not just the mean.
- Regime split in report: 2022 bear vs 2023 chop vs 2024-25 bull.

## Known limitations (stated in report, not hidden)

- Fill model is bar-based; real queue dynamics unknowable from candles. Mitigated by
  eps/q_mult pessimism, but a live A/B (small capital) is the only true test.
- Taker-style strategies (hitting rich long-period bids, e.g. today's 11% APR 120d bid)
  CANNOT be backtested without historical book data. Handle as live experiment with
  explicit rate floor, not backtest-derived. Backtest covers maker strategies only.
- Candles may aggregate all periods; if so, high spikes partly reflect long-period
  trades and the 2d fill model is slightly optimistic — noted in report.
