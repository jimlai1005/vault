import pandas as pd

from hlvault.io.cache import apply_asof


def test_asof_filters_future_rows():
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
            "v": [1, 2, 3],
        }
    )
    out = apply_asof(df, as_of=pd.Timestamp("2026-02-15"), time_col="time")
    assert list(out["v"]) == [1, 2]


def test_asof_none_passthrough():
    df = pd.DataFrame({"time": pd.to_datetime(["2026-01-01"]), "v": [1]})
    out = apply_asof(df, as_of=None, time_col="time")
    assert list(out["v"]) == [1]
