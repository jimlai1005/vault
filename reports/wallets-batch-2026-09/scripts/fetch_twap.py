"""Paginate userTwapSliceFillsByTime and save as a fills-shaped list.

Why this exists (2026-09-21): userFillsByTime does NOT return TWAP slice fills. A wallet that
routes part of its flow through TWAP orders therefore shows position jumps with no fills behind
them — position reconstruction drifts, episodes break, hold times and taker share are wrong.
fetch_wallet.py only took the first page (2000 rows) of the TWAP endpoint, which hid the size
of the hole. Verified on 0x41c684cb: 2000-row cap, BTC reconstruction off by 4.12 BTC.

Usage: python fetch_twap.py <address>
Output: data/<addr10>/twap_fills.json.gz  (each row is the inner `fill` object with twapId set)
"""
import gzip, json, sys, time, pathlib
import requests

ADDR = sys.argv[1].lower()
URL = "https://api.hyperliquid.xyz/info"
OUT = pathlib.Path(__file__).parent.parent / "data" / ADDR[:10]


def q(payload, retries=8):
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()
        time.sleep(15.0 * (2 ** i) if r.status_code == 429 else 2.0 * (i + 1))
    r.raise_for_status()


rows, start, seen = [], 0, set()
while True:
    batch = q({"type": "userTwapSliceFillsByTime", "user": ADDR, "startTime": start, "aggregateByTime": False})
    if not batch:
        break
    new = 0
    for x in batch:
        f = dict(x["fill"])
        f["twapId"] = x.get("twapId")
        if f["tid"] in seen:
            continue
        seen.add(f["tid"]); rows.append(f); new += 1
    last_t = batch[-1]["fill"]["time"]
    print(f"[{ADDR[:10]}] twap page {len(batch)} (+{new} new) last={last_t}")
    if len(batch) < 2000:
        break
    if new == 0:                      # every row already seen: advance past the boundary ms
        start = last_t + 1
    else:
        start = last_t                # overlap; same-ms rows deduped by tid
    time.sleep(0.5)

# normalize fee to USD (spot buys are charged in the base token) — same rule as fetch_wallet.py
n_conv = 0
for f in rows:
    tok = f.get("feeToken", "USDC")
    if tok not in ("USDC", "USDH", "USDT0", "USDE"):
        f["feeRaw"] = f["fee"]; f["fee"] = f"{float(f['fee']) * float(f['px']):.6f}"; n_conv += 1

with gzip.open(OUT / "twap_fills.json.gz", "wt") as f:
    json.dump(rows, f)
print(f"[{ADDR[:10]}] saved twap_fills: {len(rows)} (fee normalized on {n_conv})")
