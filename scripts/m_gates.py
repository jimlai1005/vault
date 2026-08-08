"""Sub-project M — M-G2~G7 與判定表。spec §6.3~§6.7。

任何 gate 失敗都不得由作者裁量覆蓋（spec §6.6）。
"""
import hashlib
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg      # noqa: E402
import m_stats as ms        # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from k_gates_eval import deflated_sharpe  # noqa: E402


def split_is_oos(trades):
    t = trades.copy()
    t["is_is"] = t["as_of"] <= cfg.IS_END_MS
    return t


def is_holdout(symbol):
    return int(hashlib.sha256(symbol.encode("utf-8")).hexdigest(), 16) % 2 == 1


def check_sr_list(sr_list):
    assert len(sr_list) == cfg.N_OBSERVABLE_TRIALS == 480, (
        f"sr_list={len(sr_list)}，spec §6.3 要求恰為 480")


def gate_g2(series):
    return ms.lower_95_of_mean(series, gate_id="M-G2")


def gate_g3(series_pattern, series_control):
    return ms.lower_95_of_paired_diff(series_pattern, series_control,
                                      gate_id="M-G3")


def gate_g4(sr_list, primary_oos_series):
    check_sr_list(sr_list)
    res = deflated_sharpe(sr_list, pd.Series(primary_oos_series),
                          n_trials_declared=cfg.N_TRIALS_DECLARED)
    return res


def verdict(g):
    """spec §6.6 判定表。g = dict(G2..G7 -> bool)。"""
    if not g["G2"]:
        return "NO-GO"
    if not g["G3"]:
        return "NO-GO"
    if not g["G4"]:
        return "NO-GO（多重檢定未通過）"
    if not (g["G5"] and g["G6"]):
        return "NO-GO（過擬合）"
    if not g["G7"]:
        return "NO-GO（成本邊際）"
    return "GO"
