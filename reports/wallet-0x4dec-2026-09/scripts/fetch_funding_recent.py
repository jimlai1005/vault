"""userFunding with startTime=0 returns only the FIRST 500 rows. Paginate from
2026-03-01 to today and save funding_2026.json.  Usage: python fetch_funding_recent.py <address>
"""
import json, sys, time, pathlib, collections
from datetime import datetime, timezone
import requests

ADDR = sys.argv[1].lower(); URL = "https://api.hyperliquid.xyz/info"
OUT = pathlib.Path(__file__).parent.parent / "data" / ADDR[:10]
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
start = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
rows = []
while True:
    for i in range(6):
        r = requests.post(URL, json={"type": "userFunding", "user": ADDR, "startTime": start}, timeout=60)
        if r.status_code == 200: break
        time.sleep(15 * (2 ** i))
    b = r.json()
    if not b: break
    rows.extend(b)
    if len(b) < 500: break
    start = b[-1]["time"] + 1; time.sleep(1.0)
json.dump(rows, open(OUT / "funding_2026.json", "w"))
print(f"funding rows since 2026-03-01: {len(rows)}  total={sum(float(x['delta']['usdc']) for x in rows):.2f}")
bym = collections.defaultdict(float); byc = collections.defaultdict(float)
for x in rows:
    bym[ts(x["time"])[:7]] += float(x["delta"]["usdc"]); byc[x["delta"]["coin"]] += float(x["delta"]["usdc"])
print("by month:", {k: round(v) for k, v in sorted(bym.items())})
print("by coin (top):", sorted(((c, round(v)) for c, v in byc.items()), key=lambda x: -abs(x[1]))[:12])
