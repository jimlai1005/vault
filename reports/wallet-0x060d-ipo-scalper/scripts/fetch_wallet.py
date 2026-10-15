"""Pull public Hyperliquid info for one address into JSON files (read-only)."""
import json, sys, time, pathlib
import requests

ADDR = "0x060d6d3136d19e69707b71b0cc78540d7c2b81eb"
URL = "https://api.hyperliquid.xyz/info"
OUT = pathlib.Path(__file__).parent / "wallet"
OUT.mkdir(exist_ok=True)


def q(payload, retries=3):
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()
        time.sleep(1.5 * (i + 1))
    r.raise_for_status()


def save(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj))
    print(f"saved {name}: {len(obj) if hasattr(obj, '__len__') else obj}")


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
save("clearinghouseState_all", states)

save("spotClearinghouseState", q({"type": "spotClearinghouseState", "user": ADDR}))
save("frontendOpenOrders", q({"type": "frontendOpenOrders", "user": ADDR}))
save("portfolio", q({"type": "portfolio", "user": ADDR}))

# 2. fills, paginate by time (cap 10000 most recent)
fills, start = [], 0
while True:
    batch = q({"type": "userFillsByTime", "user": ADDR, "startTime": start,
               "aggregateByTime": False})
    if not batch:
        break
    fills.extend(batch)
    print(f"fills so far {len(fills)} last t={batch[-1]['time']}")
    if len(batch) < 2000:
        break
    start = batch[-1]["time"] + 1
    time.sleep(0.3)
save("fills", fills)

# 3. ledger (deposits/withdrawals/transfers) + funding
save("ledger", q({"type": "userNonFundingLedgerUpdates", "user": ADDR, "startTime": 0}))
save("funding", q({"type": "userFunding", "user": ADDR, "startTime": 0}))
save("twapHistory", q({"type": "userTwapSliceFillsByTime", "user": ADDR, "startTime": 0}) or [])
