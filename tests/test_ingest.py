import pandas as pd

from hlvault.ingest import fills_to_frame


def test_fills_to_frame_normalizes_units():
    raw = [
        {
            "time": 1704067200000,
            "coin": "BTC",
            "sz": "0.1",
            "px": "40000",
            "side": "B",
            "closedPnl": "0",
            "fee": "0.4",
        }
    ]
    df = fills_to_frame(raw)
    assert df.loc[0, "coin"] == "BTC"
    assert df.loc[0, "sz"] == 0.1
    assert df.loc[0, "px"] == 40000.0
    assert df.loc[0, "signed_sz"] == 0.1
    assert isinstance(df.loc[0, "time"], pd.Timestamp)


def test_empty_fills_returns_empty_frame():
    df = fills_to_frame([])
    assert df.empty
    assert "signed_sz" in df.columns
