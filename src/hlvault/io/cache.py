"""Parquet cache + as-of filter. The as-of filter is the single structural
gate that makes the OOS backtest lookahead-free (CLAUDE.md #5 forcing function)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd


def apply_asof(
    df: pd.DataFrame, as_of: pd.Timestamp | None, time_col: str = "time"
) -> pd.DataFrame:
    if as_of is None:
        return df
    return df[df[time_col] <= as_of].copy()


def cache_path(cache_dir: str, key: str) -> Path:
    p = Path(cache_dir) / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_or_compute(
    cache_dir: str, key: str, compute: Callable[[], pd.DataFrame]
) -> pd.DataFrame:
    p = cache_path(cache_dir, key)
    if p.exists():
        return pd.read_parquet(p)
    df = compute()
    df.to_parquet(p)
    return df
