"""Candidate strategies for the backtest. Pure functions of StrategyCtx.

All rates are daily decimals. APR-denominated thresholds are converted once,
here, via rates.apr_to_daily.
"""
from __future__ import annotations

from compound import rates
from compound.backtest.sim import TargetOffer


def always_close(ctx):
    """B1 baseline: lend everything at the last closed rate, 2-day period,
    rolling forever. Approximates 'just stay lent at market'."""
    last = ctx.bars[ctx.i].close
    if last <= 0 or ctx.cash <= 0:
        return []
    return [TargetOffer(rate=last, period=2, amount=ctx.cash)]


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def make_ladder(quantiles, weights, lock30_q=None, lock120_q=None,
                lock30_apr=0.08, lock120_apr=0.15,
                window_days=30, floor_apr=0.0, name=None):
    """Quantile ladder over the rolling distribution of hourly HIGH rates.

    Rung i quotes at the q_i quantile of the trailing window (never below the
    floor or below last close for the lowest rung's fill viability).

    Period escalation: a quote rich RELATIVE to the trailing window locks a
    longer period — `lock30_q`/`lock120_q` are window quantiles the quote must
    reach; `lock30_apr`/`lock120_apr` are absolute APR floors so we never lock
    long in a dead-rate regime. Both conditions must hold. (Strategy research:
    crash-day spikes decay within a day; you must already be quoted high AND
    lock the term when it fills.)
    """
    if len(quantiles) != len(weights):
        raise ValueError("quantiles and weights must align")
    total_w = sum(weights)
    lock30_abs = rates.apr_to_daily(lock30_apr)
    lock120_abs = rates.apr_to_daily(lock120_apr)
    floor_daily = rates.apr_to_daily(floor_apr)

    def strategy(ctx):
        if ctx.cash <= 0:
            return []
        window = int(window_days * 24)
        lo = max(0, ctx.i + 1 - window)
        highs = sorted(b.high for b in ctx.bars[lo: ctx.i + 1])
        last_close = ctx.bars[ctx.i].close
        t30 = max(_quantile(highs, lock30_q), lock30_abs) if lock30_q else lock30_abs
        t120 = max(_quantile(highs, lock120_q), lock120_abs) if lock120_q else lock120_abs
        out = []
        for q, w in zip(quantiles, weights):
            rate = max(_quantile(highs, q), last_close, floor_daily)
            if rate >= t120:
                period = 120
            elif rate >= t30:
                period = 30
            else:
                period = 2
            out.append(TargetOffer(rate=rate, period=period,
                                   amount=ctx.cash * (w / total_w)))
        return out

    strategy.__name__ = name or "ladder"
    return strategy


def make_ladder2(short, term, spike, lock30_apr=0.06, lock120_apr=0.10,
                 window_days=30, name=None):
    """Three explicit tranches, each a list of (quantile, weight):

    - short: priced off the 2d-period market (hourly highs), period 2 —
      keeps capital earning the base rate.
    - term: priced off the 30d-period market (daily high30), period 30 —
      harvests the term premium (2024+ median ≈ +2.8pp APR).
    - spike: priced high off the 30d market, period 120 — pre-placed
      spike catcher (research: spikes decay within a day; you must already
      be quoted).

    Absolute APR floors stop term/spike from locking in a dead-rate regime:
    quotes never go below them, so in low regimes those rungs simply don't
    fill rather than locking cheap money.
    """
    lock30_abs = rates.apr_to_daily(lock30_apr)
    lock120_abs = rates.apr_to_daily(lock120_apr)
    total_w = sum(w for _, w in short) + sum(w for _, w in term) + \
        sum(w for _, w in spike)

    def strategy(ctx):
        if ctx.cash <= 0:
            return []
        window = int(window_days * 24)
        lo = max(0, ctx.i + 1 - window)
        recent = ctx.bars[lo: ctx.i + 1]
        highs2 = sorted(b.high for b in recent)
        highs30 = sorted(b.high30 for b in recent if b.high30 is not None)
        last_close = ctx.bars[ctx.i].close
        out = []
        for q, w in short:
            rate = max(_quantile(highs2, q), last_close)
            out.append(TargetOffer(rate=rate, period=2,
                                   amount=ctx.cash * (w / total_w)))
        anchor30 = highs30 if highs30 else highs2
        for q, w in term:
            rate = max(_quantile(anchor30, q), lock30_abs)
            out.append(TargetOffer(rate=rate, period=30,
                                   amount=ctx.cash * (w / total_w)))
        for q, w in spike:
            rate = max(_quantile(anchor30, q), lock120_abs)
            out.append(TargetOffer(rate=rate, period=120,
                                   amount=ctx.cash * (w / total_w)))
        return out

    strategy.__name__ = name or "ladder2"
    return strategy


def make_ladder3(short, term, spike_aprs, spike_weight_each=1.0,
                 lock30_apr=0.06, window_days=30, name=None):
    """ladder2 variant where the spike tranche sits at ABSOLUTE APR levels
    (e.g. 0.25, 0.50, 1.00) with period 120, instead of window quantiles.
    Rolling-window quantiles cap out near recently-seen rates; true crash
    spikes (research: crash-day mean 153% APR) blow far past any 30-day
    quantile, so fixed high rungs are the only way to be quoted there."""
    lock30_abs = rates.apr_to_daily(lock30_apr)
    total_w = sum(w for _, w in short) + sum(w for _, w in term) + \
        spike_weight_each * len(spike_aprs)

    def strategy(ctx):
        if ctx.cash <= 0:
            return []
        window = int(window_days * 24)
        lo = max(0, ctx.i + 1 - window)
        recent = ctx.bars[lo: ctx.i + 1]
        highs2 = sorted(b.high for b in recent)
        highs30 = sorted(b.high30 for b in recent if b.high30 is not None)
        anchor30 = highs30 if highs30 else highs2
        last_close = ctx.bars[ctx.i].close
        out = []
        for q, w in short:
            rate = max(_quantile(highs2, q), last_close)
            out.append(TargetOffer(rate=rate, period=2,
                                   amount=ctx.cash * (w / total_w)))
        for q, w in term:
            rate = max(_quantile(anchor30, q), lock30_abs)
            out.append(TargetOffer(rate=rate, period=30,
                                   amount=ctx.cash * (w / total_w)))
        for apr in spike_aprs:
            out.append(TargetOffer(rate=rates.apr_to_daily(apr), period=120,
                                   amount=ctx.cash * (spike_weight_each / total_w)))
        return out

    strategy.__name__ = name or "ladder3"
    return strategy
