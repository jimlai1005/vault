# tests/test_n_gates.py
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_gates as ng


def base(**kw):
    d = dict(G0=True, G1=True, G1b=True, G2=True, G3=True, G4=True,
             G5=True, G6=True, G7=True, G8=True)
    d.update(kw)
    return d


def test_all_pass_is_go():
    assert ng.verdict(base()) == "GO"


def test_g8_fail_is_go_with_mechanism_unsupported():
    assert ng.verdict(base(G8=False)) == "GO（機制未獲支持）"


def test_g0_or_g1_fail_voids_everything():
    assert ng.verdict(base(G0=False)) == "作廢"
    assert ng.verdict(base(G1=False)) == "作廢"


def test_exposure_is_disclosure_only_after_a4():
    """修訂 A4：G1b 降級為揭露項，不再作廢（spec §7.3.1）。

    但仍必須提供該鑰匙——缺 key 要 KeyError，不得靜默預設。
    """
    assert ng.verdict(base(G1b=False)) == "GO"
    import pytest
    with pytest.raises(KeyError):
        ng.verdict({k: True for k in ng.GATE_KEYS if k != "G1b"})


def test_g2_fail_is_nogo_regardless_of_g3():
    assert ng.verdict(base(G2=False, G3=True)) == "NO-GO"
    assert ng.verdict(base(G2=False, G3=False)) == "NO-GO"


def test_g3_fail_is_nogo():
    assert ng.verdict(base(G3=False)) == "NO-GO"


def test_any_of_g4_g5_g7_fail_is_nogo():
    for k in ("G4", "G5", "G7"):
        assert ng.verdict(base(**{k: False})) == "NO-GO"


def test_g6_fail_is_nogo():
    assert ng.verdict(base(G6=False)) == "NO-GO"


def test_verdict_requires_all_keys():
    import pytest
    with pytest.raises(KeyError):
        ng.verdict({"G2": True})
