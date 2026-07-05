#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Research: optimal leverage per BTC 4-year-cycle phase.

Data:
  data/btcusd_1D.csv      -- BTC/USD daily OHLC (Bitfinex), 2016-01-01 .. now
  data/candles_1D_p2.csv  -- fUSD 2-day funding candles; close = simple DAILY
                             interest rate in decimal (0.00037 = 0.037%/day)

Phases (consistent with reports/cycle_allocation_verdict.md):
  halvings 2016-07-09 / 2020-05-11 / 2024-04-20
  P1 H+0-6m, P2 H+6-12m, P3 H+12-18m, P4 H+18-30m, P5 H+30-48m
  Each phase window is capped at the next halving date (cycle overlap) and at
  the end of available data.  Cycle-3 P4 is PARTIAL (through data end);
  cycle-3 P5 has not started.

Simulation versions (daily-rebalanced constant leverage L on the BTC leg):
  A ideal      : no liquidation, no costs (pure-math contrast)
  B liq        : isolated-margin liquidation off the DAILY LOW
                 bust when (prev_close - low)/prev_close >= 1/L - 0.5% (L>1)
                 -> leg wealth = 0 for the rest of that phase in that cycle
  C liq+gap    : same, but the effective worst fill is 5% BELOW the low
  D liq+fUSD   : B + borrow cost (L-1)*fUSD_daily_rate while L>1;
                 idle cash (1-L) credited at 8%/365 while L<1
  E liq+perp   : B + perp-funding scenario cost on the (L-1) topping notional
                 (structure: 1x spot + (L-1)x perp): 15%/yr in P1/P2/P3/P5,
                 0%/yr in P4.  SCENARIO ASSUMPTION -- no historical perp
                 funding series in data/.

Kelly: gaussian L* = (mu_d - rf_d)/sigma_d^2 with rf = 8%/yr (neutral-leg
opportunity cost), daily moments.

Run: .venv/bin/python scripts/research_leverage_phases.py
"""
import numpy as np
import pandas as pd
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HALVINGS = [pd.Timestamp("2016-07-09"), pd.Timestamp("2020-05-11"),
            pd.Timestamp("2024-04-20")]
PHASE_DEFS = [("P1", 0, 6), ("P2", 6, 12), ("P3", 12, 18),
              ("P4", 18, 30), ("P5", 30, 48)]
PHASE_LABEL = {"P1": "H+0-6m", "P2": "H+6-12m", "P3": "H+12-18m",
               "P4": "H+18-30m", "P5": "H+30-48m"}
RF_ANNUAL = 0.08
RF_D = RF_ANNUAL / 365.0
MM = 0.005                       # maintenance margin rate
GAP = 0.05                       # liquidity-black-hole slippage below low
L_GRID = np.round(np.arange(0.25, 5.01, 0.25), 2)
PERP_FUNDING_ANNUAL = {"P1": 0.15, "P2": 0.15, "P3": 0.15,
                       "P4": 0.00, "P5": 0.15}   # scenario assumption


def load_data():
    btc = pd.read_csv(os.path.join(ROOT, "data", "btcusd_1D.csv"),
                      parse_dates=["date_iso"])
    btc["date"] = btc["date_iso"].dt.tz_localize(None).dt.normalize()
    btc = btc.set_index("date").sort_index()
    btc = btc[~btc.index.duplicated(keep="last")]
    btc["ret"] = btc["close"].pct_change()
    btc["low_ret"] = btc["low"] / btc["close"].shift(1) - 1.0

    f = pd.read_csv(os.path.join(ROOT, "data", "candles_1D_p2.csv"),
                    parse_dates=["date_iso"])
    f["date"] = f["date_iso"].dt.tz_localize(None).dt.normalize()
    f = f.set_index("date").sort_index()
    f = f[~f.index.duplicated(keep="last")]
    r = f["close"].replace(0.0, np.nan)          # 0%/day borrow is a data hole
    r = r.reindex(btc.index).ffill().bfill()     # gaps + pre-2016-07-31 stub
    btc["fusd_daily"] = r
    return btc


def phase_segments(btc):
    """[(phase, cycle_idx, df_segment, partial_flag)]"""
    out = []
    data_end = btc.index.max()
    for ci, h in enumerate(HALVINGS):
        nxt = HALVINGS[ci + 1] if ci + 1 < len(HALVINGS) else pd.Timestamp.max
        for ph, m0, m1 in PHASE_DEFS:
            s = h + pd.DateOffset(months=m0)
            e = min(h + pd.DateOffset(months=m1), nxt)
            if s >= nxt or s > data_end:
                continue
            partial = e > data_end + pd.Timedelta(days=1)
            e = min(e, data_end + pd.Timedelta(days=1))
            seg = btc.loc[(btc.index >= s) & (btc.index < e)].dropna(
                subset=["ret", "low_ret"])
            if len(seg) < 30:
                continue
            out.append((ph, ci, seg.assign(_phase=ph), partial))
    return out


def seg_stats(seg):
    r = seg["ret"].values
    mu, sd = r.mean(), r.std(ddof=1)
    sk = pd.Series(r).skew()
    ku = pd.Series(r).kurt()          # excess kurtosis
    w1 = r.min()
    cp = np.cumprod(1 + r)
    worst = {}
    for n in (3, 7):
        if len(r) > n:
            roll = cp[n:] / cp[:-n] - 1
            worst[n] = min(roll.min(), (cp[n - 1] - 1))
        else:
            worst[n] = w1
    kelly = (mu - RF_D) / (sd ** 2)
    return dict(n=len(r), mu=mu, sd=sd, skew=sk, exkurt=ku,
                w1=w1, w3=worst[3], w7=worst[7], kelly=kelly)


def sim_path(seg, L, version, mu_shrink=0.0):
    """Return (wealth_relatives_array, busted_bool). Daily rebalanced."""
    r = seg["ret"].values - mu_shrink
    lr = seg["low_ret"].values - mu_shrink
    fusd = seg["fusd_daily"].values
    ph = seg["_phase"].iloc[0]
    path = np.empty(len(r))
    w = 1.0
    for i in range(len(r)):
        if version != "A" and L > 1.0:
            eff_low = lr[i] if version in ("B", "D", "E") else \
                (1.0 + lr[i]) * (1.0 - GAP) - 1.0
            if -eff_low >= 1.0 / L - MM:
                path[i:] = 0.0
                return path, True
        cost = 0.0
        if version == "D":
            cost = (L - 1.0) * fusd[i] if L > 1.0 else -(1.0 - L) * RF_D
        elif version == "E":
            fd = PERP_FUNDING_ANNUAL[ph] / 365.0
            cost = (L - 1.0) * fd if L > 1.0 else -(1.0 - L) * RF_D
        w *= (1.0 + L * r[i] - cost)
        if w <= 0.0:
            path[i:] = 0.0
            return path, True
        path[i] = w
    return path, False


def merged_metrics(segs, L, version, mu_shrink_map=None):
    """Chain a phase's segments across cycles. Returns geo-annualized, maxDD,
    bust cycle count, total days."""
    wealth, busts, days = 1.0, 0, 0
    full_path = []
    for ph, ci, seg, partial in segs:
        shr = mu_shrink_map.get((ph, ci), 0.0) if mu_shrink_map else 0.0
        path, busted = sim_path(seg, L, version, shr)
        full_path.append(wealth * path)
        wealth *= path[-1]
        busts += int(busted)
        days += len(path)
        if wealth <= 0:
            break
    fp = np.concatenate(full_path)
    peak = np.maximum.accumulate(np.concatenate(([1.0], fp)))[1:]
    mdd = float(np.min(fp / peak - 1.0)) if len(fp) else 0.0
    if wealth <= 0:
        return -1.0, -1.0, busts, days
    geo = wealth ** (365.0 / days) - 1.0
    return geo, mdd, busts, days


def optimal_L(segs, version, mu_shrink_map=None):
    best_L, best_g = None, -np.inf
    rows = {}
    for L in L_GRID:
        g, _, b, _ = merged_metrics(segs, L, version, mu_shrink_map)
        rows[L] = (g, b)
        if g > best_g:
            best_g, best_L = g, L
    return best_L, best_g, rows


def fmt_pct(x, d=1):
    return "bust" if x <= -0.999 else "{:+.{}f}%".format(100 * x, d)


def main():
    btc = load_data()
    segs = phase_segments(btc)
    by_phase = {}
    for item in segs:
        by_phase.setdefault(item[0], []).append(item)

    print("=" * 78)
    print("SECTION 1 -- per-phase / per-cycle daily-return statistics")
    print("=" * 78)
    hdr = ("phase|cycle|days|mu_d|sigma_d|ann_mu|ann_vol|skew|exkurt|"
           "worst1d|worst3d|worst7d|Kelly L*")
    print(hdr)
    stat_merged = {}
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        pool = []
        for _, ci, seg, partial in by_phase.get(ph, []):
            st = seg_stats(seg)
            pool.append(seg)
            tag = "{}{}".format(2016 + 4 * ci, "*" if partial else "")
            print("{}|{}|{}|{:.4%}|{:.3%}|{:+.0%}|{:.0%}|{:+.2f}|{:.1f}|"
                  "{:.1%}|{:.1%}|{:.1%}|{:.2f}".format(
                      ph, tag, st["n"], st["mu"], st["sd"],
                      st["mu"] * 365, st["sd"] * np.sqrt(365), st["skew"],
                      st["exkurt"], st["w1"], st["w3"], st["w7"],
                      st["kelly"]))
        allseg = pd.concat(pool)
        st = seg_stats(allseg)
        stat_merged[ph] = st
        print("{}|MERGED|{}|{:.4%}|{:.3%}|{:+.0%}|{:.0%}|{:+.2f}|{:.1f}|"
              "{:.1%}|{:.1%}|{:.1%}|{:.2f}".format(
                  ph, st["n"], st["mu"], st["sd"], st["mu"] * 365,
                  st["sd"] * np.sqrt(365), st["skew"], st["exkurt"],
                  st["w1"], st["w3"], st["w7"], st["kelly"]))

    print()
    print("=" * 78)
    print("SECTION 2 -- optimal L by version (merged across cycles per phase)")
    print("versions: A ideal | B liq(low) | C liq(low-5% gap) | "
          "D liq+fUSD borrow | E liq+perp funding scenario")
    print("=" * 78)
    print("phase|ver|opt L|geo ann @opt|busts@opt|geo ann @L=1|geo ann @L=2"
          "|busts@L=2|geo ann @L=3|busts@L=3")
    opt_tbl = {}
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        for ver in ("A", "B", "C", "D", "E"):
            bl, bg, rows = optimal_L(by_phase[ph], ver)
            opt_tbl[(ph, ver)] = (bl, bg, rows)
            print("{}|{}|{:.2f}|{}|{}|{}|{}|{}|{}|{}".format(
                ph, ver, bl, fmt_pct(bg), rows[bl][1],
                fmt_pct(rows[1.0][0]), fmt_pct(rows[2.0][0]), rows[2.0][1],
                fmt_pct(rows[3.0][0]), rows[3.0][1]))

    print()
    print("SECTION 2b -- per-cycle optimal L (version B: liquidation, "
          "no cost) and version A ideal")
    print("phase|cycle|optL_A|geoA|optL_B|geoB")
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        for item in by_phase[ph]:
            _, ci, seg, partial = item
            blA, bgA, _ = optimal_L([item], "A")
            blB, bgB, _ = optimal_L([item], "B")
            tag = "{}{}".format(2016 + 4 * ci, "*" if partial else "")
            print("{}|{}|{:.2f}|{}|{:.2f}|{}".format(
                ph, tag, blA, fmt_pct(bgA), blB, fmt_pct(bgB)))

    print()
    print("=" * 78)
    print("SECTION 3 -- borrow-cost drag check (version D vs B at same L)")
    print("=" * 78)
    print("phase|mean fUSD daily rate in phase (ann.)|optL_B|optL_D|"
          "geo@2x_B|geo@2x_D|drag@2x")
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        pool = pd.concat([s for _, _, s, _ in by_phase[ph]])
        annr = pool["fusd_daily"].mean() * 365
        _, _, rB = opt_tbl[(ph, "B")]
        _, _, rD = opt_tbl[(ph, "D")]
        drag = (rB[2.0][0] - rD[2.0][0]) if rB[2.0][0] > -0.999 and \
            rD[2.0][0] > -0.999 else float("nan")
        print("{}|{:.1%}|{:.2f}|{:.2f}|{}|{}|{:+.1f}pp".format(
            ph, annr, opt_tbl[(ph, "B")][0], opt_tbl[(ph, "D")][0],
            fmt_pct(rB[2.0][0]), fmt_pct(rD[2.0][0]), 100 * drag))

    print()
    print("=" * 78)
    print("SECTION 4 -- fractional-Kelly tiers, evaluated under version D")
    print("(aggressive = hist-opt L of version D; base = 1/2 Kelly; "
          "conservative = 1/4 Kelly; Kelly from merged moments, rf=8%)")
    print("=" * 78)
    print("phase|tier|L|geo ann|maxDD|bust cycles/total cycles")
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        k = stat_merged[ph]["kelly"]
        ncyc = len(by_phase[ph])
        tiers = [("aggr(histD)", float(opt_tbl[(ph, "D")][0])),
                 ("half-Kelly", max(0.0, k / 2)),
                 ("quarter-Kelly", max(0.0, k / 4))]
        for name, L in tiers:
            g, mdd, b, _ = merged_metrics(by_phase[ph], L, "D")
            print("{}|{}|{:.2f}|{}|{:.1%}|{}/{}".format(
                ph, name, L, fmt_pct(g), mdd, b, ncyc))

    print()
    print("=" * 78)
    print("SECTION 5 -- robustness: shrink mu by 30% (ret' = ret - 0.3*mu)")
    print("=" * 78)
    print("phase|Kelly(0.7mu)|optL_D(0.7mu)|geo@that L|optL_D(full mu)|"
          "geo penalty if you run full-mu optimal L in 0.7mu world")
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        shrink = {}
        for _, ci, seg, _ in by_phase[ph]:
            shrink[(ph, ci)] = 0.3 * seg["ret"].mean()
        k7 = (0.7 * stat_merged[ph]["mu"] - RF_D) / stat_merged[ph]["sd"] ** 2
        bl7, bg7, rows7 = optimal_L(by_phase[ph], "D", shrink)
        blF = float(opt_tbl[(ph, "D")][0])
        gF_in7 = rows7[blF][0]
        print("{}|{:.2f}|{:.2f}|{}|{:.2f}|{} vs {} (delta {:+.1f}pp)".format(
            ph, k7, bl7, fmt_pct(bg7), blF, fmt_pct(gF_in7), fmt_pct(bg7),
            100 * (gF_in7 - bg7) if gF_in7 > -0.999 else float("nan")))

    print()
    print("SECTION 6 -- L-grid geo-annualized detail, version D (merged)")
    print("phase|" + "|".join("{:.2f}".format(L) for L in L_GRID))
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        _, _, rows = opt_tbl[(ph, "D")]
        print(ph + "|" + "|".join(fmt_pct(rows[L][0], 0) for L in L_GRID))
    print()
    print("SECTION 6b -- same, version C (liq + 5% gap, no cost)")
    print("phase|" + "|".join("{:.2f}".format(L) for L in L_GRID))
    for ph in ("P1", "P2", "P3", "P4", "P5"):
        _, _, rows = opt_tbl[(ph, "C")]
        print(ph + "|" + "|".join(fmt_pct(rows[L][0], 0) for L in L_GRID))

    print()
    print("* = partial phase (data ends {}); cycle-3 P4 runs 2025-10-20.."
          .format(btc.index.max().date()))
    print("done.")


if __name__ == "__main__":
    pd.set_option("mode.chained_assignment", None)
    main()
