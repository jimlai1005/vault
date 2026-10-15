import json, pathlib, time
import numpy as np, pandas as pd, requests
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 300)
D = pathlib.Path(__file__).parent / "wallet"
f = pd.read_pickle(D / "fills.pkl").sort_values("time").reset_index(drop=True)
f["signed"] = np.where(f.side == "B", f.sz, -f.sz); f["endPos"] = f.startPosition + f.signed; f["maker"] = ~f.crossed
print("cloid present share:", f.cloid.notna().mean(), " fills/oid:", len(f) / f.oid.nunique())

TOP = ["xyz:CXMT", "PONS", "xyz:SKHY", "xyz:DRAM", "CASHCAT", "xyz:SPCX", "xyz:UNITREE", "io:GPRO", "xyz:QNT", "xyz:MRNA", "xyz:CBRS", "para:UNITREE", "xyz:SHEIN"]
URL = "https://api.hyperliquid.xyz/info"

def candles(coin, t0, t1, iv="1h"):
    r = requests.post(URL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": iv, "startTime": int(t0), "endTime": int(t1)}}, timeout=30)
    c = pd.DataFrame(r.json())
    if len(c):
        for k in ["o", "h", "l", "c", "v"]: c[k] = c[k].astype(float)
        c["t"] = pd.to_datetime(c.t, unit="ms")
    return c

rows = []
allc = {}
for coin in TOP:
    g = f[f.coin == coin]
    c = candles(coin, 0, g.time.max() + 86400_000)
    time.sleep(0.3)
    allc[coin] = c
    if not len(c):
        rows.append(dict(coin=coin, note="no candles")); continue
    win = c[(c.t >= g.t.min().floor("h")) & (c.t <= g.t.max())]
    mkt_not = (win.v * win.c).sum()
    rows.append(dict(coin=coin, first_candle=c.t.min(), first_fill=g.t.min(), age_at_first_fill_d=(g.t.min() - c.t.min()).total_seconds() / 86400,
                     hrs_traded=len(win), mkt_notional_in_window=mkt_not, wallet_share=g.notional.sum() / mkt_not if mkt_not else np.nan,
                     px_first=g.px.iloc[0], px_last=g.px.iloc[-1], px_move=g.px.iloc[-1] / g.px.iloc[0] - 1,
                     win_range=(win.h.max() / win.l.min() - 1) if len(win) else np.nan))
print(pd.DataFrame(rows).round(3).to_string())
pd.to_pickle(allc, D / "candles.pkl")

# inventory / round-trip behaviour
print("=== inventory behaviour per coin ===")
rows = []
for coin in TOP:
    g = f[f.coin == coin].sort_values("time")
    pos = g.endPos.values; t = g.time.values
    # time-weighted |pos| in USD and share of time long/short/flat within active span
    dt = np.diff(t, append=t[-1]) / 1000
    usd = np.abs(pos) * g.px.values
    tw = (usd * dt).sum() / dt.sum()
    sign = np.sign(pos)
    flips = (np.diff(sign) != 0).sum()
    # holding time: duration between position leaving zero and returning to zero
    zero = np.abs(pos) < 1e-9
    seg_start, hold = None, []
    for i in range(len(pos)):
        if not zero[i] and seg_start is None: seg_start = t[i]
        if zero[i] and seg_start is not None: hold.append((t[i] - seg_start) / 60000); seg_start = None
    rows.append(dict(coin=coin, tw_pos_usd=tw, sign_flips=flips, roundtrips=len(hold), med_hold_min=np.median(hold) if hold else np.nan,
                     p90_hold_min=np.percentile(hold, 90) if hold else np.nan, long_time_share=(dt * (sign > 0)).sum() / dt.sum(), short_time_share=(dt * (sign < 0)).sum() / dt.sum()))
print(pd.DataFrame(rows).round(2).to_string())

# both-sided quoting: within 60s windows, share of windows with both buy and sell maker fills
print("=== two-sided maker activity ===")
m = f[f.maker]
m["w"] = m.time // 60000
ws = m.groupby(["coin", "w"]).side.nunique()
print(ws.groupby("coin").apply(lambda s: (s == 2).mean()).loc[[c for c in TOP if c in ws.index.get_level_values(0)]].round(2))

print("=== raw sample: xyz:CXMT 15 min ===")
g = f[f.coin == "xyz:CXMT"]
t0 = g.time.iloc[len(g) // 2]
print(g[(g.time >= t0) & (g.time < t0 + 15 * 60000)][["t", "side", "px", "sz", "maker", "dir", "startPosition", "endPos", "closedPnl", "oid"]].head(60).to_string())
print("=== raw sample: io:GPRO first 40 ===")
print(f[f.coin == "io:GPRO"][["t", "side", "px", "sz", "maker", "dir", "startPosition", "endPos", "closedPnl"]].head(40).to_string())
