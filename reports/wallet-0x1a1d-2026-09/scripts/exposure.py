"""Dollar exposure and the May-2026 blowup in detail.

  (a) sanity: reconstructed EOD positions vs live clearinghouseState (drift check);
  (b) daily EOD gross long / gross short / net USD exposure (pair-trading test);
  (c) vault follower flows by day, 2026-05-10..05-31;
  (d) HYPE hourly position path on 2026-05-19..05-21.

Usage: python exposure.py 0x4dec0a85
"""
import gzip, json, sys, pathlib, collections, time
from datetime import datetime, timezone
import requests

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])  # stable: keep API order within the same ms (tid order != execution order)
ledger = json.load(open(D / "ledger.json"))
states = json.load(open(D / "clearinghouseState_all.json"))
URL = "https://api.hyperliquid.xyz/info"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def day_ms(d): return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

# ---- (a) final reconstructed position per coin (from last fill's startPosition+sz)
last = {}
for f in fills:
    sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
    last[f["coin"]] = (ep, f["time"], sp, sz, f["side"])
# 2026-09-21: merge ALL perp dexes (HIP-3 positions live under e.g. states["xyz"], not "default")
live = {ap["position"]["coin"]: float(ap["position"]["szi"]) for st in states.values() for ap in (st or {}).get("assetPositions", [])}
print("-- (a) reconstructed vs live:")
for c, (ep, t, sp, sz, side) in sorted(last.items(), key=lambda kv: -abs(kv[1][0])):
    lv = live.get(c, 0.0)
    if abs(ep) > 1e-9 or abs(lv) > 0:
        print(f"   {c:>6} recon={ep:>14.6f} live={lv:>14.6f} {'OK' if abs(ep-lv) < 1e-6 else 'DRIFT'} last_fill={ts(t)} start={sp} sz={sz} side={side}")

# ---- (b) daily EOD exposure with daily closes
_c = {}
def closes(coin):
    if coin not in _c:
        for i in range(5):
            r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": day_ms("2026-03-01"), "endTime": int(time.time() * 1000)}}, timeout=30)
            if r.status_code == 200: break
            time.sleep(10 * (i + 1))
        _c[coin] = {ts(c["t"])[:10]: float(c["c"]) for c in (r.json() if r.status_code == 200 else [])}
        time.sleep(0.25)
    return _c[coin]
pos = {}; days = []
for f in fills:
    sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
    pos[f["coin"]] = ep if abs(ep) > 1e-9 else 0.0
    d = ts(f["time"])[:10]
    if not days or days[-1][0] != d: days.append((d, None))
    days[-1] = (d, dict(pos))
print("-- (b) EOD USD exposure (gross long / gross short / net / n coins), every 3rd active day + all of May:")
rows = []
for d, p in days:
    L = S = 0.0; nl = ns = 0; big = []
    for c, q in p.items():
        if q == 0: continue
        px = closes(c).get(d)
        if px is None: continue
        v = q * px
        if v > 0: L += v; nl += 1
        else: S += -v; ns += 1
        big.append((c, round(v)))
    big.sort(key=lambda x: -abs(x[1]))
    rows.append((d, L, S, nl, ns, big[:5]))
json.dump(rows, open(D / "exposure_daily.json", "w"))
for i, (d, L, S, nl, ns, big) in enumerate(rows):
    if i % 3 == 0 or d >= "2026-08-15":
        print(f"   {d} long={L:>10.0f} ({nl:>2}) short={S:>10.0f} ({ns:>2}) net={L-S:>+10.0f} gross={L+S:>10.0f} top={big}")

# ---- (c) all ledger flows (deposits / withdrawals / sends), full history
print("-- (c) ledger flows (all):")
for l in ledger:
    x = l["delta"]; print(f"   {ts(l['time'])} {x.get('type')} {json.dumps({k: v for k, v in x.items() if k != 'type'})[:200]}")

# ---- (d) hourly path of one coin over a window: PUMP 08-22..08-24 (first big exit) and ZEC 09-09..09-12
def hourly(coin, d0, d1):
    print(f"-- (d) {coin} hourly {d0}..{d1}: EOH position, hour realized net, vwap buy/sell, 1h candle")
    r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": day_ms(d0), "endTime": day_ms(d1) + 86400000}}, timeout=30)
    h1 = {ts(c["t"])[:13]: c for c in r.json()} if r.status_code == 200 else {}
    hr = collections.defaultdict(lambda: {"net": 0.0, "n": 0, "bq": 0.0, "bv": 0.0, "sq": 0.0, "sv": 0.0, "eoh": None, "tk": 0})
    for f in fills:
        if f["coin"] != coin: continue
        d = ts(f["time"])[:13]
        if not (d0 <= d[:10] <= d1): continue
        x = hr[d]; sz = float(f["sz"]); px = float(f["px"]); sp = float(f["startPosition"])
        x["net"] += float(f["closedPnl"]) - float(f["fee"]); x["n"] += 1; x["eoh"] = sp + (sz if f["side"] == "B" else -sz); x["tk"] += 1 if f.get("crossed") else 0
        if f["side"] == "B": x["bq"] += sz; x["bv"] += sz * px
        else: x["sq"] += sz; x["sv"] += sz * px
    for d in sorted(hr):
        x = hr[d]; c = h1.get(d, {})
        print(f"   {d}:00 eoh_pos={x['eoh']:>12.1f} net={x['net']:>8.0f} fills={x['n']:>4} taker={x['tk']:>3} buy={x['bq']:>10.0f}@{(x['bv']/x['bq'] if x['bq'] else 0):.5g} sell={x['sq']:>10.0f}@{(x['sv']/x['sq'] if x['sq'] else 0):.5g} {coin} o={c.get('o','-')} h={c.get('h','-')} l={c.get('l','-')} c={c.get('c','-')}")
    time.sleep(0.3)
hourly("PUMP", "2026-08-22", "2026-08-24")
hourly("ZEC", "2026-09-09", "2026-09-12")
