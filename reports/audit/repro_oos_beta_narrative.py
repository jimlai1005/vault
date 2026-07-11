"""Read-only reproduction: tests the oos-verdict.md claim #3 ("These traders
are net-long crypto beta, not market-neutral alpha... tracked the BTC bear
market down") against two direct measurements:

  (a) the SAME portfolio_betas() function the pipeline itself uses to hedge,
      evaluated at each rebalance for the actually-selected sub-portfolio
      (in-sample, static OLS beta as of T);
  (b) an EX-POST regression of the realized, concatenated OOS portfolio
      returns against realized BTC/ETH returns over the actual hold windows
      -- i.e. did the selected traders, in fact, move with the market when it
      mattered?

Run: .venv/bin/python reports/audit/repro_oos_beta_narrative.py
(read-only: only reads data/cache/*, writes nothing)
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hlvault.config import Settings  # noqa: E402
from hlvault.metrics import sharpe  # noqa: E402
from hlvault.pipeline import portfolio_betas, select_at  # noqa: E402
from hlvault.reconstruct import daily_pnl_panel, load_fill_shards, returns_panel  # noqa: E402


def main():
    cfg = Settings()
    fills = load_fill_shards(str(ROOT / "data/cache/fills"))
    av = json.loads((ROOT / "data/cache/account_values.json").read_text())
    panel = returns_panel(daily_pnl_panel(fills), av).dropna(how="all", axis=1)
    prices = pd.read_parquet(ROOT / "data/cache/prices.parquet")
    btc, eth = prices["btc"].dropna(), prices["eth"].dropna()

    H = cfg.rebalance_horizon_days
    start, end = panel.index.min(), panel.index.max()
    rebal = pd.date_range(start + pd.Timedelta(days=H), end - pd.Timedelta(days=H), freq=f"{H}D")

    print("=" * 78)
    print("§1 in-sample static beta_btc/beta_eth of the SELECTED sub-portfolio per rebalance")
    print("   (same portfolio_betas() the pipeline uses to build the 'market-neutral' hedge)")
    raw_segs = []
    for t in rebal:
        past = panel[panel.index <= t]
        w = select_at(past, btc, eth, top_n=cfg.top_n, min_alpha_tstat=cfg.min_alpha_tstat,
                      min_history_months=6, n_trials=panel.shape[1])
        if not len(w):
            continue
        b_btc, b_eth = portfolio_betas(past, w, btc, eth)
        future = panel[(panel.index > t) & (panel.index <= t + pd.Timedelta(days=H))]
        cols = [c for c in w.index if c in future.columns]
        port = (future[cols] * w[cols]).sum(axis=1)
        raw_segs.append(port)
        print(f"   T={t.date()} beta_btc={b_btc:+.3f} beta_eth={b_eth:+.3f}  n_picks={len(w)}")

    raw = pd.concat(raw_segs).sort_index()
    raw = raw.groupby(raw.index).mean()
    btc_oos = btc.reindex(raw.index).fillna(0.0)
    eth_oos = eth.reindex(raw.index).fillna(0.0)

    print("\n" + "=" * 78)
    print("§2 EX-POST regression: realized OOS portfolio return vs realized BTC/ETH return")
    print(f"   portfolio OOS total return: {(1+raw).prod()-1:+.1%}   Sharpe={sharpe(raw):.2f}")
    print(f"   BTC        OOS total return: {(1+btc_oos).prod()-1:+.1%}")
    X = sm.add_constant(pd.DataFrame({"btc": btc_oos, "eth": eth_oos}))
    model = sm.OLS(raw.values, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    print(f"   realized beta_btc={model.params['btc']:+.3f} (t={model.tvalues['btc']:+.2f})  "
          f"beta_eth={model.params['eth']:+.3f} (t={model.tvalues['eth']:+.2f})")
    print(f"   realized alpha (daily)={model.params['const']:+.5f}  "
          f"annualized={model.params['const']*252:+.1%}  (t={model.tvalues['const']:+.2f})")
    print(f"   r_squared={model.rsquared:.4f}  simple corr(port,BTC)={raw.corr(btc_oos):.3f}")


if __name__ == "__main__":
    main()
