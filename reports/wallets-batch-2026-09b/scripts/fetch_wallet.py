"""Pull public Hyperliquid info for one address into JSON files (read-only).

Usage: python fetch_wallet.py <address>
Output: reports/wallet-0x4dec-2026-09/data/<addr10>/*.json
"""
import gzip, json, sys, time, pathlib
import requests

ADDR = sys.argv[1].lower()
URL = "https://api.hyperliquid.xyz/info"
OUT = pathlib.Path(__file__).parent.parent / "data" / ADDR[:10]
OUT.mkdir(parents=True, exist_ok=True)


def q(payload, retries=8):
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()
        wait = 15.0 * (2 ** i) if r.status_code == 429 else 2.0 * (i + 1)
        print(f"[{ADDR[:10]}] http {r.status_code}, sleep {wait:.0f}s")
        time.sleep(wait)
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
PART = OUT / "fills_partial.json.gz"
if PART.exists():
    fills = json.load(gzip.open(PART))
    start = fills[-1]["time"]
    print(f"[{ADDR[:10]}] resume from {len(fills)} fills, start={start}")
while True:
    batch = q({"type": "userFillsByTime", "user": ADDR, "startTime": start,
               "aggregateByTime": False})
    if not batch:
        break
    fills.extend(batch)
    print(f"[{ADDR[:10]}] fills so far {len(fills)} last t={batch[-1]['time']}")
    if len(batch) < 2000:
        break
    start = batch[-1]["time"]  # overlap: same-ms fills straddling a page boundary are re-fetched, deduped by tid below
    with gzip.open(PART, "wt") as f:
        json.dump(fills, f)
    time.sleep(1.0)
seen = set(); dedup = []
for f in fills:
    if f["tid"] not in seen:
        seen.add(f["tid"]); dedup.append(f)
print(f"[{ADDR[:10]}] raw {len(fills)} -> dedup {len(dedup)}")
# 2b. normalize fee to USD. Spot BUY fills are charged in the base token (feeToken = PURR/HYPE/MAX/...),
#     so fee must be multiplied by px; perps and spot sells are USDC. Keep the raw value in feeRaw.
#     (2026-09-21: 0xf97ad MAX/USDC buys had fee=177,504 MAX ≈ $1.8 — summing raw fee as USD fabricated a -172k day.)
n_conv = 0
for f in dedup:
    tok = f.get("feeToken", "USDC")
    if tok not in ("USDC", "USDH", "USDT0", "USDE"):
        f["feeRaw"] = f["fee"]; f["fee"] = f"{float(f['fee']) * float(f['px']):.6f}"; n_conv += 1
print(f"[{ADDR[:10]}] fee normalized to USD on {n_conv} base-token-fee fills")
save("fills", dedup, gz=True)
PART.unlink(missing_ok=True)

# 3. ledger (deposits/withdrawals/transfers) + funding
save("ledger", q({"type": "userNonFundingLedgerUpdates", "user": ADDR, "startTime": 0}))
save("funding", q({"type": "userFunding", "user": ADDR, "startTime": 0}))
save("twapHistory", q({"type": "userTwapSliceFillsByTime", "user": ADDR, "startTime": 0}) or [])
