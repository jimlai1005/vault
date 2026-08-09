import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_sweep as sw

BAR = 3_600_000


def bars(rows):
    """rows: (o, h, l, c)。t 由 0 起每根 BAR。"""
    a = np.array(rows, dtype=float)
    return pd.DataFrame({"t": np.arange(len(rows), dtype=np.int64) * BAR,
                         "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]})


def test_unswept_true_until_exceeded():
    h = np.array([10.0, 9.0, 9.5, 9.9])
    assert sw.is_unswept(h, pool=10.0, i=0, j=4, kind="high") is True
    h2 = np.array([10.0, 9.0, 10.1, 9.9])
    assert sw.is_unswept(h2, pool=10.0, i=0, j=4, kind="high") is False


def test_unswept_excludes_forming_bar_itself():
    """池所在那根棒不算把自己掃掉。"""
    h = np.array([10.0, 9.0])
    assert sw.is_unswept(h, pool=10.0, i=0, j=2, kind="high") is True


def test_sweep_requires_strict_penetration_and_strict_reclaim():
    """P5：high[j] > P 嚴格；close[j] < P 嚴格。等號一律不算。"""
    assert sw.is_sweep(high=10.1, low=9.0, close=9.9, pool=10.0, direction=-1) is True
    assert sw.is_sweep(high=10.0, low=9.0, close=9.9, pool=10.0, direction=-1) is False
    assert sw.is_sweep(high=10.1, low=9.0, close=10.0, pool=10.0, direction=-1) is False


def test_sweep_mirrors_for_bullish():
    assert sw.is_sweep(high=11.0, low=9.9, close=10.1, pool=10.0, direction=+1) is True
    assert sw.is_sweep(high=11.0, low=10.0, close=10.1, pool=10.0, direction=+1) is False
    assert sw.is_sweep(high=11.0, low=9.9, close=10.0, pool=10.0, direction=+1) is False


def test_pick_nearest_pool_to_close():
    """P6：一棒掃到多個池時取價格上離 close 最近的。"""
    assert sw.pick_pool([10.0, 10.5, 11.0], close=9.8) == 10.0
    assert sw.pick_pool([10.0, 10.5, 11.0], close=10.9) == 11.0


def test_build_events_finds_bearish_sweep():
    """pivot high 於 idx=2（L=2 -> confirm 於 idx=4），idx=7 掃它。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 5
    ev = sw.build_events(bars(rows), symbol="X", interval="1h", L=2)
    assert len(ev) >= 1
    e = ev[ev["j"] == 7].iloc[0]
    assert e["direction"] == -1
    assert e["pool"] == pytest.approx(12.0)
    assert e["as_of"] == 7 * BAR + BAR - 1


def test_build_events_respects_pool_confirmation_time():
    """未確認的 pivot 不得使用：L=2 的 pivot 要到 idx+2 收盤才確認。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 12.5, 8.5, 9)] \
        + [(9, 9.5, 8.5, 9)] * 6
    ev = sw.build_events(bars(rows), symbol="X", interval="1h", L=2)
    assert (ev["j"] > 4).all() if len(ev) else True


@pytest.mark.parametrize("k", [9, 11, 13])
def test_no_lookahead_truncation(k):
    """N-G1：只餵前 k 根，前 k 根內偵測到的事件必須與全量一致。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 6
    b = bars(rows)
    full = sw.build_events(b, "X", "1h", L=2)
    trunc = sw.build_events(b.iloc[:k].copy(), "X", "1h", L=2)
    keep = full[full["j"] < k - 2]          # 尾端 L 根的 pivot 尚未確認，不比較
    for _, r in keep.iterrows():
        m = trunc[trunc["j"] == r["j"]]
        assert len(m) == 1, f"截斷後遺失事件 j={r['j']}"
        assert m.iloc[0]["pool"] == pytest.approx(r["pool"])
        assert m.iloc[0]["direction"] == r["direction"]
