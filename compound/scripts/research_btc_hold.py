#!/usr/bin/env python3
"""BTC buy-and-hold / DCA benchmarks on the halving clock (report section 7).

Data: data/btcusd_1D.csv. Phases: months since halving 0-6/6-12/12-18/18-30/30-48.
7a  per cycle x phase: annualized return + intra-phase max drawdown
7b  per full cycle (2016->2020, 2020->2024) + partial 2024 cycle:
      (i)  lump-sum hold
      (ii) naive weekly DCA (budget in 0% cash, deployed in equal weekly buys)
      (iii) clock rule (NOT optimized): H+0-18m 100% BTC; H+18-30m 0% BTC
            (cash at 10% APR neutral strategy); H+30m->next halving weekly DCA
            back in (remaining cash keeps earning 10%)
"""
from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
HALVINGS = [date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20)]
NEXT = {2016: date(2020, 5, 11), 2020: date(2024, 4, 20), 2024: None}
PHASES = [("H+0-6m", 0, 6), ("H+6-12m", 6, 12), ("H+12-18m", 12, 18),
          ("H+18-30m", 18, 30), ("H+30-48m", 30, 999)]
MONTH_DAYS = 30.4375

px = {}
with open(DATA / "btcusd_1D.csv", newline="") as f:
    for row in csv.DictReader(f):
        px[date.fromisoformat(row["date_iso"][:10])] = float(row["close"])
DAYS = sorted(px)
LAST = DAYS[-1]


def price(d):
    while d not in px and d >= DAYS[0]:
        d -= timedelta(days=1)
    return px[d]


def mdd(series):
    peak, worst = -1e18, 0.0
    for v in series:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def ann(p0, p1, days):
    return (p1 / p0) ** (365.0 / days) - 1


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


print("## 7a per cycle x phase: BTC annualized return / intra-phase MDD")
print("| phase | 2016 cycle | 2020 cycle | 2024 cycle |")
print("|---|---|---|---|")
rows = {}
for name, lo, hi in PHASES:
    cells = []
    for h in HALVINGS:
        s = h + timedelta(days=int(lo * MONTH_DAYS))
        e = h + timedelta(days=int(min(hi, 48) * MONTH_DAYS))
        nxt = NEXT[h.year]
        if nxt:
            e = min(e, nxt)
        e = min(e, LAST)
        if s >= LAST or (e - s).days < 30:
            cells.append("no data")
            continue
        p0, p1 = price(s), price(e)
        series = [price(d) for d in daterange(s, e)]
        d = (e - s).days
        tot = p1 / p0 - 1
        cells.append("%+.0f%% tot / %+.0f%% ann / MDD %.0f%%%s"
                     % (tot * 100, ann(p0, p1, d) * 100, mdd(series) * 100,
                        " (partial)" if e == LAST and (not nxt or e < nxt) else ""))
    print("| %s | %s |" % (name, " | ".join(cells)))

print("\n## 7b full-cycle variants (start value 1.0 at halving)")
print("| cycle | variant | final/invested | max drawdown |")
print("|---|---|---|---|")
for h in HALVINGS:
    end = NEXT[h.year] or LAST
    tag = "%d cycle%s" % (h.year, " (partial, to %s)" % LAST if not NEXT[h.year] else "")
    days_all = list(daterange(h, end))

    # (i) lump sum
    series = [price(d) / price(h) for d in days_all]
    print("| %s | (i) lump-sum hold | %.2fx | %.0f%% |" % (tag, series[-1], mdd(series) * 100))

    # (ii) naive weekly DCA, budget 1.0 in 0% cash
    weeks = [h + timedelta(days=7 * k) for k in range(math.ceil((end - h).days / 7))]
    per = 1.0 / len(weeks)
    cash, units = 1.0, 0.0
    buy = {w: per for w in weeks}
    series = []
    for d in days_all:
        if d in buy:
            amt = min(buy[d], cash)
            units += amt / price(d)
            cash -= amt
        series.append(cash + units * price(d))
    print("| %s | (ii) weekly DCA (0%% cash) | %.2fx | %.0f%% |" % (tag, series[-1], mdd(series) * 100))

    # (iii) clock rule
    t18 = h + timedelta(days=int(18 * MONTH_DAYS))
    t30 = h + timedelta(days=int(30 * MONTH_DAYS))
    dca_weeks = []
    if end > t30:
        dca_weeks = [t30 + timedelta(days=7 * k)
                     for k in range(math.ceil((end - t30).days / 7))]
    cash, units = 0.0, 1.0 / price(h)
    per_frac = 1.0 / len(dca_weeks) if dca_weeks else 0.0
    dca_amt = None
    series = []
    daily_r = 0.10 / 365.0
    for d in days_all:
        if d == t18 and units > 0:
            cash += units * price(d)
            units = 0.0
        if d >= t18:
            cash *= (1 + daily_r)
        if dca_weeks and d in dca_weeks:
            if dca_amt is None:
                dca_amt = cash * per_frac  # equal slices of the pile at DCA start
            amt = min(dca_amt, cash)
            units += amt / price(d)
            cash -= amt
        series.append(cash + units * price(d))
    print("| %s | (iii) clock rule (naive, unoptimized) | %.2fx | %.0f%% |"
          % (tag, series[-1], mdd(series) * 100))

print("\n## 7c current cycle vs clock: key marks")
h = HALVINGS[-1]
for m in (6, 12, 18, 26):
    d = min(h + timedelta(days=int(m * MONTH_DAYS)), LAST)
    print("H+%2dm (%s): BTC %.0f (%+.0f%% vs halving)" % (m, d, price(d), (price(d) / price(h) - 1) * 100))
ath = max(price(d) for d in daterange(h, LAST))
ath_d = max(daterange(h, LAST), key=lambda d: price(d))
print("cycle ATH %.0f on %s (H+%.1fm); now %.0f = %+.0f%% vs ATH"
      % (ath, ath_d, (ath_d - h).days / MONTH_DAYS, price(LAST), (price(LAST) / ath - 1) * 100))
