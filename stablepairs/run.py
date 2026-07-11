"""Orchestrator — run the full pipeline on live exchange data (needs internet).

  python run.py

Steps: discover live stablecoin pairs -> pick the tightest cointegrated one ->
fit the 2-state Markov-switching OU -> honest backtest (regime ON vs OFF) ->
print suggested Pine inputs.
"""
import numpy as np
import pandas as pd

from config import Config
from data import load_series
from discovery import rank_pairs
from spread import build_spread, ar1_halflife
from regime_hmm import fit_regime_ou, suggest_pine_inputs
from backtest import backtest


def rolling_is_revert(spread: pd.Series, window: int = 120, kappa_min: float = 0.0) -> pd.Series:
    """Observable regime proxy (what Pine computes live): rolling AR(1) kappa > min."""
    ds = spread.diff()
    sl = spread.shift(1)
    cov = (ds * sl).rolling(window).mean() - ds.rolling(window).mean() * sl.rolling(window).mean()
    var = (sl * sl).rolling(window).mean() - sl.rolling(window).mean() ** 2
    b = cov / var
    kappa = -b
    return (kappa > kappa_min).fillna(False)


def main():
    cfg = Config()
    print(f"[1] discovering live {cfg.quote} stablecoin pairs on {cfg.exchange} ...")
    ranked = rank_pairs(cfg)
    if ranked.empty:
        print("  no cointegrated pairs found — widen stable_universe or lower volume floor.")
        return
    print(ranked.head(10).to_string(index=False))

    best = ranked.iloc[0]
    legA, legB = best["legA"], best["legB"]
    print(f"\n[2] best pair: {legA} vs {legB}  (coint p={best['coint_p']:.4g})")

    la = np.log(load_series(legA, cfg)["close"])
    lb = np.log(load_series(legB, cfg)["close"])
    df = pd.concat([la, lb], axis=1, keys=["a", "b"]).dropna()
    spread, z, params = build_spread(df["a"], df["b"], cfg.train_frac)
    print(f"    beta={params['beta']:.4f}  half-life={ar1_halflife(spread)['half_life']:.1f} bars")

    print("\n[3] fitting 2-state Markov-switching OU ...")
    fit = fit_regime_ou(spread, cfg.k_regimes)
    if fit["ok"]:
        for r in fit["regimes"]:
            tag = "REVERT" if r["regime"] == fit["revert_id"] else "DIVERGE"
            print(f"    regime {r['regime']} [{tag:7}] phi={r['phi']:.4f} "
                  f"kappa={r['kappa_lin']:.4f} half-life={r['half_life']:.1f} sigma={r['sigma']:.2e}")
        pine = suggest_pine_inputs(fit, cfg)
        kappa_min = pine["kappaMin"]
    else:
        print("   ", fit["note"])
        kappa_min = 0.0
        pine = {"kappaMin": kappa_min}

    # trade the noisier leg (proxy for the illiquid third-leg you actually scalp)
    traded = load_series(legA, cfg)["close"].reindex(df.index)
    is_rev = rolling_is_revert(spread, window=120, kappa_min=kappa_min)

    print("\n[4] backtest (honest fees):")
    on = backtest(z, traded, is_rev, cfg, use_regime=True)
    off = backtest(z, traded, is_rev, cfg, use_regime=False)
    for name, r in [("regime ON ", on), ("regime OFF", off)]:
        print(f"    {name}: ret={r['total_return']*100:6.2f}%  Sharpe={r['sharpe']:5.2f}  "
              f"maxDD={r['max_drawdown']*100:6.2f}%  trades={r['n_trades']}  {r['exit_reasons']}")

    print("\n[5] suggested Pine inputs -> paste into 'Stay Cool C — Regime-Hardened':")
    for k, v in pine.items():
        print(f"    {k} = {v}")


if __name__ == "__main__":
    main()
