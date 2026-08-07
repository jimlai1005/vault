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
