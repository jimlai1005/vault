"""B1-universe candidate backtest — 12-coin B0/B1 grid + 9 combo comparisons.

Motivation: owner needs to pick ~6 coins for a new B1 live instance. Existing
proxy-research universe (5 coins: BTC/ETH/SOL/DOGE/XRP) is compared against 7
new listing/liquidity-screened candidates (BNB/ADA/AVAX/LINK/BCH/LTC/DOT),
both per-coin (B0 = m=1.0 constant notional; B1 = per-coin EWMA-vol-target
sizing) and as 6/7-coin equal-weight portfolios.

Read-only reuse, NO modification of any pinned/frozen module:
  - scripts/cta_proxy_lib.py        (build_frames/shifted_signals/crowd_off/
                                      profit_factor/SYMBOLS_5 — imported as-is)
  - scripts/cta_l_stage1.py         (simulate_l/run_cell_l/build_sigma_m/
                                      make_m_fn/const_m — imported as-is;
                                      sigma_target=0.60/span=180/clip=0.25-1.0
                                      are that module's own frozen defaults,
                                      NOT re-specified here)
Config pinned to phase-2b's production cell "4h-p10-fuel24-short" (crowd_on
=True), cost = FEE_RATE(0.045%) + DEFAULT_SLIPPAGE_PER_SIDE(0.01%) = 0.055%/
side (both l1 module defaults, unchanged). Main window 2020-09-14 ->
2026-06-30, IDENTICAL to scripts/cta_l_stage1_runs.py's MAIN_WINDOW and
stats_start formula (MAIN_WINDOW[0] + CROWD_WARMUP_DAYS days, ceil('D')) —
this identity is what makes the spot-check (guard 5 below) meaningful: the
5-coin "combo_5" B0/B1 runs in this script are BYTE-FOR-BYTE the same call
cta_l_stage1_runs.py made to produce data/cache/cta_l/{b0,v1}.csv.

Per-coin window/stats_start: a coin's own EFFECTIVE window start is
max(MAIN_WINDOW[0], own_first_bar) (own_first_bar ceil'd to a UTC day); its
own stats_start is that effective start + CROWD_WARMUP_DAYS(30) days, ceil
('D') — same 30-day-crowd-warmup rule the baseline applies globally, just
evaluated per-coin instead of assuming every coin already has 30d of history
by 2020-09-14. Of the 12 coins here, only AVAX's own listing (2020-09-23,
confirmed by data/cache/cta_proxy/_pull_summary_b1_candidates.json) is AFTER
2020-09-14, so it is the only coin whose per-coin window differs from the
baseline's global one. Portfolio/combo runs (Step 3) use the GLOBAL window/
stats_start uniformly (matching the baseline exactly) — AVAX's own signal
frame simply has no rows before 2020-09-23 and its crowd signal is
warmup-gated (NaN->False) until 2020-10-23 regardless, so the natural
per-coin data boundary already prevents any premature AVAX trade even under
the global window; no special-casing needed at the portfolio level.

MDD/MAR: spec's corrected FIXED-BASE convention (see docs/superpowers/specs/
2026-07-13-cta-staged-sizing-design.md 修正案 1, and its verbatim port in
scripts/cta_l_stage1_recon_mdd.py::mdd_frac_fixed_base / cta_l_stage1_gates.py
::ann_return_frac). NOT run_cell_l's own r["mdd_pct"] field, which is the
OLD peak-relative convention and is deliberately unused here for MDD (still
read for Sharpe/PF/trades, which are convention-independent).

Read-only: only touches data/cache/cta_proxy/*.parquet (input) and writes
under data/cache/cta_b1_universe/ (new, gitignored-pattern-consistent dir)
plus the scratchpad report. No network calls, no .env* access, no orders.
data/cache/cta_l/ and cta_l2/ are read-only inputs (manifest.json + b0.csv/
v1.csv) for the spot-check only.

Usage: .venv/bin/python scripts/research_cta_b1_universe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import cta_l_stage1 as l1     # noqa: E402
import cta_proxy_lib as lib   # noqa: E402

REPO_ROOT = _SCRIPTS.parent
OUT_DIR = REPO_ROOT / "data" / "cache" / "cta_b1_universe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Config (pinned; identical to scripts/cta_l_stage1_runs.py)
# ---------------------------------------------------------------------------
TF, PCTILE, FUEL_LB, SIDE, CROWD_ON = "4h", 10, 24, "short", True
MAIN_WINDOW = (pd.Timestamp("2020-09-14"), pd.Timestamp("2026-06-30"))
STD_SLIPPAGE = l1.DEFAULT_SLIPPAGE_PER_SIDE          # 1bp
STD_FEE = l1.FEE_RATE                                # 0.045%
CROWD_WARMUP_DAYS = lib.CROWD_WARMUP_DAYS            # 30
MDD_FLOOR = 0.005                                    # spec Sec.2: max(|MDD|, 0.5%)
ANN_DAYS = 365.0

CANDIDATES_7 = {"BNBUSDT": "BNB", "ADAUSDT": "ADA", "AVAXUSDT": "AVAX",
                 "LINKUSDT": "LINK", "BCHUSDT": "BCH", "LTCUSDT": "LTC",
                 "DOTUSDT": "DOT"}
SYMBOLS_5 = lib.SYMBOLS_5                            # BTC/ETH/SOL/DOGE/XRP
SYMBOLS_12 = {**SYMBOLS_5, **CANDIDATES_7}


# ---------------------------------------------------------------------------
# Fixed-base MDD / MAR (spec 修正案 1; verbatim logic, re-derived here since
# cta_l_stage1_gates.py operates on cached CSVs, not on run_cell_l's in-memory
# daily Series -- this is a re-implementation from the SAME spec formula, not
# an import, so it is spot-checked against gates.py's own output for the
# combo_5 b0/v1 case in the guard-5 section below.)
# ---------------------------------------------------------------------------

def mdd_fixed_base(daily_pnl: pd.Series, port_base: float) -> float:
    """spec 修正案1: eq_t = 1 + cumsum(r_s), r_s = $pnl_s/port_base (fraction,
    non-compounding); MDD = min_t[eq_t - running_max(eq_t)] (base = 1, i.e.
    NOT divided by running peak)."""
    r = (daily_pnl / port_base).to_numpy(dtype=float)
    if len(r) == 0:
        return 0.0
    cr = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cr]))[1:]
    dd = cr - peak
    return float(dd.min())


def mar_fixed(daily_pnl: pd.Series, port_base: float) -> float:
    r = (daily_pnl / port_base).to_numpy(dtype=float)
    n = len(r)
    ann = float(np.sum(r) * ANN_DAYS / n) if n > 0 else 0.0
    denom = max(abs(mdd_fixed_base(daily_pnl, port_base)), MDD_FLOOR)
    return ann / denom


# ---------------------------------------------------------------------------
# Step 1: data readiness (7 candidates; baseline 5 included for reference)
# ---------------------------------------------------------------------------

def gap_report(sym: str, window_start: pd.Timestamp, window_end: pd.Timestamp) -> dict:
    """4h-bar interval check within [window_start, window_end] intersected
    with the symbol's actual cached history. Expected spacing: exactly 4h."""
    df = pd.read_parquet(lib.PCACHE / f"{sym}_4h.parquet")
    idx = pd.to_datetime(df["open_time"], unit="ms")
    full_first, full_last = idx.iloc[0], idx.iloc[-1]
    sel = idx[(idx >= window_start) & (idx <= window_end)]
    n_bars_in_window = len(sel)
    if n_bars_in_window >= 2:
        diffs = sel.diff().dropna()
        expected = pd.Timedelta(hours=4)
        bad = diffs[diffs != expected]
        gap_list = [
            {"after": str(sel.iloc[i - 1]), "before": str(sel.iloc[i]),
             "gap_hours": diffs.iloc[i - 1].total_seconds() / 3600.0}
            for i in range(1, len(sel)) if diffs.iloc[i - 1] != expected
        ]
    else:
        bad, gap_list = pd.Series(dtype="timedelta64[ns]"), []
    return {
        "symbol": sym,
        "full_history_bars": len(df),
        "full_history_first": str(full_first),
        "full_history_last": str(full_last),
        "window_start_used": str(window_start),
        "window_end_used": str(window_end),
        "bars_in_window": n_bars_in_window,
        "n_gaps": len(bad),
        "gap_detail": gap_list[:20],  # cap listing, n_gaps still gives the true count
    }


def coin_effective_window(first_bar_ts: pd.Timestamp) -> tuple[tuple[pd.Timestamp, pd.Timestamp], pd.Timestamp]:
    ws = max(MAIN_WINDOW[0], first_bar_ts.ceil("D"))
    ss = (ws + pd.Timedelta(days=CROWD_WARMUP_DAYS)).ceil("D")
    return (ws, MAIN_WINDOW[1]), ss


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    lines: list[str] = []
    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("# B1-universe candidate backtest — full detail")
    emit()
    emit(f"Config: {TF}-p{PCTILE}-fuel{FUEL_LB}-{SIDE}, crowd_on={CROWD_ON}, "
         f"cost={ (STD_FEE+STD_SLIPPAGE)*100:.4f}%/side "
         f"(fee {STD_FEE*100:.4f}% + slippage {STD_SLIPPAGE*100:.4f}%)")
    emit(f"Main window: [{MAIN_WINDOW[0]:%Y-%m-%d} .. {MAIN_WINDOW[1]:%Y-%m-%d}]")
    emit(f"B1 sigma params: target={l1.SIGMA_TARGET}, span={l1.SIGMA_SPAN}, "
         f"clip=[{l1.SIGMA_CLIP_LO},{l1.SIGMA_CLIP_HI}]")
    emit()

    # ---- Step 1: data readiness -------------------------------------------------
    emit("## Step 1 — data readiness (7 new candidates)")
    emit()
    emit("| symbol | full bars | full first | full last | bars in main window | gaps in window |")
    emit("|---|---|---|---|---|---|")
    readiness = {}
    for sym in CANDIDATES_7:
        g = gap_report(sym, MAIN_WINDOW[0], MAIN_WINDOW[1])
        readiness[sym] = g
        emit(f"| {sym} | {g['full_history_bars']} | {g['full_history_first']} | "
             f"{g['full_history_last']} | {g['bars_in_window']} | {g['n_gaps']} |")
    emit()
    any_gaps = {k: v for k, v in readiness.items() if v["n_gaps"] > 0}
    if any_gaps:
        emit("Gap detail (symbols with n_gaps > 0):")
        for sym, g in any_gaps.items():
            emit(f"- {sym}: {g['n_gaps']} gaps, first 20 shown:")
            for d in g["gap_detail"]:
                emit(f"    {d['after']} -> {d['before']}  ({d['gap_hours']:.2f}h)")
    else:
        emit("No gaps (n_gaps == 0 for all 7 candidates): 4h bar spacing is exactly "
             "4 hours throughout the main window for every candidate. Usable as-is.")
    emit()

    # ---- build frames for all 12 coins ------------------------------------------
    emit("## Building frames (12-coin universe)")
    frames, cov_start, cov_end = lib.build_frames(SYMBOLS_12, fuel_lookbacks=(FUEL_LB,))
    emit(f"raw frame coverage (intersection, pre-window-slice): "
         f"[{cov_start:%Y-%m-%d} .. {cov_end:%Y-%m-%d}]")
    emit()

    # per-coin first-bar / effective window (report for all 12, all 4h frames)
    first_bar = {coin: frames[(coin, TF)].index.min() for coin in SYMBOLS_12.values()}
    coin_win: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    coin_stats_start: dict[str, pd.Timestamp] = {}
    for sym, coin in SYMBOLS_12.items():
        w, ss = coin_effective_window(first_bar[coin])
        coin_win[coin] = w
        coin_stats_start[coin] = ss
    emit("Per-coin effective window (own listing later than main window start "
         "-> own start + 30d crowd-warmup; else the global main window):")
    for sym, coin in SYMBOLS_12.items():
        w = coin_win[coin]
        tag = "" if w[0] == MAIN_WINDOW[0] else "  <- adjusted (later listing)"
        emit(f"- {coin}: window=[{w[0]:%Y-%m-%d}..{w[1]:%Y-%m-%d}] "
             f"stats_start={coin_stats_start[coin]:%Y-%m-%d}{tag}")
    emit()

    # ---- B1 sigma/m table for all 12 coins (module defaults; NOT re-specified) --
    _, m_by_coin_v1 = l1.build_sigma_m(frames, SYMBOLS_12, TF)
    m_fn_v1 = l1.make_m_fn(m_by_coin_v1)

    # ---- Step 2: per-coin B0/B1 --------------------------------------------------
    emit("## Step 2 — per-coin B0 / B1 (fixed $100/coin notional base)")
    emit()
    per_coin_rows = []
    for sym, coin in SYMBOLS_12.items():
        w, ss = coin_win[coin], coin_stats_start[coin]
        for variant, m_fn in (("B0", l1.const_m), ("B1", m_fn_v1)):
            r = l1.run_cell_l(frames, {sym: coin}, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                               ss, window=w, m_fn=m_fn,
                               slippage_per_side=STD_SLIPPAGE, fee_rate=STD_FEE)
            d = r["daily"].loc[ss:]
            mdd = mdd_fixed_base(d, r["port_base"])
            mar = mar_fixed(d, r["port_base"])
            row = {
                "coin": coin, "variant": variant, "pnl": r["pnl"], "sharpe": r["sharpe"],
                "mdd_fixed_pct": mdd * 100.0, "mar": mar, "pf": r["pf"],
                "trades": r["trades"], "win_pct": r["win_pct"],
            }
            if variant == "B1":
                tr = [t for t in r["all_trades"] if t["entry_time"] >= ss]
                ms = np.array([t["m"] for t in tr], dtype=float)
                row["m_median"] = float(np.median(ms)) if len(ms) else float("nan")
                row["m_pct_at_1"] = float(np.mean(ms >= 0.999999)) * 100.0 if len(ms) else 0.0
            per_coin_rows.append(row)

    emit("| coin | variant | pnl($) | sharpe | MDD_fixed(%) | MAR | PF | trades | win% | m_median | m%=1.0 |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|")
    for row in per_coin_rows:
        m_med = f"{row.get('m_median', float('nan')):.3f}" if "m_median" in row else "-"
        m_pct = f"{row.get('m_pct_at_1', float('nan')):.1f}" if "m_pct_at_1" in row else "-"
        emit(f"| {row['coin']} | {row['variant']} | {row['pnl']:.2f} | {row['sharpe']:.3f} | "
             f"{row['mdd_fixed_pct']:.3f} | {row['mar']:.3f} | {row['pf']:.3f} | "
             f"{row['trades']} | {row['win_pct']:.1f} | {m_med} | {m_pct} |")
    emit()

    # ---- Step 3: portfolio combos (B1) -------------------------------------------
    emit("## Step 3 — portfolio combos (equal-weight $100/coin, B1 sizing unless noted)")
    emit()
    global_stats_start = (MAIN_WINDOW[0] + pd.Timedelta(days=CROWD_WARMUP_DAYS)).ceil("D")
    emit(f"Global stats_start (matches cta_l_stage1_runs.py exactly): {global_stats_start:%Y-%m-%d}")
    emit()

    combos: dict[str, dict] = {"combo_5_baseline": SYMBOLS_5}
    for sym, coin in CANDIDATES_7.items():
        combos[f"combo_5_plus_{coin}"] = {**SYMBOLS_5, sym: coin}
    combos["combo_7_5plusBNBplusADA"] = {**SYMBOLS_5, "BNBUSDT": "BNB", "ADAUSDT": "ADA"}

    combo_rows = []
    combo_raw = {}
    for name, symdict in combos.items():
        variants = [("B1", m_fn_v1)]
        if name == "combo_5_baseline":
            variants = [("B0", l1.const_m), ("B1", m_fn_v1)]
        for variant, m_fn in variants:
            r = l1.run_cell_l(frames, symdict, TF, SIDE, CROWD_ON, PCTILE, FUEL_LB,
                               global_stats_start, window=MAIN_WINDOW, m_fn=m_fn,
                               slippage_per_side=STD_SLIPPAGE, fee_rate=STD_FEE)
            d = r["daily"].loc[global_stats_start:]
            mdd = mdd_fixed_base(d, r["port_base"])
            mar = mar_fixed(d, r["port_base"])
            combo_raw[(name, variant)] = r
            combo_rows.append({
                "combo": name, "n_coins": len(symdict), "coins": ",".join(symdict.values()),
                "variant": variant, "pnl": r["pnl"], "sharpe": r["sharpe"],
                "mdd_fixed_pct": mdd * 100.0, "mar": mar, "pf": r["pf"], "trades": r["trades"],
            })

    emit("| combo | n_coins | coins | variant | pnl($) | sharpe | MDD_fixed(%) | MAR | PF | trades |")
    emit("|---|---|---|---|---|---|---|---|---|---|")
    for row in combo_rows:
        emit(f"| {row['combo']} | {row['n_coins']} | {row['coins']} | {row['variant']} | "
             f"{row['pnl']:.2f} | {row['sharpe']:.3f} | {row['mdd_fixed_pct']:.3f} | "
             f"{row['mar']:.3f} | {row['pf']:.3f} | {row['trades']} |")
    emit()

    # ---- Step 4: spot-check against data/cache/cta_l/manifest.json --------------
    emit("## Step 4 — spot-check vs data/cache/cta_l/ (pre-existing, validated pipeline)")
    emit()
    manifest_path = REPO_ROOT / "data" / "cache" / "cta_l" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    spot_ok = True
    for name, my_variant in (("b0", "B0"), ("v1", "B1")):
        mine = combo_raw[("combo_5_baseline", my_variant)]
        ref = manifest[name]["summary"]
        pnl_diff = abs(mine["pnl"] - ref["pnl"])
        trades_match = mine["trades"] == ref["trades_post_stats_start"]
        ok = pnl_diff < 1e-6 and trades_match
        spot_ok = spot_ok and ok
        emit(f"- {name}: mine pnl={mine['pnl']:.10f} trades={mine['trades']}  |  "
             f"manifest pnl={ref['pnl']:.10f} trades={ref['trades_post_stats_start']}  |  "
             f"pnl_diff={pnl_diff:.2e}  MATCH={ok}")
    emit()
    emit(f"**Spot-check overall: {'PASS' if spot_ok else 'FAIL'}**")
    emit()

    # ---- write outputs ------------------------------------------------------------
    detail_path = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                        "083f97aa-8ce0-469a-b855-cbd455501c26/scratchpad/"
                        "b1_universe_backtest.md")
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text("\n".join(lines) + "\n")
    emit(f"\nFull detail written to: {detail_path}")

    # also cache raw per-coin/combo rows as csv for traceability
    pd.DataFrame(per_coin_rows).to_csv(OUT_DIR / "per_coin_b0_b1.csv", index=False)
    pd.DataFrame(combo_rows).to_csv(OUT_DIR / "combos.csv", index=False)
    for sym, g in readiness.items():
        pass
    (OUT_DIR / "readiness.json").write_text(json.dumps(readiness, indent=2, default=str))

    return 0 if spot_ok else 1


if __name__ == "__main__":
    sys.exit(main())
