"""Diagnostics for interpreting the go/no-go: per-rebalance selection funnel +
strategy comparison (alpha-filtered HRP vs equal-weight-of-qualifying vs BTC)
so the verdict rests on understood mechanics, not a single opaque number."""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.factors import alpha_beta  # noqa: E402
from hlvault.metrics import sharpe  # noqa: E402
from hlvault.pipeline import MIN_OBS, select_at  # noqa: E402
from hlvault.prices import get_daily_returns  # noqa: E402
from hlvault.reconstruct import daily_pnl_panel, load_fill_shards, returns_panel  # noqa: E402

MIN_MONTHS = 6
HORIZON = 30


def main() -> None:
    fills = load_fill_shards("data/cache/fills")
    av = json.loads(Path("data/cache/account_values.json").read_text())
    panel = returns_panel(daily_pnl_panel(fills), av).dropna(how="all", axis=1)
    btc = get_daily_returns(
        "BTC", int(panel.index.min().timestamp() * 1000),
        int(panel.index.max().timestamp() * 1000),
    )
    eth = get_daily_returns(
        "ETH", int(panel.index.min().timestamp() * 1000),
        int(panel.index.max().timestamp() * 1000),
    )

    start, end = panel.index.min(), panel.index.max()
    rebal = pd.date_range(start + pd.Timedelta(days=HORIZON),
                          end - pd.Timedelta(days=HORIZON), freq=f"{HORIZON}D")

    hrp_seg, eqw_seg = [], []
    print(f"{'rebal date':<12} {'gate':>5} {'alpha>=2':>9} {'picked':>7}  top trader")
    for t in rebal:
        past = panel[panel.index <= t]
        # funnel counts
        gate = alpha = 0
        qualifying = []
        for u in past.columns:
            r = past[u].dropna()
            if len(r) < MIN_OBS:
                continue
            if (r.index.max() - r.index.min()).days < MIN_MONTHS * 30:
                continue
            gate += 1
            qualifying.append(u)
            try:
                fit = alpha_beta(r, btc.reindex(r.index), eth.reindex(r.index))
                if np.isfinite(fit.alpha_tstat) and fit.alpha_tstat >= 2.0:
                    alpha += 1
            except Exception:
                pass
        w = select_at(past, btc, eth, top_n=30, min_alpha_tstat=2.0,
                      min_history_months=MIN_MONTHS, n_trials=panel.shape[1])
        top = w.sort_values(ascending=False).index[0] if len(w) else "-"
        print(f"{str(t.date()):<12} {gate:>5} {alpha:>9} {len(w):>7}  {top[:12]}")

        future = panel[(panel.index > t) & (panel.index <= t + pd.Timedelta(days=HORIZON))]
        if len(w):
            cols = [c for c in w.index if c in future.columns]
            hrp_seg.append((future[cols] * w[cols]).sum(axis=1))
        if qualifying:
            qcols = [c for c in qualifying if c in future.columns]
            eqw_seg.append(future[qcols].mean(axis=1))

    def stat(segs, label):
        if not segs:
            print(f"{label:<28} no data")
            return
        s = pd.concat(segs).sort_index()
        s = s.groupby(s.index).mean()
        tot = (1 + s).prod() - 1
        print(f"{label:<28} OOS Sharpe {sharpe(s):>6.2f}  total {tot:>7.1%}  n={len(s)}")

    print("\n=== OOS strategy comparison ===")
    stat(hrp_seg, "alpha-filtered HRP (vault)")
    stat(eqw_seg, "equal-weight all qualifying")
    btc_oos = btc.reindex(pd.concat(hrp_seg).index) if hrp_seg else btc
    print(f"{'BTC buy-hold':<28} OOS Sharpe {sharpe(btc_oos.dropna()):>6.2f}  "
          f"total {((1+btc_oos.dropna()).prod()-1):>7.1%}")


if __name__ == "__main__":
    main()
