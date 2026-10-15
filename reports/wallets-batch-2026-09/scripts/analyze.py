"""Generic per-wallet deep analysis: every parameter is derived from the data.

Replaces the hand-tuned positions.py / ladder.py / events.py / deep.py trio so that a
batch of wallets can be run mechanically. Sections map 1:1 onto the five standing
questions in ~/.claude/rules/wallet-analysis.md:

  [A] account       -> Q1 account overview + equity basis reconciliation (principle #1)
  [B] mechanism     -> Q1 trade mechanism, externalized rule by rule
  [C] bigdays       -> Q2/Q3 big-move days with market context and what the account did
  [D] holdtime      -> Q4 hold-time distribution
  [E] limits        -> Q6 data limits

Usage: python analyze.py <addr10>
Output: stdout (redirect to data/<addr10>/analysis.txt)
"""
import gzip, json, sys, pathlib, collections, statistics, time
from datetime import datetime, timezone
import requests

ROOT = pathlib.Path(__file__).parent.parent
A10 = sys.argv[1]
D = ROOT / "data" / A10
URL = "https://api.hyperliquid.xyz/info"
ADDR = [x for x in (ROOT / "addrs.txt").read_text().split() if x.startswith(A10)][0]
STABLE = {"USDC", "USDH", "USDT0", "USDE", "FEUSD"}


def q(payload, retries=6):
    for i in range(retries):
        try:
            r = requests.post(URL, json=payload, timeout=60)
            if r.status_code == 200 and r.json() is not None:
                return r.json()
        except Exception:
            pass
        time.sleep(3.0 * (i + 1))
    return None


def ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def fmt(s):
    return f"{s:.0f}s" if s < 60 else f"{s/60:.1f}m" if s < 3600 else f"{s/3600:.1f}h" if s < 86400 else f"{s/86400:.1f}d"


def day_ms(d):
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


fills = json.load(gzip.open(D / "fills.json.gz"))
# 2026-09-21: userFillsByTime does NOT include TWAP slice fills. Merge them in or position
# reconstruction drifts and every episode statistic is wrong (see fetch_twap.py docstring).
n_twap = 0
_tw = D / "twap_fills.json.gz"
if _tw.exists():
    have = {f["tid"] for f in fills}
    extra = [f for f in json.load(gzip.open(_tw)) if f["tid"] not in have]
    fills.extend(extra); n_twap = len(extra)
fills.sort(key=lambda f: f["time"])   # stable: API order within the same ms is execution order
ledger = json.load(open(D / "ledger.json"))
funding = json.load(open(D / "funding.json"))
states = json.load(open(D / "clearinghouseState_all.json"))
spotch = json.load(open(D / "spotClearinghouseState.json"))
portfolio = dict(json.load(open(D / "portfolio.json")))
openo = json.load(open(D / "frontendOpenOrders.json"))
ua = json.load(open(D / "userAbstraction.json"))

is_spot = lambda c: c.startswith("@") or "/" in c
perp = [f for f in fills if not is_spot(f["coin"])]
spotf = [f for f in fills if is_spot(f["coin"])]
net_of = lambda f: float(f["closedPnl"]) - float(f["fee"])

print("=" * 100)
print(f"WALLET {ADDR}  ({A10})   analysis generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
print("=" * 100)
if not fills:
    print("!! no fills — nothing to analyze")
    sys.exit(0)

# =============================================================== [A] account state
print("\n[A] ACCOUNT ------------------------------------------------------------------")
mids = q({"type": "allMids"}) or {}
sm = q({"type": "spotMeta"}) or {"universe": [], "tokens": []}
tokname = {t["index"]: t["name"] for t in sm["tokens"]}
pair_of, pair_label = {}, {}
for u in sm["universe"]:
    nm = tokname.get(u["tokens"][0])
    pair_label[u["name"]] = "/".join(tokname.get(i, str(i)) for i in u["tokens"])
    if nm and nm not in pair_of:
        pair_of[nm] = u["name"]
px_of = lambda coin: float(mids.get(coin, 0) or 0)

spot_free = 0.0
spot_detail = []
for b in spotch.get("balances", []):
    tot, hold = float(b["total"]), float(b.get("hold", 0) or 0)
    px = 1.0 if b["coin"] in STABLE else px_of(pair_of.get(b["coin"], ""))
    v = (tot - hold) * px
    spot_free += v
    if abs(v) > 50 or b["coin"] in STABLE:
        spot_detail.append(f"{b['coin']}: total={tot:.6g} hold={hold:.6g} free_usd={v:,.0f}")
perp_av, perp_rows = 0.0, []
for dex, st in states.items():
    if not isinstance(st, dict):
        continue
    ms = st.get("marginSummary", {})
    av = float(ms.get("accountValue", 0) or 0)
    if av or st.get("assetPositions"):
        perp_av += av
        perp_rows.append(f"  dex={dex:<10} accountValue={av:>14,.2f} totalNtlPos={float(ms.get('totalNtlPos',0)):>14,.2f} "
                         f"marginUsed={float(ms.get('totalMarginUsed',0)):>13,.2f} withdrawable={float(st.get('withdrawable',0)):>12,.2f}")
ds = q({"type": "delegatorSummary", "user": ADDR}) or {}
staked_hype = sum(float(ds.get(k, 0) or 0) for k in ("delegated", "undelegated", "totalPendingWithdrawal"))
staked = staked_hype * px_of(pair_of.get("HYPE", "@107"))
ve = q({"type": "userVaultEquities", "user": ADDR}) or []
vault = sum(float(v.get("equity", 0) or 0) for v in ve)
avh = portfolio.get("allTime", {}).get("accountValueHistory", [])
venue = float(avh[-1][1]) if avh else float("nan")
total = spot_free + perp_av + staked + vault
print(f"  userAbstraction={ua}")
print("\n".join(perp_rows) or "  (no perp dex with value)")
print("  spot: " + " | ".join(spot_detail[:10]))
print(f"  staked HYPE={staked_hype:.4g} (${staked:,.0f})   vault equity=${vault:,.0f}")
print(f"  EQUITY BASIS: spot_free {spot_free:,.0f} + perp_av {perp_av:,.0f} + staked {staked:,.0f} + vault {vault:,.0f} "
      f"= {total:,.0f}   vs venue portfolio {venue:,.0f}   drift {total-venue:+,.0f} ({(total-venue)/venue*100 if venue else 0:+.1f}%)")

lt = collections.Counter(l["delta"]["type"] for l in ledger)
flow = collections.defaultdict(float)
for l in ledger:
    x = l["delta"]
    v = x.get("usdc") or x.get("usdcValue") or x.get("amount") or x.get("requestedUsd") or 0
    try:
        flow[x["type"]] += float(v)
    except Exception:
        pass
print(f"  ledger rows: {dict(lt)}")
print("  ledger $ by type: " + ", ".join(f"{k}={v:,.0f}" for k, v in sorted(flow.items()) if abs(v) > 1))
dep, wd = flow.get("deposit", 0.0), flow.get("withdraw", 0.0)
print(f"  net external flow = deposits {dep:,.0f} - withdrawals {wd:,.0f} = {dep-wd:,.0f}")
if avh:
    print(f"  venue equity curve: {ts(avh[0][0])[:10]} ${float(avh[0][1]):,.0f} -> {ts(avh[-1][0])[:10]} ${float(avh[-1][1]):,.0f} "
          f"| allTime pnl={float(portfolio['allTime']['pnlHistory'][-1][1]):,.0f} vlm={float(portfolio['allTime']['vlm']):,.0f}")
    peak = max(float(v) for _, v in avh)
    peak_t = [ts(t)[:10] for t, v in avh if float(v) == peak][0]
    trough_after = min((float(v) for t, v in avh if ts(t)[:10] >= peak_t), default=peak)
    print(f"  venue equity peak ${peak:,.0f} on {peak_t}; min after peak ${trough_after:,.0f} "
          f"(drawdown from peak {(trough_after/peak-1)*100 if peak else 0:.1f}%)")

# ---- current positions: when opened, age, realized since open
print("\n  -- current positions (all dexes):")
pos_rows = [ap["position"] for st in states.values() if isinstance(st, dict) for ap in st.get("assetPositions", [])]
bycoin = collections.defaultdict(list)
for f in fills:
    bycoin[f["coin"]].append(f)
for p in sorted(pos_rows, key=lambda p: -abs(float(p["positionValue"]))):
    c = p["coin"]
    t_open = None
    for f in bycoin.get(c, []):
        sp = float(f["startPosition"]); sz = float(f["sz"])
        ep = sp + (sz if f["side"] == "B" else -sz)
        if abs(sp) < 1e-12 or (sp > 0 > ep) or (sp < 0 < ep):
            t_open = f["time"]
    rp = sum(net_of(f) for f in bycoin.get(c, []) if t_open and f["time"] >= t_open)
    age = (fills[-1]["time"] - t_open) / 1000 if t_open else None
    print(f"   {c:>12} szi={p['szi']:>14} entry={p['entryPx']:>11} value={float(p['positionValue']):>13,.0f} "
          f"upnl={float(p['unrealizedPnl']):>12,.0f} lev={p['leverage']['value']}x{p['leverage']['type'][:5]} "
          f"liq={p.get('liquidationPx')} opened={ts(t_open)[:16] if t_open else '?'} age={fmt(age) if age else '?'} realized_since={rp:,.0f}")

# ---- open-order ladder structure
print(f"\n  -- open orders: {len(openo)}")
byo = collections.defaultdict(list)
for o in openo:
    byo[o["coin"]].append(o)
for c, os_ in sorted(byo.items(), key=lambda kv: -len(kv[1])):
    pxs = sorted(float(o["limitPx"]) for o in os_)
    steps = [(pxs[i + 1] / pxs[i] - 1) * 1e4 for i in range(len(pxs) - 1)]
    mid = px_of(c)
    print(f"   {c:>12} n={len(os_):>3} sides={dict(collections.Counter(o['side'] for o in os_))} "
          f"px {pxs[0]:.6g}..{pxs[-1]:.6g} (span {(pxs[-1]/pxs[0]-1)*1e4:.0f}bps, median step {statistics.median(steps) if steps else 0:.0f}bps) "
          f"ntl={sum(float(o['limitPx'])*float(o['sz']) for o in os_):,.0f} mid={mid:.6g} "
          f"dist_near={(pxs[-1]/mid-1)*1e4 if mid else 0:+.0f}bps dist_far={(pxs[0]/mid-1)*1e4 if mid else 0:+.0f}bps "
          f"types={dict(collections.Counter((o.get('orderType'), o.get('tif'), bool(o.get('reduceOnly'))) for o in os_))}")

# =============================================================== episodes (flat-or-flip)
eps, cur = [], {}
for f in perp:
    c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"]); side = f["side"]
    ep = sp + (sz if side == "B" else -sz)
    px = float(f["px"])
    if cur.get(c) is None or abs(sp) < 1e-12:
        cur[c] = {"coin": c, "t0": f["time"], "side": "L" if ep > 0 else "S", "pnl": 0.0, "fee": 0.0, "n": 0,
                  "max_abs": 0.0, "max_ntl": 0.0, "ntl": 0.0, "taker": 0, "open_ntl": 0.0, "open_sz": 0.0,
                  "opens": [], "closes": [], "gap": abs(sp) > 1e-12, "liq": 0}
    r = cur[c]
    r["pnl"] += float(f["closedPnl"]); r["fee"] += float(f["fee"]); r["n"] += 1
    r["taker"] += 1 if f.get("crossed") else 0
    r["liq"] += 1 if f.get("liquidation") else 0
    r["max_abs"] = max(r["max_abs"], abs(ep)); r["max_ntl"] = max(r["max_ntl"], abs(ep) * px)
    r["ntl"] += px * sz
    opening = (f["dir"].startswith("Open") or abs(ep) > abs(sp))
    (r["opens"] if opening else r["closes"]).append((f["time"], px, bool(f.get("crossed")), sz, f.get("oid")))
    if opening:
        r["open_ntl"] += px * sz; r["open_sz"] += sz
    flipped = (sp > 0 > ep) or (sp < 0 < ep)
    if abs(ep) < 1e-12 or flipped:
        r["t1"] = f["time"]; r["hold_s"] = (r["t1"] - r["t0"]) / 1000; r["end"] = "flip" if flipped else "flat"
        eps.append(r); cur[c] = None
        if flipped:
            cur[c] = {"coin": c, "t0": f["time"], "side": "L" if ep > 0 else "S", "pnl": 0.0, "fee": 0.0, "n": 0,
                      "max_abs": abs(ep), "max_ntl": abs(ep) * px, "ntl": 0.0, "taker": 0, "open_ntl": px * abs(ep),
                      "open_sz": abs(ep), "opens": [(f["time"], px, bool(f.get("crossed")), abs(ep), f.get("oid"))],
                      "closes": [], "gap": False, "liq": 0}
closed = [e for e in eps if not e["gap"]]
openeps = [r for r in cur.values() if r]

# =============================================================== [B] mechanism
print("\n[B] MECHANISM ----------------------------------------------------------------")
tot_ntl = sum(float(f["px"]) * float(f["sz"]) for f in fills)
coin_ntl = collections.Counter()
coin_net = collections.Counter()
for f in fills:
    coin_ntl[f["coin"]] += float(f["px"]) * float(f["sz"])
    coin_net[f["coin"]] += net_of(f)
print(f"  fills={len(fills)} (perp {len(perp)} / spot {len(spotf)}) {ts(fills[0]['time'])}..{ts(fills[-1]['time'])}")
print(f"  episodes: total={len(eps)} usable={len(closed)} (dropped data-gap starts {len(eps)-len(closed)}) "
      f"ends={dict(collections.Counter(e['end'] for e in closed))} still-open={[e['coin'] for e in openeps]}")
print(f"  coins traded={len(coin_ntl)}")
print("  top coins by notional: " + ", ".join(f"{c}({v/tot_ntl:.0%},net {coin_net[c]:,.0f})" for c, v in coin_ntl.most_common(10)))
print("  top coins by |net pnl|: " + ", ".join(f"{c}({v:,.0f})" for c, v in sorted(coin_net.items(), key=lambda kv: -abs(kv[1]))[:10]))
hip3 = sum(v for c, v in coin_ntl.items() if ":" in c)
print(f"  HIP-3 share of notional={hip3/tot_ntl:.0%}  spot share={sum(v for c,v in coin_ntl.items() if is_spot(c))/tot_ntl:.0%}")
if spotf:
    print("  spot pairs used: " + ", ".join(f"{c}={pair_label.get(c, '?')}" for c in sorted({f['coin'] for f in spotf})[:12]))

# maker/taker split by open vs close — the single most diagnostic mechanism number
o_tk = [c for e in closed for (_, _, c, _, _) in e["opens"]]
c_tk = [c for e in closed for (_, _, c, _, _) in e["closes"]]
print(f"  entry fills: n={len(o_tk)} taker={(sum(o_tk)/len(o_tk)) if o_tk else 0:.0%}   exit fills: n={len(c_tk)} taker={(sum(c_tk)/len(c_tk)) if c_tk else 0:.0%}"
      + ("   (no closed perp episodes — spot-only or a single still-open position)" if not o_tk else ""))
lq = [f for f in fills if f.get("liquidation")]
print(f"  liquidation fills={len(lq)} in {sum(1 for e in closed if e['liq'])} episodes"
      + (f"  first={ts(lq[0]['time'])[:16]} last={ts(lq[-1]['time'])[:16]}" if lq else ""))
tw = [f for f in fills if f.get("twapId")]
print(f"  TWAP slice fills={len(tw)} ({len(tw)/len(fills):.0%} of all fills; {n_twap} merged from the TWAP endpoint, "
      f"which userFillsByTime omits)  distinct oids={len({f.get('oid') for f in fills})}  "
      f"fills/oid={len(fills)/max(1,len({f.get('oid') for f in fills})):.2f}")

# ladder shape / averaging-down evidence
def summ(rs, label):
    if not rs:
        print(f"   {label:<34}: none")
        return
    med = lambda k: statistics.median(r[k] for r in rs)
    print(f"   {label:<34}: n={len(rs):>4} | entry: fills p50={med('n_open'):>3.0f} oids p50={med('open_oids'):>3.0f} "
          f"span p50={med('open_span_bps'):>5.0f}bps maker p50={med('open_maker'):>4.0%} build p50={fmt(med('open_dur')):>6} "
          f"depth p50={med('depth_bps'):>+5.0f}bps | exit: fills p50={med('n_close'):>3.0f} maker p50={med('close_maker'):>4.0%} "
          f"unwind p50={fmt(med('close_dur')):>6} | ntl p50={med('ntl'):>10,.0f} net p50={med('net'):>9,.0f}")


def span_bps(lst):
    """Price span in bps, guarding against px=0 fills (settlement/ADL rows come through at 0)."""
    lst = [p for p in lst if p > 0]
    return (max(lst) / min(lst) - 1) * 1e4 if len(lst) > 1 else 0.0


rows = []
for e in closed:
    if not e["opens"]:
        continue
    op = [p for (_, p, _, _, _) in e["opens"] if p > 0]
    cp = [p for (_, p, _, _, _) in e["closes"] if p > 0]
    if not op:
        continue
    rows.append({
        "coin": e["coin"], "side": e["side"], "t0": e["t0"], "t1": e["t1"], "hold": e["hold_s"],
        "net": e["pnl"] - e["fee"], "ntl": e["ntl"], "max_ntl": e["max_ntl"], "liq": e["liq"],
        "n_open": len(e["opens"]), "open_oids": len({o[4] for o in e["opens"]}),
        "open_span_bps": span_bps(op),
        "open_maker": sum(1 for o in e["opens"] if not o[2]) / len(e["opens"]),
        "n_close": len(e["closes"]), "close_maker": (sum(1 for o in e["closes"] if not o[2]) / len(e["closes"])) if e["closes"] else 0,
        "close_span_bps": span_bps(cp),
        "open_dur": (e["opens"][-1][0] - e["opens"][0][0]) / 1000,
        "close_dur": (e["closes"][-1][0] - e["closes"][0][0]) / 1000 if e["closes"] else 0,
        # depth: how far the entry ladder walked against the first entry (negative = averaged down on a long)
        "depth_bps": ((min(op) / op[0] - 1) * 1e4 if e["side"] == "L" else (max(op) / op[0] - 1) * 1e4) if len(op) > 1 and op[0] > 0 else 0,
        # adverse adds: share of entry fills at a worse price than the first entry
        "adverse": sum(1 for p in op[1:] if (p < op[0] if e["side"] == "L" else p > op[0])) / max(1, len(op) - 1),
    })
print("\n  -- entry/exit shape (medians). 'depth' = how far the entry ladder walked against the first entry:")
summ(rows, "all episodes")
summ([r for r in rows if r["n_open"] >= 5], "episodes with >=5 entry fills")
summ([r for r in rows if r["net"] > 0], "winners")
summ([r for r in rows if r["net"] <= 0], "losers")
summ([r for r in rows if r["max_ntl"] >= 1e5], "large (peak notional >= 100k)")
if rows:
    adv = statistics.median(r["adverse"] for r in rows if r["n_open"] > 1) if any(r["n_open"] > 1 for r in rows) in (True,) else 0
    multi = [r for r in rows if r["n_open"] > 1]
    print(f"  averaging-in: {len(multi)}/{len(rows)} episodes have >1 entry fill; "
          f"median share of entries at a worse price than the first = {statistics.median(r['adverse'] for r in multi) if multi else 0:.0%}")
    deep = sorted([r for r in rows if r["n_open"] > 1], key=lambda r: r["depth_bps"])[:10]
    print("  -- 10 deepest entry ladders (walked furthest against the first entry):")
    for r in deep:
        print(f"     {ts(r['t0'])[:16]} {r['coin']:>10} {r['side']} depth={r['depth_bps']:>+6.0f}bps span={r['open_span_bps']:>5.0f}bps "
              f"entries={r['n_open']:>4} maker={r['open_maker']:.0%} hold={fmt(r['hold']):>7} peak_ntl={r['max_ntl']:>11,.0f} "
              f"net={r['net']:>10,.0f} exit_maker={r['close_maker']:.0%}")
    print("  -- 10 worst episodes: how were they exited? (stop-loss evidence)")
    for r in sorted(rows, key=lambda r: r["net"])[:10]:
        print(f"     {ts(r['t0'])[:16]}->{ts(r['t1'])[:16]} {r['coin']:>10} {r['side']} net={r['net']:>10,.0f} "
              f"hold={fmt(r['hold']):>7} peak_ntl={r['max_ntl']:>11,.0f} entries={r['n_open']:>4} depth={r['depth_bps']:>+6.0f}bps "
              f"exits={r['n_close']:>3} exit_maker={r['close_maker']:.0%} unwind={fmt(r['close_dur']):>6} liq_fills={r['liq']}")
    print("  -- 10 best episodes:")
    for r in sorted(rows, key=lambda r: -r["net"])[:10]:
        print(f"     {ts(r['t0'])[:16]}->{ts(r['t1'])[:16]} {r['coin']:>10} {r['side']} net={r['net']:>10,.0f} "
              f"hold={fmt(r['hold']):>7} peak_ntl={r['max_ntl']:>11,.0f} entries={r['n_open']:>4} depth={r['depth_bps']:>+6.0f}bps "
              f"exits={r['n_close']:>3} entry_maker={r['open_maker']:.0%} exit_maker={r['close_maker']:.0%}")

# sizing vs equity
if rows and venue == venue and venue > 0:
    mn = sorted(r["max_ntl"] for r in rows)
    pc = lambda p: mn[min(len(mn) - 1, int(p * len(mn)))]
    print(f"\n  position sizing: peak notional p25={pc(.25):,.0f} p50={pc(.5):,.0f} p75={pc(.75):,.0f} p90={pc(.9):,.0f} max={mn[-1]:,.0f}"
          f"  (vs current equity {venue:,.0f} -> p50 {pc(.5)/venue:.2f}x, max {mn[-1]/venue:.2f}x)")
cur_gross = sum(abs(float(p["positionValue"])) for p in pos_rows)
print(f"  current gross exposure={cur_gross:,.0f} = {cur_gross/venue if venue else 0:.2f}x equity  "
      f"(long {sum(float(p['positionValue']) for p in pos_rows if float(p['szi'])>0):,.0f} / "
      f"short {sum(float(p['positionValue']) for p in pos_rows if float(p['szi'])<0):,.0f})")

# timing
hod = collections.defaultdict(lambda: [0, 0.0])
for e in closed:
    h = datetime.fromtimestamp(e["t0"] / 1000, tz=timezone.utc).hour
    hod[h][0] += 1; hod[h][1] += e["pnl"] - e["fee"]
print("  entries by UTC hour (n/net): " + " ".join(f"{h:02d}:{v[0]}/{v[1]:,.0f}" for h, v in sorted(hod.items())))
dow = collections.defaultdict(int)
for e in closed:
    dow[datetime.fromtimestamp(e["t0"] / 1000, tz=timezone.utc).strftime("%a")] += 1
print(f"  entries by weekday: {dict(dow)}")

# cadence over time: fills and net per calendar month
mon = collections.defaultdict(lambda: {"n": 0, "net": 0.0, "ntl": 0.0, "coins": set(), "tk": 0})
for f in fills:
    m = ts(f["time"])[:7]
    x = mon[m]; x["n"] += 1; x["net"] += net_of(f); x["ntl"] += float(f["px"]) * float(f["sz"])
    x["coins"].add(f["coin"]); x["tk"] += 1 if f.get("crossed") else 0
print("\n  -- monthly cadence (realized net of fees; taker share):")
for m in sorted(mon):
    x = mon[m]
    print(f"     {m}  fills={x['n']:>6} taker={x['tk']/x['n']:>4.0%} coins={len(x['coins']):>3} ntl={x['ntl']:>14,.0f} net={x['net']:>12,.0f}")

# =============================================================== [C] big days
print("\n[C] BIG DAYS -----------------------------------------------------------------")
day = collections.defaultdict(lambda: {"net": 0.0, "n": 0, "ntl": 0.0, "coins": collections.Counter(), "tk": 0})
daycoin = collections.defaultdict(lambda: collections.defaultdict(float))
for f in fills:
    d = ts(f["time"])[:10]
    x = day[d]; x["net"] += net_of(f); x["n"] += 1; x["ntl"] += float(f["px"]) * float(f["sz"])
    x["coins"][f["coin"]] += float(f["px"]) * float(f["sz"]); x["tk"] += 1 if f.get("crossed") else 0
    daycoin[d][f["coin"]] += net_of(f)
dv = sorted(day.items())
eq_ref = venue if venue == venue and venue > 0 else 1.0
ths = [5000, 10000, 20000, 0.05 * eq_ref]
print(f"  active days={len(dv)} span={ts(fills[0]['time'])[:10]}..{ts(fills[-1]['time'])[:10]}")
for th in ths:
    n = sum(1 for _, v in dv if abs(v["net"]) >= th)
    print(f"   |daily realized net| >= ${th:,.0f}{' (=5% of equity)' if th == ths[-1] else ''}: {n} days")

# market context for the coin that dominated each big day
_cd = {}
def candles(coin, start_day):
    if coin not in _cd:
        r = q({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d",
                                                 "startTime": day_ms(start_day), "endTime": int(time.time() * 1000)}})
        _cd[coin] = {ts(c["t"])[:10]: c for c in (r or [])}
        time.sleep(0.15)
    return _cd[coin]


th_big = min(5000.0, 0.02 * eq_ref)
bigdays = sorted([(d, v) for d, v in dv if abs(v["net"]) >= th_big], key=lambda kv: -abs(kv[1]["net"]))[:25]
print(f"\n  -- top {len(bigdays)} days by |realized net| (threshold ${th_big:,.0f}); market ctx = that day's 1d candle of the dominant coin:")
print(f"     {'date':<11}{'net':>12} {'fills':>6} {'taker':>6} {'notional':>14}  dominant coins (net)   | market: coin day% range%")
start_day = ts(fills[0]["time"])[:10]
for d, v in bigdays:
    tops = sorted(daycoin[d].items(), key=lambda kv: -abs(kv[1]))[:3]
    dom = v["coins"].most_common(1)[0][0] if v["coins"] else None
    ctx = ""
    if dom and not is_spot(dom):
        c = candles(dom, start_day).get(d)
        if c:
            o, h, l, cl = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
            ctx = f"{dom} {(cl/o-1)*100:+.1f}% range {(h/l-1)*100:.1f}%"
        else:
            ctx = f"{dom} (no candle)"
    print(f"     {d:<11}{v['net']:>12,.0f} {v['n']:>6} {v['tk']/v['n']:>5.0%} {v['ntl']:>14,.0f}  "
          + ", ".join(f"{c}:{p:,.0f}" for c, p in tops) + f"   | {ctx}")

# what the account did on the 8 biggest days: episodes touching that day
print("\n  -- what the account did on the 8 biggest days (episodes overlapping the day):")
for d, v in bigdays[:8]:
    d0, d1 = day_ms(d), day_ms(d) + 86400000
    ep_day = [r for r in rows if r["t0"] < d1 and r["t1"] > d0]
    print(f"     {d} net={v['net']:,.0f} fills={v['n']} taker={v['tk']/v['n']:.0%} — {len(ep_day)} episodes overlapping:")
    hrs = collections.defaultdict(lambda: [0, 0.0])
    for f in fills:
        if ts(f["time"])[:10] != d:
            continue
        hrs[ts(f["time"])[11:13]][0] += 1; hrs[ts(f["time"])[11:13]][1] += net_of(f)
    print("        by hour (n/net): " + " ".join(f"{h}:{n}/{p:,.0f}" for h, (n, p) in sorted(hrs.items())))
    for r in sorted(ep_day, key=lambda r: -abs(r["net"]))[:5]:
        print(f"        {r['coin']:>10} {r['side']} {ts(r['t0'])[:16]}->{ts(r['t1'])[:16]} hold={fmt(r['hold']):>7} "
              f"peak_ntl={r['max_ntl']:>11,.0f} entries={r['n_open']} exits={r['n_close']} exit_maker={r['close_maker']:.0%} net={r['net']:,.0f}")

# daily trajectory for the top-4 PnL coins
TRACK = [c for c, _ in sorted(coin_net.items(), key=lambda kv: -abs(kv[1]))[:4]]
print(f"\n  -- daily trajectory of the 4 coins that dominate PnL: {TRACK}")
eod = collections.defaultdict(lambda: collections.defaultdict(lambda: {"net": 0.0, "n": 0, "buy": 0.0, "sell": 0.0, "eod": None}))
for f in fills:
    c = f["coin"]; sp = float(f["startPosition"]); sz = float(f["sz"])
    ep = sp + (sz if f["side"] == "B" else -sz)
    r = eod[c][ts(f["time"])[:10]]
    r["net"] += net_of(f); r["n"] += 1; r["eod"] = ep
    if f["side"] == "B":
        r["buy"] += sz
    else:
        r["sell"] += sz
for c in TRACK:
    cc = candles(c, start_day) if not is_spot(c) else {}
    cum = 0.0
    dsr = sorted(eod[c])
    print(f"   [{c}] {len(dsr)} active days, total net={coin_net[c]:,.0f}")
    show = dsr if len(dsr) <= 45 else [d for i, d in enumerate(dsr) if i % max(1, len(dsr) // 40) == 0 or abs(eod[c][d]['net']) >= th_big]
    for d in dsr:
        cum += eod[c][d]["net"]
        if d not in show:
            continue
        r = eod[c][d]; k = cc.get(d, {})
        pxmove = f"{(float(k['c'])/float(k['o'])-1)*100:+.1f}% rng {(float(k['h'])/float(k['l'])-1)*100:.1f}%" if k else "-"
        print(f"     {d} eod_pos={r['eod']:>14.4g} buy={r['buy']:>12.4g} sell={r['sell']:>12.4g} fills={r['n']:>5} "
              f"net={r['net']:>11,.0f} cum={cum:>12,.0f} | {pxmove}")

# =============================================================== [D] hold time
print("\n[D] HOLD TIME ----------------------------------------------------------------")
def hold_stats(es, label):
    if not es:
        print(f"   {label:<38}: none")
        return
    hs = sorted(e["hold_s"] for e in es)
    pct = lambda p: hs[min(len(hs) - 1, int(p * len(hs)))]
    tw = sum(e["ntl"] for e in es); acc = 0; wmed = hs[-1]
    for h, n in sorted((e["hold_s"], e["ntl"]) for e in es):
        acc += n
        if acc >= tw / 2:
            wmed = h; break
    wins = [e for e in es if e["pnl"] - e["fee"] > 0]
    losses = [e for e in es if e["pnl"] - e["fee"] <= 0]
    b = collections.Counter()
    for s in hs:
        b["<1m" if s < 60 else "<10m" if s < 600 else "<1h" if s < 3600 else "<4h" if s < 14400 else "<1d" if s < 86400 else "<7d" if s < 604800 else ">=7d"] += 1
    print(f"   {label:<38}: n={len(es):>4} p10={fmt(pct(.1)):>7} p25={fmt(pct(.25)):>7} p50={fmt(pct(.5)):>7} "
          f"p75={fmt(pct(.75)):>7} p90={fmt(pct(.9)):>7} max={fmt(hs[-1]):>7} | ntl-weighted p50={fmt(wmed):>7}")
    print(f"   {'':<38}  buckets={dict(b)}")
    print(f"   {'':<38}  win={len(wins)/len(es):.0%} avgWin={statistics.mean([e['pnl']-e['fee'] for e in wins]) if wins else 0:,.0f} "
          f"avgLoss={statistics.mean([e['pnl']-e['fee'] for e in losses]) if losses else 0:,.0f} "
          f"hold(win) p50={fmt(statistics.median([e['hold_s'] for e in wins])) if wins else '-':>7} "
          f"hold(loss) p50={fmt(statistics.median([e['hold_s'] for e in losses])) if losses else '-':>7}")


hold_stats(closed, "all episodes")
hold_stats([e for e in closed if e["side"] == "L"], "long only")
hold_stats([e for e in closed if e["side"] == "S"], "short only")
hold_stats([e for e in closed if e["pnl"] - e["fee"] > 0], "winners")
hold_stats([e for e in closed if e["pnl"] - e["fee"] <= 0], "losers")
hold_stats([e for e in closed if e["max_ntl"] >= 1e5], "large (peak notional >= 100k)")
# auto eras: 4 equal-time segments across the fill window
t0, t1 = fills[0]["time"], fills[-1]["time"]
for i in range(4):
    a = t0 + (t1 - t0) * i // 4
    b = t0 + (t1 - t0) * (i + 1) // 4
    hold_stats([e for e in closed if a <= e["t0"] < b], f"era {i+1}: {ts(a)[:10]}..{ts(b)[:10]}")
print("\n   -- era summary (fills, taker, realized net, fee bps):")
for i in range(4):
    a = t0 + (t1 - t0) * i // 4
    b = t0 + (t1 - t0) * (i + 1) // 4
    fs = [f for f in fills if a <= f["time"] < b]
    if not fs:
        continue
    ntl = sum(float(f["px"]) * float(f["sz"]) for f in fs)
    fee = sum(float(f["fee"]) for f in fs)
    print(f"     {ts(a)[:10]}..{ts(b)[:10]}: fills={len(fs):>6} days={len({ts(f['time'])[:10] for f in fs}):>3} "
          f"taker={sum(1 for f in fs if f.get('crossed'))/len(fs):>4.0%} ntl={ntl:>14,.0f} "
          f"net={sum(net_of(f) for f in fs):>12,.0f} fee_bps={fee/ntl*1e4 if ntl else 0:>5.2f}")

# =============================================================== [E] limits
print("\n[E] DATA LIMITS --------------------------------------------------------------")
print(f"  fills returned={len(fills)} (HL returns at most the 10000 most recent per page; pagination with tid dedup used)")
first_led = min((l["time"] for l in ledger), default=None)
print(f"  first ledger row={ts(first_led) if first_led else '-'} vs first fill={ts(fills[0]['time'])} "
      f"-> {'fills window likely TRUNCATED, earlier activity not visible' if first_led and first_led < fills[0]['time'] - 86400000 else 'fills appear to cover the account life'}")
if avh:
    print(f"  venue equity curve starts {ts(avh[0][0])[:10]}; fills start {ts(fills[0]['time'])[:10]}")
print(f"  funding rows={len(funding)} covering {ts(funding[0]['time'])[:10] if funding else '-'}.. "
      f"(userFunding startTime=0 returns only the first 500 rows — totals below are a LOWER bound)")
print(f"  realized closedPnl={sum(float(f['closedPnl']) for f in fills):,.0f} fees={sum(float(f['fee']) for f in fills):,.0f} "
      f"funding={sum(float(x['delta']['usdc']) for x in funding):,.0f}")
print("  spot sells: closedPnl is accounting vs historical average cost (cost basis may predate the window) — not a same-day market PnL")
print("  daily PnL is realized only, cut on UTC; the venue portfolio curve includes unrealized")

# reconstruction check (principle #1: reconstructed position must equal the exchange's)
print("\n  -- position reconstruction vs exchange (every coin must be OK):")
recon = {}
for f in perp:
    sp = float(f["startPosition"]); sz = float(f["sz"])
    recon[f["coin"]] = sp + (sz if f["side"] == "B" else -sz)
live = {p["coin"]: float(p["szi"]) for p in pos_rows}
last_fill_of = {}
for f in perp:
    last_fill_of[f["coin"]] = f["time"]
bad = stale = 0
for c in sorted(set(recon) | set(live)):
    r, l = recon.get(c, 0.0), live.get(c, 0.0)
    if abs(r - l) <= 1e-6:
        continue
    # a coin whose last fill is long past and which the exchange now shows flat was almost
    # certainly settled/delisted by the venue (HIP-3 stock and commodity perps expire) — that is
    # not a data gap. Anything else is a real hole and invalidates the episode stats.
    quiet_d = (fills[-1]["time"] - last_fill_of.get(c, 0)) / 86400000
    # a "#NNNN" coin id is a market no longer in HL's universe (expired HIP-3 / delisted) — the venue
    # settled it, so a flat live position with a non-zero reconstruction is settlement, not a data hole
    tag = "stale(settled/delisted?)" if abs(l) < 1e-12 and (quiet_d > 2 or c.startswith("#")) else "DRIFT"
    if tag == "DRIFT":
        bad += 1
    else:
        stale += 1
    print(f"     {c:>12} recon={r:>16.6f} live={l:>16.6f} diff={r-l:+.6f} last_fill={ts(last_fill_of.get(c,0))[:10]} ({quiet_d:.0f}d ago) {tag}")
print(f"     -> {bad} real DRIFT, {stale} stale/settled."
      + ("  OK: position reconstruction matches the exchange." if not bad
         else "  !! real DRIFT present — fills are incomplete, episode stats are NOT trustworthy."))

# =============================================================== counterparties
print("\n  -- transfer counterparties (ledger 'send' rows; who funds this wallet / where money goes):")
cp = collections.defaultdict(lambda: {"in_n": 0, "in_v": 0.0, "out_n": 0, "out_v": 0.0, "first": None, "last": None})
me = ADDR.lower()
for l in ledger:
    x = l["delta"]
    if x.get("type") != "send":
        continue
    src, dst = (x.get("user") or "").lower(), (x.get("destination") or "").lower()
    other = dst if src == me else src
    v = 0.0
    for k in ("usdcValue", "usdc", "amount"):
        try:
            v = float(x.get(k) or 0)
            if v:
                break
        except Exception:
            pass
    r = cp[other]
    if src == me:
        r["out_n"] += 1; r["out_v"] += v
    else:
        r["in_n"] += 1; r["in_v"] += v
    r["first"] = r["first"] or l["time"]; r["last"] = l["time"]
for addr_, r in sorted(cp.items(), key=lambda kv: -(kv[1]["in_v"] + kv[1]["out_v"]))[:12]:
    print(f"     {addr_}  in {r['in_n']:>3} rows ${r['in_v']:>12,.0f} | out {r['out_n']:>3} rows ${r['out_v']:>12,.0f} "
          f"| {ts(r['first'])[:10]}..{ts(r['last'])[:10]}")

json.dump(rows, open(D / "episodes_rows.json", "w"))
json.dump({d: v["net"] for d, v in dv}, open(D / "daily_net.json", "w"))
print("\n[done]")
