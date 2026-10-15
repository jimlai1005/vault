"""segments.py <addr10> — split one wallet's activity into asset-class segments and compare them
as copy-trading candidates (win rate, Sharpe, drawdown, concentration).

Segments (coin -> segment, written to data/<addr10>/segments.json so copyscore.py --segment can reuse it):
  crypto   : HL native perps (no dex prefix) + spot pairs
  us_stock : HIP-3 perps whose underlying is a US-listed single stock, ADR, ETF or US equity index
  other    : every other HIP-3 market (commodities, FX, non-US stocks/indices, HL synthetic indices)
  all      : everything

Per segment:
  * realized net (closedPnl - fee), perp vs spot, funding (lower bound)
  * episodes (flat-or-flip, same cut as analyze.py): n, win rate, avg win/loss, profit factor, hold p50, taker share
  * daily P&L two ways: realized-only, and perp MTM (HL 1d closes) — Sharpe (sqrt 365), Sortino, MDD ($ and % of
    leader equity), daily win rate, best-day concentration, by-quarter Sharpe
Writes data/<addr10>/segments.txt (this report) + segments.json (coin map + metrics).
"""
import collections, gzip, json, math, pathlib, statistics, sys, time
from datetime import datetime, timezone, timedelta

import requests

ADDR10 = sys.argv[1]
ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "data" / ADDR10
CAND = ROOT / "data" / "_candles1d"
CAND.mkdir(exist_ok=True)
URL = "https://api.hyperliquid.xyz/info"

# ---------------------------------------------------------------- classification tables (xyz dex names)
US_SINGLE = {"TSLA", "NVDA", "HOOD", "INTC", "PLTR", "COIN", "META", "AAPL", "MSFT", "ORCL", "GOOGL", "AMZN", "AMD", "MU",
             "SNDK", "MSTR", "CRCL", "NFLX", "COST", "LLY", "RIVN", "USAR", "CRWV", "GME", "HIMS", "DKNG", "LITE", "BX",
             "MRVL", "RKLB", "ZM", "EBAY", "DELL", "IBM", "AVGO", "NOW", "NBIS", "WDC", "BE", "QCOM", "STRC", "AMAT", "GEV",
             "IREN", "NET", "CRWD", "RDDT", "AAOI", "MRNA", "BMNR", "CVX", "LRCX", "TWST", "GLW", "ACN", "OURA", "SNXX"}
US_ADR = {"TSM", "BABA", "ASML", "ARM", "NOK", "UMC"}
US_ETF_INDEX = {"XYZ100", "SP500", "VIX", "XLE", "SMH", "SOXL", "MAGS", "XBI", "TLT", "URNM", "EWY", "EWJ", "EWZ", "EWT"}
COMMODITY = {"GOLD", "SILVER", "CL", "COPPER", "NATGAS", "URANIUM", "ALUMINIUM", "PLATINUM", "PALLADIUM", "BRENTOIL", "CORN",
             "WHEAT", "TTF", "HO"}
FX = {"JPY", "EUR", "GBP", "KRW", "DXY"}
NON_US_EQ = {"SMSN", "SKHX", "SKHY", "HYUNDAI", "KIOXIA", "SOFTBANK", "IBIDEN", "CATL", "RELIANCE", "JIO", "CXMT", "YMTC",
             "CAMBRICON", "AMEC", "INNOLIGHT", "GIGADEV", "ZHIPU", "UNITREE", "MINIMAX", "SHEIN", "KR200", "JP225", "NIFTY",
             "IBOV", "KSTR", "KORU", "SHAZ", "SPCX"}


def is_spot(c):
    return c.startswith("@") or "/" in c


def seg_of(coin):
    if is_spot(coin) or ":" not in coin:
        return "crypto"
    dex, name = coin.split(":", 1)
    if dex == "xyz" and (name in US_SINGLE or name in US_ADR or name in US_ETF_INDEX):
        return "us_stock"
    return "other"


def sub_of(coin):
    if is_spot(coin):
        return "spot"
    if ":" not in coin:
        return "perp"
    name = coin.split(":", 1)[1]
    for lab, s in (("US單一股票", US_SINGLE), ("US ADR", US_ADR), ("US ETF/指數", US_ETF_INDEX), ("商品", COMMODITY),
                   ("外匯", FX), ("非美股票/指數", NON_US_EQ)):
        if name in s:
            return lab
    return "未分類HIP-3"


# ---------------------------------------------------------------- load
def q(payload, retries=6):
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()
        time.sleep(15 * (2 ** i) if r.status_code == 429 else 2 * (i + 1))
    r.raise_for_status()


fills = json.load(gzip.open(D / "fills.json.gz"))
tw = D / "twap_fills.json.gz"
if tw.exists():
    have = {f["tid"] for f in fills}
    fills += [f for f in json.load(gzip.open(tw)) if f["tid"] not in have]
fills.sort(key=lambda f: f["time"])
portfolio = dict(json.load(open(D / "portfolio.json")))
funding = json.load(open(D / "funding.json"))
f26 = D / "funding_2026.json"
if f26.exists():
    seen = {(x["time"], x["delta"].get("coin")) for x in funding}
    funding += [x for x in json.load(open(f26)) if (x["time"], x["delta"].get("coin")) not in seen]

ms2d = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
d2ms = lambda d: int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
fmt_h = lambda s: (f"{s:.0f}s" if s < 90 else f"{s/60:.1f}m" if s < 5400 else f"{s/3600:.1f}h" if s < 172800 else f"{s/86400:.1f}d")

DAY0, DAY1 = ms2d(fills[0]["time"]), ms2d(fills[-1]["time"])
days_all = []
d = datetime.strptime(DAY0, "%Y-%m-%d")
while d.strftime("%Y-%m-%d") <= DAY1:
    days_all.append(d.strftime("%Y-%m-%d")); d += timedelta(days=1)

coin_map = {c: seg_of(c) for c in {f["coin"] for f in fills}}
coin_sub = {c: sub_of(c) for c in coin_map}

# leader equity per day (portfolio accountValueHistory, linear interp) for % metrics
avh = sorted((int(t), float(v)) for t, v in portfolio["allTime"]["accountValueHistory"])
def L_at(day):
    t = d2ms(day)
    if t <= avh[0][0]: return avh[0][1]
    if t >= avh[-1][0]: return avh[-1][1]
    for (t0, v0), (t1, v1) in zip(avh, avh[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
L = {d: L_at(d) for d in days_all}

# ---------------------------------------------------------------- 1d closes for perp MTM
def closes_1d(coin):
    p = CAND / (coin.replace("/", "_").replace(":", "__") + ".json")
    if p.exists():
        return json.load(open(p))
    try:
        rows = q({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": d2ms(DAY0) - 86400000,
                                                     "endTime": d2ms(DAY1) + 2 * 86400000}})
        out = {ms2d(r["t"]): float(r["c"]) for r in rows} if isinstance(rows, list) else {}
    except Exception as e:  # noqa
        out = {}
    json.dump(out, open(p, "w"))
    time.sleep(0.2)
    return out


perp_coins = sorted({f["coin"] for f in fills if not is_spot(f["coin"])})
px1d = {c: closes_1d(c) for c in perp_coins}
no_px = [c for c in perp_coins if not px1d[c]]

# ---------------------------------------------------------------- episodes (flat-or-flip; identical cut to analyze.py)
def episodes(perp):
    eps, cur = [], {}
    for f in perp:
        c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"]); side = f["side"]
        ep = sp + (sz if side == "B" else -sz); px = float(f["px"])
        if cur.get(c) is None or abs(sp) < 1e-12:
            cur[c] = {"coin": c, "t0": f["time"], "side": "L" if ep > 0 else "S", "pnl": 0.0, "fee": 0.0, "n": 0,
                      "max_ntl": 0.0, "taker": 0, "gap": abs(sp) > 1e-12, "n_open": 0, "tk_open": 0, "n_close": 0, "tk_close": 0}
        r = cur[c]
        r["pnl"] += float(f["closedPnl"]); r["fee"] += float(f["fee"]); r["n"] += 1
        r["taker"] += 1 if f.get("crossed") else 0
        r["max_ntl"] = max(r["max_ntl"], abs(ep) * px)
        opening = (f["dir"].startswith("Open") or abs(ep) > abs(sp))
        if opening:
            r["n_open"] += 1; r["tk_open"] += 1 if f.get("crossed") else 0
        else:
            r["n_close"] += 1; r["tk_close"] += 1 if f.get("crossed") else 0
        flipped = (sp > 0 > ep) or (sp < 0 < ep)
        if abs(ep) < 1e-12 or flipped:
            r["t1"] = f["time"]; r["hold"] = (r["t1"] - r["t0"]) / 1000; r["net"] = r["pnl"] - r["fee"]
            eps.append(r); cur[c] = None
            if flipped:
                cur[c] = {"coin": c, "t0": f["time"], "side": "L" if ep > 0 else "S", "pnl": 0.0, "fee": 0.0, "n": 0,
                          "max_ntl": abs(ep) * px, "taker": 0, "gap": False, "n_open": 1, "tk_open": 1 if f.get("crossed") else 0,
                          "n_close": 0, "tk_close": 0}
    return [e for e in eps if not e["gap"]], [r for r in cur.values() if r]


# ---------------------------------------------------------------- daily series
class Book:
    def __init__(self): self.qty = 0.0; self.cost = 0.0
    def trade(self, dq, px):
        real = 0.0
        if self.qty * dq < 0:  # reducing
            closed = min(abs(dq), abs(self.qty)) * (1 if self.qty > 0 else -1)
            real = closed * (px - self.cost)
            self.qty -= closed; dq += closed
            if abs(self.qty) < 1e-12: self.qty = 0.0; self.cost = 0.0
        if abs(dq) > 0:
            self.cost = (self.cost * abs(self.qty) + px * abs(dq)) / (abs(self.qty) + abs(dq)) if self.qty * dq >= 0 and abs(self.qty) > 0 else px
            self.qty += dq
        return real


def daily_series(fs, fund_by_day):
    """returns (realized_daily, mtm_daily, gross_daily) over days_all. realized = closedPnl - fee (+funding, perp);
    mtm = realized + change in unrealized at HL 1d close (perp only; spot folded in as realized)."""
    real = collections.defaultdict(float); byday = collections.defaultdict(list)
    for f in fs:
        d = ms2d(f["time"])
        real[d] += float(f["closedPnl"]) - float(f["fee"])
        if not is_spot(f["coin"]):
            byday[d].append(f)
    books = collections.defaultdict(Book); prev_u = 0.0; last_px = {}
    mtm, gross = {}, {}
    seeded = set()
    for d in days_all:
        for f in byday.get(d, []):
            c = f["coin"]
            if c not in seeded:
                # fills window is truncated by the API: a coin's first fill may land on a pre-existing position
                # (startPosition != 0). Seed the book with that size at the first fill's price, so the window
                # starts with zero unrealized instead of mistaking the first reduce for an opposite-side open.
                seeded.add(c)
                sp = float(f["startPosition"])
                if abs(sp) > 1e-12:
                    books[c].qty = sp; books[c].cost = float(f["px"])
            dq = float(f["sz"]) * (1 if f["side"] == "B" else -1)
            books[c].trade(dq, float(f["px"]))
        u, g = 0.0, 0.0
        for c, b in books.items():
            if abs(b.qty) < 1e-9: continue
            px = px1d.get(c, {}).get(d, last_px.get(c))
            if px is None: continue
            last_px[c] = px
            u += b.qty * (px - b.cost); g += abs(b.qty) * px
        fd = fund_by_day.get(d, 0.0)
        mtm[d] = real.get(d, 0.0) + fd + (u - prev_u); prev_u = u
        gross[d] = g
        real[d] = real.get(d, 0.0) + fd
    return dict(real), mtm, gross


def curve_stats(series, days, label):
    xs = [series.get(d, 0.0) for d in days]
    n = len(xs); tot = sum(xs)
    mu = tot / n if n else 0.0
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    dn = [x for x in xs if x < 0]
    dsd = math.sqrt(sum(x * x for x in dn) / n) if n and dn else 0.0
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else float("nan")
    sortino = mu / dsd * math.sqrt(365) if dsd > 0 else float("nan")
    # drawdown in $ and in % of leader equity at the peak day
    cum = peak = 0.0; mdd = 0.0; mdd_pct = 0.0; dd_start = dd_end = None; cur_start = days[0]
    for d, x in zip(days, xs):
        cum += x
        if cum >= peak: peak = cum; cur_start = d
        dd = peak - cum
        if dd > mdd:
            mdd = dd; dd_start, dd_end = cur_start, d
            mdd_pct = dd / max(1.0, L[cur_start])
    act = [x for x in xs if abs(x) > 1e-9]
    pos = sum(1 for x in act if x > 0)
    srt = sorted(xs, reverse=True)
    top1 = srt[0] if srt else 0.0; top5 = sum(srt[:5])
    worst = min(xs) if xs else 0.0
    # return-based Sharpe (daily $ / leader equity) for reference
    rets = [series.get(d, 0.0) / max(1.0, L[d]) for d in days]
    rmu = statistics.fmean(rets) if rets else 0; rsd = statistics.pstdev(rets) if len(rets) > 1 else 0
    r_sharpe = rmu / rsd * math.sqrt(365) if rsd > 0 else float("nan")
    return {"label": label, "days": n, "active_days": len(act), "net": tot, "mean": mu, "sd": sd, "sharpe": sharpe,
            "sortino": sortino, "sharpe_ret": r_sharpe, "mdd": mdd, "mdd_pct": mdd_pct, "mdd_window": (dd_start, dd_end),
            "day_win": pos / len(act) if act else float("nan"), "best": top1, "best_share": top1 / tot if tot > 0 else float("nan"),
            "top5_share": top5 / tot if tot > 0 else float("nan"), "worst": worst, "ex_best5": tot - top5, "ann_ret_on_L": rmu * 365}


def fund_by_day_for(coins):
    out = collections.defaultdict(float)
    for x in funding:
        c = x["delta"].get("coin")
        if c in coins:
            out[ms2d(x["time"])] += float(x["delta"]["usdc"])
    return out


# ---------------------------------------------------------------- run per segment
SEGS = ["crypto", "crypto_perp", "us_stock", "other", "all"]
out_json = {"addr10": ADDR10, "window": [DAY0, DAY1], "coin_map": coin_map, "coin_sub": coin_sub, "segments": {}}
lines = []
P = lines.append
P(f"SEGMENTS {ADDR10}  fills={len(fills)} window {DAY0}..{DAY1} ({len(days_all)} days)  perp coins w/o 1d closes: {no_px or 'none'}")
P(f"leader equity L_t: first {L[DAY0]:,.0f} last {L[DAY1]:,.0f} peak {max(L.values()):,.0f}")
P("")
P("[0] coin classification (HIP-3 only; everything without a dex prefix and all spot pairs = crypto)")
for seg in ("us_stock", "other"):
    cs = sorted(c for c, s in coin_map.items() if s == seg)
    P(f"  {seg:<9}: " + ", ".join(f"{c}[{coin_sub[c]}]" for c in cs))
P("")

seg_fills = {s: [f for f in fills if coin_map[f["coin"]] == s] for s in ("crypto", "us_stock", "other")}
seg_fills["crypto_perp"] = [f for f in seg_fills["crypto"] if not is_spot(f["coin"])]
seg_fills["all"] = fills
# common window: first day on which all three asset classes have traded, so Sharpe/MDD are comparable
COMMON0 = max(ms2d(seg_fills[s][0]["time"]) for s in ("crypto", "us_stock", "other") if seg_fills[s])
common_days = [d for d in days_all if d >= COMMON0]
common_rows = []
rows_tbl = []
for seg in SEGS:
    fs = seg_fills[seg]
    if not fs:
        P(f"=== {seg}: no fills"); continue
    coins = {f["coin"] for f in fs}
    perp = [f for f in fs if not is_spot(f["coin"])]
    spot = [f for f in fs if is_spot(f["coin"])]
    s0, s1 = ms2d(fs[0]["time"]), ms2d(fs[-1]["time"])
    seg_days = [d for d in days_all if s0 <= d <= s1]
    ntl = sum(float(f["px"]) * float(f["sz"]) for f in fs)
    cp = sum(float(f["closedPnl"]) for f in fs); fee = sum(float(f["fee"]) for f in fs)
    cp_p = sum(float(f["closedPnl"]) - float(f["fee"]) for f in perp)
    cp_s = sum(float(f["closedPnl"]) - float(f["fee"]) for f in spot)
    fbd = fund_by_day_for(coins); fund_tot = sum(fbd.values())
    taker = sum(1 for f in fs if f.get("crossed")) / len(fs)
    closed, still_open = episodes(perp)
    wins = [e for e in closed if e["net"] > 0]; loss = [e for e in closed if e["net"] <= 0]
    gw = sum(e["net"] for e in wins); gl = -sum(e["net"] for e in loss)
    real, mtm, gross = daily_series(fs, fbd)
    cs_real = curve_stats(real, seg_days, "realized")
    cs_mtm = curve_stats(mtm, seg_days, "mtm")
    act_days = len({ms2d(f["time"]) for f in fs})

    P(f"=== {seg.upper()}  {s0}..{s1} ({len(seg_days)} d, {act_days} active)  fills={len(fs)} (perp {len(perp)}/spot {len(spot)})  coins={len(coins)}  notional={ntl:,.0f}  taker={taker:.0%}")
    P(f"  realized: closedPnl {cp:,.0f} − fee {fee:,.0f} = {cp-fee:,.0f}  (perp {cp_p:,.0f} / spot {cp_s:,.0f})  funding(lower bound) {fund_tot:,.0f}  → net incl funding {cp-fee+fund_tot:,.0f}")
    if closed:
        hold = sorted(e["hold"] for e in closed)
        pct = lambda p: hold[min(len(hold) - 1, int(p * len(hold)))]
        o_n = sum(e["n_open"] for e in closed); o_t = sum(e["tk_open"] for e in closed)
        c_n = sum(e["n_close"] for e in closed); c_t = sum(e["tk_close"] for e in closed)
        big = [e for e in closed if e["max_ntl"] >= 100_000]
        P(f"  episodes: n={len(closed)} (still open {[e['coin'] for e in still_open]})  win={len(wins)/len(closed):.1%}  avg win {gw/max(1,len(wins)):,.0f} / avg loss {-gl/max(1,len(loss)):,.0f}  "
          f"PF={gw/gl if gl else float('inf'):.2f}  median net {statistics.median(e['net'] for e in closed):,.0f}  long {sum(1 for e in closed if e['side']=='L')} / short {sum(1 for e in closed if e['side']=='S')}")
        P(f"  hold: p10 {fmt_h(pct(.1))} p25 {fmt_h(pct(.25))} p50 {fmt_h(pct(.5))} p75 {fmt_h(pct(.75))} p90 {fmt_h(pct(.9))} max {fmt_h(hold[-1])}  "
          f"max_ntl p50 {statistics.median(e['max_ntl'] for e in closed):,.0f}  entry taker {o_t/max(1,o_n):.0%}  exit taker {c_t/max(1,c_n):.0%}  "
          f"ntl≥100k: n={len(big)} win={sum(1 for e in big if e['net']>0)/max(1,len(big)):.0%} net={sum(e['net'] for e in big):,.0f}")
        by_side = {}
        for sd_ in ("L", "S"):
            es = [e for e in closed if e["side"] == sd_]
            if es:
                w = [e for e in es if e["net"] > 0]
                by_side[sd_] = (len(es), len(w) / len(es), sum(e["net"] for e in es))
        P("  by side: " + "  ".join(f"{k}: n={v[0]} win={v[1]:.0%} net={v[2]:,.0f}" for k, v in by_side.items()))
        # per-coin
        cn = collections.defaultdict(lambda: [0, 0, 0.0])
        for e in closed:
            cn[e["coin"]][0] += 1; cn[e["coin"]][1] += e["net"] > 0; cn[e["coin"]][2] += e["net"]
        top = sorted(cn.items(), key=lambda kv: -abs(kv[1][2]))[:12]
        P("  by coin (n/win/net): " + ", ".join(f"{c} {v[0]}/{v[1]/v[0]:.0%}/{v[2]:,.0f}" for c, v in top))
        # loser exits
        worst = sorted(closed, key=lambda e: e["net"])[:5]
        P("  5 worst episodes: " + "; ".join(f"{e['coin']} {e['side']} {ms2d(e['t0'])} hold {fmt_h(e['hold'])} ntl {e['max_ntl']:,.0f} net {e['net']:,.0f}" for e in worst))
        best = sorted(closed, key=lambda e: -e["net"])[:5]
        P("  5 best episodes:  " + "; ".join(f"{e['coin']} {e['side']} {ms2d(e['t0'])} hold {fmt_h(e['hold'])} ntl {e['max_ntl']:,.0f} net {e['net']:,.0f}" for e in best))
    else:
        P("  episodes: none closed")
    for cs_ in (cs_real, cs_mtm):
        P(f"  daily[{cs_['label']:<8}] net {cs_['net']:>10,.0f}  mean {cs_['mean']:>7,.0f}  sd {cs_['sd']:>7,.0f}  Sharpe {cs_['sharpe']:>5.2f}  Sortino {cs_['sortino']:>5.2f}  "
          f"Sharpe(ret/L) {cs_['sharpe_ret']:>5.2f}  ann ret on L {cs_['ann_ret_on_L']:>6.1%}  MDD {cs_['mdd']:>9,.0f} ({cs_['mdd_pct']:.1%} of L, {cs_['mdd_window'][0]}→{cs_['mdd_window'][1]})  "
          f"day win {cs_['day_win']:.0%} of {cs_['active_days']} active  best {cs_['best']:,.0f} ({cs_['best_share']:.0%})  top5 {cs_['top5_share']:.0%}  ex-top5 {cs_['ex_best5']:,.0f}  worst {cs_['worst']:,.0f}")
    srt_days = sorted(seg_days, key=lambda d: mtm.get(d, 0.0))
    P("  worst mtm days: " + ", ".join(f"{d} {mtm[d]:,.0f} (real {real.get(d,0):,.0f})" for d in srt_days[:6]))
    P("  best mtm days:  " + ", ".join(f"{d} {mtm[d]:,.0f} (real {real.get(d,0):,.0f})" for d in srt_days[-6:][::-1]))
    gmax = max(gross.values()) if gross else 0
    gmed = statistics.median([g for g in gross.values() if g > 0] or [0])
    P(f"  perp gross notional held: max {gmax:,.0f} ({gmax/max(1,max(L.values())):.1f}x of peak L)  median(active) {gmed:,.0f}")
    # by quarter (MTM)
    qs = collections.defaultdict(list)
    for d in seg_days:
        y, m = d[:4], int(d[5:7]); qs[f"{y}Q{(m-1)//3+1}"].append(d)
    qrows = []
    for k in sorted(qs):
        c = curve_stats(mtm, qs[k], k)
        qrows.append(f"{k}: net {c['net']:,.0f} Sharpe {c['sharpe']:.2f} dayWin {c['day_win']:.0%} MDD {c['mdd']:,.0f}")
    P("  by quarter (mtm): " + " | ".join(qrows))
    # hour-of-day (UTC) by fill count & net — useful for stocks (US session?)
    hh = collections.Counter(); hn = collections.defaultdict(float)
    for f in fs:
        h = datetime.fromtimestamp(f["time"] / 1000, tz=timezone.utc).hour
        hh[h] += 1; hn[h] += float(f["closedPnl"]) - float(f["fee"])
    P("  hours UTC (fills): " + ", ".join(f"{h:02d}:{hh[h]}" for h in sorted(hh)))
    P("  hours UTC (net):   " + ", ".join(f"{h:02d}:{hn[h]:,.0f}" for h in sorted(hn)))
    # monthly table
    mm = collections.defaultdict(float); mr = collections.defaultdict(float)
    for d in seg_days:
        mm[d[:7]] += mtm.get(d, 0.0); mr[d[:7]] += real.get(d, 0.0)
    P("  monthly (mtm/real): " + ", ".join(f"{k} {mm[k]:,.0f}/{mr[k]:,.0f}" for k in sorted(mm)))
    P(f"  monthly win (mtm): {sum(1 for v in mm.values() if v>0)}/{len(mm)}")
    P("")
    cc_m = curve_stats(mtm, common_days, "mtm"); cc_r = curve_stats(real, common_days, "real")
    cc_eps = [e for e in closed if ms2d(e["t0"]) >= COMMON0]
    cc_w = sum(1 for e in cc_eps if e["net"] > 0); cc_gw = sum(e["net"] for e in cc_eps if e["net"] > 0); cc_gl = -sum(e["net"] for e in cc_eps if e["net"] <= 0)
    common_rows.append((seg, len(cc_eps), cc_w / len(cc_eps) if cc_eps else float("nan"), (cc_gw / cc_gl) if cc_gl else float("inf"),
                        cc_m["net"], cc_m["sharpe"], cc_r["sharpe"], cc_m["mdd"], cc_m["mdd_pct"], cc_m["day_win"], cc_m["best_share"], cc_m["top5_share"], len(common_days)))
    out_json["segments"].setdefault("_common", {})[seg] = {"mtm": cc_m, "real": cc_r, "episodes": len(cc_eps), "ep_win": cc_w / len(cc_eps) if cc_eps else None}
    rows_tbl.append((seg, len(closed), (len(wins) / len(closed)) if closed else float("nan"), (gw / gl) if gl else float("inf"),
                     cp - fee + fund_tot, cs_mtm["sharpe"], cs_real["sharpe"], cs_mtm["mdd"], cs_mtm["mdd_pct"], cs_mtm["day_win"],
                     cs_mtm["best_share"], cs_mtm["top5_share"], len(seg_days)))
    out_json["segments"][seg] = {
        "span": [s0, s1], "days": len(seg_days), "active_days": act_days, "fills": len(fs), "perp_fills": len(perp), "spot_fills": len(spot),
        "coins": len(coins), "notional": ntl, "closedPnl": cp, "fee": fee, "net_realized": cp - fee, "perp_net": cp_p, "spot_net": cp_s,
        "funding_lb": fund_tot, "taker": taker, "episodes": len(closed), "ep_win": (len(wins) / len(closed)) if closed else None,
        "avg_win": gw / len(wins) if wins else None, "avg_loss": -gl / len(loss) if loss else None, "pf": (gw / gl) if gl else None,
        "hold_p50_s": statistics.median(e["hold"] for e in closed) if closed else None,
        "realized": cs_real, "mtm": cs_mtm, "gross_max": gmax, "daily_mtm": {d: mtm[d] for d in seg_days}, "daily_real": {d: real.get(d, 0.0) for d in seg_days},
    }

P("[SUMMARY]  (Sharpe = mean/sd of daily $ P&L × √365 over the segment's own span, zero days included; mtm = perp marked at HL 1d close)")
P(f"  {'seg':<12}{'eps':>6}{'epWin':>8}{'PF':>7}{'net':>12}{'ShMTM':>7}{'ShReal':>8}{'MDD$':>10}{'MDD%L':>7}{'dayWin':>8}{'best1':>7}{'top5':>6}{'days':>6}")
for r in rows_tbl:
    P(f"  {r[0]:<9}{r[1]:>6}{r[2]:>8.1%}{r[3]:>7.2f}{r[4]:>12,.0f}{r[5]:>7.2f}{r[6]:>8.2f}{r[7]:>10,.0f}{r[8]:>7.1%}{r[9]:>8.0%}{r[10]:>7.0%}{r[11]:>6.0%}{r[12]:>6}")

P("")
P(f"[COMMON WINDOW {COMMON0}..{DAY1}]  same days for every segment (first day all three asset classes are active)")
P(f"  {'seg':<12}{'eps':>6}{'epWin':>8}{'PF':>7}{'netMTM':>12}{'ShMTM':>7}{'ShReal':>8}{'MDD$':>10}{'MDD%L':>7}{'dayWin':>8}{'best1':>7}{'top5':>6}{'days':>6}")
for r in common_rows:
    P(f"  {r[0]:<12}{r[1]:>6}{r[2]:>8.1%}{r[3]:>7.2f}{r[4]:>12,.0f}{r[5]:>7.2f}{r[6]:>8.2f}{r[7]:>10,.0f}{r[8]:>7.1%}{r[9]:>8.0%}{r[10]:>7.0%}{r[11]:>6.0%}{r[12]:>6}")
txt = "\n".join(lines)
(D / "segments.txt").write_text(txt + "\n")
json.dump(out_json, open(D / "segments.json", "w"), default=str)
print(txt)
