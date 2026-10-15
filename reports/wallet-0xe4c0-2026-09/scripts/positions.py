"""Position-trajectory analysis for 0x4dec (pmalt vault).

The flat->flat round-trip reconstruction in overview.py breaks when a position
flips sign without passing through flat (dir "Long > Short"). Here we:
  (a) build per-coin position episodes that end on flat OR on flip;
  (b) hold-time stats overall, by era, and notional-weighted;
  (c) HYPE daily table 2026-04-10..2026-06-01: EOD position, realized pnl, close px;
  (d) current open positions: when opened, age, VWAP;
  (e) spot fills check; per-era summary; hour-of-day; long/short concurrency.

Usage: python positions.py 0x4dec0a85
"""
import gzip, json, sys, pathlib, collections, statistics, time
from datetime import datetime, timezone
import requests

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])  # stable: keep API order within the same ms (tid order != execution order)
URL = "https://api.hyperliquid.xyz/info"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def day_ms(d): return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
def fmt(s): return f"{s:.0f}s" if s < 60 else f"{s/60:.1f}m" if s < 3600 else f"{s/3600:.1f}h" if s < 86400 else f"{s/86400:.1f}d"

_c = {}
def daily(coin):
    if coin not in _c:
        r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": day_ms("2026-02-01"), "endTime": int(time.time() * 1000)}}, timeout=30)
        _c[coin] = {ts(c["t"])[:10]: c for c in (r.json() if r.status_code == 200 else [])}
        time.sleep(0.25)
    return _c[coin]

# ---- (e) spot check
spot = [f for f in fills if f["coin"].startswith("@") or "/" in f["coin"]]
print(f"spot fills: {len(spot)}")

# ---- (a) episodes: end on flat or flip
eps = []; cur = {}
for f in fills:
    c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"]); side = f["side"]
    ep = sp + (sz if side == "B" else -sz)
    if cur.get(c) is None or abs(sp) < 1e-12:
        cur[c] = {"coin": c, "t0": f["time"], "side": "L" if ep > 0 else "S", "pnl": 0.0, "fee": 0.0, "n": 0, "max_abs": 0.0, "ntl": 0.0, "taker": 0, "open_ntl": 0.0, "open_sz": 0.0, "gap": abs(sp) > 1e-12}
    r = cur[c]
    r["pnl"] += float(f["closedPnl"]); r["fee"] += float(f["fee"]); r["n"] += 1; r["taker"] += 1 if f.get("crossed") else 0
    r["max_abs"] = max(r["max_abs"], abs(ep)); r["ntl"] += float(f["px"]) * sz
    if f["dir"].startswith("Open"):
        r["open_ntl"] += float(f["px"]) * sz; r["open_sz"] += sz
    flipped = (sp > 0 > ep) or (sp < 0 < ep)
    if abs(ep) < 1e-12 or flipped:
        r["t1"] = f["time"]; r["hold_s"] = (r["t1"] - r["t0"]) / 1000; r["end"] = "flip" if flipped else "flat"
        eps.append(r); cur[c] = None
        if flipped:  # new episode starts with the residual
            cur[c] = {"coin": c, "t0": f["time"], "side": "L" if ep > 0 else "S", "pnl": 0.0, "fee": 0.0, "n": 0, "max_abs": abs(ep), "ntl": 0.0, "taker": 0, "open_ntl": float(f["px"]) * abs(ep), "open_sz": abs(ep), "gap": False}
closed = [e for e in eps if not e["gap"]]
print(f"episodes total={len(eps)} (data-gap starts dropped: {len(eps)-len(closed)})  ends: {collections.Counter(e['end'] for e in closed)}")
json.dump(eps, open(D / "episodes.json", "w"))

def hold_stats(es, label):
    if not es: print(f"  {label}: none"); return
    hs = sorted(e["hold_s"] for e in es)
    def pct(p): return hs[min(len(hs) - 1, int(p * len(hs)))]
    # notional-weighted: weight by max_abs * open vwap
    w = [(e["hold_s"], e["ntl"]) for e in es]; tw = sum(x[1] for x in w)
    acc = 0; wmed = None
    for h, n in sorted(w):
        acc += n
        if acc >= tw / 2: wmed = h; break
    wins = [e for e in es if e["pnl"] - e["fee"] > 0]; losses = [e for e in es if e["pnl"] - e["fee"] <= 0]
    b = collections.Counter()
    for s in hs: b["<10m" if s < 600 else "<1h" if s < 3600 else "<4h" if s < 14400 else "<1d" if s < 86400 else "<7d" if s < 7 * 86400 else ">=7d"] += 1
    print(f"  {label}: n={len(es)} p10={fmt(pct(.1))} p25={fmt(pct(.25))} p50={fmt(pct(.5))} p75={fmt(pct(.75))} p90={fmt(pct(.9))} max={fmt(hs[-1])} | notional-weighted median={fmt(wmed)} | buckets={dict(b)}")
    print(f"      win={len(wins)/len(es):.1%} avgWin={statistics.mean([e['pnl']-e['fee'] for e in wins]) if wins else 0:.0f} avgLoss={statistics.mean([e['pnl']-e['fee'] for e in losses]) if losses else 0:.0f} | hold(win) p50={fmt(statistics.median([e['hold_s'] for e in wins])) if wins else '-'} hold(loss) p50={fmt(statistics.median([e['hold_s'] for e in losses])) if losses else '-'}")

print("-- (b) hold time, episodes ending flat or flip:")
hold_stats(closed, "all")
eras = [("2026-03-27..07-31 (grind)", day_ms("2026-03-27"), day_ms("2026-08-01")), ("2026-08 (alt pump)", day_ms("2026-08-01"), day_ms("2026-09-01")), ("2026-09-01..09-21", day_ms("2026-09-01"), day_ms("2026-09-22"))]
for lbl, a, b in eras:
    hold_stats([e for e in closed if a <= e["t0"] < b], lbl)
hold_stats([e for e in closed if e["side"] == "L"], "long only"); hold_stats([e for e in closed if e["side"] == "S"], "short only")
hold_stats([e for e in closed if e["ntl"] >= 1e5], "episodes with notional >= 100k")

print("-- (b2) largest 15 episodes by |net| (flip-aware):")
for e in sorted(closed, key=lambda e: -abs(e["pnl"] - e["fee"]))[:15]:
    vw = e["open_ntl"] / e["open_sz"] if e["open_sz"] else 0
    print(f"   {ts(e['t0'])} -> {ts(e['t1'])} {e['coin']:>6} {e['side']} end={e['end']:>4} hold={fmt(e['hold_s']):>7} maxsz={e['max_abs']:.4g} vwap_open={vw:.5g} ntl={e['ntl']:>12.0f} fills={e['n']:>5} taker={e['taker']/e['n']:.0%} net={e['pnl']-e['fee']:>11.2f}")

# ---- (c) per-coin daily trajectory for the coins that dominate PnL
TRACK = [("PUMP", "2026-08-15", "2026-09-21"), ("HYPE", "2026-08-01", "2026-09-21"), ("BTC", "2026-08-01", "2026-09-21"), ("ZEC", "2026-09-01", "2026-09-21")]
print("-- (c) daily per tracked coin: EOD position, day realized pnl (net of fee), fills, close, cumulative net")
pos = collections.defaultdict(float); last_pos = {}
dayrow = collections.defaultdict(lambda: collections.defaultdict(lambda: {"pnl": 0.0, "n": 0, "buy": 0.0, "sell": 0.0}))
for f in fills:
    c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
    d = ts(f["time"])[:10]
    r = dayrow[d][c]; r["pnl"] += float(f["closedPnl"]) - float(f["fee"]); r["n"] += 1
    if f["side"] == "B": r["buy"] += sz
    else: r["sell"] += sz
    r["eod"] = ep; r["eod_px"] = float(f["px"])
for coin, d0, d1 in TRACK:
    cum = 0.0; cc = daily(coin)
    print(f"   [{coin}] {d0}..{d1}")
    for d in sorted(dayrow):
        if not (d0 <= d <= d1): continue
        r = dayrow[d].get(coin)
        if not r: continue
        cum += r["pnl"]; c = cc.get(d, {})
        print(f"   {d} eod_pos={r['eod']:>12.1f} buy={r['buy']:>11.0f} sell={r['sell']:>11.0f} fills={r['n']:>5} net={r['pnl']:>9.0f} cum={cum:>9.0f} {coin} o={c.get('o','-')} c={c.get('c','-')} h={c.get('h','-')} l={c.get('l','-')}")

# ---- (d) current open positions: find last flat time per coin
print("-- (d) open positions: since when")
states = json.load(open(D / "clearinghouseState_all.json"))
for ap in states["default"].get("assetPositions", []):
    p = ap["position"]; c = p["coin"]
    cf = [f for f in fills if f["coin"] == c]
    t_open = None
    for f in cf:
        sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
        if abs(sp) < 1e-12 or (sp > 0 > ep) or (sp < 0 < ep): t_open = f["time"]
    if t_open is None: t_open = cf[0]["time"] if cf else None
    age = (fills[-1]["time"] - t_open) / 1000 if t_open else 0
    rp = sum(float(f["closedPnl"]) - float(f["fee"]) for f in cf if t_open and f["time"] >= t_open)
    px = daily(c); last = list(px.values())[-1]["c"] if px else "-"
    print(f"   {c:>5} szi={p['szi']:>12} entry={p['entryPx']:>9} upnl={float(p['unrealizedPnl']):>10.0f} lev={p['leverage']['value']}x open_since={ts(t_open) if t_open else '-'} age={fmt(age)} realized_since_open={rp:.0f} last_close={last}")

# ---- (f) era summary
print("-- (f) era summary (net = closedPnl - fee)")
for lbl, a, b in eras + [("all", 0, 1 << 62)]:
    fs = [f for f in fills if a <= f["time"] < b]
    if not fs: continue
    net = sum(float(f["closedPnl"]) - float(f["fee"]) for f in fs); fee = sum(float(f["fee"]) for f in fs)
    ntl = sum(float(f["px"]) * float(f["sz"]) for f in fs); tk = sum(1 for f in fs if f.get("crossed")) / len(fs)
    days = len(set(ts(f["time"])[:10] for f in fs))
    print(f"   {lbl:>22}: fills={len(fs):>6} days={days:>3} net={net:>11.0f} fee={fee:>9.0f} ntl={ntl:>12.0f} taker={tk:.0%} fee_bps={fee/ntl*1e4:.2f}")

# ---- (g) hour-of-day (UTC) of fills & net
hod = collections.defaultdict(lambda: [0, 0.0])
for f in fills:
    h = int(ts(f["time"])[11:13]); hod[h][0] += 1; hod[h][1] += float(f["closedPnl"]) - float(f["fee"])
print("-- (g) fills by UTC hour (n, net):", {h: (v[0], round(v[1])) for h, v in sorted(hod.items())})

# ---- (h) long/short concurrency: at each fill time track sign per coin; sample daily at last fill
print("-- (h) EOD concurrency: #coins long / #coins short (sampled days, every 7th day)")
sign = {}; seen_days = []
for f in fills:
    c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
    sign[c] = ep; d = ts(f["time"])[:10]
    if not seen_days or seen_days[-1][0] != d: seen_days.append((d, None))
    seen_days[-1] = (d, {k: v for k, v in sign.items() if abs(v) > 1e-12})
for i, (d, s) in enumerate(seen_days):
    if i % 7 == 0 or d >= "2026-09-08":
        L = [k for k, v in s.items() if v > 0]; S = [k for k, v in s.items() if v < 0]
        print(f"   {d} long={len(L)} {L[:6]} short={len(S)} {S[:8]}")

# ---- day count of big moves relative to AV
print("-- (i) big days: |daily net| thresholds")
dj = json.load(open(D / "daily.json"))
for th in (2000, 5000, 10000, 20000):
    ds = [d for d, v in dj.items() if abs(v["net"]) >= th]
    print(f"   |net|>={th}: {len(ds)} days  {sorted(ds) if th >= 5000 else ''}")
