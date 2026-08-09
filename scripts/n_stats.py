"""Sub-project N — 事件層統計。spec §7.3、§7.4。

主要統計量是【每事件 E[R]】而非日報酬均值（P16）——日報酬與交易頻率相依，
跨格比較無效。M2 的 B5 事故即源於此：對照臂曝險達事件臂的 1.19~7.52 倍時，
兩臂皆負 EV 的逐日配對差會機械性轉正。

自助法以 symbol 為叢集重抽（P17），尊重同幣事件的相依性。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
from m_stats import gate_rng  # noqa: E402


def exposure_ratio(n_events, ctl_weight_sum):
    return float(ctl_weight_sum) / max(float(n_events), 1e-12)


def exposure_ok(ratio):
    lo, hi = cfg.EXPOSURE_BAND
    return bool(lo <= float(ratio) <= hi)


def weighted_event_mean(df):
    """加權每事件 E[R]。無 weight 欄視為每列權重 1。"""
    if len(df) == 0:
        return float("nan")
    w = df["weight"].to_numpy(dtype=float) if "weight" in df else np.ones(len(df))
    r = df["R_net"].to_numpy(dtype=float)
    return float((r * w).sum() / max(w.sum(), 1e-12))


def _cluster_stats(df):
    """依 symbol 聚合出 (Σ w·R, Σ w)，供叢集自助法用。"""
    w = df["weight"].to_numpy(dtype=float) if "weight" in df else np.ones(len(df))
    g = pd.DataFrame({"symbol": df["symbol"].to_numpy(),
                      "wr": df["R_net"].to_numpy(dtype=float) * w,
                      "w": w}).groupby("symbol", sort=True).sum()
    return g


def cluster_boot_lower95(arm_a, arm_b, gate_id, B=None):
    """lower_95 of (E[R]_a − E[R]_b)，以 symbol 為叢集重抽。

    arm_b 傳 None 時退化為單臂的 lower_95(E[R])。
    """
    B = cfg.BOOTSTRAP_B if B is None else B
    ga = _cluster_stats(arm_a)
    gb = _cluster_stats(arm_b) if arm_b is not None else None
    syms = sorted(set(ga.index) | (set(gb.index) if gb is not None else set()))
    a_wr = np.array([float(ga["wr"].get(s, 0.0)) for s in syms])
    a_w = np.array([float(ga["w"].get(s, 0.0)) for s in syms])
    if gb is not None:
        b_wr = np.array([float(gb["wr"].get(s, 0.0)) for s in syms])
        b_w = np.array([float(gb["w"].get(s, 0.0)) for s in syms])

    def stat(ix):
        a = a_wr[ix].sum() / max(a_w[ix].sum(), 1e-12)
        if gb is None:
            return a
        return a - b_wr[ix].sum() / max(b_w[ix].sum(), 1e-12)

    rng = gate_rng(gate_id)
    n = len(syms)
    boot = np.array([stat(rng.integers(0, n, n)) for _ in range(int(B))])
    return float(np.percentile(boot, 5.0))
