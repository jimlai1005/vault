"""Stage 9: verdict + report. GO iff OOS mean return significantly > 0 AND the
OOS Sharpe beats BTC buy-hold. Honest about the realized OOS expectation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from scipy import stats

from .metrics import max_drawdown, sharpe


@dataclass
class Verdict:
    decision: str
    oos_tstat: float
    oos_sharpe: float
    btc_sharpe: float
    oos_mdd: float
    note: str


def verdict(oos_returns: pd.Series, btc_returns: pd.Series) -> Verdict:
    clean = oos_returns.dropna()
    if len(clean) < 3:
        return Verdict("NO-GO", 0.0, 0.0, 0.0, 0.0, "Insufficient OOS sample.")
    t, p = stats.ttest_1samp(clean, 0.0)
    osr = sharpe(clean)
    bsr = sharpe(btc_returns.dropna())
    mdd = max_drawdown((1 + clean).cumprod())
    go = (t > 2.0) and (p < 0.05) and (osr > bsr)
    decision = "GO" if go else "NO-GO"
    note = (
        "Past winners show significant OOS alpha beating BTC."
        if go
        else "Thesis NOT confirmed OOS — do not deploy capital."
    )
    return Verdict(decision, float(t), float(osr), float(bsr), float(mdd), note)


def write_report(
    path, verdict_obj: Verdict, selection: pd.DataFrame, weights: pd.Series
) -> None:
    lines = [
        f"# OOS Verdict: {verdict_obj.decision}",
        "",
        verdict_obj.note,
        "",
        f"- OOS t-stat: {verdict_obj.oos_tstat:.2f}",
        f"- OOS Sharpe: {verdict_obj.oos_sharpe:.2f} "
        f"(BTC {verdict_obj.btc_sharpe:.2f})",
        f"- OOS max drawdown: {verdict_obj.oos_mdd:.1%}",
        "",
        "## Selected traders + weights",
        "",
        weights.to_frame("weight").to_markdown(),
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines))
