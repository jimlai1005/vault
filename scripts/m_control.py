"""Sub-project M — 匹配隨機對照組。spec §5.4。

只為通過前置守門的事件生成；δ 只取正向 {131..300}；比值平移不重算；
每事件 RNG 由 (SEED, event_id) 決定性派生（與處理順序無關）。
"""
import hashlib
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402


def _event_rng(event_id):
    h = int(hashlib.sha256(f"{cfg.SEED}:{event_id}".encode()).hexdigest(), 16)
    return np.random.default_rng([cfg.SEED, h % (2 ** 32)])


def make_controls(ev, bars_df):
    """單一（已通過守門的）事件 → 至多 K 個對照事件 dict。

    對照欄位與原事件同 schema，另加 delta_bars 與 weight = 1/K_actual。
    窗口超界重抽最多 10 次；仍失敗則捨棄該對照。
    """
    t = bars_df["t"].to_numpy() if not isinstance(bars_df, dict) else bars_df["t"]
    c = bars_df["c"].to_numpy() if not isinstance(bars_df, dict) else bars_df["c"]
    n = len(t)
    bar_ms = int(t[1] - t[0])
    ic0 = int(np.searchsorted(t, ev["as_of"], side="right")) - 1
    anchor0 = float(c[ic0])
    need = cfg.TTL_BARS + cfg.MAX_HOLD_BARS           # 曝險窗
    rng = _event_rng(ev["event_id"])
    out = []
    for k in range(cfg.CONTROL_K):
        ok = False
        for _ in range(10):
            delta = int(rng.integers(cfg.CONTROL_DELTA_MIN,
                                     cfg.CONTROL_DELTA_MAX + 1))
            ic = ic0 + delta
            if ic + 1 + need < n:                     # 完整曝險窗在資料內
                ok = True
                break
        if not ok:
            continue
        anchor = float(c[ic])
        scale = anchor / anchor0
        out.append(dict(
            event_id=f"{ev['event_id']}__ctrl{k}",
            symbol=ev["symbol"], interval=ev["interval"],
            pattern=ev["pattern"], direction=ev["direction"],
            as_of=int(t[ic]) + bar_ms - 1,
            prz_low=ev["prz_low"] * scale, prz_high=ev["prz_high"] * scale,
            sl=ev["sl"] * scale,
            p_X=ev["p_X"] * scale, p_A=ev["p_A"] * scale,
            p_B=ev["p_B"] * scale, p_C=ev["p_C"] * scale,
            delta_bars=delta))
    for x in out:
        x["weight"] = 1.0 / len(out)
    return out


def mapped_term_t(ctrl_trade, bar_ms):
    """spec §5.4 日曆對齊：對照的日報酬記在 term_t − δ·bar_ms。"""
    return int(ctrl_trade["term_t"]) - int(ctrl_trade["delta_bars"]) * bar_ms
