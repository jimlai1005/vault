"""Momentum vol-target sizing retest (sub-project J, item A).

Pre-registered protocol: docs/superpowers/specs/2026-07-12-momentum-voltarget-retest.md
Builds on the audit's verified-no-lookahead reproduction code:
reports/audit/repro_momentum_sizing_funding.py (vol-target overlay + funding PnL
integration; signal/risk functions reused unmodified from hlvault.momentum, per
that script's own docstring and CLAUDE.md #5 "one implementation").

Changes vs. the audit repro:
  - Pinned data window (2024-07-02T00:00:00Z -> 2026-07-02T00:00:00Z, hardcoded
    ms constants below) instead of "N days back from time.time()" -- the same
    window the original verdict (reports/momentum-backtest-verdict.md) used.
    Audit Finding 3 flagged the non-pinned window as a reproducibility bug;
    this protocol fixes it.
  - Adds a slippage cost term (1bp/side) on top of the original 5bp/side fee
    (spec section 2: "原判漏項，從嚴" -- the original backtest modeled zero
    slippage).
  - Adds split-half consistency (G-A2) and a Deflated Sharpe Ratio gate (G-A3,
    Bailey & Lopez de Prado 2012 PSR) across 8 pre-specified trials, and a
    cost x1.5 robustness run (G-A4). None of these existed in the shipped
    backtest or the audit repro.

Read-only: only hits HL's public candleSnapshot / fundingHistory endpoints via
hlvault.prices / hlvault.carry.funding (both unmodified, both already routed
through the shared resilient_read boundary). Does not touch src/hlvault/ or
any .env* file. Writes only to data/momentum_retest/ (gitignored) and
reports/momentum-voltarget-retest-verdict.md (DRAFT -- not a final verdict).

Run:
    .venv/bin/python scripts/research_momentum_voltarget.py
(several minutes: funding history is paginated per-coin over ~2 years of
hourly data, same cost the audit repro already paid.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, "/Users/jim/projects/vault/src")

from hlvault.momentum import config as cfg
from hlvault.momentum.backtest import run_backtest
from hlvault.momentum.risk import risk_budget_per_coin, target_position_notional
from hlvault.momentum.signals import composite_score, daily_log_returns, position_signal
from hlvault.prices import get_candles
from hlvault.carry.funding import _fetch_funding

# ---- spec §2 pinned window: 2024-07-02T00:00:00Z -> 2026-07-02T00:00:00Z ----
# Hardcoded per protocol -- NOT derived from time.time() (that was audit
# Finding 3: "run_momentum_backtest.py:26-27 ... produces different numbers
# a few days later with no record of the discrepancy").
START_MS = 1719878400000
END_MS = 1782950400000

CAPITAL = 10_000.0
FEE_RATE = 0.0005          # 5bps/side, unchanged from the original verdict (not lowered)
SLIP_RATE = 0.0001         # 1bp/side, NEW: audit Finding 6 (original backtest modeled zero slippage)
COST_RATE = FEE_RATE + SLIP_RATE                    # primary / sensitivity basis
COST_RATE_X1_5 = FEE_RATE * 1.5 + SLIP_RATE * 1.5   # G-A4 robustness (both legs x1.5)

ANN_FACTOR = 365 ** 0.5    # matches hlvault.momentum.backtest.run_backtest's own convention
SPLIT_DATE = pd.Timestamp("2025-07-02")
EULER_MASCHERONI = 0.5772156649
N_TRIALS = 8

OUT_DIR = Path("/Users/jim/projects/vault/data/momentum_retest")
REPORT_PATH = Path("/Users/jim/projects/vault/reports/momentum-voltarget-retest-verdict.md")


def load_panel() -> pd.DataFrame:
    closes = {}
    for coin in cfg.COIN_UNIVERSE:
        df = get_candles(coin, "1d", START_MS, END_MS)
        if len(df) < 150:
            print(f"skip {coin}: {len(df)} days")
            continue
        closes[coin] = df.set_index("day")["c"]
    panel = pd.DataFrame(closes).dropna(how="all")
    return panel


def get_funding_panel(closes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Real HL fundingHistory, paginated (500-row/response cap -- HL's
    fundingHistory endpoint truncates a 2-year pull without this, per
    repro_momentum_sizing_funding.py's own note), for every coin in `closes`.

    Returns (rate_panel, coverage_mask): rate_panel has missing days filled
    with 0.0 (spec §4: gap days counted as 0 funding PnL); coverage_mask is
    True where at least one funding sample existed that day, so callers can
    still distinguish a real gap from a genuine zero rate."""
    coins = list(closes.columns)
    start_ms = int(closes.index.min().timestamp() * 1000)
    end_ms = int(closes.index.max().timestamp() * 1000) + 86400_000
    funding_daily = {}
    for c in coins:
        all_rows, cursor = [], start_ms
        while cursor < end_ms:
            rows = _fetch_funding(c, cursor)
            if not rows:
                break
            all_rows.extend(rows)
            last_t = int(rows[-1]["time"])
            if last_t <= cursor:
                break
            cursor = last_t + 1
            if len(rows) < 500:
                break  # short page = end of available history
        if not all_rows:
            funding_daily[c] = pd.Series(dtype=float)
            continue
        df = pd.DataFrame(all_rows).drop_duplicates(subset=["time"])
        df["day"] = pd.to_datetime(df["time"].astype("int64"), unit="ms").dt.normalize()
        df["fundingRate"] = pd.to_numeric(df["fundingRate"])
        daily = df.groupby("day")["fundingRate"].sum()
        print(f"  funding rows for {c}: {len(df)} ({df['day'].min().date()} -> {df['day'].max().date()})")
        funding_daily[c] = daily
    rate_panel = pd.DataFrame(funding_daily).reindex(closes.index)
    coverage = rate_panel.notna()
    rate_panel = rate_panel.fillna(0.0)
    return rate_panel, coverage


def report_funding_gaps(closes: pd.DataFrame, coverage: pd.DataFrame) -> dict:
    """Gap days counted only over days the coin actually had a tradeable
    price (pre-listing days aren't real funding gaps -- there was nothing to
    hold, so nothing to omit)."""
    gaps = {}
    for c in closes.columns:
        tradeable = closes[c].notna()
        gaps[c] = int((tradeable & ~coverage[c]).sum())
    return gaps


class BTResult:
    __slots__ = ("equity_curve", "daily_returns", "detail", "sharpe", "max_drawdown", "total_return")


def vol_target_backtest(closes, returns, signals, funding_panel, *, capital,
                        max_coin_allocation_pct, vol_lookback, target_ann_vol,
                        max_gross_leverage, cost_rate, include_funding) -> BTResult:
    """Causal (day-t sizing uses only realized vol/returns up to t-1) portfolio
    vol-target overlay -- structurally unchanged from
    reports/audit/repro_momentum_sizing_funding.py's vol_target_with_funding
    (already verified no-lookahead by a fresh auditor), generalized with a
    cost_rate parameter (fee+slip vs. fee-only) and an include_funding toggle
    so one function serves every trial in this script. The one exception is
    the flat-3x "as shipped" trial, which calls the unmodified
    hlvault.momentum.backtest.run_backtest directly (see main())."""
    coins = list(closes.columns)
    trailing_vol = returns.rolling(vol_lookback).std(ddof=1)

    target_daily_vol = target_ann_vol / (365 ** 0.5)
    equity = capital
    equity_curve = []
    prev_notional = {c: 0.0 for c in coins}
    strat_ret_hist = []
    detail_rows = []
    scale = 1.0

    for t in closes.index:
        vol_by_coin = {
            c: float(trailing_vol.loc[t, c]) for c in coins
            if pd.notna(trailing_vol.loc[t, c]) and trailing_vol.loc[t, c] > 0
        }
        if not vol_by_coin:
            equity_curve.append(equity)
            strat_ret_hist.append(0.0)
            detail_rows.append((t, 0.0, equity, 0.0, 0.0, 0.0))
            continue
        budgets = risk_budget_per_coin(vol_by_coin, equity, max_coin_allocation_pct)
        raw_target = {}
        for c in vol_by_coin:
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            raw_target[c] = target_position_notional(sig, budgets.get(c, 0.0), 1.0)  # base leverage=1
        scaled_target = {c: v * scale for c, v in raw_target.items()}
        gross = sum(abs(v) for v in scaled_target.values())
        cap_notional = max_gross_leverage * equity
        if gross > cap_notional and gross > 0:
            shrink = cap_notional / gross
            scaled_target = {c: v * shrink for c, v in scaled_target.items()}

        gross_pnl = 0.0
        cost = 0.0
        funding_pnl = 0.0
        for c in vol_by_coin:
            target = scaled_target.get(c, 0.0)
            ret = float(returns.loc[t, c]) if pd.notna(returns.loc[t, c]) else 0.0
            gross_pnl += prev_notional[c] * ret
            cost += abs(target - prev_notional[c]) * cost_rate
            if include_funding:
                frate = float(funding_panel.loc[t, c]) if t in funding_panel.index else 0.0
                funding_pnl -= prev_notional[c] * frate  # HL: positive rate -> longs pay shorts
            prev_notional[c] = target
        day_pnl = gross_pnl - cost + funding_pnl
        equity_prev = equity
        equity += day_pnl
        equity_curve.append(equity)
        day_ret = day_pnl / equity_prev if equity_prev else 0.0
        gross_ret = gross_pnl / equity_prev if equity_prev else 0.0
        strat_ret_hist.append(day_ret)
        detail_rows.append((t, day_ret, equity, gross_ret, funding_pnl, cost))

        recent = strat_ret_hist[-vol_lookback:]
        if len(recent) >= vol_lookback:
            realized = float(np.std(recent, ddof=1))
            if realized > 0:
                scale = min(max(target_daily_vol / realized, 0.0), max_gross_leverage)

    eq = pd.Series(equity_curve, index=closes.index)
    daily_ret = eq.pct_change().dropna()
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min()) if len(eq) else 0.0
    sharpe = 0.0
    if len(daily_ret) and daily_ret.std(ddof=1) > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * ANN_FACTOR)
    total_return = float(eq.iloc[-1] / capital - 1.0) if len(eq) else 0.0

    r = BTResult()
    r.equity_curve = eq
    r.daily_returns = daily_ret
    r.detail = pd.DataFrame(
        detail_rows, columns=["date", "ret", "equity", "gross_ret", "funding_pnl", "cost"]
    ).set_index("date")
    r.sharpe = sharpe
    r.max_drawdown = max_dd
    r.total_return = total_return
    return r


def daily_sr(returns: pd.Series) -> float:
    """Unannualized daily Sharpe: mean(r)/std(r, ddof=1). Spec G-A3 formula."""
    if len(returns) < 2 or returns.std(ddof=1) == 0:
        return 0.0
    return float(returns.mean() / returns.std(ddof=1))


def half_stats(eq: pd.Series, daily_ret: pd.Series, mask) -> tuple[float, float]:
    """Sharpe (annualized) and MDD for a half-window slice, each computed
    from that half's own return series and its own running peak (spec §4:
    "各半自己的起點起算" -- no drawdown carried over from before the split)."""
    ret_half = daily_ret[mask(daily_ret.index)]
    sharpe = 0.0
    if len(ret_half) > 1 and ret_half.std(ddof=1) > 0:
        sharpe = float(ret_half.mean() / ret_half.std(ddof=1) * ANN_FACTOR)
    eq_half = eq[mask(eq.index)]
    running_max = eq_half.cummax()
    mdd = float(((eq_half - running_max) / running_max).min()) if len(eq_half) else 0.0
    return sharpe, mdd


def main():
    print(f"pinned window: {pd.Timestamp(START_MS, unit='ms')} -> {pd.Timestamp(END_MS, unit='ms')}")
    panel = load_panel()
    print(f"panel: {panel.shape[0]} days x {panel.shape[1]} coins "
         f"({panel.index.min().date()} -> {panel.index.max().date()})")

    print("\nfetching funding history (paginated)...")
    funding_panel, coverage = get_funding_panel(panel)
    gaps = report_funding_gaps(panel, coverage)
    print("funding gap days (tradeable days with no funding sample, filled 0):")
    for c, g in gaps.items():
        print(f"  {c}: {g} days")
    total_gap_days = sum(gaps.values())

    coins = list(panel.columns)
    returns = pd.DataFrame({c: daily_log_returns(panel[c]) for c in coins}).reindex(panel.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(panel.index)
    signals = pd.DataFrame({c: position_signal(scores[c], cfg.ENTRY_THRESHOLD) for c in coins}).reindex(panel.index)

    def run_vt(target, lookback, cost_rate, include_funding=True, max_gross_leverage=3.0):
        return vol_target_backtest(
            panel, returns, signals, funding_panel,
            capital=CAPITAL, max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
            vol_lookback=lookback, target_ann_vol=target,
            max_gross_leverage=max_gross_leverage, cost_rate=cost_rate,
            include_funding=include_funding,
        )

    print("\n--- trial 1/8: flat-3x, as originally shipped/judged (no funding, fee-only, unmodified run_backtest) ---")
    flat3x = run_backtest(panel, capital=CAPITAL,
                          max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                          max_leverage=cfg.LEVERAGE, entry_threshold=cfg.ENTRY_THRESHOLD,
                          vol_lookback=cfg.VOL_LOOKBACK_DAYS)
    print(f"  sharpe={flat3x.sharpe:.3f} total_ret={flat3x.total_return:.1%} mdd={flat3x.max_drawdown:.1%}")

    print("\n--- primary config: target=20%, lookback=20d, lev cap=3x, cost=fee+slip, funding ---")
    primary = run_vt(0.20, 20, COST_RATE)
    print(f"  sharpe={primary.sharpe:.3f} total_ret={primary.total_return:.1%} mdd={primary.max_drawdown:.1%}")

    print("\n--- audit variants (rerun on pinned window, primary's cost model, DSR trial pool) ---")
    audit_variants = {
        "vt20_lb20_funding": primary,  # == primary; listed per spec's explicit duplicate-allowance
        "vt15_lb20_funding": run_vt(0.15, 20, COST_RATE),
        "vt25_lb20_funding": run_vt(0.25, 20, COST_RATE),
        "vt30_lb20_funding": run_vt(0.30, 20, COST_RATE),
        "vt20_lb10_funding": run_vt(0.20, 10, COST_RATE),
        "vt20_lb40_funding": run_vt(0.20, 40, COST_RATE),
    }
    for label, res in audit_variants.items():
        print(f"  {label:22s} sharpe={res.sharpe:6.3f} total_ret={res.total_return:8.1%} mdd={res.max_drawdown:8.1%}")

    print("\n--- sensitivity report (target x lookback, report-only, not gated) ---")
    sensitivity = {
        (0.15, 20): audit_variants["vt15_lb20_funding"],
        (0.15, 40): run_vt(0.15, 40, COST_RATE),
        (0.25, 20): audit_variants["vt25_lb20_funding"],
        (0.25, 40): run_vt(0.25, 40, COST_RATE),
    }
    for (tv, lb), res in sensitivity.items():
        print(f"  target={tv:.0%} lookback={lb}d  sharpe={res.sharpe:6.3f} total_ret={res.total_return:8.1%} mdd={res.max_drawdown:8.1%}")

    print("\n--- G-A4: cost x1.5 robustness (primary params, fee+slip x1.5) ---")
    cost_x15 = run_vt(0.20, 20, COST_RATE_X1_5)
    print(f"  sharpe={cost_x15.sharpe:.3f} total_ret={cost_x15.total_return:.1%} mdd={cost_x15.max_drawdown:.1%}")

    # ---- G-A2: split-half ----
    print("\n--- G-A2: split-half (boundary 2025-07-02) ---")
    first_sharpe, first_mdd = half_stats(primary.equity_curve, primary.daily_returns,
                                          lambda idx: idx < SPLIT_DATE)
    second_sharpe, second_mdd = half_stats(primary.equity_curve, primary.daily_returns,
                                           lambda idx: idx >= SPLIT_DATE)
    print(f"  first half:  sharpe={first_sharpe:.3f} mdd={first_mdd:.1%}")
    print(f"  second half: sharpe={second_sharpe:.3f} mdd={second_mdd:.1%}")

    # ---- G-A3: Deflated Sharpe Ratio ----
    print("\n--- G-A3: Deflated Sharpe Ratio ---")
    sr_list = [
        daily_sr(flat3x.daily_returns),
        daily_sr(audit_variants["vt20_lb20_funding"].daily_returns),
        daily_sr(audit_variants["vt15_lb20_funding"].daily_returns),
        daily_sr(audit_variants["vt25_lb20_funding"].daily_returns),
        daily_sr(audit_variants["vt30_lb20_funding"].daily_returns),
        daily_sr(audit_variants["vt20_lb10_funding"].daily_returns),
        daily_sr(audit_variants["vt20_lb40_funding"].daily_returns),
        daily_sr(primary.daily_returns),
    ]
    assert len(sr_list) == N_TRIALS
    V = float(np.var(sr_list, ddof=1))
    z1 = float(stats.norm.ppf(1 - 1.0 / N_TRIALS))
    z2 = float(stats.norm.ppf(1 - 1.0 / (N_TRIALS * np.e)))
    SR_star = (V ** 0.5) * ((1 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)

    r = primary.daily_returns
    n = len(r)
    SR = daily_sr(r)
    g3 = float(stats.skew(r, bias=True))
    g4 = float(stats.kurtosis(r, fisher=False, bias=True))
    psr_num = (SR - SR_star) * (n - 1) ** 0.5
    psr_den = (1 - g3 * SR + ((g4 - 1) / 4) * SR ** 2) ** 0.5
    PSR = float(stats.norm.cdf(psr_num / psr_den))

    print(f"  SR list (8 trials, daily unannualized): {[round(s, 5) for s in sr_list]}")
    print(f"  V (var of 8 SRs, ddof=1) = {V:.8f}")
    print(f"  z(1-1/N)={z1:.5f}  z(1-1/(N*e))={z2:.5f}")
    print(f"  SR* = {SR_star:.6f}")
    print(f"  primary SR (daily) = {SR:.6f}  n={n}")
    print(f"  gamma3 (skew) = {g3:.6f}  gamma4 (kurtosis, non-excess) = {g4:.6f}")
    print(f"  PSR = {PSR:.6f}")

    # ---- gates ----
    ga1 = primary.sharpe >= 0.5 and primary.total_return > 0 and abs(primary.max_drawdown) <= 0.20
    ga2 = (first_sharpe > 0 and second_sharpe > 0
          and abs(first_mdd) <= 0.25 and abs(second_mdd) <= 0.25)
    ga3 = PSR >= 0.95
    ga4 = cost_x15.sharpe >= 0.4 and abs(cost_x15.max_drawdown) <= 0.22

    print("\n=== GATES ===")
    print(f"G-A1 (full-window):  {'PASS' if ga1 else 'FAIL'}  sharpe={primary.sharpe:.3f} total_ret={primary.total_return:.1%} mdd={primary.max_drawdown:.1%}")
    print(f"G-A2 (split-half):   {'PASS' if ga2 else 'FAIL'}  first(sharpe={first_sharpe:.3f}, mdd={first_mdd:.1%}) second(sharpe={second_sharpe:.3f}, mdd={second_mdd:.1%})")
    print(f"G-A3 (DSR/PSR>=0.95):{'PASS' if ga3 else 'FAIL'}  PSR={PSR:.4f}")
    print(f"G-A4 (cost x1.5):    {'PASS' if ga4 else 'FAIL'}  sharpe={cost_x15.sharpe:.3f} mdd={cost_x15.max_drawdown:.1%}")
    all_pass = ga1 and ga2 and ga3 and ga4
    print(f"\noverall: {'conditional GO' if all_pass else 'NO-GO'}")

    # ---- write CSVs ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    primary.detail.to_csv(OUT_DIR / "primary_daily_returns.csv")
    # G-A4 leg gets its own csv so the cost-x1.5 gate is independently verifiable
    # from disk, same columns as primary.
    cost_x15.detail.to_csv(OUT_DIR / "primary_cost_x15_daily_returns.csv")
    sens_files = {}
    for (tv, lb), res in sensitivity.items():
        fname = f"sensitivity_target{int(round(tv*100))}_lb{lb}d_daily_returns.csv"
        res.detail.to_csv(OUT_DIR / fname)
        sens_files[(tv, lb)] = fname
    print(f"\ncsv written to {OUT_DIR} ({2 + len(sens_files)} files, {len(primary.detail)} rows each for the primary set)")

    # ---- write draft verdict report ----
    write_report(
        panel=panel, gaps=gaps, total_gap_days=total_gap_days,
        flat3x=flat3x, primary=primary, audit_variants=audit_variants,
        sensitivity=sensitivity, cost_x15=cost_x15,
        first_sharpe=first_sharpe, first_mdd=first_mdd,
        second_sharpe=second_sharpe, second_mdd=second_mdd,
        sr_list=sr_list, V=V, z1=z1, z2=z2, SR_star=SR_star, SR=SR, n=n,
        g3=g3, g4=g4, PSR=PSR,
        ga1=ga1, ga2=ga2, ga3=ga3, ga4=ga4, all_pass=all_pass,
        sens_files=sens_files,
    )
    print(f"report draft written to {REPORT_PATH}")


def write_report(*, panel, gaps, total_gap_days, flat3x, primary, audit_variants,
                 sensitivity, cost_x15, first_sharpe, first_mdd, second_sharpe,
                 second_mdd, sr_list, V, z1, z2, SR_star, SR, n, g3, g4, PSR,
                 ga1, ga2, ga3, ga4, all_pass, sens_files):
    lines = []
    lines.append("# Momentum Vol-Target Retest Verdict — DRAFT")
    lines.append("")
    lines.append("**狀態：DRAFT（未經 fresh verifier / opus 二審，不得直接作為上線依據——見協議 §6）**")
    lines.append("")
    lines.append("依據：`docs/superpowers/specs/2026-07-12-momentum-voltarget-retest.md`；"
                 "基底碼：`reports/audit/repro_momentum_sizing_funding.py`；"
                 "腳本：`scripts/research_momentum_voltarget.py`")
    lines.append("")
    lines.append(f"**資料窗（釘死）：** {panel.index.min().date()} -> {panel.index.max().date()} "
                 f"({panel.shape[0]} 天 x {panel.shape[1]} 幣：{', '.join(panel.columns)})")
    lines.append(f"**成本模型：** fee {FEE_RATE*1e4:.1f}bps/side + slip {SLIP_RATE*1e4:.1f}bps/side "
                 f"= {COST_RATE*1e4:.1f}bps/side（單邊，換手時計）；G-A4 用 x1.5 = {COST_RATE_X1_5*1e4:.2f}bps/side")
    lines.append("**funding 缺洞天數**（有價格但無 funding 樣本的可交易日，缺洞以 0 計入）：" +
                "；".join(f"{c}={g}" for c, g in gaps.items()) + f"；合計 {total_gap_days} 天")
    lines.append("")

    lines.append("## Gates 判定表")
    lines.append("")
    lines.append("| Gate | 判準 | 結果 | 數字 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| G-A1 | Sharpe>=0.5 且 總報酬>0 且 MDD<=20% | {'PASS' if ga1 else 'FAIL'} | "
                 f"sharpe={primary.sharpe:.3f}, total_ret={primary.total_return:.1%}, mdd={primary.max_drawdown:.1%} |")
    lines.append(f"| G-A2 | split-half 各半 sharpe>0 且 mdd<=25% | {'PASS' if ga2 else 'FAIL'} | "
                 f"前半 sharpe={first_sharpe:.3f} mdd={first_mdd:.1%}；後半 sharpe={second_sharpe:.3f} mdd={second_mdd:.1%} |")
    lines.append(f"| G-A3 | PSR>=0.95（DSR） | {'PASS' if ga3 else 'FAIL'} | PSR={PSR:.4f}, SR={SR:.6f}, SR*={SR_star:.6f} |")
    lines.append(f"| G-A4 | 成本x1.5：sharpe>=0.4 且 mdd<=22% | {'PASS' if ga4 else 'FAIL'} | "
                 f"sharpe={cost_x15.sharpe:.3f}, mdd={cost_x15.max_drawdown:.1%} |")
    lines.append("")
    lines.append(f"**綜合判定：{'conditional GO（四關全過）' if all_pass else 'NO-GO（至少一關不過，本線收檔，不再有下一輪 sizing 變體）'}**")
    lines.append("")

    lines.append("## G-A1 主配置全窗數字")
    lines.append("")
    lines.append(f"target=20%, lookback=20d, 槓桿上限=3x, entry_threshold={cfg.ENTRY_THRESHOLD}, "
                 f"universe={cfg.COIN_UNIVERSE}")
    lines.append("")
    lines.append(f"- Sharpe (ann., x{ANN_FACTOR:.4f}) = {primary.sharpe:.4f}")
    lines.append(f"- 總報酬 = {primary.total_return:.2%}")
    lines.append(f"- MDD = {primary.max_drawdown:.2%}")
    lines.append("")
    lines.append("對照：原判 flat-3x（同一釘死窗，backtest.py 未改動、無 funding）：")
    lines.append(f"- Sharpe = {flat3x.sharpe:.4f}, 總報酬 = {flat3x.total_return:.2%}, MDD = {flat3x.max_drawdown:.2%}")
    lines.append("")

    lines.append("## 敏感度組（僅呈報，不參與判定）")
    lines.append("")
    lines.append("| target | lookback | Sharpe | 總報酬 | MDD | csv |")
    lines.append("|---|---|---:|---:|---:|---|")
    for (tv, lb), res in sensitivity.items():
        lines.append(f"| {tv:.0%} | {lb}d | {res.sharpe:.3f} | {res.total_return:.1%} | {res.max_drawdown:.1%} | `{sens_files[(tv, lb)]}` |")
    lines.append("")

    lines.append("## Split-half（G-A2）")
    lines.append("")
    lines.append("| 半段 | 起訖 | Sharpe (ann.) | MDD（各半自己起點起算） |")
    lines.append("|---|---|---:|---:|")
    lines.append(f"| 前半 | {panel.index.min().date()} -> {(SPLIT_DATE - pd.Timedelta(days=1)).date()} | {first_sharpe:.3f} | {first_mdd:.1%} |")
    lines.append(f"| 後半 | {SPLIT_DATE.date()} -> {panel.index.max().date()} | {second_sharpe:.3f} | {second_mdd:.1%} |")
    lines.append("")

    lines.append("## DSR 中間量（G-A3）")
    lines.append("")
    lines.append("8 個試驗（日頻、未年化 SR = mean(r)/std(r, ddof=1)）：")
    lines.append("")
    lines.append("| # | 試驗 | SR (daily) |")
    lines.append("|---|---|---:|")
    trial_labels = ["原判 flat-3x（無 funding）", "vt20_lb20+funding（=主配置）", "vt15_lb20+funding",
                    "vt25_lb20+funding", "vt30_lb20+funding", "vt20_lb10+funding",
                    "vt20_lb40+funding", "主配置（重複列入）"]
    for i, (label, s) in enumerate(zip(trial_labels, sr_list), 1):
        lines.append(f"| {i} | {label} | {s:.6f} |")
    lines.append("")
    lines.append(f"- V = var(8 個 SR, ddof=1) = {V:.8f}")
    lines.append(f"- N = 8, γ (Euler-Mascheroni) = {EULER_MASCHERONI}")
    lines.append(f"- z(1-1/N) = {z1:.6f}, z(1-1/(N·e)) = {z2:.6f}")
    lines.append(f"- SR* = sqrt(V) x [(1-γ)z(1-1/N) + γ·z(1-1/(N·e))] = {SR_star:.6f}")
    lines.append(f"- 主配置日報酬：n = {n}, SR = {SR:.6f}")
    lines.append(f"- γ3（偏度，主配置日報酬）= {g3:.6f}")
    lines.append(f"- γ4（峰度，non-excess，主配置日報酬）= {g4:.6f}")
    lines.append(f"- PSR = Φ((SR-SR*)·sqrt(n-1) / sqrt(1-γ3·SR+((γ4-1)/4)·SR²)) = {PSR:.6f}")
    lines.append(f"- **判準 PSR>=0.95：{'PASS' if ga3 else 'FAIL'}**")
    lines.append("")

    lines.append("## G-A4 成本穩健性")
    lines.append("")
    lines.append(f"成本 x1.5（fee {FEE_RATE*1.5*1e4:.3f}bps + slip {SLIP_RATE*1.5*1e4:.3f}bps = {COST_RATE_X1_5*1e4:.3f}bps/side）：")
    lines.append(f"Sharpe = {cost_x15.sharpe:.3f}, 總報酬 = {cost_x15.total_return:.1%}, MDD = {cost_x15.max_drawdown:.1%}")
    lines.append("")

    lines.append("## 誠實條款")
    lines.append("")
    lines.append("- 本重測與原判/審計同窗，不構成樣本外證據；真 OOS 見協議 §5（paper/dry-run ≥4週）。")
    lines.append("- funding 缺洞期以 0 計入（見上方缺洞天數統計），非零缺洞代表該期間的 funding PnL 被低估為 0（低估方向依當期真實費率正負而定，未逐一定向核實）。")
    lines.append("- DSR 的試驗集（N=8）由本協議預先鎖定（原判 1＋審計變體 6＋主配置 1，含主配置與其一變體重複列入），非事後從更大候選集挑選最小方差組合。")
    lines.append("- 敏感度組非判定依據，僅供解讀穩健性方向；判定看四個 Gate（G-A1~G-A4，G-A4 是四關之一）。")
    lines.append("")
    lines.append("---")
    lines.append("*本檔為腳本自動產出的草稿，供 fresh verifier 以 csv 重算全部 gate 數字後轉正。*")

    REPORT_PATH.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
