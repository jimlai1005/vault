import numpy as np
import pandas as pd

from hlvault.cli import run_backtest_pipeline


def test_pipeline_produces_verdict(tmp_path):
    rng = np.random.default_rng(11)
    idx = pd.date_range("2025-01-01", periods=400, freq="D")
    panel = pd.DataFrame(
        rng.normal(0.001, 0.01, (400, 8)),
        index=idx,
        columns=[f"t{i}" for i in range(8)],
    )
    btc = pd.Series(rng.normal(0.0, 0.02, 400), index=idx)
    out = run_backtest_pipeline(panel, btc, top_n=3, report_path=tmp_path / "v.md")
    assert out.decision in ("GO", "NO-GO")
    assert (tmp_path / "v.md").exists()
