"""Compact one-block-per-wallet triage table over data/<addr10>/.

Usage: python triage.py            (all wallets found under data/)
Emits ~8 lines per wallet: equity buckets, activity, style fingerprint, PnL, hold time.
Designed so the main thread can read all 22 wallets in one go without pulling raw JSON.
"""
import gzip, json, pathlib, collections, statistics, sys
from datetime import datetime, timezone
import requests

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"
URL = "https://api.hyperliquid.xyz/info"


def ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def fmt_s(s):
    return f"{s:.0f}s" if s < 90 else (f"{s/60:.1f}m" if s < 3600 else (f"{s/3600:.1f}h" if s < 86400 else f"{s/86400:.1f}d"))


# --- spot pricing (for spot token equity) -------------------------------------
def q(payload, retries=8):
    import time
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=60)
        if r.status_code == 200 and r.json() is not None:
            return r.json()
        time.sleep(5.0 * (i + 1))
    raise RuntimeError(f"info query failed: {payload['type']}")


mids = q({"type": "allMids"})
sm = q({"type": "spotMeta"})
pair_of = {}   # token name -> "@NNN" pair name
for u in sm["universe"]:
    base = u["tokens"][0]
    name = next((t["name"] for t in sm["tokens"] if t["index"] == base), None)
    if name and name not in pair_of:
        pair_of[name] = u["name"]
STABLE = {"USDC", "USDH", "USDT0", "USDE", "FEUSD"}


def spot_value(balances):
    """Spot value FREE of margin.

    2026-09-21: `total` includes the balance held as perp margin (unifiedAccount posts margin
    out of spot; portfolioMargin can even show a negative hold = borrowing). Adding `total` to
    perp accountValue double-counts that bucket — engineering principle #1. Use total - hold.
    """
    cash, toks, detail = 0.0, 0.0, []
    for b in balances:
        t = float(b["total"]) - float(b.get("hold", 0) or 0)
        if abs(t) < 1e-9:
            continue
        if b["coin"] in STABLE:
            cash += t
            detail.append(f"{b['coin']}={t:.0f}(free)")
        else:
            px = float(mids.get(pair_of.get(b["coin"], ""), 0) or 0)
            v = t * px
            toks += v
            if abs(v) > 50:
                detail.append(f"{b['coin']}={t:.4g}(${v:.0f})")
    return cash, toks, detail


def analyze(d):
    a10 = d.name
    out = []
    try:
        fills = json.load(gzip.open(d / "fills.json.gz"))
    except Exception as e:
        return [f"### {a10}  !! no fills file ({e})"]
    # userFillsByTime omits TWAP slice fills — merge them or every number here is understated
    n_twap = 0
    if (d / "twap_fills.json.gz").exists():
        have = {f["tid"] for f in fills}
        extra = [f for f in json.load(gzip.open(d / "twap_fills.json.gz")) if f["tid"] not in have]
        fills.extend(extra); n_twap = len(extra)
    states = json.load(open(d / "clearinghouseState_all.json"))
    spot = json.load(open(d / "spotClearinghouseState.json"))
    ledger = json.load(open(d / "ledger.json"))
    openo = json.load(open(d / "frontendOpenOrders.json"))
    portfolio = dict(json.load(open(d / "portfolio.json")))
    ua = json.load(open(d / "userAbstraction.json"))
    funding = json.load(open(d / "funding.json"))

    # ---- equity buckets
    perp_av, perp_ntl, dexes, poss = 0.0, 0.0, [], []
    for dex, st in states.items():
        if not isinstance(st, dict):
            continue
        ms = st.get("marginSummary", {})
        av = float(ms.get("accountValue", 0) or 0)
        if av > 0 or st.get("assetPositions"):
            perp_av += av
            perp_ntl += float(ms.get("totalNtlPos", 0) or 0)
            dexes.append(f"{dex}:{av:.0f}")
            for ap in st.get("assetPositions", []):
                p = ap["position"]
                poss.append((p["coin"], float(p["szi"]), float(p["positionValue"]), float(p["unrealizedPnl"])))
    cash, toks, sdetail = spot_value(spot.get("balances", []))
    # staked HYPE is a bucket of its own and is invisible in spot/perp state (0x9e2cbb5d: 98% of equity)
    addr_full = [x for x in (ROOT / "addrs.txt").read_text().split() if x.startswith(a10)][0]
    ds = q({"type": "delegatorSummary", "user": addr_full}) or {}
    staked = sum(float(ds.get(k, 0) or 0) for k in ("delegated", "undelegated", "totalPendingWithdrawal")) \
        * float(mids.get(pair_of.get("HYPE", "@107"), 0) or 0)
    equity = perp_av + cash + toks + staked
    upnl = sum(p[3] for p in poss)

    if not fills:
        return [f"### {a10}  !! zero fills; equity=${equity:.0f} ua={ua}"]
    fills.sort(key=lambda f: f["time"])

    # ---- activity
    first, last = fills[0]["time"], fills[-1]["time"]
    span_d = (last - first) / 86400000 or 1
    is_spot = lambda c: c.startswith("@") or "/" in c
    perp_f = [f for f in fills if not is_spot(f["coin"])]
    spot_f = [f for f in fills if is_spot(f["coin"])]
    ntl = sum(float(f["px"]) * float(f["sz"]) for f in perp_f)
    taker = sum(1 for f in fills if f.get("crossed"))
    buys = sum(1 for f in perp_f if f["side"] == "B")
    coins = collections.Counter(f["coin"] for f in fills)
    coin_ntl = collections.Counter()
    for f in fills:
        coin_ntl[f["coin"]] += float(f["px"]) * float(f["sz"])
    hip3 = sum(v for c, v in coin_ntl.items() if ":" in c)
    liq = [f for f in fills if f.get("liquidation")]
    twap = sum(1 for f in fills if f.get("twapId"))

    # ---- money in/out
    dep = sum(float(l["delta"].get("usdc", 0) or 0) for l in ledger if l["delta"]["type"] == "deposit")
    wd = sum(float(l["delta"].get("usdc", 0) or 0) for l in ledger if l["delta"]["type"] == "withdraw")
    lt = collections.Counter(l["delta"]["type"] for l in ledger)
    cpnl = sum(float(f["closedPnl"]) for f in fills)
    fee = sum(float(f["fee"]) for f in fills)
    fund = sum(float(x["delta"]["usdc"]) for x in funding)

    # ---- portfolio curve
    pcurve = ""
    for k in ("allTime",):
        if k in portfolio:
            avh = portfolio[k]["accountValueHistory"]
            if avh:
                pcurve = f"{ts(avh[0][0])[:10]} av={float(avh[0][1]):.0f} -> {ts(avh[-1][0])[:10]} av={float(avh[-1][1]):.0f} pnl={float(portfolio[k]['pnlHistory'][-1][1]):.0f} vlm={float(portfolio[k]['vlm']):.0f}"

    # ---- daily net realized
    day = collections.defaultdict(float)
    for f in fills:
        day[ts(f["time"])[:10]] += float(f["closedPnl"]) - float(f["fee"])
    dv = sorted(day.items())
    big5 = sum(1 for _, v in dv if abs(v) >= 5000)
    big20 = sum(1 for _, v in dv if abs(v) >= 20000)
    worst = min(dv, key=lambda x: x[1]) if dv else ("-", 0)
    best = max(dv, key=lambda x: x[1]) if dv else ("-", 0)

    # ---- round trips (perp only)
    trips, cur = [], {}
    for f in perp_f:
        c = f["coin"]
        sp, sz, side = float(f["startPosition"]), float(f["sz"]), f["side"]
        ep = sp + (sz if side == "B" else -sz)
        if cur.get(c) is None or abs(sp) < 1e-12:
            cur[c] = {"coin": c, "t0": f["time"], "side": "L" if side == "B" else "S", "pnl": 0.0, "fee": 0.0,
                      "n": 0, "ntl": 0.0, "max_abs": 0.0, "taker": 0}
        r = cur[c]
        r["pnl"] += float(f["closedPnl"]); r["fee"] += float(f["fee"]); r["n"] += 1
        r["ntl"] += float(f["px"]) * sz; r["max_abs"] = max(r["max_abs"], abs(ep) * float(f["px"]))
        r["taker"] += 1 if f.get("crossed") else 0
        if abs(ep) < 1e-12:
            r["hold_s"] = (f["time"] - r["t0"]) / 1000
            trips.append(r); cur[c] = None
    hold = ""
    if trips:
        hs = sorted(t["hold_s"] for t in trips)
        p = lambda q: hs[min(len(hs) - 1, int(q * len(hs)))]
        wins = [t for t in trips if t["pnl"] - t["fee"] > 0]
        losses = [t for t in trips if t["pnl"] - t["fee"] <= 0]
        ls = collections.Counter(t["side"] for t in trips)
        hold = (f"trips={len(trips)} p25={fmt_s(p(.25))} med={fmt_s(p(.5))} p75={fmt_s(p(.75))} p90={fmt_s(p(.9))} max={fmt_s(hs[-1])} "
                f"win={len(wins)/len(trips):.0%} avgW={statistics.mean([t['pnl']-t['fee'] for t in wins]) if wins else 0:.0f} "
                f"avgL={statistics.mean([t['pnl']-t['fee'] for t in losses]) if losses else 0:.0f} L/S={ls['L']}/{ls['S']} "
                f"pnlL={sum(t['pnl']-t['fee'] for t in trips if t['side']=='L'):.0f} pnlS={sum(t['pnl']-t['fee'] for t in trips if t['side']=='S'):.0f}")

    oo_ntl = sum(float(o["sz"]) * float(o["limitPx"]) for o in openo)
    oo_side = collections.Counter(o["side"] for o in openo)

    out.append(f"### {a10}  equity=${equity:,.0f} (perp {perp_av:,.0f} [{' '.join(dexes) or '-'}] + spot cash {cash:,.0f} + spot tok {toks:,.0f} + staked {staked:,.0f}) ua={ua}")
    out.append(f"  pos({len(poss)}): " + (", ".join(f"{c}{'+' if s>0 else ''}{s:.4g}(${v:,.0f},u{u:,.0f})" for c, s, v, u in sorted(poss, key=lambda x: -x[2])[:8]) or "flat") + f"  upnl={upnl:,.0f} perpNtl={perp_ntl:,.0f}")
    out.append(f"  orders={len(openo)} {dict(oo_side)} ntl=${oo_ntl:,.0f} | ledger={dict(lt)} dep={dep:,.0f} wd={wd:,.0f}")
    out.append(f"  fills={len(fills)} (perp {len(perp_f)} / spot {len(spot_f)}; twap {twap}, {n_twap} merged) {ts(first)}..{ts(last)} span={span_d:.0f}d rate={len(fills)/span_d:.1f}/d taker={taker/len(fills):.0%} buy={buys/max(1,len(perp_f)):.0%} liqFills={len(liq)}")
    out.append(f"  coins={len(coins)} top: " + ", ".join(f"{c}({v/max(1,sum(coin_ntl.values())):.0%})" for c, v in coin_ntl.most_common(6)) + f" | HIP3ntl={hip3/max(1,sum(coin_ntl.values())):.0%}")
    out.append(f"  realized closedPnl={cpnl:,.0f} fees={fee:,.0f} funding={fund:,.0f} net={cpnl-fee:,.0f} | perpNtlTraded={ntl:,.0f}")
    out.append(f"  portfolio: {pcurve}")
    out.append(f"  days={len(dv)} |net|>=5k:{big5} >=20k:{big20} best={best[0]} {best[1]:,.0f} worst={worst[0]} {worst[1]:,.0f}")
    out.append(f"  {hold}")
    out.append(f"  spotBal: {', '.join(sdetail[:8]) or '-'}")
    return out


targets = sys.argv[1:] or sorted(p.name for p in DATA.iterdir() if p.is_dir())
for a in targets:
    d = DATA / a
    try:
        for line in analyze(d):
            print(line)
    except Exception as e:
        print(f"### {a}  !! ERROR {type(e).__name__}: {e}")
    print()
