"""Market-neutral variant of the go/no-go.

Same alpha selection, but OOS we hedge out the portfolio's in-sample BTC/ETH
beta and test whether the residual (alpha) return is positive. Benchmark is
zero (cash) — a market-neutral book should make money in any regime if the
traders have real skill, not just crypto beta.

    python scripts/run_neutral.py            # 6-month gate via env
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.config import Settings  # noqa: E402
from hlvault.metrics import max_drawdown, sharpe  # noqa: E402
from hlvault.pipeline import portfolio_betas, select_at  # noqa: E402
from hlvault.prices import get_daily_returns  # noqa: E402
from hlvault.reconstruct import daily_pnl_panel, load_fill_shards, returns_panel  # noqa: E402


def main() -> None:
    cfg = Settings()
    fills = load_fill_shards("data/cache/fills")
    av = json.loads(Path("data/cache/account_values.json").read_text())
    panel = returns_panel(daily_pnl_panel(fills), av).dropna(how="all", axis=1)
    s = int(panel.index.min().timestamp() * 1000)
    e = int(panel.index.max().timestamp() * 1000)
    btc = get_daily_returns("BTC", s, e)
    eth = get_daily_returns("ETH", s, e)

    H = cfg.rebalance_horizon_days
    start, end = panel.index.min(), panel.index.max()
    rebal = pd.date_range(start + pd.Timedelta(days=H), end - pd.Timedelta(days=H),
                          freq=f"{H}D")

    raw_seg, hedged_seg = [], []
    for t in rebal:
        past = panel[panel.index <= t]
        w = select_at(past, btc, eth, top_n=cfg.top_n,
                      min_alpha_tstat=cfg.min_alpha_tstat,
                      min_history_months=cfg.min_history_months,
                      n_trials=panel.shape[1])
        if not len(w):
            continue
        b_btc, b_eth = portfolio_betas(past, w, btc, eth)
        future = panel[(panel.index > t) & (panel.index <= t + pd.Timedelta(days=H))]
        cols = [c for c in w.index if c in future.columns]
        port = (future[cols] * w[cols]).sum(axis=1)
        hedge = (b_btc * btc.reindex(port.index).fillna(0.0)
                 + b_eth * eth.reindex(port.index).fillna(0.0))
        raw_seg.append(port)
        hedged_seg.append(port - hedge)

    def summarize(segs, label):
        s = pd.concat(segs).sort_index()
        s = s.groupby(s.index).mean()
        t, p = stats.ttest_1samp(s, 0.0)
        tot = (1 + s).prod() - 1
        mdd = max_drawdown((1 + s).cumprod())
        print(f"{label:<24} Sharpe {sharpe(s):>6.2f}  total {tot:>7.1%}  "
              f"t {t:>5.2f}  p {p:>5.3f}  maxDD {mdd:>6.1%}  n={len(s)}")
        return t, p, sharpe(s)

    print(f"rebalances used: {len(hedged_seg)}")
    summarize(raw_seg, "raw (long-only)")
    t, p, sr = summarize(hedged_seg, "market-neutral (hedged)")

    decision = "GO" if (t > 2.0 and p < 0.05 and sr > 0) else "NO-GO"
    print(f"\nMARKET-NEUTRAL VERDICT: {decision}")
    if decision == "NO-GO":
        print("Hedged (alpha) return not significantly positive OOS.")
    else:
        print("Hedged alpha is significantly positive OOS — promising; re-run "
              "with deeper history before sizing capital.")


if __name__ == "__main__":
    main()
