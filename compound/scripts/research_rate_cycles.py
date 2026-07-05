#!/usr/bin/env python3
"""Research: Bitfinex fUSD lending rates vs the BTC 4-year halving cycle.

Feeds reports/research_rate_cycles.md. Analyses:
  A2  high-rate episode census (APR >= 15/20/25%, gaps <= 3d merged)
  A3  cycle-clock: rate stats by months-since-halving phase, per cycle
  A4  P(any APR>=20% day in next 30d | BTC state today)
  A5  hourly spike census by quarter (2021+), APR >= 20% / >= 50%

Data: data/candles_1D_p2.csv (fUSD 2d daily, rate = per-day decimal, APR = x365),
      data/candles_1h_p2.csv (hourly, 2021+), data/btcusd_1D.csv (tBTCUSD 1D).
Run:  .venv/bin/python scripts/research_rate_cycles.py
"""
from __future__ import annotations

import csv
import math
import statistics as st
from datetime import date, datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

HALVINGS = [date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20)]
# Bitfinex BTCUSD all-time high before our data starts (Nov 2013 cycle top).
PRE_2016_ATH = 1163.0
MONTH_DAYS = 30.4375

PHASES = [("H+0-6m", 0, 6), ("H+6-12m", 6, 12), ("H+12-18m", 12, 18),
          ("H+18-30m", 18, 30), ("H+30-48m", 30, 999)]


def load_daily(path, close_col="close"):
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            d = date.fromisoformat(row["date_iso"][:10])
            out[d] = {k: float(row[k]) for k in ("open", "close", "high", "low", "volume")}
    return out


def months_since_halving(d):
    last = None
    for h in HALVINGS:
        if d >= h:
            last = h
    if last is None:
        return None, None
    return last, (d - last).days / MONTH_DAYS


def phase_of(d):
    h, m = months_since_halving(d)
    if m is None:
        return None, None
    for name, lo, hi in PHASES:
        if lo <= m < hi:
            return h.year, name
    return h.year, PHASES[-1][0]


def pct(x):
    return "%.1f%%" % (x * 100)


def quantile(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def main():
    fusd = load_daily(DATA / "candles_1D_p2.csv")
    btc = load_daily(DATA / "btcusd_1D.csv")
    today = datetime.now(timezone.utc).date()
    # drop still-forming day
    fusd = {d: v for d, v in fusd.items() if d < today}
    btc = {d: v for d, v in btc.items() if d < today}
    fdays = sorted(fusd)
    bdays = sorted(btc)
    apr = {d: fusd[d]["close"] * 365 for d in fdays}

    # BTC running ATH (seeded with pre-2016 ATH) and daily log returns
    ath = {}
    run_ath = PRE_2016_ATH
    for d in bdays:
        run_ath = max(run_ath, btc[d]["close"])
        ath[d] = run_ath
    logret = {}
    for a, b in zip(bdays, bdays[1:]):
        logret[b] = math.log(btc[b]["close"] / btc[a]["close"])

    def btc_close(d):
        # last available close on/before d (handles the 2016 hack gap)
        while d not in btc and d >= bdays[0]:
            d = date.fromordinal(d.toordinal() - 1)
        return btc.get(d, {}).get("close")

    def btc_ath(d):
        while d not in ath and d >= bdays[0]:
            d = date.fromordinal(d.toordinal() - 1)
        return ath.get(d)

    print("data: fUSD %s..%s (%d d), BTC %s..%s (%d d)" %
          (fdays[0], fdays[-1], len(fdays), bdays[0], bdays[-1], len(bdays)))

    # sanity: days >= 20% APR per year (ground truth cross-check)
    per_year = {}
    for d in fdays:
        if apr[d] >= 0.20:
            per_year[d.year] = per_year.get(d.year, 0) + 1
    print("days APR>=20%% by year:", {y: per_year[y] for y in sorted(per_year)})

    # ---------------------------------------------------------------- A2
    print("\n## A2 episode census")
    for thr in (0.15, 0.20, 0.25):
        qual = [d for d in fdays if apr[d] >= thr]
        episodes = []
        for d in qual:
            if episodes and (d - episodes[-1][-1]).days <= 4:  # gap of <=3 non-qual days
                episodes[-1].append(d)
            else:
                episodes.append([d])
        print("\n### threshold APR >= %s: %d qualifying days, %d episodes" %
              (pct(thr), len(qual), len(episodes)))
        print("| start | end | span d | qual d | mean APR | peak APR | BTC ret | m after halving | vs ATH |")
        print("|---|---|---|---|---|---|---|---|---|")
        for ep in episodes:
            s, e = ep[0], ep[-1]
            span = [d for d in fdays if s <= d <= e]
            mean_apr = st.mean(apr[d] for d in span)
            peak_apr = max(apr[d] for d in span)
            b0, b1 = btc_close(s), btc_close(e)
            btc_ret = (b1 / b0 - 1) if b0 and b1 else float("nan")
            _, m = months_since_halving(s)
            a = btc_ath(s)
            vs_ath = (b0 / a - 1) if b0 and a else float("nan")
            print("| %s | %s | %d | %d | %s | %s | %+.1f%% | %.1f | %+.1f%% |" %
                  (s, e, (e - s).days + 1, len(ep), pct(mean_apr), pct(peak_apr),
                   btc_ret * 100, m, vs_ath * 100))

    # ---------------------------------------------------------------- A3
    print("\n## A3 cycle clock (per-day APR stats by phase)")
    buckets = {}
    for d in fdays:
        cyc, ph = phase_of(d)
        if ph is None:
            continue
        buckets.setdefault((cyc, ph), []).append(apr[d])
    for scope in ("ALL", 2016, 2020, 2024):
        print("\n### cycle: %s" % scope)
        print("| phase | days | median APR | p90 APR | share days >=20% | share >=15% |")
        print("|---|---|---|---|---|---|")
        for name, lo, hi in PHASES:
            if scope == "ALL":
                vals = sum((v for (c, p), v in buckets.items() if p == name), [])
            else:
                vals = buckets.get((scope, name), [])
            if not vals:
                print("| %s | 0 | - | - | - | - |" % name)
                continue
            sv = sorted(vals)
            print("| %s | %d | %s | %s | %s | %s |" %
                  (name, len(vals), pct(st.median(sv)), pct(quantile(sv, 0.90)),
                   pct(sum(1 for v in sv if v >= 0.20) / len(sv)),
                   pct(sum(1 for v in sv if v >= 0.15) / len(sv))))

    # cross-cycle same-phase table (median APR + >=20% share), the secular-decay view
    print("\n### cross-cycle same-phase comparison (median APR | p90 | %days>=20%)")
    print("| phase | 2016 cycle | 2020 cycle | 2024 cycle |")
    print("|---|---|---|---|")
    for name, lo, hi in PHASES:
        cells = []
        for cyc in (2016, 2020, 2024):
            vals = sorted(buckets.get((cyc, name), []))
            if not vals:
                cells.append("no data")
            else:
                cells.append("%s | %s | %s (n=%d)" %
                             (pct(st.median(vals)), pct(quantile(vals, 0.90)),
                              pct(sum(1 for v in vals if v >= 0.20) / len(vals)), len(vals)))
        print("| %s | %s |" % (name, " | ".join(cells)))

    # ---------------------------------------------------------------- A4
    print("\n## A4 conditional probability: P(any APR>=20%% day in next 30d | BTC state)")
    # feature per day
    feats = {}
    for i, d in enumerate(fdays):
        b_now = btc_close(d)
        d90 = date.fromordinal(d.toordinal() - 90)
        b_90 = btc_close(d90) if d90 >= bdays[0] else None
        if b_now is None or b_90 is None:
            continue
        r90 = b_now / b_90 - 1
        a = btc_ath(d)
        dist = b_now / a - 1
        # 30d realized vol (annualized) from BTC daily log returns
        rets = []
        dd = d
        while len(rets) < 30 and dd > bdays[0]:
            if dd in logret:
                rets.append(logret[dd])
            dd = date.fromordinal(dd.toordinal() - 1)
        if len(rets) < 20:
            continue
        vol = st.pstdev(rets) * math.sqrt(365)
        feats[d] = (r90, dist, vol)

    # outcome: any APR>=20% day within (d, d+30]
    hot = sorted(d for d in fdays if apr[d] >= 0.20)
    import bisect
    def outcome(d):
        lo = bisect.bisect_right(hot, d)
        return lo < len(hot) and (hot[lo] - d).days <= 30

    def r90_bin(x):
        if x < -0.30: return "r90 < -30%"
        if x < 0.0:   return "r90 -30..0%"
        if x < 0.30:  return "r90 0..+30%"
        if x < 1.00:  return "r90 +30..+100%"
        return "r90 > +100%"
    def ath_bin(x):
        if x > -0.05: return "ATH: within 5%"
        if x > -0.20: return "ATH: -5..-20%"
        if x > -0.50: return "ATH: -20..-50%"
        return "ATH: < -50%"
    def vol_bin(x):
        if x < 0.40: return "vol30 < 40%"
        if x < 0.70: return "vol30 40-70%"
        if x < 1.00: return "vol30 70-100%"
        return "vol30 > 100%"

    for scope, days_scope in (("full 2016-2026", [d for d in feats if d <= fdays[-1] and (fdays[-1] - d).days >= 30]),
                              ("2024-01 onwards", [d for d in feats if d >= date(2024, 1, 1) and (fdays[-1] - d).days >= 30])):
        base = sum(outcome(d) for d in days_scope) / len(days_scope)
        print("\n### scope %s: n=%d days, base rate P=%s" % (scope, len(days_scope), pct(base)))
        for label, binfn, idx in (("90d BTC return", r90_bin, 0),
                                  ("distance from ATH", ath_bin, 1),
                                  ("30d realized vol", vol_bin, 2)):
            groups = {}
            for d in days_scope:
                groups.setdefault(binfn(feats[d][idx]), []).append(outcome(d))
            print("| %s bin | n days | P(hot 30d) | lift vs base |" % label)
            print("|---|---|---|---|")
            for k in sorted(groups, key=lambda k: -len(groups[k])):
                p = sum(groups[k]) / len(groups[k])
                print("| %s | %d | %s | %.2fx |" % (k, len(groups[k]), pct(p),
                                                    p / base if base > 0 else float("inf")))

    # ---------------------------------------------------------------- A5
    print("\n## A5 hourly spike census (candles_1h_p2, close-based APR)")
    qtr = {}
    with open(DATA / "candles_1h_p2.csv", newline="") as f:
        for row in csv.DictReader(f):
            d = row["date_iso"]
            q = "%sQ%d" % (d[:4], (int(d[5:7]) - 1) // 3 + 1)
            c = float(row["close"]) * 365
            h = float(row["high"]) * 365
            e = qtr.setdefault(q, [0, 0, 0, 0, 0])  # hours, c>=20, c>=50, h>=20, h>=50
            e[0] += 1
            e[1] += c >= 0.20
            e[2] += c >= 0.50
            e[3] += h >= 0.20
            e[4] += h >= 0.50
    print("| quarter | hours | close>=20% | close>=50% | high>=20% | high>=50% |")
    print("|---|---|---|---|---|---|")
    for q in sorted(qtr):
        e = qtr[q]
        print("| %s | %d | %d | %d | %d | %d |" % (q, *e))


if __name__ == "__main__":
    main()
