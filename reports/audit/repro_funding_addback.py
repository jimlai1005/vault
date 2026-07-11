"""Audit repro (read-only) — Q4 of the phase-2b adversarial audit.

Phase-2b's verdict explicitly caveats: "Phase 2b PnL therefore has no funding
accrual." Phase 2a *did* include real HL hourly funding cash-flow (short
receives positive funding when funding > 0, the market's usual sign during
bullish/crowded-long conditions). Phase 2b's strategy family specifically
enters SHORT when retail positioning is crowded LONG -- exactly the condition
historically correlated with elevated (positive) funding paid to shorts. If
that's true empirically over this window, dropping funding is a one-directional
omission that UNDERSTATES the short side's real edge (wrongly-penalizes /
"冤枉", not "over-generous").

This script reconstructs phase-2b's signals (via import, not reimplementation
of the signal logic) for the median config, the best config, and the 8
short-only configs, adds a funding accrual term using the SAME mechanics
research_cta_positioning.py (phase 2a) used -- pnl += -dir * fund_accr * NOTIONAL
per bar while holding a position, funding sourced from the real
data/cache/funding/{COIN}.parquet HL hourly series for the SAME phase-2b
window -- and reports the funding-inclusive vs funding-exclusive Sharpe/tstat/
MDD/gate-2 outcome.

Read-only. Writes nothing outside reports/audit/.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import research_cta_positioning_phase2b as p2b  # noqa: E402

SYMBOLS = p2b.SYMBOLS
TFS = p2b.TFS
NOTIONAL = p2b.NOTIONAL
FEE_SIDE = p2b.FEE_SIDE
MAX_HOLD = p2b.MAX_HOLD
STOP_ATR_MULT = p2b.STOP_ATR_MULT
FCACHE = REPO / "data" / "cache" / "funding"


def load_funding(coin: str) -> pd.Series:
    df = pd.read_parquet(FCACHE / f"{coin}.parquet")
    idx = pd.to_datetime(df["time"], unit="ms").dt.floor("h")
    s = pd.Series(df["fundingRate"].values, index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def fund_accr_for_bars(frate: pd.Series, idx: pd.DatetimeIndex, tf: str) -> pd.Series:
    """Sum of hourly funding within each bar -- identical resample mechanics to
    phase 2a's bar_frame() 'fund_accr' column."""
    rule = TFS[tf]["rule"]
    fsum = frate.resample(rule, label="left", closed="left").sum()
    return fsum.reindex(idx).fillna(0.0)


def simulate_with_funding(sig: pd.DataFrame, side: str, fund_accr: pd.Series):
    """Copy of p2b.simulate() with a funding accrual term added, mirroring
    research_cta_positioning.py's (phase 2a) exact accrual mechanics:
    pnl += -dir * fund_accr[i] * NOTIONAL while a position is held (entry bar
    included, matching phase 2a; the exit bar's partial-period funding is
    NOT credited, also matching phase 2a -- so this is an apples-to-apples
    re-application of phase 2a's own funding convention, not a new one)."""
    idx = sig.index
    o, h, l, c = (sig[k].to_numpy() for k in ("open", "high", "low", "close"))
    tu, td = sig["trend_up"].to_numpy(), sig["trend_dn"].to_numpy()
    cl, cs = sig["crowd_long"].to_numpy(), sig["crowd_short"].to_numpy()
    fk = sig["fuel_ok"].to_numpy()
    atr = sig["atr"].to_numpy()
    fa = fund_accr.reindex(idx).fillna(0.0).to_numpy()
    bar_pnl = np.zeros(len(sig))
    bar_fund = np.zeros(len(sig))
    pos = None

    def close_trade(i, exit_px):
        d = pos["dir"]
        return d * (exit_px - pos["mark"]) / pos["entry_px"] * NOTIONAL - FEE_SIDE

    for i in range(len(sig)):
        pnl = 0.0
        fund_this_bar = 0.0
        exited_this_bar = False
        if pos is not None:
            d = pos["dir"]
            flip = (d == 1 and not tu[i]) or (d == -1 and not td[i])
            fuel_fail = not fk[i]
            too_long = idx[i] - pos["t0"] >= MAX_HOLD
            if flip or fuel_fail or too_long:
                pnl += close_trade(i, o[i])
                pos, exited_this_bar = None, True
            else:
                stop_px = None
                if d == -1 and h[i] >= pos["stop"]:
                    stop_px = o[i] if o[i] >= pos["stop"] else pos["stop"]
                elif d == 1 and l[i] <= pos["stop"]:
                    stop_px = o[i] if o[i] <= pos["stop"] else pos["stop"]
                if stop_px is not None:
                    pnl += close_trade(i, stop_px)
                    pos, exited_this_bar = None, True
                else:
                    pnl += d * (c[i] - pos["mark"]) / pos["entry_px"] * NOTIONAL
                    fund_this_bar = -d * fa[i] * NOTIONAL
                    pnl += fund_this_bar
                    pos["mark"] = c[i]
        if pos is None and not exited_this_bar:
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
                if hit:
                    pnl += close_trade(i, stop)
                    pos = None
                else:
                    pnl += d * (c[i] - entry_px) / entry_px * NOTIONAL
                    fund_this_bar = -d * fa[i] * NOTIONAL
                    pnl += fund_this_bar
                    pos["mark"] = c[i]
        bar_pnl[i] = pnl
        bar_fund[i] = fund_this_bar
    if pos is not None:
        d = pos["dir"]
        bar_pnl[-1] += -FEE_SIDE
    return pd.Series(bar_pnl, index=idx), pd.Series(bar_fund, index=idx)


def sharpe_tstat_mdd(d: pd.Series, port_base: float) -> dict:
    mu, sd, n = d.mean(), d.std(ddof=1), len(d)
    sharpe = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    tstat = mu / sd * math.sqrt(n) if sd > 0 else 0.0
    eq = port_base + d.cumsum()
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {"pnl": d.sum(), "sharpe": sharpe, "tstat": tstat, "mdd": mdd, "n": n}


def run_config(tf: str, pct: int, fuel_lb: int, side: str, frames, frates, stats_start):
    sigs = {coin: p2b.shifted_signals(frames[(coin, tf)], pct, fuel_lb)
            for coin in SYMBOLS.values()}
    per_coin_nofund, per_coin_fund, per_coin_fundonly = {}, {}, {}
    for coin, sig in sigs.items():
        fa = fund_accr_for_bars(frates[coin], sig.index, tf)
        bar_pnl_nofund, _ = p2b.simulate(sig, side), None
        bar_pnl_fund, bar_fund = simulate_with_funding(sig, side, fa)
        per_coin_nofund[coin] = bar_pnl_nofund[0].resample("1D").sum()
        per_coin_fund[coin] = bar_pnl_fund.resample("1D").sum()
        per_coin_fundonly[coin] = bar_fund.resample("1D").sum()
    daily_nofund = pd.concat(per_coin_nofund.values(), axis=1).fillna(0).sum(axis=1).loc[stats_start:]
    daily_fund = pd.concat(per_coin_fund.values(), axis=1).fillna(0).sum(axis=1).loc[stats_start:]
    daily_fundonly = pd.concat(per_coin_fundonly.values(), axis=1).fillna(0).sum(axis=1).loc[stats_start:]
    return daily_nofund, daily_fund, daily_fundonly


def main():
    frames = {}
    cov_starts, cov_ends = [], []
    frates = {}
    for sym, coin in SYMBOLS.items():
        kls = p2b.load_klines(sym)
        oi, long_pct = p2b.load_coinalyze(coin)
        for tf in TFS:
            bars = p2b.bar_frame(kls[tf], oi, long_pct, tf)
            frames[(coin, tf)] = p2b.raw_indicators(bars, tf)
        b4 = frames[(coin, "4h")]
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())
        frates[coin] = load_funding(coin)
        print(f"{coin:5s} funding hours={len(frates[coin])} "
              f"[{frates[coin].index.min():%Y-%m-%d} .. {frates[coin].index.max():%Y-%m-%d}] "
              f"mean_rate={frates[coin].mean():.6f} pct_positive={100*(frates[coin]>0).mean():.1f}%")

    window_start = max(cov_starts)
    window_end = min(cov_ends)
    stats_start = (window_start + pd.Timedelta(days=p2b.CROWD_WARMUP_DAYS)).ceil("D")
    port_base = p2b.PORT_BASE

    targets = [
        ("median (1d-p20-fuel24-short)", "1d", 20, 24, "short"),
        ("best (4h-p10-fuel24-short)", "4h", 10, 24, "short"),
    ]
    print("\n=== funding add-back: single configs ===")
    for label, tf, pct, fuel_lb, side in targets:
        nofund, withfund, fundonly = run_config(tf, pct, fuel_lb, side, frames, frates, stats_start)
        r0 = sharpe_tstat_mdd(nofund, port_base)
        r1 = sharpe_tstat_mdd(withfund, port_base)
        print(f"\n{label}:")
        print(f"  no-funding : pnl={r0['pnl']:8.2f}  sharpe={r0['sharpe']:.3f}  tstat={r0['tstat']:.3f}  mdd={r0['mdd']*100:.2f}%")
        print(f"  w/ funding : pnl={r1['pnl']:8.2f}  sharpe={r1['sharpe']:.3f}  tstat={r1['tstat']:.3f}  mdd={r1['mdd']*100:.2f}%")
        print(f"  funding-only cumulative $ = {fundonly.sum():.2f}  "
              f"(mean/day={fundonly.mean():.4f}, {100*(fundonly>0).mean():.1f}% of days net-positive)")
        print(f"  delta: pnl {r1['pnl']-r0['pnl']:+.2f}  sharpe {r1['sharpe']-r0['sharpe']:+.3f}  tstat {r1['tstat']-r0['tstat']:+.3f}")

    # 8 short-only configs ensemble
    print("\n=== funding add-back: equal-weight ensemble of the 8 short-only configs ===")
    ens_nofund_list, ens_fund_list = [], []
    for tf in TFS:
        for pct in p2b.PCTILES:
            for fuel_lb in p2b.FUEL_LOOKBACKS:
                nofund, withfund, _ = run_config(tf, pct, fuel_lb, "short", frames, frates, stats_start)
                ens_nofund_list.append(nofund.rename(f"{tf}-p{pct}-fuel{fuel_lb}"))
                ens_fund_list.append(withfund.rename(f"{tf}-p{pct}-fuel{fuel_lb}"))
    ens_nofund = pd.concat(ens_nofund_list, axis=1).fillna(0).mean(axis=1)
    ens_fund = pd.concat(ens_fund_list, axis=1).fillna(0).mean(axis=1)
    r0 = sharpe_tstat_mdd(ens_nofund, port_base)
    r1 = sharpe_tstat_mdd(ens_fund, port_base)
    print(f"  no-funding : sharpe={r0['sharpe']:.3f}  tstat={r0['tstat']:.3f}")
    print(f"  w/ funding : sharpe={r1['sharpe']:.3f}  tstat={r1['tstat']:.3f}")
    print(f"  delta: sharpe {r1['sharpe']-r0['sharpe']:+.3f}  tstat {r1['tstat']-r0['tstat']:+.3f}")


if __name__ == "__main__":
    main()
