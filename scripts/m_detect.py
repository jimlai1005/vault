"""Sub-project M — 偵測器。spec §4。

【因果性】本模組的每一個輸出都只能由 close_time <= as_of 的 K 線算出。
spec §4.1.1 的合併規則是最容易寫錯的一段：v2 的版本因為需要知道「同型段何時
結束」而引入 look-ahead，且 M-G1 的斷言方向錯誤而抓不到。
"""
import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402


@dataclass(frozen=True)
class Pivot:
    idx: int
    kind: str          # "high" | "low"
    price: float
    t: int
    confirm_idx: int
    confirm_t: int


def find_pivots(df, L):
    """spec §4.1：high[i] == max(high[i-L..i+L])，平手取最早；頭尾 L 根不判定。"""
    # 強制 float：int64 輸入會讓 .max(initial=-inf) 拋 OverflowError
    highs = df["h"].values.astype(float)
    lows = df["l"].values.astype(float)
    ts = df["t"].values
    n = len(df)
    out = []
    for i in range(L, n - L):
        win_h = highs[i - L:i + L + 1]
        if highs[i] == win_h.max() and highs[i] > highs[i - L:i].max(initial=float("-inf")):
            out.append(Pivot(i, "high", float(highs[i]), int(ts[i]),
                             i + L, int(ts[i + L])))
        win_l = lows[i - L:i + L + 1]
        if lows[i] == win_l.min() and lows[i] < lows[i - L:i].min(initial=float("inf")):
            out.append(Pivot(i, "low", float(lows[i]), int(ts[i]),
                             i + L, int(ts[i + L])))
    return sorted(out, key=lambda p: (p.idx, p.kind))


def normalize_alternating(df, L, as_of_idx):
    """spec §4.1.1 因果式合併。

    只使用 confirm_idx <= as_of_idx 的 pivot（在 as_of 當下已確認者）。
    連續同型段：【已封閉】者取極值（封閉 = 其後已出現異型 pivot）；
    【未封閉】的最後一段取截至 as_of 為止的 running extreme。
    兩者在本實作中是同一段程式——因為只掃描已確認的 pivot，未封閉段自然
    只看得到 as_of 之前的成員。
    """
    piv = [p for p in find_pivots(df, L) if p.confirm_idx <= as_of_idx]
    seq = []
    for p in piv:
        if seq and seq[-1].kind == p.kind:
            prev = seq[-1]
            better = (p.price > prev.price) if p.kind == "high" else (p.price < prev.price)
            if better:
                seq[-1] = p                       # 同段內取較極端者
            # 價格平手或較差 → 保留較早者（spec §4.1.1）
        else:
            seq.append(p)
    return seq
