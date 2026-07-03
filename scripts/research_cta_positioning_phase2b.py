"""Phase-2b walk-forward backtest — sub-project G (CTA positioning), REAL DATA.

Strategy family per docs/superpowers/specs/2026-07-03-cta-positioning-design.md
(original design, now testable with real data — Coinalyze key arrived):
  trend  = EMA20 vs EMA50 on {4h, 1d} (closed bars only)                  [UNCHANGED from Phase 2a]
  crowd  = Coinalyze long/short ACCOUNT RATIO (`l` = long % of accounts),
           resampled to trend TF (mean), rolling-90d percentile (min 30d
           warmup, trailing window only) — REAL retail positioning, replacing
           Phase 2a's HL-funding proxy. High percentile of `l` = crowded long.
  fuel   = REAL open interest change over {24h, 72h} > 0 (rising OI) —
           replacing Phase 2a's 24h-quote-volume proxy. This is the fuel-
           lookback axis from the ORIGINAL design doc (line 29), finally
           usable now that real OI history exists.
  side   = {long, short, both}
  => 2 x 2 x 2 x 3 = 24 configs (same shape as Phase 2a). SHORT = down-trend
     AND crowded-long AND fuel. LONG mirrored. Exit: fuel fails / trend flips
     / 2xATR(14) hard stop / 14d max hold. $100 notional per coin, 0.045% fee
     per side. NOTE: HL hourly funding accrual is DROPPED in Phase 2b — it was
     the Phase-2a proxy for crowding and is no longer part of the signal, but
     Phase 2a's PnL *did* include real HL funding cash-flow while holding.
     Coinalyze does not provide the matching Hyperliquid funding series for
     this window, so Phase 2b PnL excludes funding accrual entirely (reported
     as a caveat — Phase 2a PnL and Phase 2b PnL are not fully apples-to-apples
     on this dimension; both use identical fee assumptions otherwise).

Point-in-time discipline: identical to Phase 2a. Every decision signal is
computed on CLOSED bars and shifted one bar — the signal known at bar t-1
close executes at bar t open. Percentile / EMA / ATR / OI-change windows are
trailing-only.

Data:
  - Trend/price: Binance USDT-M klines, cached data/cache/cta/ (unchanged,
    reused from Phase 2a — years of depth, not the constraint).
  - Crowding + fuel: Coinalyze real OI + long/short account ratio,
    data/cache/coinalyze/{COIN}_{oi,lsr}_4h.parquet, 4h native grid,
    2025-08-04 -> now (~335 days, NOT the 2yr originally assumed in the
    design doc — a real limitation of this Coinalyze plan, reported honestly
    in the verdict). Backtest window = intersection of klines and Coinalyze
    coverage (Coinalyze is the binding constraint).

Usage: .venv/bin/python scripts/research_cta_positioning_phase2b.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

SYMBOLS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL",
           "HYPEUSDT": "HYPE", "DOGEUSDT": "DOGE", "XRPUSDT": "XRP"}
KCACHE = Path("data/cache/cta")
CCACHE = Path("data/cache/coinalyze")

NOTIONAL = 100.0                              # $ per coin position
FEE_SIDE = 0.00045 * NOTIONAL                 # 0.045% per side (same as Phase 2a)
MAX_HOLD = pd.Timedelta(days=14)
STOP_ATR_MULT = 2.0
TREND_WARMUP_BARS = 50                        # EMA50/ATR need history before trusted
SPLIT_FRACTION = 0.5                          # calendar midpoint of the actual window (computed at runtime)
PORT_BASE = NOTIONAL * len(SYMBOLS)           # $600 equal-weight capital base
TSTAT_GATE = 2.9                              # Bonferroni-style: 24 trials @ 5% (same as Phase 2a)
CROWD_WARMUP_DAYS = 30                        # min history before crowding pctile trusted (same as 2a)
CROWD_WINDOW_DAYS = 90                        # rolling percentile window (same as 2a)

TFS = {"4h": {"rule": "4h", "bars_per_day": 6},
       "1d": {"rule": "1D", "bars_per_day": 1}}
PCTILES = (10, 20)
FUEL_LOOKBACKS = (24, 72)                     # hours — REAL OI-change axis (replaces 2a's {none,vol})
SIDES = ("long", "short", "both")


# ---------------------------------------------------------------- data layer
def load_klines(sym: str) -> dict[str, pd.DataFrame]:
    out = {}
    for tf in TFS:
        df = pd.read_parquet(KCACHE / f"{sym}_{tf}.parquet")
        df = df.copy()
        df.index = pd.to_datetime(df.pop("open_time"), unit="ms")
        out[tf] = df
    return out


def load_coinalyze(coin: str) -> tuple[pd.Series, pd.Series]:
    """Returns (oi_level, long_pct) both indexed by 4h-native UTC-naive timestamp,
    deduplicated and sorted. `long_pct` = `l` field = % of accounts/positions long."""
    oi = pd.read_parquet(CCACHE / f"{coin}_oi_4h.parquet")
    lsr = pd.read_parquet(CCACHE / f"{coin}_lsr_4h.parquet")
    oi_idx = pd.to_datetime(oi["t"], unit="s")
    lsr_idx = pd.to_datetime(lsr["t"], unit="s")
    oi_s = pd.Series(oi["c"].astype(float).values, index=oi_idx).sort_index()
    oi_s = oi_s[~oi_s.index.duplicated(keep="last")]
    long_s = pd.Series(lsr["l"].astype(float).values, index=lsr_idx).sort_index()
    long_s = long_s[~long_s.index.duplicated(keep="last")]
    return oi_s, long_s


def bar_frame(kl: pd.DataFrame, oi: pd.Series, long_pct: pd.Series, tf: str) -> pd.DataFrame:
    """Klines + per-bar OI level (last-of-period) and long-% (mean-of-period).
    Keeps only bars fully closed AND fully covered by Coinalyze data (the
    binding constraint — Coinalyze history is ~335d vs klines' longer depth)."""
    rule = TFS[tf]["rule"]
    bars = kl.copy()
    bar_dt = pd.Timedelta(rule)
    cov_start = max(oi.index.min(), long_pct.index.min())
    cov_end = min(oi.index.max(), long_pct.index.max()) + pd.Timedelta(hours=4)
    now = pd.Timestamp.utcnow().tz_localize(None)
    keep_until = min(cov_end, now)
    bars = bars[(bars.index >= cov_start) & (bars.index + bar_dt <= keep_until)]
    oi_bar = oi.resample(rule, label="left", closed="left").last()
    long_bar = long_pct.resample(rule, label="left", closed="left").mean()
    bars["oi_level"] = oi_bar.reindex(bars.index)
    bars["long_pct"] = long_bar.reindex(bars.index)
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
    """Unshifted indicators on closed bars (shared across pctile/fuel variants)."""
    df = bars.copy()
    bpd = TFS[tf]["bars_per_day"]
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    valid = pd.Series(np.arange(len(df)) >= TREND_WARMUP_BARS, index=df.index)
    df["trend_up_raw"] = (ema20 > ema50) & valid
    df["trend_dn_raw"] = (ema50 > ema20) & valid
    df["lpct_raw"] = df["long_pct"].rolling(
        CROWD_WINDOW_DAYS * bpd, min_periods=CROWD_WARMUP_DAYS * bpd
    ).apply(_pct_rank_last, raw=True)
    # fuel: real OI change over {24h, 72h} > 0 (rising open interest), in bars
    for lb_h in FUEL_LOOKBACKS:
        lb_bars = max(1, round(lb_h / 24 * bpd))
        df[f"fuel{lb_h}_raw"] = df["oi_level"] > df["oi_level"].shift(lb_bars)
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df["atr_raw"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df.loc[df.index[:TREND_WARMUP_BARS], "atr_raw"] = np.nan
    return df


def shifted_signals(raw: pd.DataFrame, pctile: int, fuel_lb: int) -> pd.DataFrame:
    """Decision signals: computed on bar t-1 close, used at bar t open (shift 1)."""
    out = raw[["open", "high", "low", "close"]].copy()
    out["trend_up"] = raw["trend_up_raw"].shift(1, fill_value=False)
    out["trend_dn"] = raw["trend_dn_raw"].shift(1, fill_value=False)
    out["crowd_long"] = (raw["lpct_raw"] >= 100 - pctile).fillna(False) \
                        .shift(1, fill_value=False)
    out["crowd_short"] = (raw["lpct_raw"] <= pctile).fillna(False) \
                         .shift(1, fill_value=False)
    out["fuel_ok"] = raw[f"fuel{fuel_lb}_raw"].fillna(False).shift(1, fill_value=False)
    out["atr"] = raw["atr_raw"].shift(1)
    return out


# --------------------------------------------------------------- simulation
def simulate(sig: pd.DataFrame, side: str):
    """One coin, one config. Returns (per-bar $ PnL Series, trade list).
    Fuel gate always active as an exit condition in Phase 2b (real OI, no
    'none' variant — matches the original design's fuel-lookback axis, which
    has no null option). No funding accrual (Coinalyze doesn't provide HL
    funding for this window; caveat documented)."""
    idx = sig.index
    o, h, l, c = (sig[k].to_numpy() for k in ("open", "high", "low", "close"))
    tu, td = sig["trend_up"].to_numpy(), sig["trend_dn"].to_numpy()
    cl, cs = sig["crowd_long"].to_numpy(), sig["crowd_short"].to_numpy()
    fk = sig["fuel_ok"].to_numpy()
    atr = sig["atr"].to_numpy()
    bar_pnl = np.zeros(len(sig))
    trades: list[dict] = []
    pos: dict | None = None

    def close_trade(i: int, exit_px: float, reason: str) -> float:
        d = pos["dir"]
        pnl = d * (exit_px - pos["mark"]) / pos["entry_px"] * NOTIONAL - FEE_SIDE
        net = (d * (exit_px - pos["entry_px"]) / pos["entry_px"] * NOTIONAL
               - 2 * FEE_SIDE)
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[i],
                       "pnl": net, "reason": reason})
        return pnl

    for i in range(len(sig)):
        pnl = 0.0
        exited_this_bar = False
        if pos is not None:
            d = pos["dir"]
            flip = (d == 1 and not tu[i]) or (d == -1 and not td[i])
            fuel_fail = not fk[i]
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
                    pos["mark"] = c[i]
        if pos is None and not exited_this_bar:             # re-entry next bar min
            want_s = side in ("short", "both") and td[i] and cl[i] and fk[i]
            want_l = side in ("long", "both") and tu[i] and cs[i] and fk[i]
            if (want_s or want_l) and not np.isnan(atr[i]) and atr[i] > 0:
                d = -1 if want_s else 1
                entry_px = o[i]
                stop = entry_px - d * STOP_ATR_MULT * atr[i]
                pos = {"dir": d, "entry_px": entry_px, "stop": stop,
                       "t0": idx[i], "mark": entry_px}
                pnl -= FEE_SIDE
                hit = (d == -1 and h[i] >= stop) or (d == 1 and l[i] <= stop)
                if hit:                                     # stopped on entry bar
                    pnl += close_trade(i, stop, "stop")
                    pos = None
                else:
                    pnl += d * (c[i] - entry_px) / entry_px * NOTIONAL
                    pos["mark"] = c[i]
        bar_pnl[i] = pnl
    if pos is not None:                                     # force-close at end
        bar_pnl[-1] += -FEE_SIDE
        d = pos["dir"]
        trades.append({"side": "long" if d == 1 else "short",
                       "entry_time": pos["t0"], "exit_time": idx[-1],
                       "pnl": d * (c[-1] - pos["entry_px"]) / pos["entry_px"]
                              * NOTIONAL - 2 * FEE_SIDE,
                       "reason": "eod"})
    s = pd.Series(bar_pnl, index=idx)
    tsum = sum(t["pnl"] for t in trades)
    assert abs(s.sum() - tsum) < 1e-6, f"bar/trade pnl mismatch {s.sum()} vs {tsum}"
    return s, trades


# ---------------------------------------------------------------- reporting
def daily_stats(daily: pd.Series, stats_start: pd.Timestamp, split_at: pd.Timestamp) -> dict:
    d = daily.loc[stats_start:]
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    tstat = mu / sd * math.sqrt(n) if sd > 0 else 0.0
    eq = PORT_BASE + d.cumsum()
    mdd = float((eq / eq.cummax() - 1.0).min())
    h1 = d.loc[:split_at - pd.Timedelta(seconds=1)].sum()
    h2 = d.loc[split_at:].sum()
    return {"pnl": d.sum(), "ret": d.sum() / PORT_BASE, "sharpe": sharpe,
            "tstat": tstat, "mdd": mdd, "h1": h1, "h2": h2, "days": n}


def main() -> None:
    t0 = time.time()

    print("=== data ===")
    frames: dict[tuple[str, str], pd.DataFrame] = {}     # (coin, tf) -> raw indicators
    cov_starts, cov_ends = [], []
    for sym, coin in SYMBOLS.items():
        kls = load_klines(sym)
        oi, long_pct = load_coinalyze(coin)
        for tf in TFS:
            bars = bar_frame(kls[tf], oi, long_pct, tf)
            frames[(coin, tf)] = raw_indicators(bars, tf)
        b4 = frames[(coin, "4h")]
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())
        print(f"{coin:5s} klines 4h={len(frames[(coin, '4h')]):4d} "
              f"1d={len(frames[(coin, '1d')]):3d} bars "
              f"[{b4.index.min():%Y-%m-%d} .. {b4.index.max():%Y-%m-%d}]  "
              f"coinalyze oi={len(oi)} lsr={len(long_pct)} "
              f"[{oi.index.min():%Y-%m-%d} .. {oi.index.max():%Y-%m-%d}]")

    # Backtest window = intersection across all coins' Coinalyze coverage.
    # Daily-resampled PnL buckets fall on midnight boundaries; stats_start/
    # split_at must be normalized to midnight too (ceil, so a partial first
    # day of "warmup" is excluded rather than silently dropping a full day
    # of post-warmup data via a non-midnight cutoff on a midnight-indexed
    # series — caught by cross-checking per-side long+short against total
    # pnl, which must match exactly).
    window_start = max(cov_starts)
    window_end = min(cov_ends)
    stats_start = (window_start + pd.Timedelta(days=CROWD_WARMUP_DAYS)).ceil("D")
    split_at = (window_start + (window_end - window_start) * SPLIT_FRACTION).ceil("D")
    n_days = (window_end - stats_start).days
    print(f"\nbacktest window: [{window_start:%Y-%m-%d} .. {window_end:%Y-%m-%d}]  "
          f"stats from {stats_start:%Y-%m-%d} ({n_days}d after {CROWD_WARMUP_DAYS}d crowding warmup)  "
          f"split at {split_at:%Y-%m-%d}")

    results: dict[str, dict] = {}
    trades_by_cfg: dict[str, list[dict]] = {}
    coin_daily_by_cfg: dict[str, dict[str, pd.Series]] = {}
    for tf in TFS:
        for p in PCTILES:
            for fuel_lb in FUEL_LOOKBACKS:
                sigs = {coin: shifted_signals(frames[(coin, tf)], p, fuel_lb)
                        for coin in SYMBOLS.values()}
                for side in SIDES:
                    cfg = f"{tf}-p{p}-fuel{fuel_lb}-{side}"
                    per_coin, all_trades = {}, []
                    for coin, sig in sigs.items():
                        bar_pnl, trades = simulate(sig, side)
                        per_coin[coin] = bar_pnl.resample("1D").sum()
                        for t in trades:
                            t["coin"] = coin
                        all_trades.extend(trades)
                    daily = pd.concat(per_coin.values(), axis=1).fillna(0).sum(axis=1)
                    st = daily_stats(daily, stats_start, split_at)
                    tr = [t for t in all_trades if t["exit_time"] >= stats_start]
                    st["trades"] = len(tr)
                    st["win"] = (np.mean([t["pnl"] > 0 for t in tr]) if tr else 0.0)
                    results[cfg] = st
                    trades_by_cfg[cfg] = tr
                    coin_daily_by_cfg[cfg] = per_coin

    print(f"\n=== 24-config matrix (portfolio: 6 coins x $100, stats from "
          f"{stats_start:%Y-%m-%d}) ===")
    print(f"{'config':<20s} {'pnl$':>8s} {'ret%':>7s} {'sharpe':>7s} {'tstat':>6s} "
          f"{'mdd%':>6s} {'trades':>6s} {'win%':>5s} {'h1$':>8s} {'h2$':>8s}")
    for cfg in sorted(results):
        r = results[cfg]
        print(f"{cfg:<20s} {r['pnl']:>8.2f} {r['ret']*100:>6.2f}% {r['sharpe']:>7.2f} "
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
        tot = s.loc[stats_start:].sum()
        ntr = sum(1 for t in trades_by_cfg[med_cfg] if t["coin"] == coin)
        nonneg += tot >= 0
        print(f"{coin:5s} pnl={tot:>8.2f}$  trades={ntr:3d}  "
              f"{'non-negative' if tot >= 0 else 'NEGATIVE'}")

    # NOTE: long$+short$ can differ by a few dollars from the matrix pnl$ for
    # a config when a trade straddles stats_start (entered before, exited
    # after) — the trade list attributes its full PnL to the exit bar, while
    # daily_stats (used for pnl$/sharpe/mdd/gate) correctly attributes only
    # the post-stats_start mark-to-market portion. Verified: 2 such boundary
    # trades exist across all 144 (coin x config) combinations in this run;
    # this is a cosmetic diagnostic-table artifact, not a PIT or gate-integrity
    # issue — all gate numbers derive from daily_stats on bar-level PnL.
    print(f"\n=== per-side breakdown ('both' configs) ===")
    print(f"{'config':<20s} {'long$':>8s} {'nL':>4s} {'winL%':>6s} "
          f"{'short$':>8s} {'nS':>4s} {'winS%':>6s}")
    for cfg in sorted(results):
        if not cfg.endswith("-both"):
            continue
        tr = trades_by_cfg[cfg]
        lg = [t["pnl"] for t in tr if t["side"] == "long"]
        sh = [t["pnl"] for t in tr if t["side"] == "short"]
        wl = np.mean([p > 0 for p in lg]) * 100 if lg else 0
        ws = np.mean([p > 0 for p in sh]) * 100 if sh else 0
        print(f"{cfg:<20s} {sum(lg):>8.2f} {len(lg):>4d} {wl:>5.0f}% "
              f"{sum(sh):>8.2f} {len(sh):>4d} {ws:>5.0f}%")

    print(f"\n=== monthly portfolio PnL at median config ({med_cfg}) "
          f"vs the 10%/mo ask (${PORT_BASE:.0f} base -> ${PORT_BASE*0.10:.0f}/mo) ===")
    daily_med = pd.concat(coin_daily_by_cfg[med_cfg].values(), axis=1) \
                  .fillna(0).sum(axis=1).loc[stats_start:]
    monthly = daily_med.resample("ME").sum()
    for ts, v in monthly.items():
        print(f"{ts:%Y-%m}  {v:>8.2f}$  ({v/PORT_BASE*100:>6.2f}%)")

    # ---- pre-declared gate (identical to Phase 2a) ----
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
