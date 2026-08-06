import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import m_detect


def _ev(eid, tx, ta, tb, tc, as_of, L, pattern="bat"):
    return dict(event_id=eid, symbol="BTCUSDT", interval="1h", pattern=pattern,
                direction=1, pivot_length=L, t_X=tx, t_A=ta, t_B=tb, t_C=tc,
                as_of=as_of, dedup_merged=0)


def test_connected_components_merge_transitively():
    """e1~e2、e2~e3 但 e1≁e3（只差 2 個時間戳）→ 三者仍應併為一列。"""
    e1 = _ev("e1", 1, 2, 3, 4, as_of=100, L=5)
    e2 = _ev("e2", 1, 2, 3, 9, as_of=110, L=10)     # 與 e1 差 t_C
    e3 = _ev("e3", 1, 2, 8, 9, as_of=120, L=20)     # 與 e2 差 t_B；與 e1 差兩個
    out = m_detect.dedup(pd.DataFrame([e1, e2, e3]))
    assert len(out) == 1
    assert out.iloc[0]["event_id"] == "e1"          # as_of 最小
    assert out.iloc[0]["dedup_merged"] == 2


def test_tiebreak_prefers_smallest_as_of_then_L_then_id():
    a = _ev("zzz", 1, 2, 3, 4, as_of=100, L=20)
    b = _ev("aaa", 1, 2, 3, 4, as_of=100, L=20)     # as_of 與 L 皆同 → 字典序
    c = _ev("mmm", 1, 2, 3, 4, as_of=100, L=5)      # L 較小
    d = _ev("nnn", 1, 2, 3, 4, as_of=90, L=40)      # as_of 最小 → 勝出
    out = m_detect.dedup(pd.DataFrame([a, b, c, d]))
    assert len(out) == 1 and out.iloc[0]["event_id"] == "nnn"

    out2 = m_detect.dedup(pd.DataFrame([a, b, c]))
    assert out2.iloc[0]["event_id"] == "mmm"        # L 最小

    out3 = m_detect.dedup(pd.DataFrame([a, b]))
    assert out3.iloc[0]["event_id"] == "aaa"        # 字典序


def test_different_patterns_never_merge():
    """spec §4.2 末段：不跨形態合併。"""
    a = _ev("a", 1, 2, 3, 4, as_of=100, L=5, pattern="bat")
    b = _ev("b", 1, 2, 3, 4, as_of=100, L=5, pattern="crab")
    out = m_detect.dedup(pd.DataFrame([a, b]))
    assert len(out) == 2


def test_unrelated_events_survive():
    a = _ev("a", 1, 2, 3, 4, as_of=100, L=5)
    b = _ev("b", 50, 60, 70, 80, as_of=200, L=5)
    assert len(m_detect.dedup(pd.DataFrame([a, b]))) == 2
