from compound.backtest.sim import (
    BASE,
    FillParams,
    Loan,
    OpenOffer,
    TargetOffer,
    run,
)
from compound.backtest.data import Bar
from compound.backtest import strategies

import pytest

MTS0 = 1609459200000  # 2021-01-01
HOUR_MS = 3600 * 1000


def bars_of(specs):
    """specs: list of (high, close, volume). The synthetic 30d market mirrors
    the 2d market so period>7 offers stay testable."""
    out = []
    for k, (high, close, vol) in enumerate(specs):
        out.append(Bar(mts=MTS0 + k * HOUR_MS, open=close, close=close,
                       high=high, low=close / 2, volume=vol,
                       high30=high, vol30=vol))
    return out


def one_offer(rate, period=2, amount=1000.0):
    def strat(ctx):
        if ctx.i == 0 and ctx.cash >= amount:
            return [TargetOffer(rate=rate, period=period, amount=amount)]
        return []
    strat.__name__ = "one_offer"
    return strat


NO_FRICTION = FillParams(eps=0.0, q_mult=0.0, survival=1.0, label="test")


def test_no_lookahead_same_bar_never_fills():
    # High enough to fill on bar 0, but offers placed on bar 0 may fill from bar 1 on.
    bars = bars_of([(0.01, 0.0005, 1e9), (0.0001, 0.0001, 1e9)])
    res = run(bars, one_offer(0.001), NO_FRICTION, capital=1000.0,
              rebalance_every=1000)
    assert res.fills == 0


def test_fill_and_interest_accrual():
    # Offer 0.001 daily on 1000 USD; fills on bar 1; accrues bars 1..3 (3 bars).
    bars = bars_of([(0.0005, 0.0005, 1e9)] + [(0.002, 0.001, 1e9)] * 3)
    res = run(bars, one_offer(0.001), NO_FRICTION, fee=0.15, capital=1000.0,
              rebalance_every=1000)
    assert res.fills == 1
    expected = 1000.0 * 0.001 * (1 / 24) * 0.85 * 3
    assert res.net_interest == pytest.approx(expected)


def test_eps_and_volume_gates():
    bars = bars_of([(0.0005, 0.0005, 1e9)] + [(0.00104, 0.001, 1e9)] * 3)
    tight = FillParams(eps=0.05, q_mult=0.0, survival=1.0)   # needs high >= 0.00105
    assert run(bars, one_offer(0.001), tight, capital=1000.0,
               rebalance_every=1000).fills == 0
    thin = FillParams(eps=0.0, q_mult=5.0, survival=1.0)     # needs volume >= 5000
    bars2 = bars_of([(0.0005, 0.0005, 1e9)] + [(0.002, 0.001, 4000.0)] * 3)
    assert run(bars2, one_offer(0.001), thin, capital=1000.0,
               rebalance_every=1000).fills == 0


def test_principal_returns_after_period():
    # 2-day loan: fills bar 1, expires bar 1+48. Re-quote disabled.
    specs = [(0.0005, 0.0005, 1e9)] + [(0.002, 0.0005, 1e9)] + \
            [(0.0001, 0.0001, 1e9)] * 60
    bars = bars_of(specs)
    res = run(bars, one_offer(0.001), NO_FRICTION, capital=1000.0,
              rebalance_every=1000)
    assert res.fills == 1
    # utilization: loaned during 48 bars of 62 total
    assert res.utilization == pytest.approx(48 / 62, abs=0.02)


def test_survival_shortens_long_loans_but_not_2d():
    specs = [(0.0005, 0.0005, 1e9)] + [(0.02, 0.0005, 1e9)] + \
            [(0.0001, 0.0001, 1e9)] * 200
    bars = bars_of(specs)
    half = FillParams(eps=0.0, q_mult=0.0, survival=0.5)
    res30 = run(bars, one_offer(0.01, period=30), half, capital=1000.0,
                rebalance_every=1000)
    res2 = run(bars, one_offer(0.01, period=2), half, capital=1000.0,
               rebalance_every=1000)
    # 30d at survival 0.5 -> 15 days = 360 bars > sim length, still out
    assert res30.utilization > res2.utilization
    # 2d loan lives its full 48 bars regardless of survival
    assert res2.utilization == pytest.approx(48 / 202, abs=0.02)


def test_illegal_period_raises():
    def bad(ctx):
        return [TargetOffer(rate=0.001, period=1, amount=1000.0)]
    bars = bars_of([(0.001, 0.001, 1e9)] * 3)
    with pytest.raises(ValueError, match="illegal period"):
        run(bars, bad, NO_FRICTION, capital=1000.0)


def test_ladder_respects_cash_and_periods():
    bars = bars_of([(0.0003 + k * 1e-6, 0.0002, 1e9) for k in range(100)])
    strat = strategies.make_ladder(
        quantiles=[0.5, 0.9, 0.99], weights=[1, 1, 1],
        lock30_apr=0.15, lock120_apr=0.30)
    ctx_offers = strat(
        type("Ctx", (), {"bars": bars, "i": 99, "cash": 900.0,
                         "open_offers": [], "loans": []})()
    )
    assert len(ctx_offers) == 3
    assert sum(o.amount for o in ctx_offers) <= 900.0 + 1e-9
    assert all(o.period in (2, 30, 120) for o in ctx_offers)
    assert all(o.rate > 0 for o in ctx_offers)


def test_baseline_always_close():
    bars = bars_of([(0.001, 0.0008, 1e9)] * 50)
    res = run(bars, strategies.always_close, NO_FRICTION, capital=1000.0,
              rebalance_every=4)
    assert res.fills >= 1
    assert res.net_interest > 0


def test_compounding_does_not_inflate_metrics():
    # 2 years of constantly fillable high rates: interest compounds, equity
    # grows ~44%; utilization must stay <= 1 and APR must reflect equity basis.
    bars = bars_of([(0.002, 0.0012, 1e9)] * (24 * 730))
    res = run(bars, strategies.always_close, NO_FRICTION, fee=0.15,
              capital=1000.0, rebalance_every=4)
    assert res.utilization <= 1.0 + 1e-9
    # daily 0.0012 net 0.00102 -> full-load ceiling 37.2% APR; re-quote gaps
    # cost a bit. The initial-capital-denominator mistake would report ~44%+.
    ceiling = 0.0012 * 0.85 * 365
    assert 0.9 * ceiling <= res.net_apr <= ceiling * 1.001
    for y, apr in res.yearly_apr.items():
        assert 0.85 * ceiling <= apr <= ceiling * 1.001
