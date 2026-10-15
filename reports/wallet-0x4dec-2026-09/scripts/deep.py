"""Second pass: full-life equity curve from portfolio endpoint, inbound sends,
trip debugging for a coin, and micro-structure of seconds-scale trips.

Usage: python deep.py <addr10> [debug_coin]
"""
import gzip, json, sys, pathlib, collections, statistics
from datetime import datetime, timezone

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])  # stable: keep API order within the same ms (tid order != execution order)
ledger = json.load(open(D / "ledger.json"))
portfolio = dict(json.load(open(D / "portfolio.json")))

def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

print("=" * 80); print("WALLET", sys.argv[1])
# ---- inbound/outbound sends and other ledger rows (starting capital)
print("-- ledger non-staking rows:")
for l in ledger:
    d = l["delta"]
    if d["type"] in ("cStakingTransfer", "vaultDeposit", "vaultWithdraw"): continue
    print(f"   {ts(l['time'])} {json.dumps(d)[:200]}")
st = [l for l in ledger if l["delta"]["type"] == "cStakingTransfer"]
if st:
    print(f"-- cStakingTransfer rows={len(st)} first={ts(st[0]['time'])} last={ts(st[-1]['time'])} sample={json.dumps(st[0]['delta'])[:150]}")

# ---- full-life equity curve (portfolio allTime + month) -> daily changes
print("-- portfolio allTime accountValueHistory / pnlHistory (daily deltas):")
avh = portfolio["allTime"]["accountValueHistory"]; ph = portfolio["allTime"]["pnlHistory"]
rows = []
for (t, av), (_, p) in zip(avh, ph):
    rows.append((t, float(av), float(p)))
prev = None
deltas = []
for t, av, p in rows:
    if prev:
        dp = p - prev[2]; dav = av - prev[1]
        deltas.append((ts(t)[:10], dp, dav, av, p))
    prev = (t, av, p)
for d, dp, dav, av, p in deltas:
    flag = " <==" if abs(dp) > 0.15 * max(1.0, av - dp) and abs(dp) > 500 else ""
    print(f"   {d} dPnl={dp:>11.2f} dAV={dav:>11.2f} AV={av:>11.2f} cumPnl={p:>11.2f}{flag}")
print("-- portfolio month (finer) largest |dPnl| points:")
avh = portfolio["month"]["accountValueHistory"]; ph = portfolio["month"]["pnlHistory"]
mrows = [(t, float(av), float(p)) for (t, av), (_, p) in zip(avh, ph)]
md = [(ts(mrows[i][0]), mrows[i][2] - mrows[i-1][2], mrows[i][1]) for i in range(1, len(mrows))]
for d, dp, av in sorted(md, key=lambda x: -abs(x[1]))[:10]:
    print(f"   {d} dPnl={dp:>11.2f} AV={av:>11.2f}")

# ---- debug a coin's fill sequence (optional)
if len(sys.argv) > 2:
    coin = sys.argv[2]
    print(f"-- fills for {coin} (first 80):")
    for f in [x for x in fills if x["coin"] == coin][:80]:
        print(f"   {ts(f['time'])} {f['dir']:>12} side={f['side']} sz={f['sz']:>12} px={f['px']:>10} start={f['startPosition']:>12} pnl={float(f['closedPnl']):>10.2f} fee={float(f['fee']):>7.3f} taker={f.get('crossed')} liq={'Y' if f.get('liquidation') else ''}")

# ---- micro-structure for seconds-scale trips (0x9264 style)
trips = json.load(open(D / "trips.json"))
if trips and statistics.median(t["hold_s"] for t in trips) < 60:
    print("-- micro-structure of top 8 trips:")
    byk = collections.defaultdict(list)
    for f in fills: byk[f["coin"]].append(f)
    for t in sorted(trips, key=lambda t: -abs(t["pnl"] - t["fee"]))[:8]:
        fs = [f for f in byk[t["coin"]] if t["t0"] <= f["time"] <= t["t1"]]
        opens = [f for f in fs if f["dir"].startswith("Open")]; closes = [f for f in fs if f["dir"].startswith("Close")]
        liqc = sum(1 for f in fs if f.get("liquidation"))
        po = sum(float(f["px"]) * float(f["sz"]) for f in opens) / max(1e-9, sum(float(f["sz"]) for f in opens))
        pc = sum(float(f["px"]) * float(f["sz"]) for f in closes) / max(1e-9, sum(float(f["sz"]) for f in closes))
        t_open = (opens[-1]["time"] - opens[0]["time"]) / 1000 if opens else 0
        t_gap = (closes[0]["time"] - opens[-1]["time"]) / 1000 if opens and closes else 0
        t_close = (closes[-1]["time"] - closes[0]["time"]) / 1000 if closes else 0
        print(f"   {ts(t['t0'])} {t['coin']:>9} {t['side']} net={t['pnl']-t['fee']:>9.2f} opens={len(opens)} ({t_open:.1f}s) gap={t_gap:.1f}s closes={len(closes)} ({t_close:.1f}s) vwap_open={po:.5g} vwap_close={pc:.5g} move={(pc/po-1)*1e4:+.1f}bps liq_fills={liqc}")
        # counterparties in opens: taker? and orders count
        oids_o = len(set(f["oid"] for f in opens)); oids_c = len(set(f["oid"] for f in closes))
        print(f"        orders: open_oids={oids_o} close_oids={oids_c}  open_taker={sum(1 for f in opens if f.get('crossed'))}/{len(opens)} close_taker={sum(1 for f in closes if f.get('crossed'))}/{len(closes)}")
    # overall: how many trips include liquidation fills; distribution of open->close gap
    n_liq = sum(1 for t in trips if any(f.get("liquidation") for f in byk[t["coin"]] if t["t0"] <= f["time"] <= t["t1"]))
    print(f"-- trips with any liquidation fill: {n_liq}/{len(trips)}")
    hs = [t["hold_s"] for t in trips]
    print(f"-- hold seconds: p50={statistics.median(hs):.2f} p90={sorted(hs)[int(.9*len(hs))]:.2f} max={max(hs):.2f}")
    # hour-of-day distribution of trips and pnl
    hod = collections.defaultdict(lambda: [0, 0.0])
    for t in trips:
        h = datetime.fromtimestamp(t["t0"] / 1000, tz=timezone.utc).hour
        hod[h][0] += 1; hod[h][1] += t["pnl"] - t["fee"]
    print("-- trips by UTC hour (n, net):", {h: (v[0], round(v[1])) for h, v in sorted(hod.items())})
    # net by trip size bucket
    sb = collections.defaultdict(lambda: [0, 0.0])
    for t in trips:
        b = "<10k" if t["ntl"] < 1e4 else "<50k" if t["ntl"] < 5e4 else "<200k" if t["ntl"] < 2e5 else ">=200k"
        sb[b][0] += 1; sb[b][1] += t["pnl"] - t["fee"]
    print("-- trips by notional bucket (n, net):", dict(sb))
    # what is being traded: orders per second aggregated — count distinct oids per trip
    print("-- median distinct oids per trip:", statistics.median(len(set(f["oid"] for f in byk[t["coin"]] if t["t0"] <= f["time"] <= t["t1"])) for t in trips))
