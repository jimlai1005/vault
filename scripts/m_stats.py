"""Sub-project M — 統計層。spec §6.1。

M-G2/G3/G4 全在同一條日報酬序列上計算；Sharpe 一律未年化日 SR（ddof=1）；
lower_95 = percentile method 單尾第 5 百分位。
"""
import hashlib
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402

from cta_l_stage1_gates import stationary_bootstrap_indices  # noqa: E402

DAY_MS = 86_400_000


def percentile_lower_95(boot):
    """spec §6.1：numpy.percentile(boot, 5.0)。錨例 −0.150005。"""
    return float(np.percentile(np.asarray(boot), 5.0))


def daily_sr(r):
    r = pd.Series(r).dropna()
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else 0.0


def daily_series(trades, weight_col="weight"):
    """trades(R_net, term_t[, weight]) → 連續 UTC 日曆日的 r_d Series。

    r_d = RISK_PER_TRADE × Σ weight·R_net（term_t 所屬日）；無事件日 r_d = 0。
    """
    t = trades.copy()
    if weight_col not in t:
        t[weight_col] = 1.0
    t["day"] = (t["term_t"] // DAY_MS).astype(int)
    g = (t["R_net"] * t[weight_col]).groupby(t["day"]).sum() * cfg.RISK_PER_TRADE
    full = pd.RangeIndex(int(g.index.min()), int(g.index.max()) + 1)
    return g.reindex(full, fill_value=0.0)


def gate_rng(gate_id):
    """spec §6.1：每 gate 以 (SEED, gate_id) 派生子種子，可複現且互不干擾。"""
    h = int(hashlib.sha256(f"{cfg.SEED}:{gate_id}".encode()).hexdigest(), 16)
    return np.random.default_rng([cfg.SEED, h % (2 ** 32)])


def _boot_stat(values, stat_fn, gate_id, B):
    v = np.asarray(values, dtype=float)
    n = len(v)
    rng = gate_rng(gate_id)
    seed = int(rng.integers(0, 2 ** 31 - 1))
    idx = stationary_bootstrap_indices(n, B, cfg.BOOTSTRAP_EXPECTED_BLOCK,
                                       seed=seed)
    return np.array([stat_fn(v[row]) for row in idx])


def lower_95_of_mean(series, gate_id, B=None):
    B = cfg.BOOTSTRAP_B if B is None else B
    boot = _boot_stat(np.asarray(series, dtype=float), np.mean, gate_id, B)
    return percentile_lower_95(boot)


def lower_95_of_paired_diff(series_a, series_b, gate_id, B=None):
    """配對 stationary bootstrap：兩序列等長、逐日對齊，同一組索引重抽。"""
    a = np.asarray(series_a, dtype=float)
    b = np.asarray(series_b, dtype=float)
    assert len(a) == len(b), "配對 bootstrap 要求等長對齊序列（spec §5.4）"
    B = cfg.BOOTSTRAP_B if B is None else B
    boot = _boot_stat(a - b, np.mean, gate_id, B)
    return percentile_lower_95(boot)
