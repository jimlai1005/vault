import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd

import m_config as cfg
import m_stats as ms

DAY = 86_400_000


def test_lower_95_anchor():
    """spec §6.1 錨例。"""
    boot = np.arange(10000) / 10000 - 0.2
    assert abs(ms.percentile_lower_95(boot) - (-0.150005)) < 1e-9


def test_daily_series_aggregation():
    """r_d = 0.01 × Σ R_net（同終止日），無事件日補 0，範圍連續。"""
    trades = pd.DataFrame({
        "R_net": [1.0, -0.5, 2.0, 0.0],
        "term_t": [0 * DAY + 5, 0 * DAY + 9, 2 * DAY + 1, 2 * DAY + 2],
        "weight": [1.0, 1.0, 1.0, 1.0]})
    s = ms.daily_series(trades)
    assert list(s.values) == [0.01 * 0.5, 0.0, 0.01 * 2.0]   # 三天連續，中間補 0
    assert len(s) == 3


def test_daily_sr_uses_ddof1():
    r = pd.Series([0.01, -0.02, 0.03, 0.0])
    assert abs(ms.daily_sr(r) - r.mean() / r.std(ddof=1)) < 1e-12


def test_bootstrap_deterministic_per_gate():
    rng_a = ms.gate_rng("M-G2")
    rng_b = ms.gate_rng("M-G2")
    rng_c = ms.gate_rng("M-G3")
    a, b, c = (r.integers(0, 1000, 5).tolist() for r in (rng_a, rng_b, rng_c))
    assert a == b and a != c


def test_lower95_of_mean_smoke():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(0.5, 1.0, 800))
    lo = ms.lower_95_of_mean(x, gate_id="TEST", B=500)
    assert 0.3 < lo < 0.5                             # 均值 0.5 的下界應在其下不遠處
