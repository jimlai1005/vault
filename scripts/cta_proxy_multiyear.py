"""Layer-2b multi-year regime study — Binance-only proxy engine.

Runs the production-equivalent config (4h, crowd-percentile 10, fuel 24h)
across ~5.7 years of Binance-only data (funding-rate crowd proxy + volume
fuel proxy; see cta_proxy_lib.py docstring) to ask three questions the
~11-month real-crowd sample (Phase 2b) structurally cannot answer:
  (a) does the edge (short profitable, short > long) hold across MULTIPLE
      BTC cycles, not just 2025-26?
  (b) does the crowd filter's MDD-reduction value hold across cycles, or was
      it a one-regime artifact?
  (c) what is the worst full-period drawdown across the whole run (the
      honest leverage anchor)?

PRECONDITION: only meaningful because scripts/cta_proxy_validate.py PASSED
its 3-gate directional check against the real-crowd result in the overlap
window (see reports/cta_proxy_layer2b_verdict.md). This script does not
re-check that gate; it assumes it already passed.

Universe: BTC ETH SOL DOGE XRP (cta_proxy_lib.SYMBOLS_5). HYPE excluded —
Binance HYPEUSDT perp only listed 2025-05-30 (~13mo), no cycle history.
Window: intersection of all 5 coins' Binance klines+funding coverage, i.e.
[SOL's listing (2020-09-14) .. today]. SOL is the binding constraint (latest
listing among the 5); BTC/ETH/DOGE/XRP all have longer history but are
cropped to the common window for a like-for-like portfolio.

Everything here is PROXY data (Binance funding rate standing in for retail
positioning; Binance quote-volume standing in for OI momentum) — this run is
about REGIME ROBUSTNESS of the strategy structure, not a re-validation of
the live crowd signal itself. Do not treat these Sharpe/PnL numbers as a
GO/NO-GO input for capital; Phase 2b (real, ~11mo) remains the binding
verdict for that question.

Usage: .venv/bin/python scripts/cta_proxy_multiyear.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_proxy_lib as lib

SCRATCHPAD = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                  "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad")
REPORTS = Path("/Users/jim/projects/vault/reports")

TF, PCTILE, FUEL_LB = "4h", 10, 24     # production-equivalent (matches live cta/config.py)


def load_btc_daily_close() -> pd.Series:
    df = pd.read_parquet(lib.PCACHE / "BTCUSDT_1d.parquet")
    idx = pd.to_datetime(df["open_time"], unit="ms")
    return pd.Series(df["close"].astype(float).values, index=idx).sort_index()


def label_regimes(trades: list[dict], btc_close: pd.Series, vol_p33: float, vol_p67: float) -> None:
    """In-place: attach regime_a (200DMA risk-on/off) and regime_b (30d vol
    tercile) to each trade dict, using only data strictly before entry_time
    (point-in-time)."""
    for t in trades:
        prior = btc_close[btc_close.index < t["entry_time"]]
        if len(prior) >= 200:
            sma200 = prior.tail(200).mean()
            t["regime_a"] = "risk-on" if prior.iloc[-1] > sma200 else "risk-off"
        else:
            t["regime_a"] = "unknown"
        if len(prior) >= 30:
            r = np.diff(np.log(prior.tail(30).values))
            v = float(np.std(r) * np.sqrt(365))
            t["regime_b"] = "low" if v < vol_p33 else ("mid" if v < vol_p67 else "high")
        else:
            t["regime_b"] = "unknown"
        t["year"] = t["entry_time"].year


def vol_terciles(btc_close: pd.Series) -> tuple[float, float]:
    closes = btc_close.sort_index().values
    vols = []
    for i in range(30, len(closes)):
        r = np.diff(np.log(closes[i - 30:i]))
        vols.append(np.std(r) * np.sqrt(365))
    return float(np.percentile(vols, 33)), float(np.percentile(vols, 67))


def fmt_cell(tag: str, r: dict) -> str:
    return (f"{tag:<20s}{r['sharpe']:>8.2f}{r['mdd_pct']:>8.1f}%{r['pnl']:>9.2f}"
            f"{r['trades']:>8d}{r['win_pct']:>6.0f}%")


def main() -> None:
    frames, w_start, w_end = lib.build_frames(lib.SYMBOLS_5, fuel_lookbacks=(FUEL_LB,))
    stats_start = (w_start + pd.Timedelta(days=lib.CROWD_WARMUP_DAYS)).ceil("D")
    n_years = (w_end - stats_start).days / 365.25
    print(f"universe: {list(lib.SYMBOLS_5.values())}  (5 coins, HYPE excluded — see docstring)")
    print(f"window: [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]  stats from {stats_start:%Y-%m-%d}  "
          f"(~{n_years:.1f} years)")

    lines = [f"Layer-2b multi-year proxy study — {TF}-p{PCTILE}-fuel{FUEL_LB}",
             f"Universe: {list(lib.SYMBOLS_5.values())}  Window: [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]  "
             f"stats from {stats_start:%Y-%m-%d} (~{n_years:.1f}y)", ""]

    print(f"\n=== HEADLINE full-period cells ({TF}-p{PCTILE}-fuel{FUEL_LB}) ===")
    hdr = f"{'cell':<20s}{'sharpe':>8s}{'mdd%':>8s}{'pnl$':>9s}{'trades':>8s}{'win%':>7s}"
    print(hdr)
    lines.append("=== HEADLINE full-period cells ==="); lines.append(hdr)
    cells = {}
    worst_mdd = 0.0
    for side in ("short", "long"):
        for crowd_on in (True, False):
            r = lib.run_cell(frames, lib.SYMBOLS_5, TF, side, crowd_on, PCTILE, FUEL_LB, stats_start)
            cells[(side, crowd_on)] = r
            tag = f"{side}/crowd-{'ON' if crowd_on else 'OFF'}"
            print(fmt_cell(tag, r)); lines.append(fmt_cell(tag, r))
            worst_mdd = min(worst_mdd, r["mdd_pct"])

    s_on = cells[("short", True)]
    print(f"\nFULL-PERIOD WORST MDD (deployed-equivalent, short/crowd-ON): {s_on['mdd_pct']:.1f}%")
    print(f"WORST MDD across ALL four tested cells (honest leverage anchor): {worst_mdd:.1f}%")
    lines.append(f"\nFULL-PERIOD WORST MDD (short/crowd-ON, deployed-equivalent): {s_on['mdd_pct']:.1f}%")
    lines.append(f"WORST MDD across all 4 cells (short/long x crowd on/off):   {worst_mdd:.1f}%")

    # ---- year-by-year decomposition (contiguous calendar slices -> valid MDD) ----
    print(f"\n=== YEAR-BY-YEAR  (contiguous slices; MDD is a genuine path metric here) ===")
    lines.append("\n=== YEAR-BY-YEAR ===")
    yr_hdr = (f"{'year':<6s}{'side':<7s}{'crowd':<5s}{'days':>6s}{'sharpe':>8s}"
              f"{'mdd%':>8s}{'pnl$':>9s}")
    print(yr_hdr); lines.append(yr_hdr)
    years = list(range(w_start.year, w_end.year + 1))
    crowd_holds_per_year = []
    for yr in years:
        y0 = max(stats_start, pd.Timestamp(yr, 1, 1))
        y1 = min(w_end + pd.Timedelta(days=1), pd.Timestamp(yr + 1, 1, 1))
        if y0 >= y1:
            continue
        row_s_on = row_s_off = None
        for side in ("short", "long"):
            for crowd_on in (True, False):
                r = cells[(side, crowd_on)]
                ps = lib.period_stats(r["daily"], y0, y1, r["port_base"])
                if ps["n_days"] == 0:
                    continue
                tag_line = (f"{yr:<6d}{side:<7s}{'ON' if crowd_on else 'OFF':<5s}"
                            f"{ps['n_days']:>6d}{ps['sharpe']:>8.2f}{ps['mdd_pct']:>7.1f}%{ps['pnl']:>9.2f}")
                print(tag_line); lines.append(tag_line)
                if side == "short" and crowd_on:
                    row_s_on = ps
                if side == "short" and not crowd_on:
                    row_s_off = ps
        if row_s_on and row_s_off:
            crowd_holds_per_year.append((yr, row_s_on["mdd_pct"], row_s_off["mdd_pct"]))

    print("\ncrowd-filter value by year (short side, MDD ON vs OFF):")
    lines.append("\ncrowd-filter value by year (short side, MDD ON vs OFF):")
    n_years_filter_helps = 0
    for yr, mdd_on, mdd_off in crowd_holds_per_year:
        helps = abs(mdd_off) > abs(mdd_on)
        n_years_filter_helps += helps
        line = f"  {yr}: ON {mdd_on:6.1f}%  OFF {mdd_off:6.1f}%  {'filter helps' if helps else 'filter does NOT help'}"
        print(line); lines.append(line)
    frac = n_years_filter_helps / len(crowd_holds_per_year) if crowd_holds_per_year else 0.0
    summary_line = (f"\ncrowd filter reduced MDD in {n_years_filter_helps}/{len(crowd_holds_per_year)} "
                     f"years ({frac*100:.0f}%)")
    print(summary_line); lines.append(summary_line)

    # ---- regime decomposition (BTC 200DMA, 30d vol tercile) ----
    print(f"\n=== REGIME DECOMPOSITION (trade-level; non-contiguous, PnL/PF only — no MDD) ===")
    lines.append("\n=== REGIME DECOMPOSITION (BTC 200DMA / 30d vol tercile) ===")
    btc_close = load_btc_daily_close()
    vp33, vp67 = vol_terciles(btc_close)
    print(f"vol terciles: p33={vp33:.3f} p67={vp67:.3f}")
    lines.append(f"vol terciles: p33={vp33:.3f} p67={vp67:.3f}")

    reg_hdr = f"{'side':<7s}{'crowd':<5s}{'regimeA':<10s}{'trades':>7s}{'pnl$':>9s}{'PF':>7s}{'win%':>6s}"
    print(reg_hdr); lines.append(reg_hdr)
    for side in ("short", "long"):
        for crowd_on in (True, False):
            r = cells[(side, crowd_on)]
            tr = [t for t in r["all_trades"] if t["exit_time"] >= stats_start]
            label_regimes(tr, btc_close, vp33, vp67)
            for regime_a in ("risk-on", "risk-off"):
                grp = [t for t in tr if t["regime_a"] == regime_a]
                if not grp:
                    continue
                pnl = sum(t["pnl"] for t in grp)
                pf = lib.profit_factor(grp)
                win = np.mean([t["pnl"] > 0 for t in grp]) * 100
                pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
                row = (f"{side:<7s}{'ON' if crowd_on else 'OFF':<5s}{regime_a:<10s}"
                       f"{len(grp):>7d}{pnl:>9.2f}{pf_s:>7s}{win:>5.0f}%")
                print(row); lines.append(row)

    print(f"\n{'side':<7s}{'crowd':<5s}{'regimeB':<10s}{'trades':>7s}{'pnl$':>9s}{'PF':>7s}{'win%':>6s}")
    lines.append(f"\n{'side':<7s}{'crowd':<5s}{'regimeB':<10s}{'trades':>7s}{'pnl$':>9s}{'PF':>7s}{'win%':>6s}")
    for side in ("short", "long"):
        for crowd_on in (True, False):
            r = cells[(side, crowd_on)]
            tr = [t for t in r["all_trades"] if t["exit_time"] >= stats_start]
            label_regimes(tr, btc_close, vp33, vp67)
            for regime_b in ("low", "mid", "high"):
                grp = [t for t in tr if t["regime_b"] == regime_b]
                if not grp:
                    continue
                pnl = sum(t["pnl"] for t in grp)
                pf = lib.profit_factor(grp)
                win = np.mean([t["pnl"] > 0 for t in grp]) * 100
                pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
                row = (f"{side:<7s}{'ON' if crowd_on else 'OFF':<5s}{regime_b:<10s}"
                       f"{len(grp):>7d}{pnl:>9.2f}{pf_s:>7s}{win:>5.0f}%")
                print(row); lines.append(row)

    out = SCRATCHPAD / "cta_proxy_multiyear_full.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nfull table -> {out}")

    # machine-readable summary for the report writer
    summary = {
        "window": [str(w_start.date()), str(w_end.date())],
        "stats_start": str(stats_start.date()),
        "n_years": round(n_years, 2),
        "headline": {f"{s}_{('on' if c else 'off')}": {
            "sharpe": cells[(s, c)]["sharpe"], "mdd_pct": cells[(s, c)]["mdd_pct"],
            "pnl": cells[(s, c)]["pnl"], "trades": cells[(s, c)]["trades"],
        } for s in ("short", "long") for c in (True, False)},
        "worst_mdd_deployed_equiv": s_on["mdd_pct"],
        "worst_mdd_all_cells": worst_mdd,
        "years_filter_helps": f"{n_years_filter_helps}/{len(crowd_holds_per_year)}",
    }
    import json
    (SCRATCHPAD / "cta_proxy_multiyear_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"summary json -> {SCRATCHPAD / 'cta_proxy_multiyear_summary.json'}")


if __name__ == "__main__":
    main()
