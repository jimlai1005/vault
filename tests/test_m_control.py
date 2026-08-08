import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd

import m_config as cfg
import m_control as mc

H = 3_600_000


def _ev(eid="E1", as_of=1000 * H - 1):
    return dict(event_id=eid, symbol="X", interval="1h", pattern="bat",
                direction=1, as_of=as_of, prz_low=95.0, prz_high=100.0,
                sl=90.0, p_X=80.0, p_A=120.0, p_B=95.0, p_C=110.0)


def _bars(n=2000, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    return pd.DataFrame({"t": [i * H for i in range(n)], "o": close,
                         "h": close * 1.003, "l": close * 0.997, "c": close,
                         "v": 1.0, "qv": 1.0})


def test_deterministic_and_delta_range():
    bars = _bars()
    c1 = mc.make_controls(_ev(), bars)
    c2 = mc.make_controls(_ev(), bars)
    assert [x["delta_bars"] for x in c1] == [x["delta_bars"] for x in c2]
    for x in c1:
        assert cfg.CONTROL_DELTA_MIN <= x["delta_bars"] <= cfg.CONTROL_DELTA_MAX


def test_ratio_shift_preserved():
    bars = _bars()
    ev = _ev()
    ctrls = mc.make_controls(ev, bars)
    t = bars["t"].to_numpy()
    for x in ctrls:
        ic = int(np.searchsorted(t, x["as_of"], side="right")) - 1
        anchor = bars["c"].iloc[ic]
        ic0 = int(np.searchsorted(t, ev["as_of"], side="right")) - 1
        anchor0 = bars["c"].iloc[ic0]
        assert abs(x["prz_high"] / anchor - ev["prz_high"] / anchor0) < 1e-9
        assert abs(x["sl"] / anchor - ev["sl"] / anchor0) < 1e-9


def test_out_of_range_reduces_k_actual():
    bars = _bars(n=1200)                              # 尾端不夠 δ+曝險窗 → 部分捨棄
    ev = _ev(as_of=1150 * H - 1)
    ctrls = mc.make_controls(ev, bars)
    assert len(ctrls) < cfg.CONTROL_K
    for x in ctrls:
        assert x["weight"] == 1.0 / len(ctrls)        # 1/K_actual（spec §5.4）


def test_calendar_alignment_maps_back():
    """對照的日曆對齊：mapped_term_t = term_t − δ·bar_ms（spec §5.4）。"""
    x = dict(delta_bars=150, term_t=500 * H - 1)
    assert mc.mapped_term_t(x, bar_ms=H) == 500 * H - 1 - 150 * H
