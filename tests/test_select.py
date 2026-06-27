import pandas as pd

from hlvault.select import rank_and_select


def test_select_drops_pure_beta_and_takes_top_n():
    df = pd.DataFrame(
        {
            "address": ["a", "b", "c", "d"],
            "alpha_tstat": [3.0, 2.5, 1.0, 4.0],
            "dsr": [0.9, 0.8, 0.95, 0.99],
            "winrate_stability": [0.1, 0.2, 0.05, 0.05],
        }
    )
    out = rank_and_select(df, top_n=2, min_alpha_tstat=2.0)
    assert "c" not in out["address"].values
    assert len(out) == 2
    assert out.iloc[0]["address"] == "d"
