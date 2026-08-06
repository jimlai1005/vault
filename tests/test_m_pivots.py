import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import m_detect


def _bars(highs, lows):
    n = len(highs)
    return pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                         "o": lows, "h": highs, "l": lows, "c": highs,
                         "v": [1.0] * n, "qv": [1.0] * n})


def test_pivot_needs_full_window_on_both_sides():
    # L=2：索引 0,1 與 n-2,n-1 不得成為 pivot（spec §4.1 邊界）
    highs = [1, 2, 9, 2, 1, 2, 1]
    df = _bars(highs, [-h for h in highs])
    piv = m_detect.find_pivots(df, L=2)
    assert all(2 <= p.idx <= len(df) - 3 for p in piv)
    assert any(p.idx == 2 and p.kind == "high" for p in piv)


def test_pivot_confirm_time_is_L_bars_later():
    highs = [1, 2, 9, 2, 1, 2, 1]
    df = _bars(highs, [-h for h in highs])
    p = [x for x in m_detect.find_pivots(df, L=2) if x.idx == 2][0]
    assert p.confirm_idx == 4
    assert p.confirm_t == int(df["t"].iloc[4])


def test_ties_resolve_to_earliest_bar():
    highs = [1, 5, 2, 5, 1, 0, 1]        # 索引 1 與 3 同高
    df = _bars(highs, [-h for h in highs])
    piv = [p for p in m_detect.find_pivots(df, L=1) if p.kind == "high"]
    assert min(p.idx for p in piv) == 1


def test_closed_run_takes_extreme_open_run_takes_running_extreme():
    """spec §4.1.1：連續同型段合併取極值；合併只用 as_of 前【已確認】的 pivot。

    fixture 結構（L=1，已逐點驗算）：
      pivot high@1 (5, confirm 2)、pivot high@3 (8, confirm 4)——兩者之間的
      lows 嚴格遞增故【無 pivot low】，構成連續同型段；
      pivot low@5 (-5, confirm 6) 封段；pivot high@6 (4, confirm 7)。
    """
    highs = [1, 5, 2, 8, 3, 3, 4, 3]
    lows = [0.0, 0.5, 0.8, 1.0, 1.5, -5.0, 0.0, 0.5]
    df = _bars(highs, lows)

    # as_of=2：只有 high@1 已確認 → running extreme 就是它
    seq = m_detect.normalize_alternating(df, L=1, as_of_idx=2)
    assert [(p.kind, p.idx) for p in seq] == [("high", 1)]

    # as_of=4：high@1 與 high@3 皆確認、之間無已確認 pivot low
    #          → 同段合併取極值（idx 3, price 8）
    seq = m_detect.normalize_alternating(df, L=1, as_of_idx=4)
    assert [(p.kind, p.idx) for p in seq] == [("high", 3)]

    # as_of=7：low@5 與 high@6 亦確認 → 完整交替序列
    seq = m_detect.normalize_alternating(df, L=1, as_of_idx=7)
    assert [(p.kind, p.idx) for p in seq] == [("high", 3), ("low", 5), ("high", 6)]


def test_truncation_identity_randomized():
    """因果恆等式回歸防線（Task 5 sonnet 審查建議併入）。

    對任意截斷時刻 T：normalize_alternating(截斷資料, L, T) 必須恆等於
    normalize_alternating(完整資料, L, T)——這是「零 look-ahead」的數學定義。
    fixture 測試靠特定期望值間接驗證，抓不到未來重新引入的 look-ahead。
    """
    import numpy as np
    rng = np.random.default_rng(11)
    n = 300
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                       "o": close, "h": close * (1 + rng.uniform(0, 0.005, n)),
                       "l": close * (1 - rng.uniform(0, 0.005, n)), "c": close,
                       "v": 1.0, "qv": 1.0})
    for L in (2, 5, 10):
        for T in (60, 150, 240):
            full = m_detect.normalize_alternating(df, L, as_of_idx=T)
            trunc = m_detect.normalize_alternating(
                df.iloc[:T + 1].reset_index(drop=True), L, as_of_idx=T)
            assert full == trunc, f"L={L} T={T}: 截斷改變了序列（look-ahead！）"


def test_sequence_strictly_alternates():
    highs = [0, 1, 5, 1, 0, 1, 8, 1, 0, 0, 1, 0]
    lows = [0, 0, 0, 0, 1, 0, 0, 0, 1, -5, 0, 0]
    seq = m_detect.normalize_alternating(_bars(highs, lows), L=1, as_of_idx=11)
    kinds = [p.kind for p in seq]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
