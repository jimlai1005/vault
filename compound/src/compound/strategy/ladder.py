"""Production strategy: quantile ladder + 30d term tranche + absolute spike rungs.

Port of backtest winner `T-A/S-02-04-08/l7` (reports/backtest_verdict.md):
  short = [(q0.30, w2), (q0.60, w1)]           period 2, priced off 2d market
  term  = [(q0.50, w3), (q0.80, w2)]           period 30, priced off 30d market,
                                               absolute floor 7% APR
  spike = fixed 20%/40%/80% APR, w1.0 each     period 120

live_test_mode replaces this with a two-offer probe (fill-path + management
verification), enforced in decide() so no caller can forget it.
"""
from __future__ import annotations

from compound import rates
from compound.strategy.base import TargetOffer

SHORT = [(0.30, 2.0, "short-q30"), (0.60, 1.0, "short-q60")]
TERM = [(0.50, 3.0, "term-q50"), (0.80, 2.0, "term-q80")]
TERM_FLOOR_APR = 0.07
SPIKE_APRS = [(0.20, "spike-20"), (0.40, "spike-40"), (0.80, "spike-80")]
SPIKE_W = 1.0


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def decide(market, account, cfg):
    """Return target offers for ALL currently-available engine capital.

    Engine capital = min(available wallet balance, budget headroom). The
    budget also counts capital already out on our offers/loans, so the engine
    can never grow past cfg.capital_budget (coexistence rule).
    """
    # Deployable = free cash PLUS capital sitting on our own open offers: the
    # targets describe the DESIRED COMPLETE offer set, and reconcile keeps the
    # ones that already match. Sizing on cash alone made a fully-deployed
    # engine emit zero targets, which reconcile read as "cancel everything" —
    # an observed live churn loop (cancel-all one tick, re-place the next).
    on_offers = sum(o.amount or 0.0 for o in account.own_offers)
    headroom = cfg.capital_budget - account.own_committed - on_offers
    cash = max(0.0, min(account.available, headroom))
    deployable = cash + on_offers
    if deployable < cfg.min_offer:
        return []

    if cfg.live_test_mode:
        return _live_probe(market, deployable, cfg)

    highs2 = sorted(market.highs2)
    highs30 = sorted(market.highs30) if market.highs30 else highs2
    total_w = sum(w for _, w, _ in SHORT) + sum(w for _, w, _ in TERM) + \
        SPIKE_W * len(SPIKE_APRS)
    floor30 = rates.apr_to_daily(TERM_FLOOR_APR)
    out = []
    for q, w, tag in SHORT:
        rate = max(_quantile(highs2, q), market.last)
        out.append(TargetOffer(rate=rate, period=2,
                               amount=deployable * w / total_w, tag=tag))
    for q, w, tag in TERM:
        rate = max(_quantile(highs30, q), floor30)
        out.append(TargetOffer(rate=rate, period=30,
                               amount=deployable * w / total_w, tag=tag))
    for apr, tag in SPIKE_APRS:
        out.append(TargetOffer(rate=rates.apr_to_daily(apr), period=120,
                               amount=deployable * SPIKE_W / total_w, tag=tag))
    return [t for t in out if t.amount >= cfg.min_offer]


def _live_probe(market, deployable, cfg):
    """Live-test probe: one offer near the market to verify the fill path, one
    high in the window to verify offer management. Caps enforced here AND in
    the engine guardrail (belt and suspenders)."""
    highs2 = sorted(market.highs2)
    per_offer = min(cfg.live_test_max_offer, deployable / 2.0)
    if per_offer < cfg.min_offer:
        per_offer = min(cfg.live_test_max_offer, deployable)
        if per_offer < cfg.min_offer:
            return []
        return [TargetOffer(rate=max(_quantile(highs2, 0.30), market.last),
                            period=2, amount=per_offer, tag="probe-fill")]
    return [
        TargetOffer(rate=max(_quantile(highs2, 0.30), market.last),
                    period=2, amount=per_offer, tag="probe-fill"),
        TargetOffer(rate=max(_quantile(highs2, 0.90), market.last),
                    period=2, amount=per_offer, tag="probe-manage"),
    ]
