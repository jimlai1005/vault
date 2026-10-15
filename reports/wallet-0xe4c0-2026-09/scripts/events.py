"""Big-day narratives: for each wallet's largest |daily net| days, print market
context (1d candle % move of the coins traded) and what the wallet did that day.

Usage: python events.py
"""
import gzip, json, pathlib, collections, time
from datetime import datetime, timezone, timedelta
import requests

ROOT = pathlib.Path(__file__).parent.parent / "data"
URL = "https://api.hyperliquid.xyz/info"
def ts(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def day_ms(d): return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

_c = {}
def daily(coin):
    if coin not in _c:
        r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": day_ms("2026-02-01"), "endTime": int(time.time() * 1000)}}, timeout=30)
        _c[coin] = {ts(c["t"])[:10]: c for c in (r.json() if r.status_code == 200 else [])}
        time.sleep(0.2)
    return _c[coin]

def mkt(coin, d):
    c = daily(coin).get(d)
    if not c: return f"{coin}: n/a"
    o, h, l, cl = map(float, (c["o"], c["h"], c["l"], c["c"]))
    return f"{coin} {(cl/o-1)*100:+.1f}% (range {(h/l-1)*100:.1f}%, o={o:g} h={h:g} l={l:g} c={cl:g})"

WALLETS = {"0xe4c0f755": 20}
for w, topn in WALLETS.items():
    D = ROOT / w
    fills = json.load(gzip.open(D / "fills.json.gz")); fills.sort(key=lambda f: f["time"])  # stable: keep API order within the same ms (tid order != execution order)
    trips = json.load(open(D / "trips.json"))
    dailyj = json.load(open(D / "daily.json"))
    print("#" * 100); print("WALLET", w)
    days = sorted(dailyj.items(), key=lambda kv: -abs(kv[1]["net"]))[:topn]
    for d, v in sorted(days):
        t0, t1 = day_ms(d), day_ms(d) + 86400000
        fs = [f for f in fills if t0 <= f["time"] < t1]
        pnl_by_coin = collections.defaultdict(float); n_by_coin = collections.Counter()
        for f in fs:
            pnl_by_coin[f["coin"]] += float(f["closedPnl"]) - float(f["fee"]); n_by_coin[f["coin"]] += 1
        top = sorted(pnl_by_coin.items(), key=lambda kv: -abs(kv[1]))[:5]
        print("-" * 100)
        print(f"{d}  net={v['net']:.2f} fills={v['n']} ntl={v['ntl']:.0f}")
        print("  pnl by coin:", [(c, round(p), n_by_coin[c]) for c, p in top])
        print("  market:", " | ".join(mkt(c, d) for c, _ in top[:3]))
        # trips closed this day (largest)
        td = [t for t in trips if t0 <= t["t1"] < t1]
        for t in sorted(td, key=lambda t: -abs(t["pnl"] - t["fee"]))[:5]:
            hs = t["hold_s"]; hstr = f"{hs:.0f}s" if hs < 60 else f"{hs/60:.0f}m" if hs < 3600 else f"{hs/3600:.1f}h" if hs < 86400 else f"{hs/86400:.1f}d"
            print(f"    trip {t['coin']:>9} {t['side']} {ts(t['t0'])[5:16]}->{ts(t['t1'])[5:16]} hold={hstr:>6} maxsz={t['max_abs']:.4g} ntl={t['ntl']:.0f} net={t['pnl']-t['fee']:.2f}")
        # hourly pnl profile of the day (to see when it happened)
        hp = collections.defaultdict(float)
        for f in fs: hp[ts(f["time"])[11:13]] += float(f["closedPnl"]) - float(f["fee"])
        big = sorted(hp.items(), key=lambda kv: -abs(kv[1]))[:3]
        print("  biggest hours (UTC):", [(h, round(p)) for h, p in big])
