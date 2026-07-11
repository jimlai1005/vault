"""Read-only reproduction: the sample-length ("N-month track record") gate in
select_at()/returns_panel() does not measure a trader's REAL active-trading
tenure. daily_pnl_panel() pivots fills with fill_value=0.0, so every user gets
an exact-0.0 "return" for every archive day before their actual first fill —
indistinguishable from a genuinely flat trading day. Since
`(r.index.max() - r.index.min()).days` is computed on this padded series, the
gate effectively measures "how old is the archive" rather than "how long has
this address actually traded", letting short-real-tenure addresses through.

Concretely: 0x36076e4bfad9624d7feba562326fdfa2063ede23's first REAL fill is
2026-02-06. At T=2026-03-24 (6mo-gate) and T=2026-04-23, their real tenure is
46 and 76 days respectively -- far short of the 90d(3mo)/180d(6mo) requirement
-- yet select_at() passed them because the padded series spans the full
archive (2025-07-27 -> T).

This script (a) shows the padded-vs-true window discrepancy and the trader's
extreme +45%/-54% swings, and (b) re-runs the walk-forward OOS backtest with
that one address excluded, for all three reported configurations (6mo
long-only, 3mo long-only, 6mo market-neutral), to quantify how much of the
published NO-GO numbers this single gate violation explains.

Run: .venv/bin/python reports/audit/repro_oos_gate_bug.py
(read-only: only reads data/cache/*, writes nothing)
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hlvault.config import Settings  # noqa: E402
from hlvault.factors import alpha_beta  # noqa: E402
from hlvault.metrics import max_drawdown, sharpe  # noqa: E402
from hlvault.pipeline import portfolio_betas, select_at  # noqa: E402
from hlvault.reconstruct import daily_pnl_panel, load_fill_shards, returns_panel  # noqa: E402

BAD_USER = "0x36076e4bfad9624d7feba562326fdfa2063ede23"


def load_panel():
    fills = load_fill_shards(str(ROOT / "data/cache/fills"))
    av = json.loads((ROOT / "data/cache/account_values.json").read_text())
    panel = returns_panel(daily_pnl_panel(fills), av).dropna(how="all", axis=1)
    prices = pd.read_parquet(ROOT / "data/cache/prices.parquet")
    return fills, panel, prices["btc"].dropna(), prices["eth"].dropna()


def section_padding_evidence(fills, panel, btc, eth):
    print("=" * 78)
    print("§1 padded-window vs true-window alpha_tstat for", BAD_USER)
    T = pd.Timestamp("2026-03-24")
    past = panel[panel.index <= T]
    r_full = past[BAD_USER].dropna()
    fit_full = alpha_beta(r_full, btc.reindex(r_full.index), eth.reindex(r_full.index))
    print(f"  as-coded (padded) window: {r_full.index.min().date()} -> {r_full.index.max().date()} "
          f"n={len(r_full)}  alpha_tstat={fit_full.alpha_tstat:.3f}")

    fills_c = fills.copy()
    fills_c["day"] = pd.to_datetime(fills_c["time"]).dt.normalize()
    first_fill_day = fills_c.groupby("user")["day"].min()[BAD_USER]
    r_true = r_full[r_full.index >= first_fill_day]
    fit_true = alpha_beta(r_true, btc.reindex(r_true.index), eth.reindex(r_true.index))
    print(f"  TRUE active window:       {r_true.index.min().date()} -> {r_true.index.max().date()} "
          f"n={len(r_true)}  alpha_tstat={fit_true.alpha_tstat:.3f}  "
          f"(gate requires >=180d; real tenure is {len(r_true)}d)")

    n_zero_pre = int((r_full.loc[:first_fill_day - pd.Timedelta(days=1)] == 0).sum())
    print(f"  fake zero-padding rows feeding the 'buggy' regression: {n_zero_pre}/{len(r_full)} "
          f"({n_zero_pre/len(r_full):.0%})")


def section_contribution(panel, btc, eth):
    print("\n" + "=" * 78)
    print("§2 this trader's contribution to the two rebalances it was picked in (6mo gate)")
    cfg = Settings()
    H = cfg.rebalance_horizon_days
    for t_str in ["2026-03-24", "2026-04-23"]:
        t = pd.Timestamp(t_str)
        past = panel[panel.index <= t]
        w = select_at(past, btc, eth, top_n=cfg.top_n, min_alpha_tstat=cfg.min_alpha_tstat,
                      min_history_months=6, n_trials=panel.shape[1])
        future = panel[(panel.index > t) & (panel.index <= t + pd.Timedelta(days=H))]
        cols = [c for c in w.index if c in future.columns]
        port = (future[cols] * w[cols]).sum(axis=1)
        others = [c for c in cols if c != BAD_USER]
        port_wo = (future[others] * w[others]).sum(axis=1) if others else None
        own = future[BAD_USER] if BAD_USER in future.columns else None
        print(f"  T={t_str} weight={w.get(BAD_USER, float('nan')):.2f}  "
              f"port(with)={(1+port).prod()-1:+.1%}  "
              f"port(without)={(1+port_wo).prod()-1:+.1%}  "
              f"trader_own_return={(1+own).prod()-1:+.1%}" if own is not None else "")


def run_walk_forward(panel, btc, eth, min_history_months, hedge=False):
    cfg = Settings()
    H = cfg.rebalance_horizon_days
    start, end = panel.index.min(), panel.index.max()
    rebal = pd.date_range(start + pd.Timedelta(days=H), end - pd.Timedelta(days=H), freq=f"{H}D")
    segs = []
    for t in rebal:
        past = panel[panel.index <= t]
        w = select_at(past, btc, eth, top_n=cfg.top_n, min_alpha_tstat=cfg.min_alpha_tstat,
                      min_history_months=min_history_months, n_trials=panel.shape[1])
        if not len(w):
            continue
        future = panel[(panel.index > t) & (panel.index <= t + pd.Timedelta(days=H))]
        cols = [c for c in w.index if c in future.columns]
        if not cols:
            continue
        port = (future[cols] * w[cols]).sum(axis=1)
        if hedge:
            b_btc, b_eth = portfolio_betas(past, w, btc, eth)
            hedge_ret = (b_btc * btc.reindex(port.index).fillna(0.0)
                         + b_eth * eth.reindex(port.index).fillna(0.0))
            port = port - hedge_ret
        segs.append(port)
    oos = pd.concat(segs).sort_index()
    oos = oos.groupby(oos.index).mean()
    t_, p = stats.ttest_1samp(oos, 0.0)
    tot = (1 + oos).prod() - 1
    return dict(n=len(oos), total=tot, sharpe=sharpe(oos), t=t_, p=p,
                mdd=max_drawdown((1 + oos).cumprod()))


def section_sensitivity(panel, btc, eth):
    print("\n" + "=" * 78)
    print("§3 full walk-forward OOS, WITH vs WITHOUT the mis-gated trader")
    panel_excl = panel.drop(columns=[BAD_USER])
    configs = [
        ("6mo long-only", 6, False, "-23.8% Sharpe -1.42 t=-1.10"),
        ("3mo long-only", 3, False, "-22.2% Sharpe -1.02 t=-1.00"),
        ("6mo market-neutral (hedged)", 6, True, "-25.5% Sharpe -1.53 t=-1.18"),
    ]
    for label, months, hedge, published in configs:
        with_bad = run_walk_forward(panel, btc, eth, months, hedge)
        without_bad = run_walk_forward(panel_excl, btc, eth, months, hedge)
        print(f"\n  [{label}]  (published: {published})")
        print(f"    WITH bad trader   : total={with_bad['total']:+.1%} Sharpe={with_bad['sharpe']:.2f} "
              f"t={with_bad['t']:.2f} p={with_bad['p']:.3f} n={with_bad['n']}")
        print(f"    WITHOUT bad trader: total={without_bad['total']:+.1%} Sharpe={without_bad['sharpe']:.2f} "
              f"t={without_bad['t']:.2f} p={without_bad['p']:.3f} n={without_bad['n']}")


def main():
    fills, panel, btc, eth = load_panel()
    section_padding_evidence(fills, panel, btc, eth)
    section_contribution(panel, btc, eth)
    section_sensitivity(panel, btc, eth)


if __name__ == "__main__":
    main()
