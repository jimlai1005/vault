import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd

import m_config as cfg
import m_gates as mg


def test_verdict_table_branches():
    """spec §6.6 判定表：逐分支窮盡。"""
    g = dict(G2=True, G3=True, G4=True, G5=True, G6=True, G7=True)
    assert mg.verdict(g) == "GO"
    assert mg.verdict({**g, "G3": False}) == "NO-GO"
    assert mg.verdict({**g, "G4": False}) == "NO-GO（多重檢定未通過）"
    assert mg.verdict({**g, "G5": False}) == "NO-GO（過擬合）"
    assert mg.verdict({**g, "G6": False}) == "NO-GO（過擬合）"
    assert mg.verdict({**g, "G7": False}) == "NO-GO（成本邊際）"
    assert mg.verdict({**g, "G2": False}) == "NO-GO"


def test_is_oos_assignment_by_as_of():
    """spec §6.5：歸屬鍵 = as_of；跨界事件屬 IS。"""
    tr = pd.DataFrame({"as_of": [cfg.IS_END_MS - 1, cfg.IS_END_MS + 1],
                       "term_t": [cfg.OOS_START_MS + 5, cfg.OOS_START_MS + 5],
                       "R_net": [1.0, 1.0]})
    assert list(mg.split_is_oos(tr)["is_is"]) == [True, False]


def test_holdout_hash():
    """spec §6.5：sha256(symbol) % 2 == 1 為 holdout，UTF-8。"""
    import hashlib
    for s in ("BTCUSDT", "1000PEPEUSDT"):
        expect = int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16) % 2 == 1
        assert mg.is_holdout(s) == expect


def test_n_observable_assert():
    """M-G4 的 sr_list 長度必須恰為 480，否則 raise。"""
    import pytest
    with pytest.raises(AssertionError):
        mg.check_sr_list([0.01] * 479)
    mg.check_sr_list([0.01] * 480)
