"""Score arbitrary wallet addresses with the same engine used for the vault
study: reconstruct equity from fills, then risk-adjusted + alpha-vs-BTC/ETH
metrics. Fetches each address fresh from the public API (these are outside the
cached 300-candidate set).

    python scripts/analyze_addresses.py 0xabc... 0xdef...
"""
from __future__ import annotations

import json
import sys
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.factors import alpha_beta  # noqa: E402
from hlvault.io.hl_api import HLApiFillSource  # noqa: E402
from hlvault.ingest import fills_to_frame  # noqa: E402
from hlvault.metrics import deflated_sharpe, max_drawdown, sharpe, sortino  # noqa: E402
from hlvault.prices import get_daily_returns  # noqa: E402
from hlvault.reconstruct import daily_pnl_panel, returns_panel  # noqa: E402

ARCHIVE_START_MS = int(pd.Timestamp("2025-07-27").timestamp() * 1000)


def _post(body: dict):
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=25))


def account_value(addr: str) -> float:
    st = _post({"type": "clearinghouseState", "user": addr})
    try:
        return float(st["marginSummary"]["accountValue"])
    except Exception:
        return 0.0


def is_vault(addr: str) -> bool:
    try:
        d = _post({"type": "vaultDetails", "vaultAddress": addr})
        return bool(d)
    except Exception:
        return False


def analyze(addr: str, btc: pd.Series, eth: pd.Series) -> dict:
    src = HLApiFillSource()
    raw = src.get_fills_paginated(addr, start=ARCHIVE_START_MS, max_pages=80)
    av = account_value(addr)
    vault = is_vault(addr)
    if not raw:
        return {"address": addr, "status": "no fills via API", "vault": vault, "acctVal": av}
    df = fills_to_frame(raw)
    df["user"] = addr.lower()
    pnl = daily_pnl_panel(df)
    panel = returns_panel(pnl, {addr.lower(): av if av > 0 else 1.0})
    if addr.lower() not in panel.columns:
        return {"address": addr, "status": "unreconstructable equity",
                "vault": vault, "acctVal": av, "fills": len(raw)}
    r = panel[addr.lower()].dropna()
    span = (r.index.max() - r.index.min()).days
    active = int((r != 0).sum())
    try:
        fit = alpha_beta(r, btc.reindex(r.index), eth.reindex(r.index))
        a_t, a_d, bbtc = fit.alpha_tstat, fit.alpha, fit.beta_btc
    except Exception:
        a_t = a_d = bbtc = float("nan")
    return {
        "address": addr, "status": "ok", "vault": vault, "acctVal": av,
        "fills": len(raw), "span_days": span, "active_days": active,
        "total_realized_pnl": float((df["closedPnl"] - df["fee"]).sum()),
        "Sharpe": sharpe(r), "Sortino": sortino(r), "maxDD": max_drawdown((1 + r).cumprod()),
        "winrate": float((r > 0).mean()), "alpha_tstat": a_t, "alpha_daily": a_d,
        "beta_btc": bbtc, "DSR": deflated_sharpe(r, n_trials=1),
    }


def verdict(m: dict) -> str:
    if m["status"] != "ok":
        return f"INSUFFICIENT DATA — {m['status']}"
    flags = []
    if m["vault"]:
        flags.append("IS A VAULT (not an individual trader)")
    if m["span_days"] < 180:
        flags.append(f"short history ({m['span_days']}d < 6mo)")
    if not np.isfinite(m["alpha_tstat"]) or m["alpha_tstat"] < 2.0:
        flags.append(f"no significant alpha (t={m['alpha_tstat']:.2f})")
    if m["Sharpe"] < 1.0:
        flags.append(f"weak Sharpe ({m['Sharpe']:.2f})")
    if m["DSR"] < 0.9:
        flags.append(f"low deflated-Sharpe confidence ({m['DSR']:.2f})")
    if not flags:
        return "PASSES the bar — significant alpha, solid risk-adjusted return"
    return "DOES NOT meet the mirror bar: " + "; ".join(flags)


def main() -> None:
    addrs = sys.argv[1:]
    btc = pd.read_parquet("data/cache/prices.parquet")["btc"].dropna()
    eth = pd.read_parquet("data/cache/prices.parquet")["eth"].dropna()
    for a in addrs:
        m = analyze(a, btc, eth)
        print("\n" + "=" * 78)
        print(f"ADDRESS  {a}")
        if m["status"] != "ok":
            print(f"  status      : {m['status']}  (vault={m.get('vault')}, "
                  f"acctVal=${m.get('acctVal',0):,.0f}, fills={m.get('fills',0)})")
            print(f"  VERDICT     : {verdict(m)}")
            continue
        print(f"  vault?      : {m['vault']}    account value: ${m['acctVal']:,.0f}")
        print(f"  history     : {m['span_days']}d span, {m['active_days']} active days, "
              f"{m['fills']:,} fills (API window)")
        print(f"  realized PnL: ${m['total_realized_pnl']:,.0f}")
        print(f"  Sharpe {m['Sharpe']:.2f}  Sortino {m['Sortino']:.2f}  "
              f"maxDD {m['maxDD']:.1%}  winrate {m['winrate']:.1%}")
        print(f"  alpha/day {m['alpha_daily']:.5f}  alpha t-stat {m['alpha_tstat']:.2f}  "
              f"beta_btc {m['beta_btc']:.2f}  DSR {m['DSR']:.2f}")
        print(f"  VERDICT     : {verdict(m)}")


if __name__ == "__main__":
    main()
