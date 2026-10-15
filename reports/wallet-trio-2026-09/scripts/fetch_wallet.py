"""Pull public Hyperliquid info for one address into JSON files (read-only).

Usage: python fetch_wallet.py <address>
Output: reports/wallet-trio-2026-09/data/<addr8>/*.json
"""
import gzip, json, sys, time, pathlib
import requests

ADDR = sys.argv[1].lower()
URL = "https://api.hyperliquid.xyz/info"
OUT = pathlib.Path(__file__).parent.parent / "data" / ADDR[:10]
OUT.mkdir(parents=True, exist_ok=True)


def q(payload, retries=4):
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()
        time.sleep(2.0 * (i + 1))
    r.raise_for_status()


def save(name, obj, gz=False):
    if gz:
        with gzip.open(OUT / f"{name}.json.gz", "wt") as f:
            json.dump(obj, f)
    else:
        (OUT / f"{name}.json").write_text(json.dumps(obj))
    print(f"[{ADDR[:10]}] saved {name}: {len(obj) if hasattr(obj, '__len__') else obj}")


# 1. perp dexes (incident #5: multi sub-ledger)
dexs = q({"type": "perpDexs"})
save("perpDexs", dexs)
names = [None] + [d["name"] for d in dexs if d]
states = {}
for n in names:
    p = {"type": "clearinghouseState", "user": ADDR}
    if n:
        p["dex"] = n
    states[n or "default"] = q(p)
    time.sleep(0.15)
save("clearinghouseState_all", states)

save("spotClearinghouseState", q({"type": "spotClearinghouseState", "user": ADDR}))
save("frontendOpenOrders", q({"type": "frontendOpenOrders", "user": ADDR}))
save("portfolio", q({"type": "portfolio", "user": ADDR}))
save("userAbstraction", q({"type": "userAbstraction", "user": ADDR}) if True else None)

# 2. fills, paginate by time (API returns at most the 10000 most recent fills)
fills, start = [], 0
while True:
    batch = q({"type": "userFillsByTime", "user": ADDR, "startTime": start,
               "aggregateByTime": False})
    if not batch:
        break
    fills.extend(batch)
    print(f"[{ADDR[:10]}] fills so far {len(fills)} last t={batch[-1]['time']}")
    if len(batch) < 2000:
        break
    start = batch[-1]["time"] + 1
    time.sleep(0.3)
save("fills", fills, gz=True)

# 3. ledger (deposits/withdrawals/transfers) + funding
save("ledger", q({"type": "userNonFundingLedgerUpdates", "user": ADDR, "startTime": 0}))
save("funding", q({"type": "userFunding", "user": ADDR, "startTime": 0}))
save("twapHistory", q({"type": "userTwapSliceFillsByTime", "user": ADDR, "startTime": 0}) or [])
