"""Sub-project N — 匹配隨機對照組與曝險對齊。spec §7。

對照事件在【它自己的】掃單棒上重算訂單流特徵（P14），不沿用母事件的值。
兩臂共用同一個過濾器入口（FILTER_ENTRYPOINT），由測試斷言——公平性是
結構保證，不靠實作者記得。
"""
import hashlib
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_features as nf  # noqa: E402

FILTER_ENTRYPOINT = nf.arm_pass


def event_rng(event_id):
    h = int(hashlib.sha256(f"{cfg.SEED}:{event_id}".encode()).hexdigest(), 16)
    return np.random.default_rng([cfg.SEED, h % (2 ** 32)])


def make_controls(e, bars, n_bars):
    """單一事件 → 至多 K 個位移對照。價位按 close 比值平移（spec §7.1）。"""
    c = bars["c"]
    j0 = int(e["j"])
    anchor0 = float(c[j0])
    rng = event_rng(e["event_id"])
    out = []
    for k in range(cfg.CONTROL_K):
        placed = False
        for _ in range(10):
            delta = int(rng.integers(cfg.CONTROL_DELTA_MIN,
                                     cfg.CONTROL_DELTA_MAX + 1))
            j = j0 + delta
            if j + 1 + cfg.MAX_HOLD_BARS < n_bars:
                placed = True
                break
        if not placed:
            continue
        scale = float(c[j]) / anchor0
        bar_ms = int(bars["t"][1] - bars["t"][0])
        out.append(dict(
            event_id=f"{e['event_id']}__ctrl{k}", parent_id=e["event_id"],
            symbol=e["symbol"], interval=e["interval"], j=j,
            t_j=int(bars["t"][j]), as_of=int(bars["t"][j]) + bar_ms - 1,
            direction=int(e["direction"]), pool=float(e["pool"]) * scale,
            pool_t=int(bars["t"][j]) - (int(e["t_j"]) - int(e["pool_t"])),
            sweep_high=float(e["sweep_high"]) * scale,
            sweep_low=float(e["sweep_low"]) * scale,
            close_j=float(c[j]), delta_bars=delta))
    return out


def renormalize_weights(ct):
    """P15：每個母事件的存活對照，權重合計恰為 1。

    【必須在過濾之後重算】——沿用生成時的 1/K 會讓被過濾掉的名額憑空消失，
    使對照臂權重總和 < 1、系統性低估對照臂（方向恰好有利事件臂）。
    """
    out = ct.copy()
    out["weight"] = 1.0 / out.groupby("parent_id")["R_net"].transform("size")
    return out
