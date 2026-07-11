"""Discovery: find which stablecoin pairs the exchange ACTUALLY lists (with liquidity),
then rank every combination by cointegration strength.

This is the answer to "if XUSD isn't there, try other stablecoins" — it's automatic.
"""
import itertools
import numpy as np
import pandas as pd
import ccxt
from statsmodels.tsa.stattools import coint

from data import load_series


def available_symbols(cfg) -> list:
    """Stablecoin/quote symbols that are listed, active, and above the volume floor."""
    ex = getattr(ccxt, cfg.exchange)({"enableRateLimit": True})
    markets = ex.load_markets()
    try:
        tickers = ex.fetch_tickers()
    except Exception:
        tickers = {}
    out = []
    for base in cfg.stable_universe:
        sym = f"{base}/{cfg.quote}"
        m = markets.get(sym)
        if not m or not m.get("active", True):
            continue
        qv = (tickers.get(sym) or {}).get("quoteVolume")
        if qv is not None and qv < cfg.min_quote_volume_usd:
            continue
        out.append(sym)
    return out


def rank_pairs(cfg, min_overlap: int = 2000) -> pd.DataFrame:
    """Engle-Granger cointegration p-value for every listed stablecoin combination.
    Lower p = tighter long-run equilibrium = better pair candidate.
    """
    syms = available_symbols(cfg)
    series = {}
    for s in syms:
        try:
            series[s] = load_series(s, cfg)["close"]
        except Exception as e:  # pragma: no cover - network dependent
            print(f"  skip {s}: {e}")

    rows = []
    for a, b in itertools.combinations(series, 2):
        df = pd.concat([series[a], series[b]], axis=1, keys=["a", "b"]).dropna()
        if len(df) < min_overlap:
            continue
        la, lb = np.log(df["a"].values), np.log(df["b"].values)
        try:
            _, pval, _ = coint(la, lb)
        except Exception:
            continue
        rows.append({"legA": a, "legB": b, "n": len(df), "coint_p": float(pval)})

    if not rows:
        return pd.DataFrame(columns=["legA", "legB", "n", "coint_p"])
    return pd.DataFrame(rows).sort_values("coint_p").reset_index(drop=True)
