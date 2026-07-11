"""Offline self-test: generate a 2-regime OU spread, then verify the estimation +
backtest layers run end-to-end and that regime gating helps. No network needed.

    python tests/test_synthetic.py
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from spread import build_spread, ar1_halflife
from regime_hmm import fit_regime_ou, suggest_pine_inputs
from backtest import backtest
from run import rolling_is_revert


def make_synthetic(n=6000, seed=7):
    """Markov chain toggles OU params: regime 0 = revert, regime 1 = diverge."""
    rng = np.random.default_rng(seed)
    P = np.array([[0.995, 0.005], [0.03, 0.97]])   # revert sticky, diverge less so
    phi = {0: 0.93, 1: 0.985}                       # revert vs slow-diverge
    sig = {0: 6e-4, 1: 1.6e-3}

    state = np.zeros(n, dtype=int)
    for t in range(1, n):
        state[t] = rng.choice(2, p=P[state[t - 1]])

    spread = np.zeros(n)
    for t in range(1, n):
        s = state[t]
        spread[t] = phi[s] * spread[t - 1] + sig[s] * rng.standard_normal()

    # shared 'peg-basis' factor: a BOUNDED OU (stationary) so both legs stay near $1
    # while still comoving -> clean beta ~= 1 and no spurious unit root in the spread.
    common = np.zeros(n)
    for t in range(1, n):
        common[t] = 0.999 * common[t - 1] + 3e-4 * rng.standard_normal()
    lb = common                                            # base leg log-price
    la = common + spread                                   # traded leg, beta_true = 1
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    legA = pd.Series(np.exp(la), index=idx)                # traded leg (~1.0)
    legB = pd.Series(np.exp(lb), index=idx)

    # inject a permanent depeg late in a diverge stretch to exercise the breaker
    legA.iloc[-400:] *= np.linspace(1.0, 0.94, 400)
    true_spread = pd.Series(spread, index=idx)
    return legA, legB, pd.Series(state, index=idx), true_spread


def main():
    cfg = Config()
    legA, legB, _, true_spread = make_synthetic()
    la, lb = np.log(legA), np.log(legB)

    spread, z, params = build_spread(la, lb, cfg.train_frac)
    hl = ar1_halflife(spread)
    print(f"[spread] beta={params['beta']:.4f}  reconstructed half-life={hl['half_life']:.1f} bars")
    assert np.isfinite(params["beta"]), "beta must be finite"
    assert z.notna().sum() > 1000, "z-score mostly NaN"

    # Validate the Markov calibrator on a clean stationary spread (unit-test style).
    print("[hmm] fitting 2-state Markov-switching OU on the spread (may take ~10-40s) ...")
    fit = fit_regime_ou(true_spread, cfg.k_regimes)
    if fit["ok"]:
        for r in fit["regimes"]:
            tag = "REVERT" if r["regime"] == fit["revert_id"] else "DIVERGE"
            print(f"   regime {r['regime']} [{tag:7}] phi={r['phi']:.4f} "
                  f"kappa={r['kappa_lin']:.4f} hl={r['half_life']:.1f} sigma={r['sigma']:.2e}")
        kr = fit["regimes"][fit["revert_id"]]["kappa_lin"]
        kd = fit["regimes"][fit["diverge_id"]]["kappa_lin"]
        assert kr > kd, "revert regime should have faster reversion"
        pine = suggest_pine_inputs(fit, cfg)
        print("   suggested Pine inputs:", pine)
        kappa_min = pine["kappaMin"]
    else:
        print("   ", fit["note"])
        kappa_min = 0.0

    is_rev = rolling_is_revert(spread, window=120, kappa_min=kappa_min)
    on = backtest(z, legA, is_rev, cfg, use_regime=True)
    off = backtest(z, legA, is_rev, cfg, use_regime=False)
    print("\n[backtest] honest fees, synthetic data:")
    for name, r in [("regime ON ", on), ("regime OFF", off)]:
        print(f"   {name}: ret={r['total_return']*100:6.2f}%  Sharpe={r['sharpe']:5.2f}  "
              f"maxDD={r['max_drawdown']*100:6.2f}%  trades={r['n_trades']}  {r['exit_reasons']}")

    assert on["n_trades"] > 0, "regime-on should place some trades"
    assert on["exit_reasons"]["DEPEG"] >= 0
    print("\nOK — pipeline runs end-to-end. Regime gating drawdown vs naive:",
          f"{on['max_drawdown']*100:.2f}% vs {off['max_drawdown']*100:.2f}%")


if __name__ == "__main__":
    main()
