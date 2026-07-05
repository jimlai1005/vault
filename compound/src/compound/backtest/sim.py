"""Portfolio simulator for maker funding strategies over 1h bars.

Honesty rules (docs/backtest-design.md):
- An offer can fill only on bars AFTER the one where it was placed (no look-ahead).
- Fill requires bar.high >= rate*(1+eps) AND bar.volume >= q_mult*amount.
- Filled loans may be repaid early: survival fraction `s` of the nominal period
  (2-day loans always live full term).
- Interest accrues per bar at amount*rate*(hours/24)*(1-fee), credited to cash
  (continuous-compounding approximation of Bitfinex's daily payout).

The strategy is a pure function: decide(ctx) -> list of TargetOffer. It sees only
closed bars up to the current index.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

BAR_HOURS = 1.0
HOURS_PER_DAY = 24.0


@dataclass(frozen=True)
class FillParams:
    eps: float          # rate must clear our quote by this fraction
    q_mult: float       # bar volume must be >= q_mult * offer amount
    survival: float     # fraction of nominal period a filled loan survives (>7d periods)
    label: str = ""

    def __post_init__(self):
        if not (self.eps >= 0 and self.q_mult >= 0 and 0 < self.survival <= 1):
            raise ValueError("bad FillParams: %r" % (self,))


PESSIMISTIC = FillParams(eps=0.10, q_mult=5.0, survival=0.5, label="pessimistic")
BASE = FillParams(eps=0.05, q_mult=2.0, survival=0.75, label="base")
OPTIMISTIC = FillParams(eps=0.00, q_mult=1.0, survival=1.0, label="optimistic")


@dataclass(frozen=True)
class TargetOffer:
    rate: float         # daily decimal
    period: int         # days, 2..120
    amount: float       # USD


@dataclass
class OpenOffer:
    rate: float
    period: int
    amount: float
    placed_idx: int


@dataclass
class Loan:
    rate: float
    amount: float
    expires_idx: int
    period: int
    filled_idx: int


@dataclass
class StrategyCtx:
    """What a strategy may see when deciding at bar index i (bars[i] is the bar
    that JUST closed)."""
    bars: List            # full list; strategies must only read bars[: i + 1]
    i: int
    cash: float
    open_offers: List[OpenOffer]
    loans: List[Loan]


@dataclass
class SimResult:
    label: str
    net_interest: float
    avg_capital: float
    years: float
    utilization: float          # time-avg fraction of capital out on loan
    fills: int
    fill_amount: float
    worst_90d_apr: Optional[float]
    yearly_apr: dict            # year -> net APR
    period_days_weighted: float # avg lock period weighted by amount

    @property
    def net_apr(self):
        if self.avg_capital <= 0 or self.years <= 0:
            return 0.0
        return self.net_interest / self.avg_capital / self.years


def run(bars, strategy, fill, fee=0.15, capital=10_000.0,
        rebalance_every=4, min_offer=150.0, max_period=120, label=""):
    """Simulate. `strategy(ctx) -> List[TargetOffer]` called every
    `rebalance_every` bars; unfilled offers are re-placed from scratch then
    (cancel+replace is free for makers)."""
    cash = capital
    offers: List[OpenOffer] = []
    loans: List[Loan] = []
    net_interest = 0.0
    fills = 0
    fill_amount = 0.0
    weighted_period = 0.0

    n = len(bars)
    bar_interest = [0.0] * n       # net interest earned during each bar
    bar_loaned = [0.0] * n         # amount out on loan during each bar
    bar_equity = [0.0] * n         # cash + offers + loans after accrual; the
                                   # denominator basis for ALL return metrics
                                   # (interest compounds into cash, so equity
                                   # grows — dividing by initial capital would
                                   # silently overstate long backtests)

    for i in range(n):
        bar = bars[i]

        # 1) expiries: principal returns to cash
        still = []
        for ln in loans:
            if i >= ln.expires_idx:
                cash += ln.amount
            else:
                still.append(ln)
        loans = still

        # 2) fills: offers placed on earlier bars may fill on this bar.
        # Short offers fill against the 2d-period market (this bar); long
        # offers fill against the 30d-period market (that day's p30 candle,
        # broadcast onto hourly bars) — separate books, separate liquidity.
        remaining = []
        for off in offers:
            if off.period <= 7:
                hi, vol = bar.high, bar.volume
            else:
                hi, vol = getattr(bar, "high30", None), getattr(bar, "vol30", None)
            fillable = (
                off.placed_idx < i
                and hi is not None
                and vol is not None
                and hi >= off.rate * (1.0 + fill.eps)
                and vol >= fill.q_mult * off.amount
            )
            if fillable:
                surv = 1.0 if off.period <= 7 else fill.survival
                live_days = max(2.0, off.period * surv)
                expires = i + int(live_days * HOURS_PER_DAY / BAR_HOURS)
                loans.append(Loan(off.rate, off.amount, expires, off.period, i))
                fills += 1
                fill_amount += off.amount
                weighted_period += off.amount * off.period
            else:
                remaining.append(off)
        offers = remaining

        # 3) interest accrual on outstanding loans (net of fee), compounds via cash
        loaned = 0.0
        for ln in loans:
            earn = ln.amount * ln.rate * (BAR_HOURS / HOURS_PER_DAY) * (1.0 - fee)
            net_interest += earn
            bar_interest[i] += earn
            cash += earn
            loaned += ln.amount
        bar_loaned[i] = loaned
        bar_equity[i] = cash + loaned + sum(o.amount for o in offers)

        # 4) rebalance: strategy re-quotes all unfilled capital
        if i % rebalance_every == 0:
            cash += sum(o.amount for o in offers)  # cancel all own unfilled offers
            offers = []
            ctx = StrategyCtx(bars=bars, i=i, cash=cash,
                              open_offers=offers, loans=loans)
            for t in strategy(ctx):
                amt = min(t.amount, cash)
                if amt < min_offer:
                    continue
                if not (2 <= t.period <= max_period):
                    raise ValueError("strategy emitted illegal period %r" % (t.period,))
                if t.rate <= 0:
                    raise ValueError("strategy emitted non-positive rate")
                offers.append(OpenOffer(t.rate, t.period, amt, i))
                cash -= amt

    years = n * BAR_HOURS / HOURS_PER_DAY / 365.0
    avg_equity = sum(bar_equity) / n if n else 0.0
    utilization = (
        sum(l / e for l, e in zip(bar_loaned, bar_equity) if e > 0) / n if n else 0.0
    )

    # worst rolling 90d net APR (needs >= 90 days of bars)
    win = int(90 * HOURS_PER_DAY / BAR_HOURS)
    worst = None
    if n >= win:
        csum_i = [0.0]
        csum_e = [0.0]
        for x, e in zip(bar_interest, bar_equity):
            csum_i.append(csum_i[-1] + x)
            csum_e.append(csum_e[-1] + e)
        step = max(1, win // 90)
        for j in range(0, n - win + 1, step):
            eq = (csum_e[j + win] - csum_e[j]) / win
            if eq <= 0:
                continue
            apr = (csum_i[j + win] - csum_i[j]) / eq / (90.0 / 365.0)
            if worst is None or apr < worst:
                worst = apr

    # yearly split (interest over that year's average equity)
    yearly = {}
    from datetime import datetime, timezone
    acc = {}
    eqs = {}
    cnt = {}
    for i in range(n):
        y = datetime.fromtimestamp(bars[i].mts / 1000, tz=timezone.utc).year
        acc[y] = acc.get(y, 0.0) + bar_interest[i]
        eqs[y] = eqs.get(y, 0.0) + bar_equity[i]
        cnt[y] = cnt.get(y, 0) + 1
    for y in sorted(acc):
        yr_frac = cnt[y] * BAR_HOURS / HOURS_PER_DAY / 365.0
        avg_eq_y = eqs[y] / cnt[y]
        yearly[y] = acc[y] / avg_eq_y / yr_frac if yr_frac > 0 and avg_eq_y > 0 else 0.0

    return SimResult(
        label=label or getattr(strategy, "__name__", "strategy"),
        net_interest=net_interest,
        avg_capital=avg_equity,
        years=years,
        utilization=utilization,
        fills=fills,
        fill_amount=fill_amount,
        worst_90d_apr=worst,
        yearly_apr=yearly,
        period_days_weighted=(weighted_period / fill_amount) if fill_amount else 0.0,
    )
