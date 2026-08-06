import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import m_config as cfg
import m_detect


def _xabc(x, a, b, c):
    """回傳 (價格四元組, direction)。bullish: x 低 a 高 b 低 c 高。"""
    return dict(p_X=x, p_A=a, p_B=b, p_C=c, direction=1)


def test_perfect_gartley_passes_filters():
    # AB/XA = 0.618, BC/AB = 0.5（在 0.382-0.886 內）
    xa = 100.0
    x, a = 0.0, 100.0
    b = a - 0.618 * xa                       # 38.2
    c = b + 0.5 * (a - b)                    # 69.1
    assert m_detect.passes_prefilters("gartley", _xabc(x, a, b, c), cfg.TOL)


def test_ad_xa_off_by_20pct_produces_no_prz():
    xa = 100.0
    x, a = 0.0, 100.0
    b, c = a - 0.618 * xa, a - 0.618 * xa + 0.5 * 0.618 * xa
    prz = m_detect.compute_prz("gartley", _xabc(x, a, b, c), cfg.TOL, cfg.TOL_AD_XA)
    lo, hi = prz
    d_correct = a - 0.786 * xa               # 21.4
    d_off = a - 0.786 * 1.2 * xa             # 偏 20%
    assert lo <= d_correct <= hi
    assert not (lo <= d_off <= hi)


def test_shark_skips_ab_xa_filter():
    """spec §4.2：Shark 的 AB/XA 為 None。"""
    assert cfg.HARMONIC_RATIOS["shark"][0] is None
    # 一個 AB/XA 極端的 XABC，只要 BC/AB 合格就該通過
    x, a = 0.0, 100.0
    b = a - 0.95 * 100.0                     # AB/XA = 0.95，對任何有約束的形態都不合格
    c = b + 1.3 * (a - b)                    # BC/AB = 1.3，在 1.13-1.618 內
    assert m_detect.passes_prefilters("shark", _xabc(x, a, b, c), cfg.TOL)


def test_cypher_uses_xc_not_bc_ab():
    """spec §4.2：Cypher 不套 BC/AB，改用 XC/XA；PRZ 由 CD/XC 決定。"""
    x, a = 0.0, 100.0
    b = a - 0.5 * 100.0                      # AB/XA = 0.5，在 0.382-0.618 內
    c = x + 1.30 * 100.0                     # XC/XA = 1.30，在 1.272-1.414 內
    d = _xabc(x, a, b, c)
    assert m_detect.passes_prefilters("cypher", d, cfg.TOL)
    lo, hi = m_detect.compute_prz("cypher", d, cfg.TOL, cfg.TOL_AD_XA)
    expected_d = c - 0.786 * (c - x)
    assert lo <= expected_d <= hi


def test_empty_intersection_returns_none():
    """AD/XA 與 CD/BC 的區間不相交 → 候選作廢（spec §4.3）。

    已手算驗證：BC = 8.86 → CD/BC 推出的 D 區 [-11.80, 0.41]，
    與 AD/XA 的 D 區 [-66.65, -56.95] 完全分離。
    （BC = 0.4×AB 的版本兩區間仍重疊，Task 6 執行時抓到，fixture 修正為 0.1。）
    """
    x, a = 0.0, 100.0
    b = a - 0.886 * 100.0                    # deep_crab 的 AB/XA
    c = b + 0.1 * (a - b)                    # BC 極短 → CD/BC 推出的 D 區遠離 AD/XA 的 D 區
    assert m_detect.compute_prz("deep_crab", _xabc(x, a, b, c), cfg.TOL, cfg.TOL_AD_XA) is None


def test_one_xabc_can_satisfy_multiple_patterns():
    """spec §4.2 末段：as_of 前只有兩軸可驗，Bat 與 Crab 的前置過濾完全重疊。"""
    x, a = 0.0, 100.0
    b = a - 0.45 * 100.0                     # 同時落在 bat(0.382-0.50) 與 crab(0.382-0.618)
    c = b + 0.5 * (a - b)                    # BC/AB = 0.5，兩者都合格
    d = _xabc(x, a, b, c)
    hits = [p for p in ("bat", "crab") if m_detect.passes_prefilters(p, d, cfg.TOL)]
    assert hits == ["bat", "crab"]


def test_sl_does_not_depend_on_fill():
    """spec §4.5.2：SL 由 X/A 與形態常數唯一決定。"""
    x, a = 0.0, 100.0
    sl = m_detect.compute_sl("bat", _xabc(x, a, 50.0, 70.0))
    assert sl == a - cfg.SL_LEVEL_OVER_XA["bat"] * (a - x)


import numpy as np
import pandas as pd


def _zigzag_bars(anchors, n):
    """piecewise-linear 路徑：錨點即 pivot，段內嚴格單調故無多餘 pivot。"""
    path = np.interp(np.arange(n), [i for i, _ in anchors], [v for _, v in anchors])
    return pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                         "o": path, "h": path, "l": path, "c": path,
                         "v": 1.0, "qv": 1.0})


def _gartley_bars():
    # X@4=100, A@10=200, B@16=138.2, C@22=169.1（AB/XA=0.618、BC/AB=0.5 精確）
    return _zigzag_bars([(0, 150.0), (4, 100.0), (10, 200.0),
                         (16, 138.2), (22, 169.1), (39, 120.0)], 40)


def test_build_events_emits_required_schema():
    ev = m_detect.build_events(_gartley_bars(), symbol="BTCUSDT", interval="1h",
                               lengths=(2,))
    assert len(ev) >= 1, "合成 Gartley 必須至少產生一個事件"
    assert set(ev["pattern"]) == {"gartley"}
    required = {"event_id", "xabc_group_id", "symbol", "interval", "pattern",
                "direction", "pivot_length", "t_X", "t_A", "t_B", "t_C",
                "p_X", "p_A", "p_B", "p_C", "as_of", "ratio_ab_xa",
                "ratio_bc_ab", "ratio_xc_xa", "prz_low", "prz_high", "sl",
                "tp1_planned", "tp2_planned", "dedup_merged", "tol_used"}
    assert required.issubset(set(ev.columns))


def test_every_event_as_of_is_after_its_C_confirm():
    ev = m_detect.build_events(_gartley_bars(), "BTCUSDT", "1h", lengths=(2,))
    assert len(ev) >= 1
    assert (ev["as_of"] > ev["t_C"]).all()
