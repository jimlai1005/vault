"""Momentum-VT v1 gates aggregator (sub-project K, Task 3).

Protocol: docs/superpowers/specs/2026-07-13-momentum-vt-v1-protocol.md §4
(gate definitions) and §4b. Reads the 8 cells' formal-window daily csvs
(written by scripts/research_k_vt_v1.py, one file per cell:
data/k_framework/runs/cell{1..8}_formal_daily.csv) and computes G-K1..G-K5
against the primary cell (cell 2: 15%/40d/U-fixed). Does not run any
backtest itself except where a gate's definition literally requires a
rerun (G-K5's cost x1.5 leg) -- everything else is derived from the
already-committed formal csvs (CLAUDE.md #5: one implementation, reusing
research_k_vt_v1.compute_stats/daily_sr rather than re-deriving Sharpe/MDD).

G-K5 "端點±10天" (protocol §4b-6, owner-adopted adaptation): the literal
"±10 days on the window's right endpoint" is infeasible without violating
the pre-registered holdout embargo (formal window ends 2025-12-31; +10 days
would read into the locked 2026-01-01+ holdout range). Per §4b-6 the check
is: ±10 days on the OOS-accounting START (2020-07-01) plus a one-sided
-10-day probe of the window END, disclosed as such in the rendered report.

Window lock (protocol §4b-7): the G-K5 cost-x1.5 leg is the only place this
script SIMULATES (everything else re-slices committed csvs); that leg calls
research_k_vt_v1.simulate_cell(..., "formal"), which itself refuses to run
unless data/k_framework/FORMAL_UNLOCKED exists -- the same mechanical lock
the runner CLI enforces, so this script cannot touch the formal window
early either. The endpoint/split-half legs only read cell csvs, which can
only exist if the lock was open when they were produced.

Run (only after all 8 cells' formal csvs exist):
    .venv/bin/python scripts/k_gates_eval.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))

from research_k_vt_v1 import (  # noqa: E402
    CELLS,
    CLEAN_ERA_INDEXES,
    ERA_LABELS,
    ERAS,
    FORMAL_OOS_START,
    PRIMARY_CELL,
    RUNS_DIR,
    WINDOWS,
    compute_stats,
    daily_sr,
    simulate_cell,
)

REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "k-gates-draft.md"

# ---------------------------------------------------------------------------
# G-K1 DSR trial pool. Observable SRs = this task's 8 cells + 8 historical
# momentum-sizing attempts (16 series). The DECLARED trial count is 17
# (protocol §4b-7): one additional formal-window execution occurred during
# smoke testing; its numbers are voided/quarantined and never enter any file
# (so its SR cannot appear in the variance estimate), but the attempt still
# counts as a draw from the trial distribution, so it inflates N in the
# expected-max-SR quantiles as the pre-registered snooping penalty.
#
# The 8 historical daily (unannualized, mean/std ddof=1) SRs below are
# copied verbatim from the DSR table in
# reports/momentum-voltarget-retest-verdict.md lines 55-62 (2024-07-02 ->
# 2026-07-02 pinned window) -- NOT recomputed here, per that report's own
# already-verified numbers (fresh-verifier-checked 2026-07-12).
# ---------------------------------------------------------------------------
HISTORICAL_TRIAL_SRS = [
    0.014993,   # 1: 原判 flat-3x（無 funding）-- verdict L55
    0.009536,   # 2: vt20_lb20+funding（=主配置）-- verdict L56
    0.008124,   # 3: vt15_lb20+funding -- verdict L57
    0.011386,   # 4: vt25_lb20+funding -- verdict L58
    0.012621,   # 5: vt30_lb20+funding -- verdict L59
    -0.009456,  # 6: vt20_lb10+funding -- verdict L60
    0.020955,   # 7: vt20_lb40+funding -- verdict L61
    0.009536,   # 8: 主配置（重複列入，report 原文如此）-- verdict L62
]
EULER_MASCHERONI = 0.5772156649
N_OBSERVABLE_TRIALS = 16   # SR series available for the variance estimate
N_TRIALS_DECLARED = 17     # §4b-7: +1 voided formal-window smoke execution


def deflated_sharpe(sr_list: list, primary_returns: pd.Series,
                     n_trials_declared: int = N_TRIALS_DECLARED) -> dict:
    """Bailey & Lopez de Prado (2012) PSR/DSR -- identical formula to
    scripts/research_momentum_voltarget.py's G-A3 (reused, not re-derived).
    V is estimated from the observable SRs in `sr_list`; the expected-max
    quantiles use `n_trials_declared`, which may exceed len(sr_list) when a
    declared trial's result is quarantined (protocol §4b-7: the voided
    formal-window execution counts as a draw but its number is unseen)."""
    V = float(np.var(sr_list, ddof=1))
    n_trials = n_trials_declared
    z1 = float(stats.norm.ppf(1 - 1.0 / n_trials))
    z2 = float(stats.norm.ppf(1 - 1.0 / (n_trials * np.e)))
    sr_star = (V ** 0.5) * ((1 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)

    r = primary_returns.dropna()
    n = len(r)
    sr = daily_sr(r)
    g3 = float(stats.skew(r, bias=True)) if n > 2 else 0.0
    g4 = float(stats.kurtosis(r, fisher=False, bias=True)) if n > 2 else 3.0
    psr_den = (1 - g3 * sr + ((g4 - 1) / 4) * sr ** 2) ** 0.5
    psr_num = (sr - sr_star) * (n - 1) ** 0.5
    psr = float(stats.norm.cdf(psr_num / psr_den)) if psr_den > 0 else 0.0
    return dict(V=V, n_trials=n_trials, z1=z1, z2=z2, sr_star=sr_star, sr=sr, n=n,
                g3=g3, g4=g4, psr=psr)


def hac_t_stat(returns: pd.Series) -> tuple:
    """Newey-West HAC t-stat for H0: mean(daily return)=0, lag =
    ceil(1.3221 * n^0.2) (task-specified rule). Delegates the sandwich
    covariance to statsmodels (already a project dependency) rather than
    hand-rolling the Bartlett-kernel long-run-variance formula -- fewer
    places for a sign/denominator bug to hide."""
    r = returns.dropna()
    n = len(r)
    lag = max(1, math.ceil(1.3221 * n ** 0.2))
    X = np.ones((n, 1))
    model = sm.OLS(np.asarray(r, dtype=float), X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return float(model.tvalues[0]), lag


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_cell_formal_detail(cell: int) -> pd.DataFrame:
    path = RUNS_DIR / f"cell{cell}_formal_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path} -- run all 8 formal cells before gates eval")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df


def oos_returns_from_detail(df: pd.DataFrame, oos_start: str = FORMAL_OOS_START,
                             oos_end: str | None = None) -> pd.Series:
    mask = df["date"] >= pd.Timestamp(oos_start)
    if oos_end is not None:
        mask &= df["date"] <= pd.Timestamp(oos_end)
    return df.loc[mask].set_index("date")["ret"]


# ---------------------------------------------------------------------------
# G-K5 sub-checks
# ---------------------------------------------------------------------------

def gate_k5_endpoint(detail_primary: pd.DataFrame) -> dict:
    """Endpoint-sensitivity variants, all derived by RE-SLICING the ALREADY-
    SIMULATED primary-cell formal detail (no resimulation needed: the
    engine is strictly causal, so truncating the tail or shifting the OOS
    start later never changes any earlier day's decisions -- see
    scripts/research_k_vt_v1.py's module docstring). See module docstring
    above for why the right endpoint is only probed -10d, not +10d."""
    oos_start = pd.Timestamp(FORMAL_OOS_START)
    oos_end = pd.Timestamp(WINDOWS["formal"][1])
    variants = {
        "base": (oos_start, oos_end),
        "oos_start-10d": (oos_start - pd.Timedelta(days=10), oos_end),
        "oos_start+10d": (oos_start + pd.Timedelta(days=10), oos_end),
        "window_end-10d": (oos_start, oos_end - pd.Timedelta(days=10)),
    }
    results = {}
    for name, (s, e) in variants.items():
        sub = detail_primary.loc[
            (detail_primary["date"] >= s) & (detail_primary["date"] <= e)
        ].set_index("date")["ret"]
        results[name] = compute_stats(sub)
    base_positive = results["base"]["sharpe"] >= 0
    consistent = all((v["sharpe"] >= 0) == base_positive for v in results.values())
    note = (
        "端點檢查依協議 §4b-6 適配：右端 +10 天會窺入 holdout 鎖定範圍"
        f"（{WINDOWS['holdout'][0]}+），故改為 OOS 記帳起點 ±10 天（雙向）＋視窗終點"
        "單側 −10 天，如實標注（owner 已裁定採納，非擅自替換）。"
    )
    return {"results": results, "consistent": consistent, "note": note}


def gate_k5_splithalf(oos_returns: pd.Series) -> dict:
    """Own-compounding split-half, boundary at the OOS segment's own
    midpoint date (same 'each half starts fresh at 1.0' convention as
    research_momentum_voltarget.py's half_stats)."""
    idx = oos_returns.index
    mid = idx.min() + (idx.max() - idx.min()) / 2
    first = compute_stats(oos_returns[oos_returns.index < mid])
    second = compute_stats(oos_returns[oos_returns.index >= mid])
    passed = first["sharpe"] > 0 and second["sharpe"] > 0
    return {"mid": mid, "first": first, "second": second, "passed": passed}


def gate_k5_cost_x15() -> dict:
    """Genuinely requires a rerun (cost changes the equity path/ladder
    dynamics from day 1, unlike the endpoint variants above). Gated by the
    FORMAL_UNLOCKED mechanical lock inside simulate_cell itself (protocol
    §4b-7) -- this call raises unless the formal window has been officially
    unlocked, so gates eval cannot re-touch the formal window early."""
    result = simulate_cell(PRIMARY_CELL, "formal", cost_multiplier=1.5)
    cell_stats = compute_stats(result.oos_returns)
    passed = cell_stats["sharpe"] >= 0.45
    return {"stats": cell_stats, "passed": passed}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    missing = [c for c in sorted(CELLS) if not (RUNS_DIR / f"cell{c}_formal_daily.csv").exists()]
    if missing:
        print(f"missing formal runs for cells {missing} -- run all 8 formal cells "
              "(scripts/research_k_vt_v1.py --window formal) before gates eval")
        sys.exit(1)

    details = {c: load_cell_formal_detail(c) for c in sorted(CELLS)}
    oos = {c: oos_returns_from_detail(details[c]) for c in sorted(CELLS)}
    stats_by_cell = {c: compute_stats(oos[c]) for c in sorted(CELLS)}
    daily_sr_by_cell = {c: daily_sr(oos[c]) for c in sorted(CELLS)}
    zero_gross_by_cell = {
        c: float((details[c]["gross"] == 0).mean()) for c in sorted(CELLS)
    }

    primary_returns = oos[PRIMARY_CELL]
    primary_stats = stats_by_cell[PRIMARY_CELL]

    # ---- G-K1 ----
    sr_list = HISTORICAL_TRIAL_SRS + [daily_sr_by_cell[c] for c in sorted(CELLS)]
    assert len(sr_list) == N_OBSERVABLE_TRIALS, \
        f"expected {N_OBSERVABLE_TRIALS} observable trials, got {len(sr_list)}"
    dsr = deflated_sharpe(sr_list, primary_returns)
    t_hac, hac_lag = hac_t_stat(primary_returns)
    gk1_pass = primary_stats["sharpe"] >= 0.6 and dsr["psr"] >= 0.95

    # ---- G-K2 ----
    gk2_pass = primary_stats["mdd"] >= -0.20

    # ---- G-K3 ----
    era_results = []
    for i, ((start, end), label) in enumerate(zip(ERAS, ERA_LABELS)):
        era_r = primary_returns[(primary_returns.index >= start) & (primary_returns.index <= end)]
        net = float((1.0 + era_r).prod() - 1.0) if len(era_r) else None
        era_results.append({
            "label": label, "n": len(era_r), "net_return": net, "clean": i in CLEAN_ERA_INDEXES,
        })
    positive_eras = [e for e in era_results if e["net_return"] is not None and e["net_return"] > 0]
    positive_clean_eras = [e for e in positive_eras if e["clean"]]
    gk3_pass = len(positive_eras) >= 3 and len(positive_clean_eras) >= 2

    # ---- G-K4 ----
    neighbor_cells = [1, 4, 6]
    neighbor_pass_count = sum(1 for c in neighbor_cells if stats_by_cell[c]["sharpe"] >= 0.3)
    # ">=0.3 且同號": 0.3 is itself a positive threshold, so any cell clearing
    # it is automatically positive -- "same sign" is trivially satisfied
    # among passers; no separate sign check needed.
    gk4_pass = neighbor_pass_count >= 2

    # ---- G-K5 ----
    endpoint = gate_k5_endpoint(details[PRIMARY_CELL])
    splithalf = gate_k5_splithalf(primary_returns)
    cost15 = gate_k5_cost_x15()
    gk5_pass = endpoint["consistent"] and splithalf["passed"] and cost15["passed"]

    all_pass = gk1_pass and gk2_pass and gk3_pass and gk4_pass and gk5_pass

    lines = _render_report(
        details=details, stats_by_cell=stats_by_cell, daily_sr_by_cell=daily_sr_by_cell,
        zero_gross_by_cell=zero_gross_by_cell, primary_stats=primary_stats,
        sr_list=sr_list, dsr=dsr, t_hac=t_hac, hac_lag=hac_lag, gk1_pass=gk1_pass,
        gk2_pass=gk2_pass, era_results=era_results, gk3_pass=gk3_pass,
        neighbor_cells=neighbor_cells, neighbor_pass_count=neighbor_pass_count, gk4_pass=gk4_pass,
        endpoint=endpoint, splithalf=splithalf, cost15=cost15, gk5_pass=gk5_pass,
        all_pass=all_pass,
    )
    print("\n".join(lines))
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nreport written to {REPORT_PATH}")


def _render_report(*, details, stats_by_cell, daily_sr_by_cell, zero_gross_by_cell,
                    primary_stats, sr_list, dsr, t_hac, hac_lag, gk1_pass, gk2_pass,
                    era_results, gk3_pass, neighbor_cells, neighbor_pass_count, gk4_pass,
                    endpoint, splithalf, cost15, gk5_pass, all_pass) -> list:
    L = []
    L.append("# Momentum-VT v1: Gates G-K1..G-K5 — DRAFT")
    L.append("")
    L.append("**狀態：DRAFT（腳本自動產出，未經 fresh verifier / opus 二審——見協議 §5）**")
    L.append("")
    L.append("依據：`docs/superpowers/specs/2026-07-13-momentum-vt-v1-protocol.md` §4；"
              "腳本：`scripts/k_gates_eval.py`（讀 `scripts/research_k_vt_v1.py` 產出的 "
              "`data/k_framework/runs/cell{1..8}_formal_daily.csv`）")
    L.append("")
    L.append(f"主格＝cell {PRIMARY_CELL}（15%/40d/U-fixed）；"
              f"OOS 段＝{FORMAL_OOS_START} → {WINDOWS['formal'][1]}")
    L.append("")

    L.append("## Gates 判定表")
    L.append("")
    L.append("| Gate | 判準 | 結果 | 數字 |")
    L.append("|---|---|---|---|")
    L.append(f"| G-K1 | Sharpe>=0.6 且 DSR(N={N_TRIALS_DECLARED})>=0.95 | {'PASS' if gk1_pass else 'FAIL'} | "
              f"sharpe={primary_stats['sharpe']:.3f}, PSR={dsr['psr']:.4f}, "
              f"HAC-t={t_hac:.3f} (lag={hac_lag}) |")
    L.append(f"| G-K2 | MDD<=20% | {'PASS' if gk2_pass else 'FAIL'} | mdd={primary_stats['mdd']:.2%} |")
    L.append(f"| G-K3 | >=3/5 段淨報酬為正，其中>=2段在乾淨窗 | {'PASS' if gk3_pass else 'FAIL'} | "
              f"positive={sum(1 for e in era_results if e['net_return'] and e['net_return']>0)}/5 |")
    L.append(f"| G-K4 | 格1/4/6 中>=2格 Sharpe>=0.3 | {'PASS' if gk4_pass else 'FAIL'} | "
              f"{neighbor_pass_count}/3 通過 |")
    L.append(f"| G-K5 | 端點敏感度不翻盤＋split-half各半>0＋成本x1.5 Sharpe>=0.45 | "
              f"{'PASS' if gk5_pass else 'FAIL'} | "
              f"endpoint_consistent={endpoint['consistent']}, "
              f"split=({splithalf['first']['sharpe']:.3f}/{splithalf['second']['sharpe']:.3f}), "
              f"cost_x1.5_sharpe={cost15['stats']['sharpe']:.3f} |")
    L.append("")
    verdict = "conditional GO（進 G-K7 paper）" if all_pass else "NO-GO（本線收檔，8 格結果全數呈報）"
    L.append(f"**綜合判定（G-K1~K5）：{verdict}**")
    L.append("")

    L.append("## 8 格總覽（formal window, OOS 段）")
    L.append("")
    L.append("| 格 | target/lookback/universe | Sharpe(ann) | 總報酬 | MDD | daily SR(未年化) | "
              "zero-gross 天數比 |")
    L.append("|---|---|---:|---:|---:|---:|---:|")
    for c in sorted(CELLS):
        p = CELLS[c]
        s = stats_by_cell[c]
        mark = " **(主格)**" if c == PRIMARY_CELL else ""
        L.append(f"| {c}{mark} | {p['target_vol']:.0%}/{p['lookback']}d/{p['universe']} | "
                  f"{s['sharpe']:.3f} | {s['total_return']:.1%} | {s['mdd']:.1%} | "
                  f"{daily_sr_by_cell[c]:.6f} | {zero_gross_by_cell[c]:.1%} |")
    L.append("")

    L.append(f"## G-K1 DSR 中間量（申報 N={N_TRIALS_DECLARED}＝本 8 格 + 歷史動能嘗試 8 "
              "+ 1 個作廢隔離的 formal 煙測執行，協議 §4b-7）")
    L.append("")
    L.append("| # | 來源 | daily SR |")
    L.append("|---|---|---:|")
    hist_labels = ["原判 flat-3x（無funding）", "vt20_lb20+funding", "vt15_lb20+funding",
                    "vt25_lb20+funding", "vt30_lb20+funding", "vt20_lb10+funding",
                    "vt20_lb40+funding", "主配置（重複列入）"]
    for i, (label, s) in enumerate(zip(hist_labels, sr_list[:8]), 1):
        L.append(f"| {i} | 歷史-{label} | {s:.6f} |")
    for i, c in enumerate(sorted(CELLS), 9):
        L.append(f"| {i} | cell {c}（本次） | {sr_list[i-1]:.6f} |")
    L.append(f"| 17 | 作廢隔離之 formal 煙測執行（§4b-7；數字不可見，僅計入 N） | — |")
    L.append("")
    L.append(f"- V = var({N_OBSERVABLE_TRIALS} 個可見 SR, ddof=1) = {dsr['V']:.8f}"
              "（第 17 個試驗的數字已隔離，不進變異數估計）")
    L.append(f"- N（申報試驗數）= {dsr['n_trials']}, γ (Euler-Mascheroni) = {EULER_MASCHERONI}")
    L.append(f"- z(1-1/N) = {dsr['z1']:.6f}, z(1-1/(N·e)) = {dsr['z2']:.6f}")
    L.append(f"- SR* = {dsr['sr_star']:.6f}")
    L.append(f"- 主格日報酬：n={dsr['n']}, SR={dsr['sr']:.6f}, γ3={dsr['g3']:.6f}, γ4={dsr['g4']:.6f}")
    L.append(f"- PSR = {dsr['psr']:.6f}")
    L.append(f"- HAC t-stat（Newey-West, lag=ceil(1.3221·n^0.2)={hac_lag}）= {t_hac:.4f}"
              "（呈報用，非 gate 判準的一部分）")
    L.append("")
    L.append(f"**方法論但書**：可見的 {N_OBSERVABLE_TRIALS} 個試驗混合了兩種不同樣本長度"
              "（歷史 8 個來自 731 天窗，本次 8 格來自 formal OOS ~2000 天窗）；DSR 對試驗集"
              "的變異數估計因此不是嚴格同分布的。申報 N=17 中第 17 個試驗（作廢的 formal "
              "煙測）僅計入試驗數、不進變異數（其數字已隔離），此為協議 §4b-7 的預先登記補救。")
    L.append("")

    L.append("## G-K3 市場階段（乾淨窗 = 2020-Q3 → 2024-Q2）")
    L.append("")
    L.append("| 時代 | n | 淨報酬 | 乾淨窗內 |")
    L.append("|---|---:|---:|---|")
    for e in era_results:
        net_s = f"{e['net_return']:+.2%}" if e["net_return"] is not None else "無資料"
        L.append(f"| {e['label']} | {e['n']} | {net_s} | {'是' if e['clean'] else '否'} |")
    L.append("")

    L.append("## G-K5 明細")
    L.append("")
    L.append("### 端點敏感度")
    L.append("")
    L.append(endpoint["note"])
    L.append("")
    L.append("| 變體 | Sharpe(ann) | 總報酬 | MDD |")
    L.append("|---|---:|---:|---:|")
    for name, r in endpoint["results"].items():
        L.append(f"| {name} | {r['sharpe']:.3f} | {r['total_return']:.1%} | {r['mdd']:.1%} |")
    L.append("")
    L.append(f"### Split-half（邊界 {splithalf['mid'].date()}）")
    L.append("")
    L.append(f"- 前半：sharpe={splithalf['first']['sharpe']:.3f} mdd={splithalf['first']['mdd']:.1%}")
    L.append(f"- 後半：sharpe={splithalf['second']['sharpe']:.3f} mdd={splithalf['second']['mdd']:.1%}")
    L.append("")
    L.append("### 成本 x1.5")
    L.append("")
    L.append(f"- sharpe={cost15['stats']['sharpe']:.3f}, mdd={cost15['stats']['mdd']:.1%}, "
              f"total_ret={cost15['stats']['total_return']:.1%}")
    L.append("")

    L.append("## 誠實條款")
    L.append("")
    L.append("- funding 資料：`data/k_framework/funding/` 目前每個 symbol 僅有最近 ~500 筆"
              "（~5.5 個月），非協議預期的 2019 起全歷史（`scripts/k_data_layer.py` 的"
              "`fetch_funding_history` 分頁有已知 bug，其自身註解已承認）。formal 窗"
              "(2020-2025) 因此絕大多數天數的 funding PnL 以 0 記帳並計入缺洞天數"
              "（見各格 stdout 摘要），非本評估腳本吞掉。")
    L.append("- 小活躍集 cap 語義（協議 §4b-5）：≤2 個活躍資產時 35% 單資產 RC cap "
              "數學不可行（RC 恆合計 100%），有效 cap = max(35%, 1/N_active)、叢集 cap "
              "僅在叢集外有活躍資產時生效。各格 zero-gross 天數比見上表——若某 U-fixed "
              "格比例仍偏高，該格的低 Sharpe 可能部分來自訊號稀疏（同時活躍資產少），"
              "解讀 G-K1/G-K4 時應一併參考。")
    L.append("- G-K5 端點敏感度依協議 §4b-6 適配：右端點 +10 天因 holdout 鎖而未測，"
              "以 OOS 記帳起點 ±10 天（雙向）＋視窗終點 −10 天（單向）代替協議字面的"
              "雙向 ±10 天。")
    L.append("- 試驗集申報（協議 §2＋§4b-7）：本判定使用預先登記的 8 格＋8 個歷史試驗"
              "＋1 個作廢隔離的 formal 煙測執行（申報 N=17，數字不可見），不含任何"
              "事後挑選；8 格不再擴充。")
    L.append("")
    L.append("---")
    L.append("*本檔為腳本自動產出的草稿，供 fresh verifier 從 8 個 cell csv 重算全部 gate 數字後轉正。*")
    return L


if __name__ == "__main__":
    main()
