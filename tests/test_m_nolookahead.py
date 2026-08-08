"""M-G1 偵測層：截斷式無前視斷言（spec §6.2）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd
import pytest

import m_detect


def _random_walk_bars(n=1200, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    high = close * (1 + rng.uniform(0, 0.004, n))
    low = close * (1 - rng.uniform(0, 0.004, n))
    return pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                         "o": close, "h": high, "l": low, "c": close,
                         "v": 1.0, "qv": 1.0})


@pytest.mark.parametrize("frac", [0.25, 0.50, 0.75])
def test_truncation_changes_nothing_at_or_before_T(frac):
    df = _random_walk_bars()
    cut = int(len(df) * frac)
    T = int(df["t"].iloc[cut])

    full = m_detect.build_events(df, "BTCUSDT", "1h", do_dedup=False)
    trunc = m_detect.build_events(df.iloc[:cut + 1].reset_index(drop=True),
                                  "BTCUSDT", "1h", do_dedup=False)

    full_le = full[full["as_of"] <= T].sort_values("event_id").reset_index(drop=True)
    trunc_le = trunc[trunc["as_of"] <= T].sort_values("event_id").reset_index(drop=True)

    missing = set(full_le["event_id"]) - set(trunc_le["event_id"])
    appeared = set(trunc_le["event_id"]) - set(full_le["event_id"])
    assert not missing, f"截斷後消失的事件（look-ahead）：{sorted(missing)[:5]}"
    assert not appeared, f"截斷後憑空出現的事件（look-ahead）：{sorted(appeared)[:5]}"

    pd.testing.assert_frame_equal(full_le, trunc_le, check_exact=False, rtol=1e-12)


def test_events_exist_in_fixture():
    """避免上面的斷言在零事件時空轉。"""
    ev = m_detect.build_events(_random_walk_bars(), "BTCUSDT", "1h", do_dedup=False)
    assert len(ev) > 0, "隨機遊走未產生任何事件——先檢查偵測器而非放寬測試"


def test_backtest_truncation_only_settled_trades():  # spec §6.2 斷言 2
    """對 term_date <= T（完整跑的值）的交易，截斷重跑後逐欄相同。"""
    import m_backtest as bt

    df = _random_walk_bars(n=900, seed=13)
    ev_tbl = m_detect.build_events(df, "BTCUSDT", "1h", do_dedup=True)
    assert len(ev_tbl) > 0
    full = bt.run_events_on_bars(ev_tbl.assign(in_universe=True), df)
    cut = int(len(df) * 0.6)
    T = int(df["t"].iloc[cut]) + 3_600_000 - 1

    df_tr = df.iloc[:cut + 1].reset_index(drop=True)
    ev_tr = m_detect.build_events(df_tr, "BTCUSDT", "1h", do_dedup=True)
    # 只比 as_of <= T 的事件（偵測層已由斷言 1 保證一致）
    trunc = bt.run_events_on_bars(ev_tr[ev_tr["as_of"] <= T], df_tr)

    full_settled = full[(full["as_of"] <= T) & (full["term_t"] <= T)] \
        .sort_values("event_id").reset_index(drop=True)
    tr_sub = trunc[trunc["event_id"].isin(full_settled["event_id"])] \
        .sort_values("event_id").reset_index(drop=True)
    assert len(tr_sub) == len(full_settled)
    for col in ("exit_reason", "R_net", "fill", "exit_px", "term_t"):
        pd.testing.assert_series_equal(full_settled[col], tr_sub[col],
                                       check_exact=False, rtol=1e-12)
