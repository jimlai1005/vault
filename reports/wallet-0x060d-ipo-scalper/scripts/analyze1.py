import json, pathlib
import pandas as pd
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 200)
D = pathlib.Path(__file__).parent / "wallet"
L = lambda n: json.loads((D / f"{n}.json").read_text())

print("=== clearinghouse per dex ===")
for dex, s in L("clearinghouseState_all").items():
    ms = s["marginSummary"]
    if float(ms["accountValue"]) > 0 or s["assetPositions"]:
        print(dex, "acctValue", ms["accountValue"], "marginUsed", ms["totalMarginUsed"], "withdrawable", s["withdrawable"])
        for ap in s["assetPositions"]:
            p = ap["position"]
            print("   POS", p["coin"], "szi", p["szi"], "entry", p["entryPx"], "lev", p["leverage"], "upnl", p["unrealizedPnl"], "liq", p["liquidationPx"])
print("=== spot ===")
for b in L("spotClearinghouseState")["balances"]:
    if float(b["total"]) > 0: print("  ", b["coin"], b["total"])
print("=== open orders ===", len(L("frontendOpenOrders")))

pf = L("portfolio")
print("=== portfolio ===")
for k, v in pf:
    avh = v["accountValueHistory"]; ph = v["pnlHistory"]
    if avh:
        print(k, "acctValue first", avh[0], "last", avh[-1], "| pnl last", ph[-1] if ph else None, "vlm", v.get("vlm"))

led = pd.DataFrame(L("ledger"))
led["t"] = pd.to_datetime(led["time"], unit="ms")
led["type"] = led["delta"].apply(lambda d: d["type"])
led["usdc"] = led["delta"].apply(lambda d: float(d.get("usdc", d.get("amount", 0)) or 0))
print("=== ledger by type ===")
print(led.groupby("type")["usdc"].agg(["count", "sum"]))
print(led[["t", "type", "usdc"]].head(15)); print(led[["t", "type", "usdc"]].tail(15))

fund = pd.DataFrame(L("funding"))
if len(fund):
    fund["usdc"] = fund["delta"].apply(lambda d: float(d["usdc"]))
    fund["coin"] = fund["delta"].apply(lambda d: d["coin"])
    print("=== funding total ===", fund["usdc"].sum()); print(fund.groupby("coin")["usdc"].sum())

f = pd.DataFrame(L("fills"))
f["t"] = pd.to_datetime(f["time"], unit="ms")
for c in ["px", "sz", "fee", "closedPnl", "startPosition"]:
    f[c] = f[c].astype(float)
f["notional"] = f.px * f.sz
print("=== fills ===", len(f), f.t.min(), f.t.max())
print("unique oids", f.oid.nunique(), "unique tids", f.tid.nunique())
print("crossed (taker) share by count:", f.crossed.mean(), " by notional:", (f.notional * f.crossed).sum() / f.notional.sum())
print("feeToken", f.feeToken.value_counts().to_dict())
print("dir", f["dir"].value_counts().to_dict())
print("total notional", f.notional.sum(), "total fee", f.fee.sum(), "total closedPnl", f.closedPnl.sum())
g = f.groupby("coin").agg(n=("tid", "size"), notional=("notional", "sum"), fee=("fee", "sum"), pnl=("closedPnl", "sum"), first=("t", "min"), last=("t", "max"))
print(g.sort_values("notional", ascending=False).head(40))
f["day"] = f.t.dt.date
d = f.groupby("day").agg(n=("tid", "size"), notional=("notional", "sum"), pnl=("closedPnl", "sum"), coins=("coin", "nunique"))
print(d.to_string())
f.to_pickle(D / "fills.pkl")
