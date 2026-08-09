# tests/test_n_features.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_features as nf


def test_abs_ok_bearish_requires_positive_sweep_delta():
    """spec §5.2：空方掃單，池上方是【主動買】被吸收 -> D_sweep > 0。"""
    assert nf.abs_ok(d_sweep=100.0, direction=-1) is True
    assert nf.abs_ok(d_sweep=-100.0, direction=-1) is False
    assert nf.abs_ok(d_sweep=0.0, direction=-1) is False


def test_abs_ok_bullish_mirrors():
    assert nf.abs_ok(d_sweep=-100.0, direction=+1) is True
    assert nf.abs_ok(d_sweep=100.0, direction=+1) is False


def test_abs_ok_nan_rejects():
    assert nf.abs_ok(d_sweep=float("nan"), direction=-1) is False


def test_div_ok_bearish_requires_cvd_not_higher():
    """spec §5.3：價格創了比池更高的高點，但 CVD 沒有同步創高。"""
    assert nf.div_ok(cvd_j=50.0, cvd_pool=100.0, direction=-1) is True
    assert nf.div_ok(cvd_j=100.0, cvd_pool=100.0, direction=-1) is True   # <= 含等號
    assert nf.div_ok(cvd_j=150.0, cvd_pool=100.0, direction=-1) is False


def test_div_ok_bullish_mirrors():
    assert nf.div_ok(cvd_j=150.0, cvd_pool=100.0, direction=+1) is True
    assert nf.div_ok(cvd_j=50.0, cvd_pool=100.0, direction=+1) is False


def test_div_ok_nan_rejects():
    assert nf.div_ok(cvd_j=float("nan"), cvd_pool=1.0, direction=-1) is False
    assert nf.div_ok(cvd_j=1.0, cvd_pool=float("nan"), direction=-1) is False


def test_arm_pass_composes_flags():
    """spec §9 的四臂。"""
    f = dict(abs_ok=True, div_ok=False)
    assert nf.arm_pass("sweep_only", f) is True
    assert nf.arm_pass("sweep+ABS", f) is True
    assert nf.arm_pass("sweep+DIV", f) is False
    assert nf.arm_pass("sweep+ABS+DIV", f) is False
    f2 = dict(abs_ok=True, div_ok=True)
    assert nf.arm_pass("sweep+ABS+DIV", f2) is True


def test_arm_pass_rejects_unknown_arm():
    with pytest.raises(KeyError):
        nf.arm_pass("sweep+MAGIC", dict(abs_ok=True, div_ok=True))


def test_cvd_at_returns_nan_outside_range():
    bars = pd.DataFrame({"t": [0, 3600000], "cvd": [1.0, 2.0]})
    assert nf.cvd_at(bars, 0) == 1.0
    assert nf.cvd_at(bars, 3600000) == 2.0
    assert np.isnan(nf.cvd_at(bars, 7200000))
