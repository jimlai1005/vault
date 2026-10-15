import json, pathlib, time
import numpy as np, pandas as pd, requests
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 300)
D = pathlib.Path(__file__).parent / "wallet"
f = pd.read_pickle(D / "fills.pkl").sort_values("time").reset_index(drop=True)
f["signed"] = np.where(f.side == "B", f.sz, -f.sz); f["endPos"] = f.startPosition + f.signed; f["maker"] = ~f.crossed
f["hour"] = f.t.dt.hour

print("=== hour histogram per coin (UTC, share of fills) ===")
for coin in ["xyz:CXMT", "xyz:SKHY", "xyz:DRAM", "xyz:SPCX", "xyz:UNITREE", "xyz:QNT", "xyz:CBRS", "PONS", "CASHCAT", "@107"]:
    h = f[f.coin == coin].groupby("hour").size()
    h = (h / h.sum()).reindex(range(24), fill_value=0)
    print(f"{coin:12s}", " ".join(f"{int(round(x*100)):2d}" for x in h.values))

# round trips
def roundtrips(g):
    g = g.sort_values("time"); out = []; cur = None
    for r in g.itertuples():
        if cur is None:
            cur = dict(t0=r.time, side=r.side, buy_not=0, sell_not=0, buy_sz=0, sell_sz=0, pnl=0, fee=0, n=0, taker_entry=0, maker_exit=0, n_open=0, n_close=0, maxpos=0)
        cur["n"] += 1; cur["pnl"] += r.closedPnl; cur["fee"] += r.fee
        if r.side == "B": cur["buy_not"] += r.notional; cur["buy_sz"] += r.sz
        else: cur["sell_not"] += r.notional; cur["sell_sz"] += r.sz
        if r.dir.startswith("Open"): cur["n_open"] += 1; cur["taker_entry"] += r.crossed
        elif r.dir.startswith("Close"): cur["n_close"] += 1; cur["maker_exit"] += (not r.crossed)
        cur["maxpos"] = max(cur["maxpos"], abs(r.endPos) * r.px)
        if abs(r.endPos) < 1e-9:
            cur["t1"] = r.time; out.append(cur); cur = None
    return pd.DataFrame(out)

URL = "https://api.hyperliquid.xyz/info"
def candles(coin, t0, t1, iv):
    r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": iv, "startTime": int(t0), "endTime": int(t1)}}, timeout=30)
    c = pd.DataFrame(r.json())
    for k in ["o", "h", "l", "c", "v"]: c[k] = c[k].astype(float)
    return c

summary = []
for coin, iv, ivms in [("PONS", "1m", 60000), ("io:GPRO", "5m", 300000), ("xyz:SHEIN", "5m", 300000), ("CASHCAT", "5m", 300000), ("xyz:MRNA", "15m", 900000), ("xyz:UNITREE", "15m", 900000)]:
    g = f[f.coin == coin]
    rt = roundtrips(g)
    rt["dir"] = np.where(rt.side == "B", "LONG", "SHORT")
    rt["hold_s"] = (rt.t1 - rt.t0) / 1000
    rt["entry_px"] = np.where(rt.side == "B", rt.buy_not / rt.buy_sz, rt.sell_not / rt.sell_sz)
    rt["exit_px"] = np.where(rt.side == "B", rt.sell_not / rt.sell_sz, rt.buy_not / rt.buy_sz)
    rt["ret_bps"] = 1e4 * (rt.exit_px / rt.entry_px - 1) * np.where(rt.side == "B", 1, -1)
    c = candles(coin, g.time.min() - 3600_000, g.time.max() + 3600_000, iv); time.sleep(0.3)
    c = c.set_index("t")
    def ret_before(t, k):
        i = (t // ivms) * ivms
        try: return 1e4 * (c.loc[i - ivms, "c"] / c.loc[i - k * ivms, "o"] - 1)
        except KeyError: return np.nan
    def ret_after(t, k):
        i = (t // ivms) * ivms
        try: return 1e4 * (c.loc[i + k * ivms, "c"] / c.loc[i + ivms, "o"] - 1)
        except KeyError: return np.nan
    rt = rt[rt.t0 >= c.index.min() + 5 * ivms]
    if not len(rt): print(coin, "no candle coverage"); continue
    sgn = np.where(rt.side == "B", 1, -1)
    rt["pre1"] = [ret_before(t, 1) for t in rt.t0] * sgn
    rt["pre5"] = [ret_before(t, 5) for t in rt.t0] * sgn
    rt["post3_from_exit"] = [ret_after(t, 3) for t in rt.t1] * sgn
    rt["taker_entry_share"] = rt.taker_entry / rt.n_open.clip(lower=1)
    rt["maker_exit_share"] = rt.maker_exit / rt.n_close.clip(lower=1)
    print(f"=== {coin} round trips (candle {iv}, {len(rt)} trips with coverage) ===")
    print(rt[["dir", "hold_s", "maxpos", "ret_bps", "pnl", "fee", "pre1", "pre5", "post3_from_exit", "taker_entry_share", "maker_exit_share"]].describe().round(1).to_string())
    print("win rate:", (rt.pnl > 0).mean().round(3), " long share:", (rt.side == "B").mean().round(2),
          " pre5 sign agree (momentum) share:", (rt.pre5 > 0).mean().round(2), " pre1 agree:", (rt.pre1 > 0).mean().round(2))
    print("pnl by dir:"); print(rt.groupby("dir").agg(n=("pnl", "size"), pnl=("pnl", "sum"), wr=("pnl", lambda s: (s > 0).mean()), med_hold=("hold_s", "median"), med_ret=("ret_bps", "median")).round(2))
    summary.append(dict(coin=coin, trips=len(rt), wr=(rt.pnl > 0).mean(), avg_pnl=rt.pnl.mean(), med_hold_s=rt.hold_s.median(), med_ret_bps=rt.ret_bps.median(),
                        avg_pre5=rt.pre5.mean(), mom_share=(rt.pre5 > 0).mean(), avg_post3=rt.post3_from_exit.mean(), taker_entry=rt.taker_entry_share.mean(), maker_exit=rt.maker_exit_share.mean()))
print(pd.DataFrame(summary).round(2).to_string())

# global round-trip stats for all coins (no candles)
allrt = []
for coin, g in f[~f.coin.str.startswith("@")].groupby("coin"):
    rt = roundtrips(g); rt["coin"] = coin; allrt.append(rt)
A = pd.concat(allrt); A["hold_s"] = (A.t1 - A.t0) / 1000
print("=== ALL round trips ===", len(A), "win rate", (A.pnl > 0).mean().round(3), "avg pnl", A.pnl.mean().round(1), "median hold s", A.hold_s.median(), "p90 hold s", A.hold_s.quantile(.9))
print("pnl per trip quantiles:", A.pnl.quantile([.05, .25, .5, .75, .95]).round(1).to_dict())
print("worst 10 trips:"); print(A.nsmallest(10, "pnl")[["coin", "t0", "side", "hold_s", "maxpos", "pnl"]].assign(t0=lambda d: pd.to_datetime(d.t0, unit="ms")).to_string())
print("best 10 trips:"); print(A.nlargest(10, "pnl")[["coin", "t0", "side", "hold_s", "maxpos", "pnl"]].assign(t0=lambda d: pd.to_datetime(d.t0, unit="ms")).to_string())
print("maxpos quantiles:", A.maxpos.quantile([.25, .5, .75, .95]).round(0).to_dict())
print("trips per day:", A.groupby(pd.to_datetime(A.t0, unit="ms").dt.date).size().describe().round(1).to_dict())
