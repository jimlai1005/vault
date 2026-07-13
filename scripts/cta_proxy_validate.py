"""Layer-2b GATE: does a Binance-funding-based crowd proxy reproduce, in the
SAME overlap window, the DIRECTION of the known real-crowd (Coinalyze
account-ratio) result from Phase 2b / the crowd-ablation study?

This is the pass/fail checkpoint the task requires BEFORE any multi-year
number is treated as meaningful. If it fails, the correct action is to stop
and report the failure honestly — not to proceed to the multi-year run.

Known real-crowd anchors (already published, NOT recomputed here — cited by
report path so this script cannot silently drift from them):
  reports/cta-phase2b-verdict.md (production-equivalent config 4h-p10-fuel24):
    short crowd-ON : Sharpe 2.34, MDD -3.1%  (best config in the matrix)
    long  crowd-ON : Sharpe -1.61, MDD -16.0% (dead/lossy)
  scripts/research_cta_crowd_ablation.py output (same config, crowd-OFF arm):
    short crowd-OFF: MDD -14.4%  (vs -3.1% ON -> ~4.6x MDD blowup)
    long  crowd-OFF: MDD -26.0% (vs -16.0% ON)

Directional pass criteria (pre-declared, see task):
  1. proxy short/crowd-ON is profitable (positive Sharpe).
  2. proxy short/crowd-ON beats proxy long/crowd-ON (Sharpe and/or MDD).
  3. proxy crowd-OFF MDD is MEANINGFULLY worse than crowd-ON MDD on the short
     side (a clear multiple, not just noise) — mirroring the ~4.6x blowup
     the real crowd data showed.
All three must hold for PASS. Magnitude need not match the real data's
numbers (proxy != real signal) — only the DIRECTION/qualitative pattern.

Universe: BTC ETH SOL HYPE DOGE XRP (6 coins, same as phase2b) restricted to
the SAME calendar window phase2b actually used (derived here from the real
Coinalyze coverage, not hardcoded, so it cannot drift from the source data).
Proxy signals (Binance funding percentile crowd + Binance volume fuel) are
computed on each coin's FULL available Binance history (which is deeper than
Coinalyze's ~335d), then the resulting signal series is sliced down to the
declared window before simulate() runs — so trades only ever occur inside the
window, but the crowd percentile benefits from a longer trailing-history
warmup than the real LSR signal had. Flagged as an asymmetry, not hidden.

Usage: .venv/bin/python scripts/cta_proxy_validate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_proxy_lib as lib
p2b = lib.p2b

SCRATCHPAD = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                  "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad")

REAL_ANCHOR = {
    ("short", True):  {"sharpe": 2.34, "mdd_pct": -3.1},
    ("short", False): {"sharpe": None, "mdd_pct": -14.4},
    ("long", True):   {"sharpe": -1.61, "mdd_pct": -16.0},
    ("long", False):  {"sharpe": None, "mdd_pct": -26.0},
}


def real_crowd_window():
    """Re-derive phase2b's actual window_start/window_end/stats_start from
    the real Coinalyze cache (no hardcoded dates) so this gate cannot drift
    from the source report if the cache is ever refreshed."""
    cov_starts, cov_ends = [], []
    for sym, coin in p2b.SYMBOLS.items():
        kls = p2b.load_klines(sym)
        oi, long_pct = p2b.load_coinalyze(coin)
        b4 = p2b.bar_frame(kls["4h"], oi, long_pct, "4h")
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())
    window_start = max(cov_starts)
    window_end = min(cov_ends)
    stats_start = (window_start + pd.Timedelta(days=p2b.CROWD_WARMUP_DAYS)).ceil("D")
    return window_start, window_end, stats_start


def main() -> None:
    w_start, w_end, stats_start = real_crowd_window()
    print(f"real-crowd window (re-derived from Coinalyze cache): "
          f"[{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]  stats from {stats_start:%Y-%m-%d}")

    frames, cov_start, cov_end = lib.build_frames(lib.SYMBOLS_6, fuel_lookbacks=(24, 72))
    print(f"proxy full-history coverage (funding+klines): "
          f"[{cov_start:%Y-%m-%d} .. {cov_end:%Y-%m-%d}]  (deeper than Coinalyze; "
          f"sliced down to the window above before simulate())")

    tf, p, fl = "4h", 10, 24     # production-equivalent config
    print(f"\n=== PRIMARY CELL  (proxy {tf}-p{p}-fuel{fl}, same window as real-crowd) ===")
    hdr = f"{'cell':<20s}{'sharpe':>8s}{'mdd%':>8s}{'pnl$':>9s}{'trades':>8s}{'win%':>7s}"
    print(hdr)
    cells = {}
    for side in ("short", "long"):
        for crowd_on in (True, False):
            r = lib.run_cell(frames, lib.SYMBOLS_6, tf, side, crowd_on, p, fl,
                              stats_start, window=(w_start, w_end))
            cells[(side, crowd_on)] = r
            tag = f"{side}/crowd-{'ON' if crowd_on else 'OFF'}"
            print(f"{tag:<20s}{r['sharpe']:>8.2f}{r['mdd_pct']:>7.1f}%{r['pnl']:>9.2f}"
                  f"{r['trades']:>8d}{r['win_pct']:>6.0f}%")

    print("\n=== comparison to known real-crowd anchor (Coinalyze LSR, cited) ===")
    print(f"{'cell':<20s}{'proxy sharpe':>13s}{'real sharpe':>12s}{'proxy mdd%':>11s}{'real mdd%':>10s}")
    for side in ("short", "long"):
        for crowd_on in (True, False):
            r = cells[(side, crowd_on)]
            a = REAL_ANCHOR[(side, crowd_on)]
            real_s = f"{a['sharpe']:.2f}" if a["sharpe"] is not None else "n/a"
            tag = f"{side}/crowd-{'ON' if crowd_on else 'OFF'}"
            print(f"{tag:<20s}{r['sharpe']:>13.2f}{real_s:>12s}{r['mdd_pct']:>10.1f}%{a['mdd_pct']:>9.1f}%")

    # ---- pre-declared directional gate ----
    s_on, s_off = cells[("short", True)], cells[("short", False)]
    l_on = cells[("long", True)]
    g1 = s_on["sharpe"] > 0
    g2 = (s_on["sharpe"] > l_on["sharpe"]) and (s_on["mdd_pct"] > l_on["mdd_pct"])  # less negative = better
    mdd_ratio = (s_off["mdd_pct"] / s_on["mdd_pct"]) if s_on["mdd_pct"] != 0 else float("nan")
    g3 = mdd_ratio >= 1.5     # "meaningfully worse" bar; real data showed ~4.6x

    print("\n=== directional gate (ALL must hold for PASS) ===")
    print(f"1. proxy short/crowd-ON profitable (Sharpe>0)      : {s_on['sharpe']:.2f}  "
          f"{'PASS' if g1 else 'FAIL'}")
    print(f"2. proxy short/crowd-ON beats long/crowd-ON        : short Sharpe {s_on['sharpe']:.2f} "
          f"MDD {s_on['mdd_pct']:.1f}%  vs  long Sharpe {l_on['sharpe']:.2f} MDD {l_on['mdd_pct']:.1f}%  "
          f"{'PASS' if g2 else 'FAIL'}")
    print(f"3. crowd-OFF MDD meaningfully worse (short, >=1.5x): ON {s_on['mdd_pct']:.1f}% "
          f"vs OFF {s_off['mdd_pct']:.1f}%  (ratio {mdd_ratio:.2f}x, real data was ~4.6x)  "
          f"{'PASS' if g3 else 'FAIL'}")

    verdict = "PASS" if (g1 and g2 and g3) else "FAIL"
    print(f"\nVALIDATION VERDICT: {verdict}")
    print("-> proceed to multi-year run" if verdict == "PASS" else
          "-> STOP: do not treat multi-year numbers on this proxy as meaningful")

    # full sweep (both fuel lookbacks, both pctiles) -> scratchpad, for completeness
    lines = [f"Layer-2b proxy validation — full sweep, window [{w_start:%Y-%m-%d} .. {w_end:%Y-%m-%d}]",
             f"{'config':<18s}{'side':<7s}{'crowd':<5s}{'sharpe':>8s}{'mdd%':>8s}"
             f"{'pnl$':>9s}{'trades':>8s}{'win%':>7s}"]
    for tf2 in ("4h", "1d"):
        for p2 in (10, 20):
            for fl2 in (24, 72):
                for side in ("short", "long"):
                    for crowd_on in (True, False):
                        r = lib.run_cell(frames, lib.SYMBOLS_6, tf2, side, crowd_on, p2, fl2,
                                          stats_start, window=(w_start, w_end))
                        lines.append(
                            f"{tf2+'-p'+str(p2)+'-f'+str(fl2):<18s}{side:<7s}"
                            f"{'ON' if crowd_on else 'OFF':<5s}{r['sharpe']:>8.2f}"
                            f"{r['mdd_pct']:>7.1f}%{r['pnl']:>9.2f}{r['trades']:>8d}{r['win_pct']:>6.0f}%")
    out = SCRATCHPAD / "cta_proxy_validate_full_sweep.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nfull sweep -> {out}")


if __name__ == "__main__":
    main()
