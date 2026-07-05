"""Diff desired offers vs our live offers into a minimal mutation plan.

Rules:
- Only offers whose ids we own may be canceled. Foreign offers are invisible
  to the planner by construction (it only receives own_offers).
- Keep-band: an existing offer within 5% rate and same period of a target is
  kept (no churn); otherwise cancel + place.
- Guardrails applied to every planned placement (live_test_mode caps,
  min_offer, budget) — enforced here so no strategy bug can exceed them.
- Mutation cap per tick bounds blast radius of any logic error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

RATE_KEEP_BAND = 0.05
AMOUNT_KEEP_BAND = 0.10


@dataclass
class Plan:
    cancels: List = field(default_factory=list)    # FundingOffer (ours)
    places: List = field(default_factory=list)     # TargetOffer
    skipped: List = field(default_factory=list)    # (reason, TargetOffer)


def _matches(offer, target):
    if offer.period != target.period:
        return False
    if offer.rate is None or offer.rate <= 0:
        return False
    if abs(offer.rate - target.rate) / target.rate > RATE_KEEP_BAND:
        return False
    orig = offer.amount_orig or offer.amount or 0.0
    if target.amount <= 0 or abs(orig - target.amount) / target.amount > AMOUNT_KEEP_BAND:
        return False
    return True


def plan(targets, own_offers, account, cfg):
    guarded = []
    for t in targets:
        t2 = _apply_guardrails(t, cfg)
        if t2 is None:
            guarded.append(("guardrail", t))
        else:
            targets_ok = t2
            guarded.append((None, targets_ok))
    ok_targets = [t for reason, t in guarded if reason is None]

    p = Plan(skipped=[(r, t) for r, t in guarded if r is not None])

    unmatched_offers = list(own_offers)
    for t in ok_targets:
        hit = next((o for o in unmatched_offers if _matches(o, t)), None)
        if hit is not None:
            unmatched_offers.remove(hit)
        else:
            p.places.append(t)
    p.cancels = unmatched_offers

    # budget: capital out after this plan must stay within cfg.capital_budget
    kept = sum(o.amount or 0.0 for o in own_offers if o not in p.cancels)
    budget_left = cfg.capital_budget - account.own_committed - kept
    # cash freed by this tick's cancels is spendable: loop executes cancels
    # before places, so cancel-and-replace of a fully-deployed book works
    avail_left = account.available + sum(o.amount or 0.0 for o in p.cancels)
    affordable = []
    for t in p.places:
        if t.amount <= min(budget_left, avail_left) + 1e-9:
            affordable.append(t)
            budget_left -= t.amount
            avail_left -= t.amount
        else:
            p.skipped.append(("budget", t))
    p.places = affordable

    # concurrency cap (live test)
    if cfg.live_test_mode:
        room = cfg.live_test_max_concurrent - len(own_offers) + len(p.cancels)
        while len(p.places) > max(0, room):
            p.skipped.append(("concurrency", p.places.pop()))

    # mutation cap
    total = len(p.cancels) + len(p.places)
    while total > cfg.max_mutations_per_tick and p.places:
        p.skipped.append(("mutation_cap", p.places.pop()))
        total -= 1
    while total > cfg.max_mutations_per_tick and p.cancels:
        p.cancels.pop()
        total -= 1
    return p


def _apply_guardrails(t, cfg):
    from compound.strategy.base import TargetOffer

    period = t.period
    amount = t.amount
    if cfg.live_test_mode:
        period = min(period, cfg.live_test_max_period)
        amount = min(amount, cfg.live_test_max_offer)
    if amount < cfg.min_offer:
        return None
    if not 2 <= period <= cfg.max_period:
        return None
    return TargetOffer(rate=t.rate, period=period, amount=amount, tag=t.tag)
