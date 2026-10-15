"""Initiator-vs-follower test for seconds-scale trips (0x9264).

For each of the largest trips in the last ~3.3 days, print the wallet's own
open/close fill price ladder and the 1m candle that contains the trip.
"""
import gzip, json, sys, pathlib, time
from datetime import datetime, timezone
import requests

D = pathlib.Path(__file__).parent.parent / "data" / "0x92647819"
fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: (f["time"], f.get("tid", 0)))
trips = json.load(open(D / "trips.json"))
URL = "https://api.hyperliquid.xyz/info"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

now = int(time.time() * 1000)
cutoff = now - int(3.2 * 86400 * 1000)
cands = sorted([t for t in trips if t["t0"] > cutoff], key=lambda t: -abs(t["pnl"] - t["fee"]))[:10]
# also include a few *small* recent trips to see the probing behaviour
small = sorted([t for t in trips if t["t0"] > cutoff and t["ntl"] < 1e4], key=lambda t: -t["t0"])[:4]
cache = {}
def candles(coin, t0, t1):
    key = (coin, t0 // 3600000)
    if key not in cache:
        r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m", "startTime": t0 - 180000, "endTime": t1 + 180000}}, timeout=30)
        cache[key] = r.json() if r.status_code == 200 else []
        time.sleep(0.2)
    return cache[key]

for t in cands + small:
    fs = [f for f in fills if f["coin"] == t["coin"] and t["t0"] <= f["time"] <= t["t1"]]
    opens = [f for f in fs if f["dir"].startswith("Open")]; closes = [f for f in fs if f["dir"].startswith("Close")]
    po = [float(f["px"]) for f in opens]; pc = [float(f["px"]) for f in closes]
    print("=" * 100)
    print(f"{ts(t['t0'])} {t['coin']} {t['side']} net={t['pnl']-t['fee']:.2f} ntl={t['ntl']:.0f} hold={t['hold_s']:.1f}s")
    print(f"  open fills n={len(opens)} px first={po[0] if po else '-'} min={min(po) if po else '-'} max={max(po) if po else '-'} last={po[-1] if po else '-'}  span={(max(po)/min(po)-1)*1e4 if po else 0:+.1f}bps  t={ts(opens[0]['time'])[-8:]}..{ts(opens[-1]['time'])[-8:]}" if opens else "  no opens")
    print(f"  close fills n={len(closes)} px first={pc[0] if pc else '-'} min={min(pc) if pc else '-'} max={max(pc) if pc else '-'} last={pc[-1] if pc else '-'}  span={(max(pc)/min(pc)-1)*1e4 if pc else 0:+.1f}bps  t={ts(closes[0]['time'])[-8:]}..{ts(closes[-1]['time'])[-8:]}" if closes else "  no closes")
    # order sizes in opens (per oid)
    by_oid = {}
    for f in opens: by_oid.setdefault(f["oid"], [0.0, 0]); by_oid[f["oid"]][0] += float(f["sz"]); by_oid[f["oid"]][1] += 1
    print(f"  open orders: {[(round(v[0], 3), v[1]) for v in by_oid.values()]}")
    cs = candles(t["coin"], t["t0"], t["t1"])
    for c in cs:
        mark = " <== trip" if c["t"] <= t["t0"] < c["t"] + 60000 else ""
        print(f"    1m {ts(c['t'])[-8:]} o={c['o']} h={c['h']} l={c['l']} c={c['c']} v={float(c['v']):.1f} n={c['n']}{mark}")
