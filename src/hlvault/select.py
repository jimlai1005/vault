"""Stage 6: drop pure-beta, rank by composite of risk-adjusted alpha +
persistence (DSR, winrate stability), take top-N."""
from __future__ import annotations

import pandas as pd


def rank_and_select(
    df: pd.DataFrame, top_n: int, min_alpha_tstat: float = 2.0
) -> pd.DataFrame:
    survivors = df[df["alpha_tstat"] >= min_alpha_tstat].copy()

    def z(col: str) -> pd.Series:
        s = survivors[col]
        sd = s.std(ddof=0)
        return (s - s.mean()) / sd if sd > 0 else s * 0

    survivors["score"] = z("alpha_tstat") + z("dsr") - z("winrate_stability")
    return survivors.sort_values("score", ascending=False).head(top_n)
