"""Dollar exposure and the May-2026 blowup in detail.

  (a) sanity: reconstructed EOD positions vs live clearinghouseState (drift check);
  (b) daily EOD gross long / gross short / net USD exposure (pair-trading test);
  (c) vault follower flows by day, 2026-05-10..05-31;
  (d) HYPE hourly position path on 2026-05-19..05-21.

Usage: python exposure.py 0x4dec0a85
"""
import gzip, json, sys, pathlib, collections, time
from datetime import datetime, timezone
import requests

D = pathlib.Path(__file__).parent.parent / "data" / sys.argv[1]
fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])  # stable: keep API order within the same ms (tid order != execution order)
ledger = json.load(open(D / "ledger.json"))
states = json.load(open(D / "clearinghouseState_all.json"))
URL = "https://api.hyperliquid.xyz/info"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def day_ms(d): return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

# ---- (a) final reconstructed position per coin (from last fill's startPosition+sz)
last = {}
for f in fills:
    sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
    last[f["coin"]] = (ep, f["time"], sp, sz, f["side"])
# live perp positions across ALL dexes (xyz:CL lives on dex "xyz", not "default"); spot pairs are checked
# against spotClearinghouseState balances via spotMeta name lookup. Spot recon can legitimately differ from
# live when tokens were moved by send/spotTransfer (not fills) — those rows are tagged XFER? for manual check.
live = {}
for dex, st in states.items():
    if isinstance(st, dict):
        for ap in st.get("assetPositions", []): live[ap["position"]["coin"]] = float(ap["position"]["szi"])
spot_bal = {}
try:
    sb = json.load(open(D / "spotClearinghouseState.json"))
    spot_bal = {b["coin"]: float(b["total"]) for b in sb.get("balances", [])}
    sm = requests.post(URL, json={"type": "spotMeta"}, timeout=30).json(); tok = {t["index"]: t["name"] for t in sm["tokens"]}
    for u in sm["universe"]:
        base = tok.get(u["tokens"][0]); live[u["name"]] = spot_bal.get(base, 0.0)
        if "/" in u["name"] or base: live[f"{base}/USDC"] = spot_bal.get(base, 0.0)
except Exception as e:
    print("spot live lookup failed:", e)
print("-- (a) reconstructed vs live (perp: all dexes; spot: token balance):")
for c, (ep, t, sp, sz, side) in sorted(last.items(), key=lambda kv: -abs(kv[1][0])):
    lv = live.get(c, 0.0)
    if abs(ep) > 1e-9 or abs(lv) > 0:
        is_spot = c.startswith("@") or "/" in c
        tag = "OK" if abs(ep - lv) < 1e-6 else ("dust" if is_spot and abs(ep - lv) < 1 else ("XFER?" if is_spot else "DRIFT"))
        print(f"   {c:>6} recon={ep:>14.6f} live={lv:>14.6f} {tag} last_fill={ts(t)} start={sp} sz={sz} side={side}")

# ---- (b) daily EOD exposure with daily closes
_c = {}
def closes(coin):
    if coin not in _c:
        for i in range(5):
            r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": day_ms("2025-09-01"), "endTime": int(time.time() * 1000)}}, timeout=30)
            if r.status_code == 200: break
            time.sleep(10 * (i + 1))
        _c[coin] = {ts(c["t"])[:10]: float(c["c"]) for c in (r.json() if r.status_code == 200 else [])}
        time.sleep(0.25)
    return _c[coin]
pos = {}; days = []
for f in fills:
    sp = float(f["startPosition"]); sz = float(f["sz"]); ep = sp + (sz if f["side"] == "B" else -sz)
    pos[f["coin"]] = ep if abs(ep) > 1e-9 else 0.0
    d = ts(f["time"])[:10]
    if not days or days[-1][0] != d: days.append((d, None))
    days[-1] = (d, dict(pos))
print("-- (b) EOD USD exposure (gross long / gross short / net / n coins), every 3rd active day + all of May:")
rows = []
for d, p in days:
    L = S = 0.0; nl = ns = 0; big = []
    for c, q in p.items():
        if q == 0: continue
        px = closes(c).get(d)
        if px is None: continue
        v = q * px
        if v > 0: L += v; nl += 1
        else: S += -v; ns += 1
        big.append((c, round(v)))
    big.sort(key=lambda x: -abs(x[1]))
    rows.append((d, L, S, nl, ns, big[:5]))
json.dump(rows, open(D / "exposure_daily.json", "w"))
for i, (d, L, S, nl, ns, big) in enumerate(rows):
    if i % 4 == 0 or d >= "2026-08-20" or "2025-09-18" <= d <= "2025-10-15" or "2026-06-10" <= d <= "2026-06-16":
        print(f"   {d} long={L:>10.0f} ({nl:>2}) short={S:>10.0f} ({ns:>2}) net={L-S:>+10.0f} gross={L+S:>10.0f} top={big}")

# ---- (c) all ledger flows (deposits / withdrawals / sends), full history
print("-- (c) ledger flows: monthly sum by type (usdc/usdcValue/amount field), then non-deposit/withdraw/vault rows since 2025-09-01:")
_mon = collections.defaultdict(lambda: collections.defaultdict(float)); _cnt = collections.defaultdict(lambda: collections.defaultdict(int))
for l in ledger:
    x = l["delta"]; m = ts(l["time"])[:7]; t = x.get("type")
    v = x.get("usdc") or x.get("usdcValue") or x.get("amount") or x.get("requestedUsd") or 0
    try: v = float(v)
    except Exception: v = 0.0
    _mon[m][t] += v; _cnt[m][t] += 1
for m in sorted(_mon):
    if m < "2025-06": continue
    print(f"   {m}: " + " | ".join(f"{t}={v:.0f}({_cnt[m][t]})" for t, v in sorted(_mon[m].items())))
for l in ledger:
    x = l["delta"]
    if x.get("type") in ("deposit", "withdraw", "vaultDeposit", "vaultWithdraw", "accountClassTransfer", "spotGenesis"): continue
    if ts(l["time"]) < "2025-09-01": continue
    print(f"   {ts(l['time'])} {x.get('type')} {json.dumps({k: v for k, v in x.items() if k != 'type'})[:200]}")

# ---- (d) hourly path of one coin over a window: PUMP 08-22..08-24 (first big exit) and ZEC 09-09..09-12
def hourly(coin, d0, d1):
    print(f"-- (d) {coin} hourly {d0}..{d1}: EOH position, hour realized net, vwap buy/sell, 1h candle")
    r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": day_ms(d0), "endTime": day_ms(d1) + 86400000}}, timeout=30)
    h1 = {ts(c["t"])[:13]: c for c in r.json()} if r.status_code == 200 else {}
    hr = collections.defaultdict(lambda: {"net": 0.0, "n": 0, "bq": 0.0, "bv": 0.0, "sq": 0.0, "sv": 0.0, "eoh": None, "tk": 0})
    for f in fills:
        if f["coin"] != coin: continue
        d = ts(f["time"])[:13]
        if not (d0 <= d[:10] <= d1): continue
        x = hr[d]; sz = float(f["sz"]); px = float(f["px"]); sp = float(f["startPosition"])
        x["net"] += float(f["closedPnl"]) - float(f["fee"]); x["n"] += 1; x["eoh"] = sp + (sz if f["side"] == "B" else -sz); x["tk"] += 1 if f.get("crossed") else 0
        if f["side"] == "B": x["bq"] += sz; x["bv"] += sz * px
        else: x["sq"] += sz; x["sv"] += sz * px
    for d in sorted(hr):
        x = hr[d]; c = h1.get(d, {})
        print(f"   {d}:00 eoh_pos={x['eoh']:>12.1f} net={x['net']:>8.0f} fills={x['n']:>4} taker={x['tk']:>3} buy={x['bq']:>10.0f}@{(x['bv']/x['bq'] if x['bq'] else 0):.5g} sell={x['sq']:>10.0f}@{(x['sv']/x['sq'] if x['sq'] else 0):.5g} {coin} o={c.get('o','-')} h={c.get('h','-')} l={c.get('l','-')} c={c.get('c','-')}")
    time.sleep(0.3)
hourly("HYPE", "2025-09-30", "2025-09-30")
hourly("HYPE", "2025-10-10", "2025-10-11")
hourly("HYPE", "2026-06-13", "2026-06-14")
hourly("@591", "2026-06-13", "2026-06-14")
