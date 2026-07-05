#!/usr/bin/env python3
"""Strategy-family x BTC-4-year-cycle-phase fit matrix, backtested on ~10y of data.

PURPOSE (read this before quoting numbers):
  This measures PHASE FIT — which halving-cycle phase each simplified strategy
  family makes/loses money in — NOT precise return forecasts. The strategies are
  deliberately simplified price-only proxies of the user's real pilots
  (vault CTA short-only, gridbot). Differences are listed in the report.

NO PARAMETER OPTIMIZATION:
  All parameters are literature-standard or pre-specified by the task owner and
  were NOT tuned against this data. Tuning would turn phase-fit conclusions into
  overfitting artifacts. Fixed parameters:
    - Trend: EMA20/EMA50 daily cross; variant adds a 200-day SMA regime filter.
    - Grid: anchor = 30d SMA, band +/-30%, 5% spacing (12 slots), 50% invested
      at anchor, re-anchor on band exit (realizing P&L), spot-only (no leverage).
    - Benchmarks: buy&hold, 8%/yr cash-neutral, 100% cash, 50/50 hold+neutral.

COSTS (charged on every position change, per side):
    fee 0.045% + slippage 0.05%  =>  0.095% of traded notional per side.

CYCLE CLOCK:
  Halvings 2016-07-09, 2020-05-11, 2024-04-20. Phases after halving H:
    P1 H+0-6m | P2 H+6-12m | P3 H+12-18m | P4 H+18-30m | P5 H+30-48m
  Phases are truncated at the next halving and at the end of available data;
  truncated phases are flagged (coverage < 90% of nominal length => "partial").

MECHANICS / KNOWN SIMPLIFICATIONS:
  - Signals computed on daily close; trades execute at the NEXT day's close
    (no look-ahead). Trend strategies are TRADE-BASED: 1x notional sized at
    entry and held unchanged until the exit signal (matches a CTA that opens
    a position and holds it; avoids the volatility drag a daily-rebalanced
    short would show). A short whose loss reaches 100% of entry equity is
    liquidated (equity floored near zero) — this never triggered in the data.
  - Short leg ignores perp funding. In bulls funding is usually positive
    (shorts RECEIVE it), so the short results here are, if anything,
    slightly pessimistic; no leverage, no liquidation modelled.
  - Grid fills use daily high/low against limit levels; a slice bought today
    cannot be sold the same day (intra-day path unknowable on daily bars).
    Daily bars still undercount intraday grid round-trips => grid profit AND
    fees are both understated.
  - Idle grid cash earns 0%.

Run:  .venv/bin/python scripts/research_strategy_phases.py
Outputs: reports/research_strategy_phases_matrix.csv + tables on stdout.
"""

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
OUT_CSV = os.path.join(ROOT, "reports", "research_strategy_phases_matrix.csv")

COST = 0.00095          # per side: 0.045% fee + 0.05% slippage
NEUTRAL_APR = 0.08      # cash-neutral benchmark
DAYS_PER_YEAR = 365.0

HALVINGS = [pd.Timestamp("2016-07-09"), pd.Timestamp("2020-05-11"),
            pd.Timestamp("2024-04-20")]
PHASE_DEFS = [("P1 H+0-6m", 0, 6), ("P2 H+6-12m", 6, 12), ("P3 H+12-18m", 12, 18),
              ("P4 H+18-30m", 18, 30), ("P5 H+30-48m", 30, 48)]

ASSETS = {"BTC": "btcusd_1D.csv", "ETH": "ethusd_1D.csv"}


# ---------------------------------------------------------------- data

def load(asset_csv):
    df = pd.read_csv(os.path.join(DATA, asset_csv))
    df["date"] = pd.to_datetime(df["date_iso"].str[:10])
    df = df.drop_duplicates("date").set_index("date").sort_index()
    return df[["open", "close", "high", "low"]].astype(float)


# ---------------------------------------------------------------- strategies
# Each returns (daily_return_series, gross_return_series, fee_series, turnover_days)

def trend_returns(close, direction, ma200_filter=False):
    """EMA20/50 cross, trade-based. direction=+1: long on golden cross, flat
    otherwise. direction=-1: short on death cross, flat otherwise.
    ma200_filter (short only): shorts also require close < SMA200; while SMA200
    is not yet computable (warm-up) the filter blocks trading (stay flat).

    Position is sized 1x at entry (qty = equity/price) and held UNCHANGED until
    exit — no daily re-leveraging. Fees on entry and exit notional."""
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    if direction > 0:
        sig = (ema20 > ema50)
    else:
        sig = (ema20 < ema50)
        if ma200_filter:
            sma200 = close.rolling(200).mean()
            sig = sig & (close < sma200)
    # ignore warm-up: no signal before EMA50 has ~50 obs
    sig.iloc[:50] = False
    sigv = sig.to_numpy()
    c = close.to_numpy()
    n = len(c)
    eq = 1.0
    in_pos = False
    qty = 0.0
    entry_eq = 0.0
    entry_px = 0.0
    eq_arr = np.empty(n)
    fee_arr = np.zeros(n)
    trade_day = np.zeros(n, dtype=bool)
    eq_arr[0] = eq
    for t in range(1, n):
        if in_pos:
            eq = entry_eq + qty * direction * (c[t] - entry_px)
            if eq <= 0.0:  # short liquidated (never triggers on this data)
                eq = 1e-9
        desired = bool(sigv[t - 1])
        if desired and not in_pos:
            fee = eq * COST
            eq -= fee
            qty = eq / c[t]
            entry_eq, entry_px = eq, c[t]
            in_pos = True
            fee_arr[t] += fee
            trade_day[t] = True
        elif not desired and in_pos:
            fee = qty * c[t] * COST
            eq -= fee
            in_pos = False
            fee_arr[t] += fee
            trade_day[t] = True
        eq_arr[t] = eq
    eq_s = pd.Series(eq_arr, index=close.index)
    r = eq_s.pct_change().fillna(0.0)
    fee_r = (pd.Series(fee_arr, index=close.index) / eq_s.shift(1)).fillna(0.0)
    return r, r + fee_r, fee_r, pd.Series(trade_day, index=close.index)


def grid_returns(px):
    """Spot long grid. Anchor = SMA30 at (re)anchor time (falls back to close if
    close is outside the SMA30 band). 12 slots of 5% from -30% to +30%.
    At anchor: hold 6 slices (50% invested) with sell targets +5%..+30%;
    6 empty buy slots at -5%..-30%. Buy when daily low <= buy level (fill at
    level), sell held slice when daily high >= its +5% target (fill at target).
    Band exit on close => re-anchor: mark to market, resize slices to equity/12,
    rebalance holdings back to 6 slices at the close (fees on turnover)."""
    close, high, low = px["close"], px["high"], px["low"]
    sma30 = close.rolling(30).mean()
    start_i = 30  # first day with SMA30
    dates = close.index
    cash = 1.0
    coins = 0.0
    slots = {}          # slot k (k=-6..5): dict(buy_px, sell_px, qty) if held
    anchor = None
    eq_series = pd.Series(np.nan, index=dates)
    fee_series = pd.Series(0.0, index=dates)
    turn_days = pd.Series(False, index=dates)

    def levels(a):
        return {k: a * (1.0 + 0.05 * k) for k in range(-6, 7)}

    def re_anchor(i, c):
        nonlocal anchor, cash, coins, slots
        a = sma30.iloc[i]
        if not np.isfinite(a) or not (0.7 * a <= c <= 1.3 * a):
            a = c
        anchor = a
        eq = cash + coins * c
        slice_usd = eq / 12.0
        lv = levels(anchor)
        target_coins = 6.0 * slice_usd / c
        delta = target_coins - coins
        fee = abs(delta) * c * COST
        cash -= delta * c + fee
        coins = target_coins
        slots = {}
        qty = slice_usd / c
        for k in range(0, 6):          # 6 held slices, sell targets above
            slots[k] = {"sell": lv[k + 1], "qty": qty}
        return fee

    fee0 = 0.0
    for i in range(start_i, len(dates)):
        c, h, lo = close.iloc[i], high.iloc[i], low.iloc[i]
        day_fee = 0.0
        traded = False
        if anchor is None:
            day_fee += re_anchor(i, c)
            traded = True
        else:
            lv = levels(anchor)
            bought_today = set()
            # buys: empty slots k=-6..-1 whose level was touched by the low
            for k in range(-1, -7, -1):
                if k not in slots and lo <= lv[k]:
                    px_fill = lv[k]
                    eq = cash + coins * px_fill
                    # spot-only: spend at most the cash on hand (incl. fee)
                    spend = min(eq / 12.0, cash / (1.0 + COST))
                    if spend <= 1e-12 * eq:
                        continue  # fully invested; cannot buy this level
                    qty = spend / px_fill
                    fee = qty * px_fill * COST
                    cash -= qty * px_fill + fee
                    coins += qty
                    slots[k] = {"sell": lv[k + 1], "qty": qty}
                    bought_today.add(k)
                    day_fee += fee
                    traded = True
            # sells: held slots whose sell target was touched by the high
            for k in sorted(list(slots.keys())):
                if k in bought_today:
                    continue
                s = slots[k]
                if h >= s["sell"]:
                    fee = s["qty"] * s["sell"] * COST
                    cash += s["qty"] * s["sell"] - fee
                    coins -= s["qty"]
                    del slots[k]
                    day_fee += fee
                    traded = True
            # band exit on close => re-anchor
            if not (0.7 * anchor <= c <= 1.3 * anchor):
                day_fee += re_anchor(i, c)
                traded = True
        eq_now = cash + coins * c
        # invariant: spot-only grid must not lever up or go bust
        if cash < -0.02 * eq_now or eq_now <= 0:
            raise AssertionError("grid invariant broken at %s: cash=%.4f eq=%.4f"
                                 % (dates[i].date(), cash, eq_now))
        eq_series.iloc[i] = eq_now
        fee_series.iloc[i] = day_fee
        turn_days.iloc[i] = traded
    fee0 += 0.0
    eq = eq_series.dropna()
    r = eq.pct_change().fillna(0.0)
    # express fees as daily return drag (approx): fee_usd / prev equity
    prev_eq = eq.shift(1)
    fee_r = (fee_series.reindex(eq.index) / prev_eq).fillna(0.0)
    return r, r + fee_r, fee_r, turn_days.reindex(eq.index).fillna(False)


def benchmark_returns(close, kind):
    r_asset = close.pct_change().fillna(0.0)
    r_cash = (1.0 + NEUTRAL_APR) ** (1.0 / DAYS_PER_YEAR) - 1.0
    if kind == "hold":
        r = r_asset.copy()
        r.iloc[0] -= COST  # one entry fee
    elif kind == "cash8":
        r = pd.Series(r_cash, index=close.index)
    elif kind == "cash0":
        r = pd.Series(0.0, index=close.index)
    elif kind == "mix50":
        r = 0.5 * r_asset + 0.5 * r_cash  # daily-rebalanced 50/50
        r.iloc[0] -= 0.5 * COST
    z = pd.Series(0.0, index=close.index)
    return r, r, z, z > 1


# ---------------------------------------------------------------- phases

def phase_windows():
    """[(cycle_label, phase_label, start, end_exclusive, nominal_days)]"""
    out = []
    for ci, h in enumerate(HALVINGS):
        nxt = HALVINGS[ci + 1] if ci + 1 < len(HALVINGS) else pd.Timestamp("2100-01-01")
        for name, m0, m1 in PHASE_DEFS:
            s = h + pd.DateOffset(months=m0)
            e = h + pd.DateOffset(months=m1)
            nominal = (e - s).days
            e = min(e, nxt)
            if e <= s:
                continue
            out.append((str(h.year), name, s, e, nominal))
    return out


def slice_metrics(r, gross, fees, turn, s, e, nominal_days, data_end):
    idx = r.index
    m = (idx >= s) & (idx < e)
    rr = r[m]
    n = len(rr)
    eff_end = min(e, data_end + pd.Timedelta(days=1))
    if n < 10:
        return None
    tot = float((1.0 + rr).prod() - 1.0)
    ann = (1.0 + tot) ** (DAYS_PER_YEAR / n) - 1.0 if n >= 30 else np.nan
    eqc = (1.0 + rr).cumprod()
    mdd = float((eqc / eqc.cummax() - 1.0).min())
    gtot = float((1.0 + gross[m]).prod() - 1.0)
    fee_drag = float(fees[m].sum())
    ntr = int(turn[m].sum())
    covered = (eff_end - max(s, idx[m][0])).days
    coverage = "full" if covered >= 0.9 * nominal_days else "partial"
    return dict(start=str(s.date()), end=str(min(e, eff_end).date()), n_days=n,
                coverage=coverage, total_ret=tot, ann_ret=ann, mdd=mdd,
                gross_ret=gtot, fee_drag=fee_drag, n_trade_days=ntr)


# ---------------------------------------------------------------- main

STRATEGIES = ["hold", "cash8", "mix50", "trend_long", "trend_short",
              "trend_short_f200", "grid30"]


def run_asset(asset, csv_name):
    px = load(csv_name)
    close = px["close"]
    res = {}
    res["trend_long"] = trend_returns(close, +1)
    res["trend_short"] = trend_returns(close, -1)
    res["trend_short_f200"] = trend_returns(close, -1, ma200_filter=True)
    res["grid30"] = grid_returns(px)
    for b in ("hold", "cash8", "cash0", "mix50"):
        res[b] = benchmark_returns(close, b)
    rows = []
    data_end = close.index[-1]
    for strat in STRATEGIES:
        r, g, f, t = res[strat]
        for cyc, ph, s, e, nom in phase_windows():
            met = slice_metrics(r, g, f, t, s, e, nom, data_end)
            if met is None:
                continue
            rows.append(dict(asset=asset, strategy=strat, cycle=cyc, phase=ph, **met))
    return pd.DataFrame(rows)


def stability(df_sub):
    """>=2 cycles with full-ish coverage agreeing in sign => stable."""
    signs = [np.sign(x) for x in df_sub["total_ret"]]
    n = len(signs)
    if n <= 1:
        return "n=1"
    from collections import Counter
    c = Counter(signs)
    top, cnt = c.most_common(1)[0]
    if cnt >= 2 and cnt >= n - 1:
        return "stable+" if top > 0 else "stable-"
    if cnt >= 2:
        return "mixed(2/3)" if top > 0 else "mixed(2/3)-"
    return "UNSTABLE"


def fmt_pct(x):
    return "  n/a " if x is None or (isinstance(x, float) and not np.isfinite(x)) \
        else "%7.1f%%" % (100 * x)


def main():
    all_rows = [run_asset(a, f) for a, f in ASSETS.items()]
    df = pd.concat(all_rows, ignore_index=True)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    df.to_csv(OUT_CSV, index=False, float_format="%.6f")
    print("wrote %s (%d rows)\n" % (OUT_CSV, len(df)))

    pd.set_option("display.width", 200)

    # ---- per-strategy matrix: annualized return by cycle x phase
    for asset in ASSETS:
        print("=" * 100)
        print("ASSET %s — annualized return %% (phase-local MDD %% in parens); * = partial phase" % asset)
        for strat in STRATEGIES:
            sub = df[(df.asset == asset) & (df.strategy == strat)]
            print("\n  %s" % strat)
            hdr = "    %-8s" % "cycle" + "".join("%22s" % p for p, _, _ in PHASE_DEFS)
            print(hdr)
            for cyc in sorted(sub.cycle.unique()):
                line = "    %-8s" % cyc
                for ph, _, _ in PHASE_DEFS:
                    row = sub[(sub.cycle == cyc) & (sub.phase == ph)]
                    if row.empty:
                        line += "%22s" % "-"
                    else:
                        r0 = row.iloc[0]
                        star = "*" if r0.coverage == "partial" else " "
                        line += "%22s" % ("%s (%s)%s" % (fmt_pct(r0.ann_ret).strip(),
                                                         fmt_pct(r0.mdd).strip(), star))
                print(line)

    # ---- ranking per phase (BTC primary), mean ann return across cycles
    print("\n" + "=" * 100)
    print("PHASE RANKING (BTC, mean annualized return across covered cycles; stability from sign agreement)")
    for ph, _, _ in PHASE_DEFS:
        print("\n  %s" % ph)
        recs = []
        for strat in STRATEGIES:
            sub = df[(df.asset == "BTC") & (df.strategy == strat) & (df.phase == ph)]
            if sub.empty:
                continue
            mean_ann = sub.ann_ret.mean()
            med_tot = sub.total_ret.median()
            stab = stability(sub)
            esub = df[(df.asset == "ETH") & (df.strategy == strat) & (df.phase == ph)]
            eth_mean = esub.ann_ret.mean() if not esub.empty else np.nan
            recs.append((strat, mean_ann, med_tot, stab, eth_mean, len(sub)))
        recs.sort(key=lambda x: -(x[1] if np.isfinite(x[1]) else -9))
        print("    %-18s %10s %10s %12s %10s %s" % ("strategy", "BTCmeanAnn", "medTotal", "stability", "ETHmeanAnn", "n_cycles"))
        for strat, ma, mt, st, ea, n in recs:
            print("    %-18s %10s %10s %12s %10s %d" % (strat, fmt_pct(ma), fmt_pct(mt), st, fmt_pct(ea), n))

    # ---- question (a): trend_short whipsaw by phase
    print("\n" + "=" * 100)
    print("(a) trend_short whipsaw: per phase, gross vs net total return and trade-days (BTC, summed/averaged over cycles)")
    for strat in ("trend_short", "trend_short_f200"):
        print("\n  %s" % strat)
        print("    %-14s %10s %10s %10s %10s" % ("phase", "meanGross", "meanNet", "meanFee%", "avgTrades"))
        for ph, _, _ in PHASE_DEFS:
            sub = df[(df.asset == "BTC") & (df.strategy == strat) & (df.phase == ph)]
            if sub.empty:
                continue
            print("    %-14s %10s %10s %9.2f%% %10.1f" % (
                ph, fmt_pct(sub.gross_ret.mean()), fmt_pct(sub.total_ret.mean()),
                100 * sub.fee_drag.mean(), sub.n_trade_days.mean()))

    # ---- question (b): trend_long vs hold in P1-P3
    print("\n" + "=" * 100)
    print("(b) trend_long vs hold, per cycle-phase (BTC total return in phase)")
    for ph in [p for p, _, _ in PHASE_DEFS]:
        for cyc in ("2016", "2020", "2024"):
            tl = df[(df.asset == "BTC") & (df.strategy == "trend_long") & (df.phase == ph) & (df.cycle == cyc)]
            hd = df[(df.asset == "BTC") & (df.strategy == "hold") & (df.phase == ph) & (df.cycle == cyc)]
            if tl.empty or hd.empty:
                continue
            print("    %-14s %s  trend_long %s (MDD %s)   hold %s (MDD %s)   edge %s" % (
                ph, cyc, fmt_pct(tl.iloc[0].total_ret), fmt_pct(tl.iloc[0].mdd),
                fmt_pct(hd.iloc[0].total_ret), fmt_pct(hd.iloc[0].mdd),
                fmt_pct(tl.iloc[0].total_ret - hd.iloc[0].total_ret)))

    # ---- question (c): grid return/MDD ratio vs mix50
    print("\n" + "=" * 100)
    print("(c) grid30 vs mix50 (50%% hold + 50%% 8%% neutral): ann return, MDD, ratio (BTC mean across cycles)")
    print("    %-14s %12s %10s %8s %12s %10s %8s" % ("phase", "gridAnn", "gridMDD", "g-R/DD", "mixAnn", "mixMDD", "m-R/DD"))
    for ph, _, _ in PHASE_DEFS:
        g = df[(df.asset == "BTC") & (df.strategy == "grid30") & (df.phase == ph)]
        m = df[(df.asset == "BTC") & (df.strategy == "mix50") & (df.phase == ph)]
        if g.empty or m.empty:
            continue
        gr, gd = g.ann_ret.mean(), g.mdd.mean()
        mr, md = m.ann_ret.mean(), m.mdd.mean()
        print("    %-14s %12s %10s %8.2f %12s %10s %8.2f" % (
            ph, fmt_pct(gr), fmt_pct(gd), gr / abs(gd) if gd else np.nan,
            fmt_pct(mr), fmt_pct(md), mr / abs(md) if md else np.nan))


if __name__ == "__main__":
    main()
