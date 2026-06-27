"""End-to-end wiring. The live data path (universe->ingest->equity) feeds the
same `panel` the synthetic smoke test uses, so the analytic core is identical
in test and production."""
from __future__ import annotations

import argparse

import pandas as pd

from .backtest import walk_forward
from .report import Verdict, verdict, write_report
from .weights import hrp_weights


def run_backtest_pipeline(
    panel: pd.DataFrame,
    btc: pd.Series,
    top_n: int,
    report_path,
    rebalance_days: int = 30,
    horizon_days: int = 30,
) -> Verdict:
    def select(as_of, past):
        sd = past.std(ddof=1)
        scores = (past.mean() / sd.where(sd > 0)).dropna()
        chosen = scores.nlargest(min(top_n, len(scores))).index
        if len(chosen) == 0:
            return pd.Series(dtype=float)
        return hrp_weights(past[chosen])

    res = walk_forward(panel, select, rebalance_days, horizon_days)
    btc_oos = btc.reindex(res.oos_returns.index).fillna(0.0)
    v = verdict(res.oos_returns, btc_oos)
    final_w = select(panel.index.max(), panel)
    write_report(report_path, v, pd.DataFrame(), final_w)
    return v


def main(argv=None):
    p = argparse.ArgumentParser(prog="hl-vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backtest")
    sub.add_parser("select")
    sub.add_parser("report")
    args = p.parse_args(argv)
    raise SystemExit(f"cmd={args.cmd} (wire to cached parquet panels)")
