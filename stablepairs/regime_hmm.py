"""The Markov chain, done properly (offline).

Fits a 2-state Markov-switching AR(1) to the spread. Each state has its own AR
coefficient phi -> reversion speed kappa = 1 - phi (Pine convention) and
half-life = ln2 / (-ln phi). The state with faster reversion is REVERT; the other
is DIVERGE (phi near/above 1 = random walk / trending = where pair trades die).

Output: per-regime OU params, transition matrix, expected durations, and a set of
SUGGESTED PINE INPUTS (kappa_min etc.) you paste straight into the hardened strategy.
"""
import numpy as np
import pandas as pd
from statsmodels.tsa.regime_switching.markov_autoregression import MarkovAutoregression


def _params_dict(res) -> dict:
    return dict(zip(res.model.param_names, np.asarray(res.params)))


def fit_regime_ou(spread: pd.Series, k_regimes: int = 2) -> dict:
    """Fit the MS-AR(1). Returns a dict of per-regime OU params + transition info.
    Falls back to a single-regime AR(1) summary if the MS fit fails to converge.
    """
    s = spread.dropna().astype(float)
    # standardize for numerical stability — AR coefficient (hence kappa/half-life)
    # is scale-invariant, so phi is unchanged; only sigma is in std units.
    sd = s.std()
    s_std = (s - s.mean()) / (sd if sd > 0 else 1.0)
    out = {"ok": False, "k": k_regimes, "regimes": [], "note": ""}
    try:
        res = None
        for sw_var in (True, False):     # drop switching-variance if it won't converge
            try:
                mod = MarkovAutoregression(
                    s_std.values, k_regimes=k_regimes, order=1,
                    switching_ar=True, switching_variance=sw_var,
                )
                res = mod.fit(em_iter=50, search_reps=20, disp=False)
                break
            except Exception:
                continue
        if res is None:
            raise RuntimeError("MS-AR did not converge for either variance spec")
        pd_ = _params_dict(res)

        regimes = []
        for r in range(k_regimes):
            phi = float(pd_.get(f"ar.L1[{r}]", np.nan))
            s2 = pd_.get(f"sigma2[{r}]", pd_.get("sigma2", np.nan))  # switching or shared
            sig = float(np.sqrt(max(s2, 0.0))) if np.isfinite(s2) else np.nan
            kappa_lin = 1.0 - phi                       # Pine convention (matches -b)
            half_life = float(np.log(2) / (-np.log(phi))) if 0 < phi < 1 else np.inf
            regimes.append({"regime": r, "phi": phi, "kappa_lin": kappa_lin,
                            "half_life": half_life, "sigma": sig})

        # transition matrix (k x k), stationary durations
        P = np.asarray(res.regime_transition)[:, :, 0] if np.ndim(res.regime_transition) == 3 \
            else np.asarray(res.regime_transition)
        durations = [float(1.0 / (1.0 - P[i, i])) if P[i, i] < 1 else np.inf
                     for i in range(k_regimes)]

        # smoothed P(state) time series
        smp = np.asarray(res.smoothed_marginal_probabilities)

        # order regimes: REVERT = larger kappa_lin (faster pull-back)
        order = sorted(range(k_regimes), key=lambda r: regimes[r]["kappa_lin"], reverse=True)
        revert_id, diverge_id = order[0], order[-1]

        out.update({
            "ok": True, "res": res, "regimes": regimes,
            "P": P, "durations": durations, "smoothed": smp,
            "revert_id": revert_id, "diverge_id": diverge_id,
            "llf": float(res.llf),
        })
    except Exception as e:  # pragma: no cover - solver dependent
        out["note"] = f"MS-AR fit failed ({e}); use rolling AR(1) fallback."
    return out


def suggest_pine_inputs(fit: dict, cfg) -> dict:
    """Turn the regime fit into concrete inputs for the hardened Pine strategy."""
    if not fit.get("ok"):
        return {"note": fit.get("note", "no fit")}
    reg = fit["regimes"]
    kr = reg[fit["revert_id"]]["kappa_lin"]
    kd = reg[fit["diverge_id"]]["kappa_lin"]
    # kappa_min sits between the two states (Pine gates entries above this)
    kappa_min = round(max(0.0, 0.5 * (kr + kd)), 5)
    hl_revert = reg[fit["revert_id"]]["half_life"]
    # a max-hold of a few half-lives is a sane time stop
    max_hold = int(np.clip(3 * hl_revert, 20, 2000)) if np.isfinite(hl_revert) else cfg.max_hold_bars
    return {
        "kappaMin": kappa_min,
        "entryZ": cfg.entry_z,
        "exitZ": cfg.exit_z,
        "stopZ": cfg.stop_z,
        "maxHold": max_hold,
        "revert_half_life_bars": round(hl_revert, 1) if np.isfinite(hl_revert) else None,
        "revert_expected_duration_bars": round(fit["durations"][fit["revert_id"]], 1),
        "diverge_expected_duration_bars": round(fit["durations"][fit["diverge_id"]], 1),
    }
