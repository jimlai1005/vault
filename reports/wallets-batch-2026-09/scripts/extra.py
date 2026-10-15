"""Wallet-specific extras (2026-09-21, 0x1a1d): liquidation-fill roles, HIP-3 vs crypto split,
resting-ladder notional vs equity, weekday profile, self-liquidation list.

Usage: python extra.py 0x1a1d5ef3
"""
import gzip, json, pathlib, sys, collections
from datetime import datetime, timezone

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
ADDR = "0x1a1d5ef3256e1a7de2db2082d7a1eeb976c90111"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])
net = lambda f: float(f["closedPnl"]) - float(f["fee"])

# (a) liquidation fills: who was liquidated, and was this wallet maker or taker on them
print("-- (a) liquidation fills by role:")
role = collections.Counter(); role_ntl = collections.defaultdict(float); role_pnl = collections.defaultdict(float)
selfliq = []
for f in fills:
    lq = f.get("liquidation")
    if not lq: continue
    me = lq.get("liquidatedUser", "").lower() == ADDR
    mk = "taker" if f["crossed"] else "maker"
    k = ("SELF liquidated" if me else f"counterparty ({mk})")
    role[k] += 1; role_ntl[k] += float(f["px"]) * float(f["sz"]); role_pnl[k] += net(f)
    if me: selfliq.append(f)
for k in role: print(f"   {k:>22}: n={role[k]:>3} ntl={role_ntl[k]:>8.0f} net={role_pnl[k]:>8.2f}")
print("   self-liquidation fills:")
for f in selfliq: print(f"     {ts(f['time'])} {f['coin']:>12} {f['dir']:>22} sz={f['sz']} px={f['px']} net={net(f):.2f}")

# (b) HIP-3 (xyz:) vs crypto
print("-- (b) HIP-3 (xyz:*) vs crypto perps:")
g = collections.defaultdict(lambda: {"n": 0, "net": 0.0, "fee": 0.0, "ntl": 0.0, "taker": 0, "coins": set()})
for f in fills:
    k = "HIP-3" if f["coin"].startswith("xyz:") else "crypto"
    r = g[k]; r["n"] += 1; r["net"] += net(f); r["fee"] += float(f["fee"]); r["ntl"] += float(f["px"]) * float(f["sz"]); r["taker"] += f["crossed"]; r["coins"].add(f["coin"])
for k, r in g.items():
    print(f"   {k:>7}: fills={r['n']:>5} coins={len(r['coins']):>2} net={r['net']:>8.2f} fee={r['fee']:>6.2f} ntl={r['ntl']:>8.0f} taker={r['taker']/r['n']:.0%} fee_bps={r['fee']/r['ntl']*1e4:.2f}")
print("   per-coin net (all 35):", sorted(((c, round(sum(net(f) for f in fills if f["coin"] == c), 1)) for c in {f["coin"] for f in fills}), key=lambda kv: -kv[1]))

# (c) resting ladder notional vs equity
oo = json.load(open(D / "frontendOpenOrders.json"))
port = json.load(open(D / "portfolio.json"))
av = float(dict(port)["allTime"]["accountValueHistory"][-1][1])
bid = sum(float(o["limitPx"]) * float(o["sz"]) for o in oo if o["side"] == "B")
ask = sum(float(o["limitPx"]) * float(o["sz"]) for o in oo if o["side"] == "A")
print(f"-- (c) resting orders: bids ntl={bid:.0f} asks ntl={ask:.0f} vs accountValue={av:.2f} -> bids/equity={bid/av:.2f}x; all ALO={all(o.get('tif')=='Alo' for o in oo)}")

# (d) weekday profile (UTC)
print("-- (d) net by UTC weekday (Mon=0):")
wd = collections.defaultdict(lambda: [0, 0.0])
for f in fills:
    d = datetime.fromtimestamp(f["time"] / 1000, tz=timezone.utc).weekday(); wd[d][0] += 1; wd[d][1] += net(f)
print("   ", {d: (wd[d][0], round(wd[d][1], 1)) for d in sorted(wd)})

# (e) maker share by month
print("-- (e) maker share of OPENING fills by month:")
bym = collections.defaultdict(lambda: [0, 0])
for f in fills:
    if not f["dir"].startswith("Open"): continue
    m = ts(f["time"])[:7]; bym[m][0] += 1; bym[m][1] += (not f["crossed"])
print("   ", {m: f"{v[1]}/{v[0]} = {v[1]/v[0]:.0%}" for m, v in sorted(bym.items())})

# (f) daily net threshold vs equity (5% of 1304 = 65)
daily = collections.defaultdict(float)
for f in fills: daily[ts(f["time"])[:10]] += net(f)
big = sorted(daily.items(), key=lambda kv: -abs(kv[1]))
print(f"-- (f) daily net: days={len(daily)} |net|>=5% eq(65)={sum(abs(v)>=65 for v in daily.values())} |net|>=2% eq(26)={sum(abs(v)>=26 for v in daily.values())} top5={[(d, round(v, 1)) for d, v in big[:5]]}")
print(f"   positive days={sum(v>0 for v in daily.values())} negative={sum(v<0 for v in daily.values())} worst={big and min(daily.values()):.2f}")

# (g) self-liquidation anatomy: adverse move from trip VWAP-open to liquidation px, and how HIP-3 losers end
print("-- (g) self-liquidation anatomy (HIP-3): entry VWAP of the open leg vs liquidation px")
pos = collections.defaultdict(lambda: {"sz": 0.0, "cost": 0.0, "t0": None, "n_open": 0})
liq_moves = []; hip_loss_end = collections.Counter(); hip_trip = []
cur = {}
for f in fills:
    c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"]); px = float(f["px"]); side = 1 if f["side"] == "B" else -1
    ep = sp + side * sz
    st = cur.setdefault(c, {"open_sz": 0.0, "open_cost": 0.0, "net": 0.0, "t0": None, "liq": False})
    if abs(sp) < 1e-12: st.update(open_sz=0.0, open_cost=0.0, net=0.0, t0=f["time"], liq=False)
    if f["dir"].startswith("Open") or (abs(ep) > abs(sp)):
        st["open_sz"] += sz; st["open_cost"] += sz * px
    st["net"] += net(f)
    lq = f.get("liquidation")
    if lq and lq.get("liquidatedUser", "").lower() == ADDR:
        st["liq"] = True
        vw = st["open_cost"] / st["open_sz"] if st["open_sz"] else px
        mv = (px / vw - 1) * (1 if sp > 0 else -1) * 1e4
        liq_moves.append((f["time"], c, vw, px, mv, sz * px))
    if abs(ep) < 1e-12 and c.startswith("xyz:"):
        hip_trip.append((c, st["net"], st["liq"], (f["time"] - st["t0"]) / 1000 if st["t0"] else 0))
        if st["net"] < 0: hip_loss_end["liquidated" if st["liq"] else "manual close"] += 1
import statistics
mvs = sorted(m[4] for m in liq_moves)
print(f"   n={len(liq_moves)} adverse move open-VWAP->liq px (bps): p10={mvs[int(.1*len(mvs))]:.0f} p50={statistics.median(mvs):.0f} p90={mvs[int(.9*len(mvs))]:.0f} min={mvs[0]:.0f} max={mvs[-1]:.0f}")
print(f"   HIP-3 losing trips end by: {dict(hip_loss_end)}  (HIP-3 trips total={len(hip_trip)}, winners={sum(1 for t in hip_trip if t[1]>0)})")
liq_trips = [t for t in hip_trip if t[2]]
print(f"   HIP-3 trips containing a self-liquidation: n={len(liq_trips)} sum net={sum(t[1] for t in liq_trips):.2f} median hold={statistics.median([t[3] for t in liq_trips])/3600:.1f}h")
nonliq = [t for t in hip_trip if not t[2]]
print(f"   HIP-3 trips without liquidation: n={len(nonliq)} sum net={sum(t[1] for t in nonliq):.2f} win={sum(1 for t in nonliq if t[1]>0)/len(nonliq):.0%}")
# (h) live leverage settings per coin from clearinghouseState (all dexes)
states = json.load(open(D / "clearinghouseState_all.json"))
print("-- (h) live positions leverage:", [(ap["position"]["coin"], ap["position"]["leverage"], ap["position"].get("marginUsed")) for st in states.values() for ap in (st or {}).get("assetPositions", [])])
print("   xyz dex marginSummary:", states.get("xyz", {}).get("marginSummary"), " default:", states.get("default", {}).get("marginSummary"))

# (i) bot fingerprint: seconds-of-minute histogram, inter-fill cadence, re-entry latency after self-liquidation, clip-size discreteness
print("-- (i) bot fingerprint")
sec = collections.Counter(int((f["time"] // 1000) % 60) // 5 * 5 for f in fills if f["crossed"])
tot = sum(sec.values())
print("   taker fills by second-of-minute (5s bins, share):", {k: f"{v/tot:.0%}" for k, v in sorted(sec.items())})
sec_m = collections.Counter(int((f["time"] // 1000) % 60) // 5 * 5 for f in fills if not f["crossed"])
tm = sum(sec_m.values())
print("   maker fills by second-of-minute (5s bins, share):", {k: f"{v/tm:.0%}" for k, v in sorted(sec_m.items())})
minute_mod5 = collections.Counter(int((f["time"] // 60000) % 5) for f in fills if f["crossed"])
print("   taker fills by (minute mod 5):", {k: f"{v/tot:.0%}" for k, v in sorted(minute_mod5.items())})
# re-entry latency after self-liquidation
lat = []
for i, f in enumerate(fills):
    lq = f.get("liquidation")
    if not (lq and lq.get("liquidatedUser", "").lower() == ADDR): continue
    for g_ in fills[i + 1:]:
        if g_["coin"] == f["coin"] and g_["dir"].startswith("Open"):
            lat.append((g_["time"] - f["time"]) / 1000); break
lat.sort()
print(f"   re-entry after self-liquidation (same coin, next Open): n={len(lat)} p10={lat[int(.1*len(lat))]:.0f}s p50={statistics.median(lat):.0f}s p90={lat[int(.9*len(lat))]/60:.0f}m  <=60s: {sum(l<=60 for l in lat)}  <=5m: {sum(l<=300 for l in lat)}")
# clip-size discreteness per coin (top coins): distinct open sizes / opening fills
print("   opening clip sizes (top coins): distinct sizes / n opens, top-3 sizes share")
for c in ["HYPE", "xyz:SNDK", "xyz:SPCX", "ETH", "BTC", "BNB", "xyz:INTC", "XRP"]:
    szs = collections.Counter(f["sz"] for f in fills if f["coin"] == c and f["dir"].startswith("Open"))
    n = sum(szs.values()); top3 = szs.most_common(3)
    print(f"     {c:>9}: {len(szs):>3} distinct / {n:>4} opens; top3={[(s, round(k/n, 2)) for s, k in top3]}")
# median gap between consecutive taker fills on same coin (minutes), all coins
gaps = collections.defaultdict(list); last = {}
for f in fills:
    if not f["crossed"]: continue
    c = f["coin"]
    if c in last: gaps[c].append((f["time"] - last[c]) / 60000)
    last[c] = f["time"]
allg = sorted(g_ for v in gaps.values() for g_ in v)
print(f"   same-coin taker fill gap (min): p25={allg[len(allg)//4]:.1f} p50={allg[len(allg)//2]:.1f} p75={allg[3*len(allg)//4]:.1f}; share within 4.5–5.5 min or 9.5–10.5 min: {sum(1 for g_ in allg if 4.5<=g_<=5.5 or 9.5<=g_<=10.5)/len(allg):.0%}; share <1 min: {sum(1 for g_ in allg if g_<1)/len(allg):.0%}")
