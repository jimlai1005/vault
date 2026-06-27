"""Stage 2: pluggable data sources + normalization to canonical frames."""
from __future__ import annotations

from typing import Protocol

import pandas as pd


class FillSource(Protocol):
    def get_fills(self, address: str, start=None, end=None) -> list[dict]: ...


class PriceSource(Protocol):
    def get_ohlcv(
        self, coin: str, interval: str, start=None, end=None
    ) -> pd.DataFrame: ...


_FILL_COLS = ["time", "coin", "sz", "px", "signed_sz", "closedPnl", "fee"]


def fills_to_frame(raw: list[dict]) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=_FILL_COLS)
    df = pd.DataFrame(raw)
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms")
    for col in ("sz", "px", "closedPnl", "fee"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["signed_sz"] = df.apply(
        lambda r: r["sz"] if r["side"] == "B" else -r["sz"], axis=1
    )
    return df[_FILL_COLS]
