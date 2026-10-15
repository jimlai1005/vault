"""Equity basis reconciliation for every wallet under data/.

Global engineering principle #1: enumerate EVERY bucket this wallet's value can sit in,
count each exactly once, and reconcile against what the venue itself reports
(portfolio.allTime.accountValueHistory last point = HL's own equity curve).

Buckets:
  spot_free  = spot balances (total - hold), stables at 1.0, tokens at allMids
  perp_av    = sum of clearinghouseState.marginSummary.accountValue over ALL perp dexes
               (unifiedAccount: this equals the margin held out of spot + upnl, hence spot uses total-hold)
  staked     = delegatorSummary: delegated + undelegated + totalPendingWithdrawal (HYPE, priced at mid)
  vault      = userVaultEquities: equity in HL vaults
Usage: python equity_recon.py [addr10 ...]
"""
import json, pathlib, sys, time
import requests

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"
URL = "https://api.hyperliquid.xyz/info"
STABLE = {"USDC", "USDH", "USDT0", "USDE", "FEUSD"}


def q(payload, retries=8):
    for i in range(retries):
        r = requests.post(URL, json=payload, timeout=60)
        if r.status_code == 200 and r.json() is not None:
            return r.json()
        time.sleep(5.0 * (i + 1))
    raise RuntimeError(f"failed {payload['type']}")


mids = q({"type": "allMids"})
sm = q({"type": "spotMeta"})
pair_of = {}
for u in sm["universe"]:
    name = next((t["name"] for t in sm["tokens"] if t["index"] == u["tokens"][0]), None)
    if name and name not in pair_of:
        pair_of[name] = u["name"]
hype_px = float(mids.get(pair_of.get("HYPE", "@107"), 0) or 0)

print(f"{'addr':<12} {'mode':<16} {'spot_free':>12} {'perp_av':>12} {'staked':>11} {'vault':>11} {'TOTAL':>13} {'venue_pf':>13} {'drift':>11} {'drift%':>7}")
for a in (sys.argv[1:] or sorted(p.name for p in DATA.iterdir() if p.is_dir())):
    d = DATA / a
    addr = None
    try:
        sb = json.load(open(d / "spotClearinghouseState.json"))
        st = json.load(open(d / "clearinghouseState_all.json"))
        ua = json.load(open(d / "userAbstraction.json"))
        pf = dict(json.load(open(d / "portfolio.json")))
    except Exception as e:
        print(f"{a:<12} !! {e}")
        continue
    addr = [x for x in open(ROOT / "addrs.txt").read().split() if x.startswith(a)][0]

    spot_free = 0.0
    for b in sb.get("balances", []):
        free = float(b["total"]) - float(b.get("hold", 0) or 0)
        px = 1.0 if b["coin"] in STABLE else float(mids.get(pair_of.get(b["coin"], ""), 0) or 0)
        spot_free += free * px
    perp_av = sum(float((s or {}).get("marginSummary", {}).get("accountValue", 0) or 0)
                  for s in st.values() if isinstance(s, dict))
    ds = q({"type": "delegatorSummary", "user": addr})
    staked_hype = sum(float(ds.get(k, 0) or 0) for k in ("delegated", "undelegated", "totalPendingWithdrawal"))
    staked = staked_hype * hype_px
    ve = q({"type": "userVaultEquities", "user": addr}) or []
    vault = sum(float(v.get("equity", 0) or 0) for v in ve)
    total = spot_free + perp_av + staked + vault
    avh = pf.get("allTime", {}).get("accountValueHistory", [])
    venue = float(avh[-1][1]) if avh else float("nan")
    drift = total - venue
    print(f"{a:<12} {ua:<16} {spot_free:>12,.0f} {perp_av:>12,.0f} {staked:>11,.0f} {vault:>11,.0f} {total:>13,.0f} {venue:>13,.0f} {drift:>11,.0f} {drift/venue*100 if venue else 0:>6.1f}%")
    time.sleep(0.2)
