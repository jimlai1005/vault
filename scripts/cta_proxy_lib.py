"""Shared engine for the Layer-2b Binance-only proxy research (read-only).

Reuses the EXACT simulation core from research_cta_positioning_phase2b.py
(simulate(), daily_stats(), NOTIONAL/FEE_SIDE/PORT_BASE/TFS/STOP_ATR_MULT/
MAX_HOLD/TREND_WARMUP_BARS/CROWD_WARMUP_DAYS/CROWD_WINDOW_DAYS/TSTAT_GATE) via
importlib, exactly like scripts/research_cta_crowd_ablation.py already does.
Only the two INPUT SIGNALS are swapped for Binance-only-derived proxies:

  crowd (was: Coinalyze long/short account ratio `l`)
    -> Binance perpetual FUNDING RATE (fapi/v1/fundingRate), mean-resampled to
       the trend TF, rolling trailing-90d percentile (min 30d warmup) — the
       SAME percentile mechanics phase2a/phase2b use for their crowding
       signal, just fed a different point-in-time-safe input. High funding
       percentile = crowded long (longs paying shorts); low = crowded short.
       This is a re-verification of Phase-2a's own funding-based proxy
       hypothesis, but sourced from BINANCE funding (public, no key) rather
       than Hyperliquid funding (which Phase-2a used).

  fuel (was: Coinalyze real open interest change)
    -> 24h/72h quote-volume-sum-vs-prior-window, i.e. Phase-2a's ALREADY-
       DECLARED "vol" fuel proxy (research_cta_positioning.py fuel_raw =
       qv24 > qv24.shift(bpd)), generalized to a configurable lookback.
       Binance's own open-interest-history endpoint is hard-capped to ~30
       days of history regardless of startTime (confirmed empirically by
       scripts/cta_proxy_pull_data.py — see its OI diagnostic output), so it
       cannot serve as a multi-year fuel signal; volume is the only
       Binance-only series with genuine multi-year depth.

Every signal is computed on closed bars and shifted by one bar before use
(point-in-time discipline identical to phase2a/phase2b).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parent / "src"))

_spec = importlib.util.spec_from_file_location(
    "p2b", _SCRIPTS / "research_cta_positioning_phase2b.py")
p2b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2b)

PCACHE = Path("data/cache/cta_proxy")

NOTIONAL = p2b.NOTIONAL
FEE_SIDE = p2b.FEE_SIDE
PORT_BASE_6 = p2b.PORT_BASE                 # $600, 6-coin portfolio (validation universe)
TFS = p2b.TFS
TREND_WARMUP_BARS = p2b.TREND_WARMUP_BARS
CROWD_WARMUP_DAYS = p2b.CROWD_WARMUP_DAYS
CROWD_WINDOW_DAYS = p2b.CROWD_WINDOW_DAYS
TSTAT_GATE = p2b.TSTAT_GATE

SYMBOLS_6 = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL",
             "HYPEUSDT": "HYPE", "DOGEUSDT": "DOGE", "XRPUSDT": "XRP"}
# Multi-year universe excludes HYPE: Binance HYPEUSDT perp only listed
# 2025-05-30 (confirmed by cta_proxy_pull_data.py pull), ~13 months of
# history — nowhere near "years", so it cannot inform a cross-cycle/regime
# decomposition. Kept in SYMBOLS_6 for the overlap-validation universe (which
# only needs the ~11mo real-crowd window) but dropped for the multi-year run.
SYMBOLS_5 = {k: v for k, v in SYMBOLS_6.items() if v != "HYPE"}


def load_klines(sym: str) -> dict[str, pd.DataFrame]:
    out = {}
    for tf in TFS:
        df = pd.read_parquet(PCACHE / f"{sym}_{tf}.parquet")
        df = df.copy()
        df.index = pd.to_datetime(df.pop("open_time"), unit="ms")
        out[tf] = df
    return out


def load_funding(sym: str) -> pd.Series:
    """Point-in-time series: funding rate known AT fundingTime (realized, not
    predicted-future). Indexed by fundingTime, naive UTC."""
    df = pd.read_parquet(PCACHE / f"{sym}_funding.parquet")
    idx = pd.to_datetime(df["fundingTime"], unit="ms")
    s = pd.Series(df["fundingRate"].astype(float).values, index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def bar_frame(kl: pd.DataFrame, funding: pd.Series, tf: str) -> pd.DataFrame:
    """Klines + per-bar mean funding rate (for the trend TF bucket). No
    Coinalyze-style coverage-intersection cropping needed here — klines and
    funding both start at the same symbol-listing date on Binance."""
    rule = TFS[tf]["rule"]
    bars = kl.copy()
    fbar = funding.resample(rule, label="left", closed="left").mean()
    bars["funding_mean"] = fbar.reindex(bars.index)
    # Funding events land on fixed clock boundaries (historically every 8h,
    # sometimes more frequent for high-vol symbols); a bar with no event in
    # its window inherits the last REALIZED rate known at or before that bar
    # (point-in-time safe — never fills forward from the future).
    bars["funding_mean"] = bars["funding_mean"].ffill()
    return bars


def _pct_rank_last(w: np.ndarray) -> float:
    cur = w[-1]
    if np.isnan(cur):
        return np.nan
    w = w[~np.isnan(w)]
    return float((w <= cur).mean() * 100.0)


def raw_indicators(bars: pd.DataFrame, tf: str, fuel_lookbacks: tuple[int, ...]) -> pd.DataFrame:
    """Unshifted indicators on closed bars. Mirrors p2b.raw_indicators() but:
      - lpct_raw comes from funding_mean (not Coinalyze long_pct)
      - fuel{lb}_raw comes from quote_volume (Phase-2a's proxy), not OI level
    """
    df = bars.copy()
    bpd = TFS[tf]["bars_per_day"]
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    valid = pd.Series(np.arange(len(df)) >= TREND_WARMUP_BARS, index=df.index)
    df["trend_up_raw"] = (ema20 > ema50) & valid
    df["trend_dn_raw"] = (ema50 > ema20) & valid
    df["lpct_raw"] = df["funding_mean"].rolling(
        CROWD_WINDOW_DAYS * bpd, min_periods=CROWD_WARMUP_DAYS * bpd
    ).apply(_pct_rank_last, raw=True)
    for lb_h in fuel_lookbacks:
        lb_bars = max(1, round(lb_h / 24 * bpd))
        qv = df["quote_volume"].rolling(lb_bars).sum()
        df[f"fuel{lb_h}_raw"] = qv > qv.shift(lb_bars)
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df["atr_raw"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df.loc[df.index[:TREND_WARMUP_BARS], "atr_raw"] = np.nan
    return df


def shifted_signals(raw: pd.DataFrame, pctile: int, fuel_lb: int) -> pd.DataFrame:
    """Identical shift-by-one-bar mechanics to p2b.shifted_signals()."""
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


def crowd_off(sig: pd.DataFrame) -> pd.DataFrame:
    out = sig.copy()
    out["crowd_long"] = True
    out["crowd_short"] = True
    return out


def build_frames(symbols: dict[str, str], fuel_lookbacks: tuple[int, ...] = (24, 72)):
    """Load + compute raw indicators for every (coin, tf). Returns
    (frames, window_start, window_end) where window is the intersection of
    klines+funding coverage across ALL symbols (funding is never the binding
    constraint here since both start together per-symbol; window_start is
    just max of per-symbol starts = the shortest-history symbol's start)."""
    frames = {}
    cov_starts, cov_ends = [], []
    for sym, coin in symbols.items():
        kls = load_klines(sym)
        funding = load_funding(sym)
        for tf in TFS:
            bars = bar_frame(kls[tf], funding, tf)
            frames[(coin, tf)] = raw_indicators(bars, tf, fuel_lookbacks)
        b4 = frames[(coin, "4h")]
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())
    return frames, max(cov_starts), min(cov_ends)


def profit_factor(trades: list[dict]) -> float:
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def run_cell(frames, symbols, tf, side, crowd_on, p, fuel_lb, stats_start,
             split_at=None, window=None):
    """One A/B cell across the given coin universe. Reuses p2b.simulate /
    p2b.daily_stats verbatim (same $100/coin notional, same fee, same stop/
    maxhold/flip exits) — only the sig frame's crowd/fuel columns differ.

    `window`, if given, is (start, end): the signal frame (already shifted,
    i.e. using its FULL available history for percentile/EMA/ATR warmup) is
    sliced to this span before simulate() runs, so trades cannot open before
    `start` or after `end` — the walk-forward only ever *trades* inside the
    declared window, even though its indicators may draw on longer proxy
    history than the real-crowd data source had available."""
    port_base = NOTIONAL * len(symbols)
    per_coin_daily = {}
    all_trades = []
    for sym, coin in symbols.items():
        sig = shifted_signals(frames[(coin, tf)], p, fuel_lb)
        if window is not None:
            sig = sig.loc[window[0]:window[1]]
        if not crowd_on:
            sig = crowd_off(sig)
        bar_pnl, trades = p2b.simulate(sig, side)
        per_coin_daily[coin] = bar_pnl.resample("1D").sum()
        for t in trades:
            t["coin"] = coin
        all_trades.extend(trades)
    daily = pd.concat(per_coin_daily.values(), axis=1).fillna(0).sum(axis=1)
    sa = split_at if split_at is not None else stats_start
    d = daily.loc[stats_start:]
    import math
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    tstat = mu / sd * math.sqrt(n) if sd > 0 else 0.0
    eq = port_base + d.cumsum()
    mdd = float((eq / eq.cummax() - 1.0).min())
    tr = [t for t in all_trades if t["exit_time"] >= stats_start]
    return {
        "pnl": d.sum(), "ret_pct": d.sum() / port_base * 100.0,
        "sharpe": sharpe, "tstat": tstat, "mdd_pct": mdd * 100.0,
        "trades": len(tr), "pf": profit_factor(tr),
        "win_pct": (np.mean([t["pnl"] > 0 for t in tr]) * 100.0) if tr else 0.0,
        "daily": daily, "n_days": n, "port_base": port_base,
        "all_trades": all_trades,          # UNFILTERED (incl. pre-stats_start) for regime slicing
        "per_coin_daily": per_coin_daily,   # UNFILTERED per-coin daily pnl series
    }


def period_stats(daily_full: pd.Series, start: pd.Timestamp, end: pd.Timestamp,
                  port_base: float) -> dict:
    """Path-based Sharpe/MDD/PnL for a CONTIGUOUS calendar slice [start, end)
    of an already-computed daily pnl series. Valid for MDD (unlike a
    non-contiguous regime bucket) because the slice is a real, ordered span
    of calendar time."""
    d = daily_full.loc[start:end - pd.Timedelta(seconds=1)]
    if len(d) == 0:
        return {"n_days": 0, "pnl": 0.0, "sharpe": 0.0, "mdd_pct": 0.0}
    import math
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 and n > 1 else 0.0
    eq = port_base + d.cumsum()
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {"n_days": n, "pnl": d.sum(), "sharpe": sharpe, "mdd_pct": mdd * 100.0}
