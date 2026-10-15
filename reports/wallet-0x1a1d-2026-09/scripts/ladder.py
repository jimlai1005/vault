"""Ladder-specific diagnostics for 0xe4c0 (post-only ladder wallet).

  (a) live open orders grouped by coin: n, px range, median step (bps), notional, distance to last px, orderType/tif;
  (b) historical entry ladders: for each episode with >=10 opening fills, price span of opening fills (bps),
      distinct oids, share of maker; same for exits; split winners vs losers (does it market-out losers?);
  (c) CASHCAT hourly 2026-09-18..09-20 (the -12k day) with taker counts;
  (d) spot pair name lookup for '@NNN' coins;
  (e) per-episode "max adverse fill" proxy: for long episodes, (min open px / first open px - 1) = how deep the ladder got filled.

Usage: python ladder.py 0xe4c0f755
"""
import gzip, json, sys, pathlib, collections, statistics, time
from datetime import datetime, timezone
import requests

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])
oo = json.load(open(D / "frontendOpenOrders.json"))
URL = "https://api.hyperliquid.xyz/info"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def day_ms(d): return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
def fmt(s): return f"{s:.0f}s" if s < 60 else f"{s/60:.1f}m" if s < 3600 else f"{s/3600:.1f}h" if s < 86400 else f"{s/86400:.1f}d"

# ---- (d) spot pair lookup
spot_names = {}
try:
    sm = requests.post(URL, json={"type": "spotMeta"}, timeout=30).json()
    tok = {t["index"]: t["name"] for t in sm["tokens"]}
    for u in sm["universe"]:
        spot_names[u["name"]] = "/".join(tok.get(i, str(i)) for i in u["tokens"])
except Exception as e:
    print("spotMeta failed", e)
used = sorted({f["coin"] for f in fills if f["coin"].startswith("@")})
print("-- (d) spot pairs used:", {c: spot_names.get(c) for c in used})

# ---- (a) live ladder
mids = requests.post(URL, json={"type": "allMids"}, timeout=30).json()
print(f"-- (a) live open orders: {len(oo)} total")
byc = collections.defaultdict(list)
for o in oo: byc[o["coin"]].append(o)
for c, os_ in sorted(byc.items(), key=lambda kv: -len(kv[1])):
    pxs = sorted(float(o["limitPx"]) for o in os_)
    steps = [(pxs[i + 1] / pxs[i] - 1) * 1e4 for i in range(len(pxs) - 1)]
    ntl = sum(float(o["limitPx"]) * float(o["sz"]) for o in os_)
    mid = float(mids.get(c, 0) or 0)
    sides = collections.Counter(o["side"] for o in os_)
    types = collections.Counter((o.get("orderType"), o.get("tif"), o.get("reduceOnly")) for o in os_)
    print(f"   {c:>8} n={len(os_):>3} sides={dict(sides)} px {pxs[0]:.6g}..{pxs[-1]:.6g} (span {(pxs[-1]/pxs[0]-1)*1e4:.0f} bps) median step={statistics.median(steps) if steps else 0:.1f} bps ntl={ntl:>9.0f} mid={mid:.6g} dist(top)={(pxs[-1]/mid-1)*1e4 if mid else 0:+.0f} bps dist(bottom)={(pxs[0]/mid-1)*1e4 if mid else 0:+.0f} bps types={dict(types)}")

# ---- (b)(e) historical entry/exit ladders per episode
eps = json.load(open(D / "episodes.json"))
byk = collections.defaultdict(list)
for f in fills: byk[f["coin"]].append(f)
rows = []
for e in eps:
    if e.get("gap"): continue
    fs = [f for f in byk[e["coin"]] if e["t0"] <= f["time"] <= e["t1"]]
    opens = [f for f in fs if f["dir"].startswith("Open") or f["dir"] in ("Buy",) and e["side"] == "L"]
    closes = [f for f in fs if f["dir"].startswith("Close") or f["dir"] in ("Sell",) and e["side"] == "L"]
    if not opens: continue
    op = [float(f["px"]) for f in opens]; cp = [float(f["px"]) for f in closes]
    r = {"coin": e["coin"], "side": e["side"], "t0": e["t0"], "hold": e["hold_s"], "net": e["pnl"] - e["fee"], "ntl": e["ntl"],
         "n_open": len(opens), "open_span_bps": (max(op) / min(op) - 1) * 1e4, "open_oids": len({f["oid"] for f in opens}),
         "open_maker": sum(1 for f in opens if not f.get("crossed")) / len(opens),
         "n_close": len(closes), "close_span_bps": (max(cp) / min(cp) - 1) * 1e4 if cp else 0, "close_oids": len({f["oid"] for f in closes}),
         "close_maker": sum(1 for f in closes if not f.get("crossed")) / len(closes) if closes else 0,
         "open_dur": (opens[-1]["time"] - opens[0]["time"]) / 1000, "close_dur": (closes[-1]["time"] - closes[0]["time"]) / 1000 if closes else 0,
         "depth_bps": (min(op) / op[0] - 1) * 1e4 if e["side"] == "L" else (max(op) / op[0] - 1) * 1e4}
    rows.append(r)
def summ(rs, label):
    if not rs: print(f"  {label}: none"); return
    med = lambda k: statistics.median(r[k] for r in rs)
    print(f"  {label}: n={len(rs)} | open: fills p50={med('n_open'):.0f} oids p50={med('open_oids'):.0f} span p50={med('open_span_bps'):.0f} bps maker p50={med('open_maker'):.0%} build-dur p50={fmt(med('open_dur'))} depth p50={med('depth_bps'):+.0f} bps"
          f" | close: fills p50={med('n_close'):.0f} oids p50={med('close_oids'):.0f} span p50={med('close_span_bps'):.0f} bps maker p50={med('close_maker'):.0%} unwind-dur p50={fmt(med('close_dur'))}")
print("-- (b) ladder shape per episode (medians):")
big = [r for r in rows if r["n_open"] >= 10]
summ(rows, "all episodes"); summ(big, "episodes with >=10 opening fills")
summ([r for r in big if r["net"] > 0], "  ...winners"); summ([r for r in big if r["net"] <= 0], "  ...losers")
summ([r for r in rows if r["net"] <= 0], "all losers"); summ([r for r in rows if r["net"] <= 0 and r["net"] < -500], "losers < -500")
summ([r for r in rows if r["t0"] >= day_ms("2026-08-01")], "since 2026-08-01"); summ([r for r in rows if r["t0"] < day_ms("2026-08-01")], "before 2026-08-01")
print("-- (b2) 12 deepest ladders (long, most negative depth):")
for r in sorted([r for r in rows if r["side"] == "L"], key=lambda r: r["depth_bps"])[:12]:
    print(f"   {ts(r['t0'])} {r['coin']:>8} depth={r['depth_bps']:+6.0f} bps span={r['open_span_bps']:5.0f} bps opens={r['n_open']:>4} maker={r['open_maker']:.0%} hold={fmt(r['hold']):>6} ntl={r['ntl']:>8.0f} net={r['net']:>9.0f} close_maker={r['close_maker']:.0%}")
print("-- (b3) 12 worst episodes: how were they exited?")
for r in sorted(rows, key=lambda r: r["net"])[:12]:
    print(f"   {ts(r['t0'])} {r['coin']:>8} {r['side']} net={r['net']:>8.0f} hold={fmt(r['hold']):>6} opens={r['n_open']:>3} depth={r['depth_bps']:+5.0f} bps closes={r['n_close']:>3} close_maker={r['close_maker']:.0%} unwind={fmt(r['close_dur']):>6}")
json.dump(rows, open(D / "ladder_rows.json", "w"))

# ---- (c) CASHCAT hourly 09-18..09-20
def hourly(coin, d0, d1):
    print(f"-- (c) {coin} hourly {d0}..{d1}: EOH position, hour realized net, taker fills, vwap buy/sell, 1h candle")
    r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": day_ms(d0), "endTime": day_ms(d1) + 86400000}}, timeout=30)
    h1 = {ts(c["t"])[:13]: c for c in r.json()} if r.status_code == 200 else {}
    hr = collections.defaultdict(lambda: {"net": 0.0, "n": 0, "bq": 0.0, "bv": 0.0, "sq": 0.0, "sv": 0.0, "eoh": None, "tk": 0, "tk_sell": 0.0})
    for f in fills:
        if f["coin"] != coin: continue
        d = ts(f["time"])[:13]
        if not (d0 <= d[:10] <= d1): continue
        x = hr[d]; sz = float(f["sz"]); px = float(f["px"]); sp = float(f["startPosition"])
        x["net"] += float(f["closedPnl"]) - float(f["fee"]); x["n"] += 1; x["eoh"] = sp + (sz if f["side"] == "B" else -sz); x["tk"] += 1 if f.get("crossed") else 0
        if f["side"] == "B": x["bq"] += sz; x["bv"] += sz * px
        else:
            x["sq"] += sz; x["sv"] += sz * px
            if f.get("crossed"): x["tk_sell"] += sz
    for d in sorted(hr):
        x = hr[d]; c = h1.get(d, {})
        print(f"   {d}:00 eoh_pos={x['eoh']:>12.1f} net={x['net']:>8.0f} fills={x['n']:>4} taker={x['tk']:>3} buy={x['bq']:>10.0f}@{(x['bv']/x['bq'] if x['bq'] else 0):.5g} sell={x['sq']:>10.0f}@{(x['sv']/x['sq'] if x['sq'] else 0):.5g} (taker-sold {x['tk_sell']:.0f}) {coin} o={c.get('o','-')} h={c.get('h','-')} l={c.get('l','-')} c={c.get('c','-')}")
hourly("CASHCAT", "2026-09-18", "2026-09-20")
hourly("VVV", "2026-09-19", "2026-09-20")

# ---- (f) 1-minute view of CASHCAT 09-20 11:00-14:00 (the flash crash): fills by minute
print("-- (f) CASHCAT 2026-09-20 11:00..14:00 by minute (net, fills, taker, buy qty@vwap, sell qty@vwap):")
mm = collections.defaultdict(lambda: {"net": 0.0, "n": 0, "tk": 0, "bq": 0.0, "bv": 0.0, "sq": 0.0, "sv": 0.0, "eom": None})
for f in fills:
    if f["coin"] != "CASHCAT": continue
    t = ts(f["time"])
    if not ("2026-09-20 11:00" <= t < "2026-09-20 14:00"): continue
    x = mm[t[:16]]; sz = float(f["sz"]); px = float(f["px"]); sp = float(f["startPosition"])
    x["net"] += float(f["closedPnl"]) - float(f["fee"]); x["n"] += 1; x["tk"] += 1 if f.get("crossed") else 0; x["eom"] = sp + (sz if f["side"] == "B" else -sz)
    if f["side"] == "B": x["bq"] += sz; x["bv"] += sz * px
    else: x["sq"] += sz; x["sv"] += sz * px
for k in sorted(mm):
    x = mm[k]
    print(f"   {k} pos={x['eom']:>10.0f} net={x['net']:>7.0f} n={x['n']:>3} tk={x['tk']:>3} buy={x['bq']:>8.0f}@{(x['bv']/x['bq'] if x['bq'] else 0):.4g} sell={x['sq']:>8.0f}@{(x['sv']/x['sq'] if x['sq'] else 0):.4g}")
