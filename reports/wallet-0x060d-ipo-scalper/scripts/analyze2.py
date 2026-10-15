import json, pathlib
import numpy as np, pandas as pd
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 300)
D = pathlib.Path(__file__).parent / "wallet"
L = lambda n: json.loads((D / f"{n}.json").read_text())

print("=== ledger sends raw ===")
for x in L("ledger"):
    if x["delta"]["type"] in ("send", "deposit", "withdraw", "accountClassTransfer", "internalTransfer"):
        print(pd.to_datetime(x["time"], unit="ms"), x["delta"])
print("=== sample spotTransfer ===", L("ledger")[5]["delta"], L("ledger")[-1]["delta"])
print("=== sample fill keys ===", L("fills")[0])
print("=== sample fill w/ builder ===", [x for x in L("fills") if x.get("builderFee")][:2])

# equity curve + drawdown from portfolio allTime
pf = dict(L("portfolio"))
av = pd.DataFrame(pf["allTime"]["accountValueHistory"], columns=["t", "v"]); av["t"] = pd.to_datetime(av.t, unit="ms"); av["v"] = av.v.astype(float)
pnl = pd.DataFrame(pf["allTime"]["pnlHistory"], columns=["t", "v"]); pnl["t"] = pd.to_datetime(pnl.t, unit="ms"); pnl["v"] = pnl.v.astype(float)
print("=== allTime accountValue samples ===", len(av))
print(av.set_index("t").v.resample("7D").last().to_string())
peak = pnl.v.cummax(); dd = pnl.v - peak
print("pnl max drawdown (abs $):", dd.min(), "at", pnl.t[dd.idxmin()], "; pnl peak at that time", peak[dd.idxmin()])
print("pnl monthly delta:"); print(pnl.set_index("t").v.resample("M").last().diff().to_string())

f = pd.read_pickle(D / "fills.pkl").sort_values("time").reset_index(drop=True)
f["signed"] = np.where(f.side == "B", f.sz, -f.sz)
f["endPos"] = f.startPosition + f.signed
f["hour"] = f.t.dt.hour
f["maker"] = ~f.crossed

# per coin: session stats
rows = []
for coin, g in f.groupby("coin"):
    g = g.sort_values("time")
    dur_h = (g.time.max() - g.time.min()) / 3.6e6
    gaps = g.time.diff().dropna() / 1000
    # active sessions: split when gap > 2h
    sess = (gaps > 7200).cumsum().reindex(g.index, fill_value=0)
    absmax = g.endPos.abs().max()
    absnot = (g.endPos.abs() * g.px).max()
    # time at zero position share
    flat_share = (g.endPos.abs() < 1e-9).mean()
    rows.append(dict(coin=coin, n=len(g), notional=g.notional.sum(), pnl=g.closedPnl.sum(), fee=g.fee.sum(),
                     maker_ct=g.maker.mean(), maker_not=(g.notional * g.maker).sum() / g.notional.sum(),
                     sessions=sess.nunique(), span_h=dur_h, med_gap_s=gaps.median(), max_pos_usd=absnot,
                     flat_share=flat_share, med_fill_usd=g.notional.median(), oids=g.oid.nunique(),
                     long_open=(g["dir"] == "Open Long").sum(), short_open=(g["dir"] == "Open Short").sum(),
                     pnl_bps=1e4 * g.closedPnl.sum() / g.notional.sum()))
S = pd.DataFrame(rows).sort_values("notional", ascending=False)
print("=== per-coin structure ===")
print(S.head(25).round(3).to_string())

print("=== hour of day (UTC) fill count ===")
print(f.groupby("hour").size().to_string())
print("=== maker vs taker pnl ===")
print(f.groupby("maker").agg(n=("tid", "size"), notional=("notional", "sum"), pnl=("closedPnl", "sum"), fee=("fee", "sum")))
print("=== fee bps by maker ===")
print((1e4 * f.groupby("maker").fee.sum() / f.groupby("maker").notional.sum()))
print("=== dir x maker ===")
print(pd.crosstab(f["dir"], f.maker))
