"""Cross-wallet view: who is crowded into the same coin, when did they get in, at what price.

Finds the coin held by the most wallets right now, then for every wallet in the batch prints
when its CURRENT position in that coin was opened, its average entry, size, notional and PnL —
next to the coin's own daily candles. The point is to separate two readings of a crowded trade:
  (a) coordinated accumulation ahead of a move, vs
  (b) independent wallets reacting to the same visible breakout.
The opened-on dates against the daily % column decide it.

Usage: python cohort.py [COIN]
"""
import gzip, json, pathlib, sys, time, collections
from datetime import datetime, timezone
import requests

ROOT = pathlib.Path(__file__).parent.parent
URL = "https://api.hyperliquid.xyz/info"
ts = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
addrs = (ROOT / "addrs.txt").read_text().split()


def load(s):
    D = ROOT / "data" / s
    f = json.load(gzip.open(D / "fills.json.gz"))
    tw = D / "twap_fills.json.gz"
    if tw.exists():
        have = {x["tid"] for x in f}
        f += [x for x in json.load(gzip.open(tw)) if x["tid"] not in have]
    f.sort(key=lambda x: x["time"])
    return f, json.load(open(D / "clearinghouseState_all.json"))


# --- pick the most crowded coin unless one was named
held = collections.Counter()
cache = {}
for a in addrs:
    s = a[:10]
    cache[s] = load(s)
    for st in cache[s][1].values():
        if isinstance(st, dict):
            for ap in st.get("assetPositions", []):
                held[ap["position"]["coin"]] += 1
COIN = sys.argv[1] if len(sys.argv) > 1 else held.most_common(1)[0][0]
print(f"most-held coins across the {len(addrs)} wallets: {held.most_common(8)}")
print(f"\n=== cohort view: {COIN} ===\n")

rows = []
for a in addrs:
    s = a[:10]
    fills, states = cache[s]
    z = [x for x in fills if x["coin"] == COIN]
    pos = None
    for st in states.values():
        if isinstance(st, dict):
            for ap in st.get("assetPositions", []):
                if ap["position"]["coin"] == COIN:
                    pos = ap["position"]
    if not z and not pos:
        continue
    t_open = None
    for x in z:
        sp = float(x["startPosition"]); sz = float(x["sz"])
        ep = sp + (sz if x["side"] == "B" else -sz)
        if abs(sp) < 1e-12 or (sp > 0 > ep) or (sp < 0 < ep):
            t_open = x["time"]
    realized = sum(float(x["closedPnl"]) - float(x["fee"]) for x in z)
    rows.append({"w": s, "n": len(z), "first": ts(z[0]["time"]) if z else "-",
                 "szi": float(pos["szi"]) if pos else 0.0,
                 "entry": float(pos["entryPx"]) if pos else 0.0,
                 "val": float(pos["positionValue"]) if pos else 0.0,
                 "u": float(pos["unrealizedPnl"]) if pos else 0.0,
                 "liq": pos.get("liquidationPx") if pos else None,
                 "open": ts(t_open) if t_open else "-", "realized": realized})
rows.sort(key=lambda r: -abs(r["val"]))

print(f"{'wallet':<12}{'fills':>8}{'first traded':>14}{'cur pos opened':>16}{'avg entry':>11}{'size':>11}"
      f"{'notional':>13}{'unrealized':>13}{'realized':>12}{'liq px':>11}")
tv = tu = tr = 0.0
for r in rows:
    tv += r["val"]; tu += r["u"]; tr += r["realized"]
    print(f"{r['w']:<12}{r['n']:>8}{r['first']:>14}{r['open']:>16}{r['entry']:>11.2f}{r['szi']:>11.1f}"
          f"{r['val']:>13,.0f}{r['u']:>13,.0f}{r['realized']:>12,.0f}{str(r['liq'] or '-'):>11}")
print(f"{'TOTAL':<12}{'':>8}{'':>14}{'':>16}{'':>11}{'':>11}{tv:>13,.0f}{tu:>13,.0f}{tr:>12,.0f}")

holders = [r for r in rows if r["szi"]]
longs = [r for r in holders if r["szi"] > 0]
print(f"\nwallets that ever traded {COIN}: {len(rows)}/{len(addrs)}   holding now: {len(holders)} "
      f"({len(longs)} long / {len(holders)-len(longs)} short)")
oc = collections.Counter(r["open"] for r in holders)
print(f"current positions opened on: {sorted(oc.items())}")

# --- price context
r = requests.post(URL, json={"type": "candleSnapshot", "req": {
    "coin": COIN, "interval": "1d", "startTime": int((time.time() - 70 * 86400) * 1000),
    "endTime": int(time.time() * 1000)}}, timeout=60).json() or []
print(f"\n{COIN} daily (last {len(r)} days) — compare the 'cur pos opened' dates above against the chg% column:")
for c in r:
    d = ts(c["t"]); o, h, l, cl = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
    mark = "  <== " + ",".join(x["w"] for x in holders if x["open"] == d) if any(x["open"] == d for x in holders) else ""
    print(f"  {d} o={o:>9.2f} c={cl:>9.2f} chg={(cl/o-1)*100:>+6.1f}% rng={(h/l-1)*100:>5.1f}%{mark}")
