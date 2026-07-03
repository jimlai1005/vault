"""Phase-2a walk-forward backtest — sub-project G (CTA positioning).

Strategy family per docs/superpowers/specs/2026-07-03-cta-positioning-design.md
(Phase-2a amendment, pre-declared proxies):
  trend  = EMA20 vs EMA50 on {4h, 1d} (closed bars only)
  crowd  = HL hourly funding resampled to trend TF (mean), rolling-90d percentile
           (min 30d warmup, trailing window only) — PROXY for retail positioning
  fuel   = {none, 24h quote-volume sum > prior 24h} — PROXY for OI momentum
  side   = {long, short, both}
  => 2 x 2 x 2 x 3 = 24 configs. SHORT = down-trend AND crowded-long AND fuel.
  LONG mirrored. Exit: fuel fails (vol variant) / trend flips / 2xATR(14) hard
  stop / 14d max hold. $100 notional per coin, 0.045% fee per side, actual HL
  funding accrued while holding (short receives positive funding).

Point-in-time discipline: every decision signal is computed on CLOSED bars and
shifted one bar — the signal known at bar t-1 close executes at bar t open.
Percentile / EMA / ATR windows are trailing-only. Funding accrual for bar t is
cash flow DURING bar t (not a decision input, so not shifted).

Data: Binance USDT-M klines (cached data/cache/cta/), HL funding
(data/cache/funding/{COIN}.parquet, hourly, 12mo). Single continuous simulation
2025-07 -> 2026-07 (signals PIT by construction; no refit) + split-half check.

Usage: .venv/bin/python scripts/research_cta_positioning.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.io.source import TransientError, SemanticError, resilient_read  # noqa: E402

BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"
SYMBOLS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL",
           "HYPEUSDT": "HYPE", "DOGEUSDT": "DOGE", "XRPUSDT": "XRP"}
KCACHE = Path("data/cache/cta")
FCACHE = Path("data/cache/funding")

START = pd.Timestamp("2025-07-01")            # UTC, naive
NOTIONAL = 100.0                              # $ per coin position
FEE_SIDE = 0.00045 * NOTIONAL                 # 0.045% per side
MAX_HOLD = pd.Timedelta(days=14)
STOP_ATR_MULT = 2.0
TREND_WARMUP_BARS = 50                        # EMA50/ATR need history before trusted
STATS_START = pd.Timestamp("2025-08-01")      # data start + 30d crowding warmup
SPLIT_AT = pd.Timestamp("2026-01-01")         # calendar midpoint of the 12mo window
PORT_BASE = NOTIONAL * len(SYMBOLS)           # $600 equal-weight capital base
TSTAT_GATE = 2.9                              # Bonferroni-style: 24 trials @ 5%

TFS = {"4h": {"rule": "4h", "bars_per_day": 6},
       "1d": {"rule": "1D", "bars_per_day": 1}}
PCTILES = (10, 20)
FUELS = ("none", "vol")
SIDES = ("long", "short", "both")


# ---------------------------------------------------------------- data layer
def _get_json(url: str) -> object:
    def call():
        req = urllib.request.Request(url, headers={"User-Agent": "vault-research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise TransientError(f"{e.code} {url}")
            raise SemanticError(f"{e.code} {url}")
        except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
            raise TransientError(str(e))
    return resilient_read(call, max_attempts=6, base_delay=1.0)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginate Binance USDT-M futures klines forward from start_ms; cache parquet."""
    KCACHE.mkdir(parents=True, exist_ok=True)
    bar_ms = int(pd.Timedelta(TFS[interval]["rule"]).total_seconds() * 1000)
    cache = KCACHE / f"{symbol}_{interval}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if not df.empty and df["open_time"].max() >= end_ms - 2 * bar_ms:
            return df
    rows: list[list] = []
    cursor = start_ms
    for _ in range(40):
        page = _get_json(f"{BINANCE_KLINES}?symbol={symbol}&interval={interval}"
                         f"&limit=1500&startTime={cursor}")
        if not page:
            break
        rows.extend(page)
        if len(page) < 1500:
            break
        cursor = page[-1][0] + 1
        time.sleep(0.35)
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close",
                                     "volume", "close_time", "quote_volume",
                                     "trades", "tb_base", "tb_quote", "ignore"])
    for c in ("open", "high", "low", "close", "quote_volume"):
        df[c] = pd.to_numeric(df[c])
    df = (df[["open_time", "open", "high", "low", "close", "quote_volume", "close_time"]]
          .drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True))
    df.to_parquet(cache)
    return df


def load_funding(coin: str) -> pd.Series:
    """Hourly HL funding rate indexed by (floored) hour, UTC-naive."""
    df = pd.read_parquet(FCACHE / f"{coin}.parquet")
    idx = pd.to_datetime(df["time"], unit="ms").dt.floor("h")
    s = pd.Series(df["fundingRate"].values, index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def bar_frame(kl: pd.DataFrame, frate: pd.Series, tf: str) -> pd.DataFrame:
    """Klines + per-bar funding mean (crowding basis) and sum (accrual).
    Keeps only bars fully closed AND fully covered by funding data."""
    rule = TFS[tf]["rule"]
    bars = kl.copy()
    bars.index = pd.to_datetime(bars.pop("open_time"), unit="ms")
    bar_dt = pd.Timedelta(rule)
    fund_end = frate.index.max() + pd.Timedelta(hours=1)   # coverage end
    now = pd.Timestamp.utcnow().tz_localize(None)
    keep_until = min(fund_end, now)
    bars = bars[bars.index + bar_dt <= keep_until]
    fmean = frate.resample(rule, label="left", closed="left").mean()
    fsum = frate.resample(rule, label="left", closed="left").sum()
    bars["fund_mean"] = fmean.reindex(bars.index)
    bars["fund_accr"] = fsum.reindex(bars.index).fillna(0.0)
    return bars


# ------------------------------------------------------------- signal layer
def _pct_rank_last(w: np.ndarray) -> float:
    """Percentile of the CURRENT (last) value within the trailing window."""
    cur = w[-1]
    if np.isnan(cur):
        return np.nan
    w = w[~np.isnan(w)]
    return float((w <= cur).mean() * 100.0)


def raw_indicators(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Unshifted indicators on closed bars (shared across P/fuel variants)."""
    df = bars.copy()
    bpd = TFS[tf]["bars_per_day"]
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    valid = pd.Series(np.arange(len(df)) >= TREND_WARMUP_BARS, index=df.index)
    df["trend_up_raw"] = (ema20 > ema50) & valid
    df["trend_dn_raw"] = (ema50 > ema20) & valid
    df["fpct_raw"] = df["fund_mean"].rolling(90 * bpd, min_periods=30 * bpd) \
                                    .apply(_pct_rank_last, raw=True)
    qv24 = df["quote_volume"].rolling(bpd).sum()           # trailing 24h
    df["fuel_raw"] = qv24 > qv24.shift(bpd)                # vs prior 24h
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df["atr_raw"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df.loc[df.index[:TREND_WARMUP_BARS], "atr_raw"] = np.nan
    return df


def shifted_signals(raw: pd.DataFrame, pctile: int, fuel: str) -> pd.DataFrame:
    """Decision signals: computed on bar t-1 close, used at bar t open (shift 1)."""
    out = raw[["open", "high", "low", "close", "fund_accr"]].copy()
    out["trend_up"] = raw["trend_up_raw"].shift(1, fill_value=False)
    out["trend_dn"] = raw["trend_dn_raw"].shift(1, fill_value=False)
    out["crowd_long"] = (raw["fpct_raw"] >= 100 - pctile).fillna(False) \
                        .shift(1, fill_value=False)
    out["crowd_short"] = (raw["fpct_raw"] <= pctile).fillna(False) \
                         .shift(1, fill_value=False)
    if fuel == "vol":
        out["fuel_ok"] = raw["fuel_raw"].fillna(False).shift(1, fill_value=False)
    else:
        out["fuel_ok"] = True
    out["atr"] = raw["atr_raw"].shift(1)
    return out


# --------------------------------------------------------------- simulation
def simulate(sig: pd.DataFrame, side: str, fuel_exit: bool):
    """One coin, one config. Returns (per-bar $ PnL Series, trade list).
    Funding sign: pnl = -dir * rate * notional (short receives positive funding)."""
    idx = sig.index
    o, h, l, c = (sig[k].to_numpy() for k in ("open", "high", "low", "close"))
    tu, td = sig["trend_up"].to_numpy(), sig["trend_dn"].to_numpy()
    cl, cs = sig["crowd_long"].to_numpy(), sig["crowd_short"].to_numpy()
    fk = sig["fuel_ok"].to_numpy()
    fa, atr = sig["fund_accr"].to_numpy(), sig["atr"].to_numpy()
    bar_pnl = np.zeros(len(sig))
    trades: list[dict] = []
    pos: dict | None = None

    def close_trade(i: int, exit_px: float, reason: str) -> float:
        """Returns mark-to-exit pnl for this bar; records the trade."""
        d = pos["dir"]
        pnl = d * (exit_px - pos["mark"]) / pos["entry_px"] * NOTIONAL - FEE_SIDE
        net = (d * (exit_px - pos["entry_px"]) / pos["entry_px"] * NOTIONAL
               + pos["fund"] - 2 * FEE_SIDE)
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[i],
                       "pnl": net, "fund": pos["fund"], "reason": reason})
        return pnl

    for i in range(len(sig)):
        pnl = 0.0
        exited_this_bar = False
        if pos is not None:
            d = pos["dir"]
            flip = (d == 1 and not tu[i]) or (d == -1 and not td[i])
            fuel_fail = fuel_exit and not fk[i]
            too_long = idx[i] - pos["t0"] >= MAX_HOLD
            if flip or fuel_fail or too_long:
                reason = "flip" if flip else ("fuel" if fuel_fail else "maxhold")
                pnl += close_trade(i, o[i], reason)
                pos, exited_this_bar = None, True
            else:                                           # intrabar hard stop
                stop_px = None
                if d == -1 and h[i] >= pos["stop"]:
                    stop_px = o[i] if o[i] >= pos["stop"] else pos["stop"]
                elif d == 1 and l[i] <= pos["stop"]:
                    stop_px = o[i] if o[i] <= pos["stop"] else pos["stop"]
                if stop_px is not None:
                    pnl += close_trade(i, stop_px, "stop")
                    pos, exited_this_bar = None, True
                else:                                       # hold: mark to close
                    pnl += d * (c[i] - pos["mark"]) / pos["entry_px"] * NOTIONAL
                    pnl += -d * fa[i] * NOTIONAL
                    pos["fund"] += -d * fa[i] * NOTIONAL
                    pos["mark"] = c[i]
        if pos is None and not exited_this_bar:             # re-entry next bar min
            want_s = side in ("short", "both") and td[i] and cl[i] and fk[i]
            want_l = side in ("long", "both") and tu[i] and cs[i] and fk[i]
            if (want_s or want_l) and not np.isnan(atr[i]) and atr[i] > 0:
                d = -1 if want_s else 1
                entry_px = o[i]
                stop = entry_px - d * STOP_ATR_MULT * atr[i]
                pos = {"dir": d, "entry_px": entry_px, "stop": stop,
                       "t0": idx[i], "mark": entry_px, "fund": 0.0}
                pnl -= FEE_SIDE
                hit = (d == -1 and h[i] >= stop) or (d == 1 and l[i] <= stop)
                if hit:                                     # stopped on entry bar
                    pnl += close_trade(i, stop, "stop")
                    pos = None
                else:
                    pnl += d * (c[i] - entry_px) / entry_px * NOTIONAL
                    pnl += -d * fa[i] * NOTIONAL
                    pos["fund"] = -d * fa[i] * NOTIONAL
                    pos["mark"] = c[i]
        bar_pnl[i] = pnl
    if pos is not None:                                     # force-close at end
        bar_pnl[-1] += -FEE_SIDE
        d = pos["dir"]
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[-1],
                       "pnl": d * (c[-1] - pos["entry_px"]) / pos["entry_px"]
                              * NOTIONAL + pos["fund"] - 2 * FEE_SIDE,
                       "fund": pos["fund"], "reason": "eod"})
    s = pd.Series(bar_pnl, index=idx)
    tsum = sum(t["pnl"] for t in trades)
    assert abs(s.sum() - tsum) < 1e-6, f"bar/trade pnl mismatch {s.sum()} vs {tsum}"
    return s, trades


# ---------------------------------------------------------------- reporting
def daily_stats(daily: pd.Series) -> dict:
    d = daily.loc[STATS_START:]
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    tstat = mu / sd * math.sqrt(n) if sd > 0 else 0.0
    eq = PORT_BASE + d.cumsum()
    mdd = float((eq / eq.cummax() - 1.0).min())
    h1 = d.loc[:SPLIT_AT - pd.Timedelta(seconds=1)].sum()
    h2 = d.loc[SPLIT_AT:].sum()
    return {"pnl": d.sum(), "ret": d.sum() / PORT_BASE, "sharpe": sharpe,
            "tstat": tstat, "mdd": mdd, "h1": h1, "h2": h2, "days": n}


def main() -> None:
    t0 = time.time()
    start_ms = int(START.tz_localize("UTC").timestamp() * 1000)
    end_ms = int(time.time() * 1000)

    print("=== data ===")
    frames: dict[tuple[str, str], pd.DataFrame] = {}     # (coin, tf) -> raw indicators
    for sym, coin in SYMBOLS.items():
        frate = load_funding(coin)
        for tf in TFS:
            kl = fetch_klines(sym, tf, start_ms, end_ms)
            bars = bar_frame(kl, frate, tf)
            frames[(coin, tf)] = raw_indicators(bars, tf)
        b4 = frames[(coin, "4h")]
        print(f"{coin:5s} klines 4h={len(frames[(coin, '4h')]):4d} "
              f"1d={len(frames[(coin, '1d')]):3d} bars "
              f"[{b4.index.min():%Y-%m-%d} .. {b4.index.max():%Y-%m-%d}]  "
              f"funding hours={len(frate)} "
              f"[{frate.index.min():%Y-%m-%d} .. {frate.index.max():%Y-%m-%d}]")

    results: dict[str, dict] = {}
    trades_by_cfg: dict[str, list[dict]] = {}
    coin_daily_by_cfg: dict[str, dict[str, pd.Series]] = {}
    for tf in TFS:
        for p in PCTILES:
            for fuel in FUELS:
                sigs = {coin: shifted_signals(frames[(coin, tf)], p, fuel)
                        for coin in SYMBOLS.values()}
                for side in SIDES:
                    cfg = f"{tf}-p{p}-{fuel}-{side}"
                    per_coin, all_trades = {}, []
                    for coin, sig in sigs.items():
                        bar_pnl, trades = simulate(sig, side, fuel_exit=(fuel == "vol"))
                        per_coin[coin] = bar_pnl.resample("1D").sum()
                        for t in trades:
                            t["coin"] = coin
                        all_trades.extend(trades)
                    daily = pd.concat(per_coin.values(), axis=1).fillna(0).sum(axis=1)
                    st = daily_stats(daily)
                    tr = [t for t in all_trades if t["exit_time"] >= STATS_START]
                    st["trades"] = len(tr)
                    st["win"] = (np.mean([t["pnl"] > 0 for t in tr]) if tr else 0.0)
                    results[cfg] = st
                    trades_by_cfg[cfg] = tr
                    coin_daily_by_cfg[cfg] = per_coin

    print("\n=== 24-config matrix (portfolio: 6 coins x $100, stats from "
          f"{STATS_START:%Y-%m-%d}) ===")
    print(f"{'config':<18s} {'pnl$':>8s} {'ret%':>7s} {'sharpe':>7s} {'tstat':>6s} "
          f"{'mdd%':>6s} {'trades':>6s} {'win%':>5s} {'h1$':>8s} {'h2$':>8s}")
    for cfg in sorted(results):
        r = results[cfg]
        print(f"{cfg:<18s} {r['pnl']:>8.2f} {r['ret']*100:>6.2f}% {r['sharpe']:>7.2f} "
              f"{r['tstat']:>6.2f} {r['mdd']*100:>5.1f}% {r['trades']:>6d} "
              f"{r['win']*100:>4.0f}% {r['h1']:>8.2f} {r['h2']:>8.2f}")

    # median / best configs
    sharpes = {c: r["sharpe"] for c, r in results.items()}
    med_val = float(np.median(list(sharpes.values())))
    med_cfg = min(sorted(sharpes), key=lambda k: abs(sharpes[k] - med_val))
    best_cfg = max(sorted(sharpes), key=lambda k: sharpes[k])
    rm, rb = results[med_cfg], results[best_cfg]

    print(f"\nmedian config Sharpe = {med_val:.2f}  "
          f"(nearest config: {med_cfg}, sharpe {rm['sharpe']:.2f})")
    print(f"best config = {best_cfg}  sharpe {rb['sharpe']:.2f}  "
          f"tstat {rb['tstat']:.2f} (gate {TSTAT_GATE})")

    print(f"\n=== per-coin at median config ({med_cfg}) ===")
    nonneg = 0
    for coin, s in coin_daily_by_cfg[med_cfg].items():
        tot = s.loc[STATS_START:].sum()
        ntr = sum(1 for t in trades_by_cfg[med_cfg] if t["coin"] == coin)
        nonneg += tot >= 0
        print(f"{coin:5s} pnl={tot:>8.2f}$  trades={ntr:3d}  "
              f"{'non-negative' if tot >= 0 else 'NEGATIVE'}")

    print(f"\n=== per-side breakdown ('both' configs) ===")
    print(f"{'config':<18s} {'long$':>8s} {'nL':>4s} {'winL%':>6s} "
          f"{'short$':>8s} {'nS':>4s} {'winS%':>6s}")
    for cfg in sorted(results):
        if not cfg.endswith("-both"):
            continue
        tr = trades_by_cfg[cfg]
        lg = [t["pnl"] for t in tr if t["side"] == "long"]
        sh = [t["pnl"] for t in tr if t["side"] == "short"]
        wl = np.mean([p > 0 for p in lg]) * 100 if lg else 0
        ws = np.mean([p > 0 for p in sh]) * 100 if sh else 0
        print(f"{cfg:<18s} {sum(lg):>8.2f} {len(lg):>4d} {wl:>5.0f}% "
              f"{sum(sh):>8.2f} {len(sh):>4d} {ws:>5.0f}%")

    print(f"\n=== monthly portfolio PnL at median config ({med_cfg}) "
          f"vs the 10%/mo ask (${PORT_BASE:.0f} base -> ${PORT_BASE*0.10:.0f}/mo) ===")
    daily_med = pd.concat(coin_daily_by_cfg[med_cfg].values(), axis=1) \
                  .fillna(0).sum(axis=1).loc[STATS_START:]
    monthly = daily_med.resample("ME").sum()
    for ts, v in monthly.items():
        print(f"{ts:%Y-%m}  {v:>8.2f}$  ({v/PORT_BASE*100:>6.2f}%)")

    # ---- pre-declared gate ----
    g1 = med_val > 1.0
    g2 = rb["tstat"] > TSTAT_GATE
    g3 = rm["mdd"] >= -0.15
    g4 = nonneg / len(SYMBOLS) >= 0.60
    g5 = bool(np.sign(rm["h1"]) == np.sign(rm["h2"]))
    print("\n=== pre-declared gate (ALL must hold for GO) ===")
    print(f"1. median-config Sharpe > 1.0          : {med_val:6.2f}  "
          f"{'PASS' if g1 else 'FAIL'}")
    print(f"2. best-config tstat > {TSTAT_GATE} (24 trials) : {rb['tstat']:6.2f}  "
          f"{'PASS' if g2 else 'FAIL'}")
    print(f"3. aggregate MDD <= 15% (median cfg)   : {rm['mdd']*100:5.1f}%  "
          f"{'PASS' if g3 else 'FAIL'}")
    print(f"4. >=60% coins non-negative (median)   : {nonneg}/{len(SYMBOLS)}  "
          f"{'PASS' if g4 else 'FAIL'}")
    print(f"5. split halves same sign (median cfg) : h1={rm['h1']:+.2f} "
          f"h2={rm['h2']:+.2f}  {'PASS' if g5 else 'FAIL'}")
    verdict = "GO" if all((g1, g2, g3, g4, g5)) else "NO-GO"
    print(f"\nVERDICT: {verdict}   ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
