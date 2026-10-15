import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_sweep as sw

BAR = 3_600_000


def bars(rows):
    a = np.array(rows, dtype=float)
    return pd.DataFrame({"t": np.arange(len(rows), dtype=np.int64) * BAR,
                         "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]})


def test_swept_at_is_first_bar_trading_through():
    """pivot high 於 idx=2（L=2）；idx=6 首次 high>pool -> swept_at=6。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 3 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert len(hi) == 1
    assert int(hi.iloc[0]["swept_at"]) == 6


def test_swept_at_is_n_when_never_swept():
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 6
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert int(hi.iloc[0]["swept_at"]) == len(rows)


def test_swept_at_uses_strict_inequality():
    """等於池價不算掃穿（與 is_sweep 的嚴格不等號一致，P5）。

    highs = [9.5, 9.5, 12.0, 10.0, 11.0, 12.0, 12.5, ...]
    idx=2 是真 pivot high（=窗內最大且嚴格大於左側）；
    idx=5 的 12.0【等於】池價 → 不算掃穿；idx=6 的 12.5 才算 → swept_at = 6。
    """
    rows = [(9, 9.5, 8.5, 9), (9, 9.5, 8.5, 9), (9, 12.0, 8.5, 9),
            (9, 10.0, 8.5, 9), (9, 11.0, 8.5, 9), (9, 12.0, 8.5, 9),
            (9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert len(hi) == 1, "fixture 必須真的產生 idx=2 的 pivot high"
    assert int(hi.iloc[0]["swept_at"]) == 6


def test_swept_at_triggers_on_strict_exceed():
    """對照組：把等於池價的那根改成【稍微超過】，swept_at 必須提前。"""
    rows = [(9, 9.5, 8.5, 9), (9, 9.5, 8.5, 9), (9, 12.0, 8.5, 9),
            (9, 10.0, 8.5, 9), (9, 11.0, 8.5, 9), (9, 12.01, 8.5, 9),
            (9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert int(hi.iloc[0]["swept_at"]) == 5


def test_low_pool_mirrors():
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 9.5, 6.0, 9)] + [(9, 9.5, 8.5, 9)] * 3 \
        + [(9, 9.5, 5.5, 9)] + [(9, 9.5, 8.5, 9)] * 4
    pt = sw.pool_table(bars(rows), L=2)
    lo = pt[(pt["kind"] == "low") & (pt["idx"] == 2)]
    assert int(lo.iloc[0]["swept_at"]) == 6


def test_pool_table_has_confirm_t_and_is_sorted():
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 6.0, 9)] \
        + [(9, 9.5, 8.5, 9)] * 6
    pt = sw.pool_table(bars(rows), L=2)
    assert set(["idx", "kind", "price", "t", "confirm_t", "swept_at"]) <= set(pt.columns)
    assert pt["confirm_t"].is_monotonic_increasing


@pytest.mark.parametrize("k", [9, 11])
def test_pool_table_no_lookahead_for_confirmed_pools(k):
    """截斷不得改變已確認池的 price/confirm_t（swept_at 會因未來未知而不同，
    故只比對前兩者——swept_at 的 PIT 正確性由 selectable_pools 的 as_of 過濾保證）。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 6
    b = bars(rows)
    full = sw.pool_table(b, L=2).set_index(["idx", "kind"])
    tr = sw.pool_table(b.iloc[:k].copy(), L=2).set_index(["idx", "kind"])
    for idx, r in tr.iterrows():
        assert idx in full.index
        assert full.loc[idx, "price"] == pytest.approx(r["price"])
        assert full.loc[idx, "confirm_t"] == r["confirm_t"]


def test_selectable_pools_filters_by_as_of_and_unswept():
    """P9：as_of 時已確認、且 swept_at > j 才算可用。"""
    pt = pd.DataFrame({
        "idx": [1, 2, 3], "kind": ["low"] * 3, "price": [10.0, 9.0, 8.0],
        "t": [0, BAR, 2 * BAR], "confirm_t": [3 * BAR - 1, 4 * BAR - 1, 9 * BAR - 1],
        "swept_at": [5, 99, 99]})
    out = sw.selectable_pools(pt, kind="low", as_of=5 * BAR - 1, j=6, n_last=10)
    assert out["idx"].tolist() == [2]      # idx1 已被掃(5<=6)、idx3 尚未確認


def test_selectable_pools_keeps_only_last_n():
    pt = pd.DataFrame({
        "idx": list(range(10)), "kind": ["low"] * 10,
        "price": [float(i) for i in range(10)],
        "t": [i * BAR for i in range(10)],
        "confirm_t": [(i + 1) * BAR - 1 for i in range(10)],
        "swept_at": [99] * 10})
    out = sw.selectable_pools(pt, kind="low", as_of=100 * BAR, j=50, n_last=3)
    assert out["idx"].tolist() == [7, 8, 9]
