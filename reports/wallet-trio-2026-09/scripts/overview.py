"""Per-wallet overview: account state, fills profile, daily PnL, round-trips.

Usage: python overview.py <addr10>   (e.g. 0x92647819)
"""
import gzip, json, sys, pathlib, collections, statistics
from datetime import datetime, timezone, timedelta

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
fills = json.load(gzip.open(D / "fills.json.gz"))
ledger = json.load(open(D / "ledger.json"))
funding = json.load(open(D / "funding.json"))
states = json.load(open(D / "clearinghouseState_all.json"))
spot = json.load(open(D / "spotClearinghouseState.json"))
portfolio = json.load(open(D / "portfolio.json"))
openo = json.load(open(D / "frontendOpenOrders.json"))
ua = json.load(open(D / "userAbstraction.json"))

def ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

fills.sort(key=lambda f: (f["time"], f.get("tid", 0)))
print("=" * 80)
print(f"WALLET {sys.argv[1]}  fills={len(fills)}  range {ts(fills[0]['time'])} .. {ts(fills[-1]['time'])}")
print(f"userAbstraction={ua}")

# ---- account state
tot_av = 0.0
for dex, st in states.items():
    ms = st.get("marginSummary", {})
    av = float(ms.get("accountValue", 0))
    if av > 0 or st.get("assetPositions"):
        tot_av += av
        print(f"  dex={dex}: accountValue={av:.2f} totalNtl={float(ms.get('totalNtlPos',0)):.2f} withdrawable={float(st.get('withdrawable',0)):.2f}")
        for ap in st.get("assetPositions", []):
            p = ap["position"]
            print(f"     pos {p['coin']} szi={p['szi']} entry={p['entryPx']} upnl={p['unrealizedPnl']} lev={p['leverage']} liq={p.get('liquidationPx')}")
print(f"  spot balances: {[(b['coin'], b['total']) for b in spot.get('balances', []) if float(b['total'])>0]}")
print(f"  open orders: {len(openo)}")
for o in openo[:15]:
    print(f"     {o['coin']} {o['side']} sz={o['sz']} px={o['limitPx']} type={o.get('orderType')} tif={o.get('tif')} reduce={o.get('reduceOnly')} trig={o.get('triggerPx')}")

# ---- portfolio (allTime accountValueHistory)
pf = dict(portfolio)
for k in ("allTime", "month", "week"):
    if k in pf:
        avh = pf[k]["accountValueHistory"]; ph = pf[k]["pnlHistory"]
        print(f"  portfolio[{k}]: n={len(avh)} first={ts(avh[0][0])} av={avh[0][1]} last={ts(avh[-1][0])} av={avh[-1][1]}  pnl_last={ph[-1][1]} vlm={pf[k]['vlm']}")

# ---- ledger
lc = collections.Counter(l["delta"]["type"] for l in ledger)
print(f"  ledger types: {dict(lc)}")
dep = wd = 0.0
for l in ledger:
    d = l["delta"]; t = d["type"]
    if t == "deposit": dep += float(d["usdc"])
    elif t == "withdraw": wd += float(d["usdc"])
    elif t in ("accountClassTransfer",):
        pass
print(f"  deposits={dep:.2f} withdrawals={wd:.2f}")
for l in ledger:
    d = l["delta"]
    if d["type"] in ("deposit", "withdraw", "internalTransfer", "subAccountTransfer", "vaultDeposit", "vaultWithdraw"):
        print(f"     {ts(l['time'])} {d['type']} {d.get('usdc', d)}" if d["type"] in ("deposit","withdraw") else f"     {ts(l['time'])} {d['type']} {json.dumps(d)[:160]}")

# ---- fills profile
coins = collections.Counter(f["coin"] for f in fills)
print(f"  coins ({len(coins)}): {coins.most_common(20)}")
dirs = collections.Counter(f.get("dir") for f in fills)
print(f"  dirs: {dict(dirs)}")
crossed = collections.Counter(f.get("crossed") for f in fills)
print(f"  crossed(taker=True): {dict(crossed)}")
fees = sum(float(f["fee"]) for f in fills)
cpnl = sum(float(f["closedPnl"]) for f in fills)
ntl = sum(float(f["px"]) * float(f["sz"]) for f in fills if not f["coin"].startswith("@") and "/" not in f["coin"])
print(f"  sum closedPnl={cpnl:.2f} fees={fees:.2f} perp notional traded={ntl:.0f}")
fund = sum(float(x["delta"]["usdc"]) for x in funding)
print(f"  funding(last {len(funding)} rows, {ts(funding[0]['time']) if funding else '-'}..): {fund:.2f}")
liq = [f for f in fills if f.get("liquidation")]
print(f"  liquidation fills: {len(liq)}")
for f in liq[:10]:
    print(f"     {ts(f['time'])} {f['coin']} {f['dir']} sz={f['sz']} px={f['px']} pnl={f['closedPnl']} {f['liquidation']}")

# ---- daily pnl (closedPnl - fee), by UTC day
day = collections.defaultdict(lambda: {"pnl": 0.0, "fee": 0.0, "n": 0, "ntl": 0.0, "coins": collections.Counter()})
for f in fills:
    d = ts(f["time"])[:10]
    day[d]["pnl"] += float(f["closedPnl"]); day[d]["fee"] += float(f["fee"]); day[d]["n"] += 1
    day[d]["ntl"] += float(f["px"]) * float(f["sz"]); day[d]["coins"][f["coin"]] += 1
days = sorted(day.items())
print(f"  active days={len(days)}  span days={(datetime.strptime(days[-1][0],'%Y-%m-%d')-datetime.strptime(days[0][0],'%Y-%m-%d')).days+1}")
net = [(d, v["pnl"] - v["fee"]) for d, v in days]
sd = statistics.pstdev([x[1] for x in net]) if len(net) > 1 else 0
print(f"  daily net pnl: mean={statistics.mean([x[1] for x in net]):.2f} sd={sd:.2f}")
print("  top 12 |daily net pnl|:")
for d, v in sorted(days, key=lambda kv: -abs(kv[1]["pnl"] - kv[1]["fee"]))[:12]:
    print(f"     {d} net={v['pnl']-v['fee']:>12.2f} fills={v['n']:>5} ntl={v['ntl']:>12.0f} coins={v['coins'].most_common(4)}")

# ---- round-trip reconstruction per coin
# position runs: from flat -> nonflat -> flat. Use startPosition field to align.
trips = []
cur = {}
for f in fills:
    c = f["coin"]
    if c.startswith("@") or "/" in c:  # spot
        continue
    sp = float(f["startPosition"]); sz = float(f["sz"]); side = f["side"]
    ep = sp + (sz if side == "B" else -sz)
    if cur.get(c) is None or abs(sp) < 1e-12:
        # start a new run (flat -> nonflat); a previous unclosed run is dropped (data gap)
        cur[c] = {"coin": c, "t0": f["time"], "side": "L" if side == "B" else "S", "open": True, "pnl": 0.0, "fee": 0.0,
                  "n": 0, "max_abs": 0.0, "ntl": 0.0, "px0": float(f["px"]), "taker": 0}
    r = cur[c]
    if r is None:
        continue
    r["pnl"] += float(f["closedPnl"]); r["fee"] += float(f["fee"]); r["n"] += 1
    r["max_abs"] = max(r["max_abs"], abs(ep)); r["ntl"] += float(f["px"]) * sz
    r["taker"] += 1 if f.get("crossed") else 0
    if abs(ep) < 1e-12:
        r["t1"] = f["time"]; r["open"] = False; r["px1"] = float(f["px"])
        r["hold_s"] = (r["t1"] - r["t0"]) / 1000
        trips.append(r); cur[c] = None
closed = [t for t in trips]
print(f"  round-trips closed={len(closed)}  still open={[c for c, r in cur.items() if r and r['open']]}")
if closed:
    hs = sorted(t["hold_s"] for t in closed)
    def pct(p): return hs[min(len(hs) - 1, int(p * len(hs)))]
    def fmt(s):
        return f"{s/60:.1f}m" if s < 3600 else (f"{s/3600:.1f}h" if s < 86400 else f"{s/86400:.1f}d")
    print(f"  hold time: p10={fmt(pct(.1))} p25={fmt(pct(.25))} median={fmt(pct(.5))} p75={fmt(pct(.75))} p90={fmt(pct(.9))} max={fmt(hs[-1])}")
    buckets = collections.Counter()
    for s in hs:
        buckets["<1m" if s < 60 else "<10m" if s < 600 else "<1h" if s < 3600 else "<4h" if s < 14400 else "<1d" if s < 86400 else "<7d" if s < 7 * 86400 else ">=7d"] += 1
    print(f"  hold buckets: {dict(buckets)}")
    wins = [t for t in closed if t["pnl"] - t["fee"] > 0]
    print(f"  win rate={len(wins)/len(closed):.2%}  avg win={statistics.mean([t['pnl']-t['fee'] for t in wins]) if wins else 0:.2f}  avg loss={statistics.mean([t['pnl']-t['fee'] for t in closed if t['pnl']-t['fee']<=0]) if len(wins)<len(closed) else 0:.2f}")
    ls = collections.Counter(t["side"] for t in closed)
    print(f"  long/short trips: {dict(ls)}  pnl long={sum(t['pnl']-t['fee'] for t in closed if t['side']=='L'):.2f} short={sum(t['pnl']-t['fee'] for t in closed if t['side']=='S'):.2f}")
    print("  top 12 |trip net pnl|:")
    for t in sorted(closed, key=lambda t: -abs(t["pnl"] - t["fee"]))[:12]:
        print(f"     {ts(t['t0'])} -> {ts(t['t1'])} {t['coin']:>8} {t['side']} hold={fmt(t['hold_s']):>7} maxsz={t['max_abs']:.4g} ntl={t['ntl']:>11.0f} fills={t['n']:>4} taker%={t['taker']/t['n']:.0%} net={t['pnl']-t['fee']:>10.2f}")
    # per coin summary
    pc = collections.defaultdict(lambda: [0, 0.0])
    for t in closed:
        pc[t["coin"]][0] += 1; pc[t["coin"]][1] += t["pnl"] - t["fee"]
    print("  per-coin trips/net:", sorted(((c, n, round(p, 0)) for c, (n, p) in pc.items()), key=lambda x: -abs(x[2]))[:15])
json.dump(closed, open(D / "trips.json", "w"))
json.dump({d: {"net": v["pnl"] - v["fee"], "n": v["n"], "ntl": v["ntl"]} for d, v in days}, open(D / "daily.json", "w"))
