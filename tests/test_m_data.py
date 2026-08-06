import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import pytest

import m_config as cfg
import m_data


def _fake_rows(start_ms, n, step_ms):
    """模仿 Binance kline 陣列：[open_time, o, h, l, c, vol, close_time, quote_vol, ...]"""
    return [[start_ms + i * step_ms, "1", "2", "0.5", "1.5", "10",
             start_ms + (i + 1) * step_ms - 1, "15", 3, "5", "7", "0"]
            for i in range(n)]


def test_pull_klines_paginates_and_respects_fixed_end(monkeypatch):
    step = 3_600_000
    start, end = cfg.FETCH_START_MS, cfg.FETCH_START_MS + step * 2500 - 1
    calls = []

    def fake_raw(symbol, interval, start_ms, end_ms, limit=1500):
        calls.append(start_ms)
        remaining = (end_ms - start_ms) // step + 1
        return _fake_rows(start_ms, min(limit, max(0, remaining)), step)

    monkeypatch.setattr(m_data, "_binance_klines_raw", fake_raw)
    df = m_data.pull_klines("BTCUSDT", "1h", start, end)

    assert len(calls) >= 2, "2500 根必須分頁"
    assert df["t"].min() == start
    assert df["t"].max() <= end, "不得抓取超過固定終點的資料"
    assert df["t"].is_monotonic_increasing and not df["t"].duplicated().any()
    assert list(df.columns) == ["t", "o", "h", "l", "c", "v", "qv"]


def test_pull_klines_never_calls_datetime_now():
    import inspect
    src = inspect.getsource(m_data)
    assert "datetime.now" not in src, "spec §6.7 禁止；右端點必須硬編"


def test_cache_roundtrip(tmp_path, monkeypatch):
    step = 3_600_000
    monkeypatch.setattr(m_data, "_binance_klines_raw",
                        lambda *a, **k: _fake_rows(cfg.FETCH_START_MS, 10, step))
    monkeypatch.setattr(m_data, "CACHE_DIR", tmp_path)
    a = m_data.load_klines("BTCUSDT", "1h", cfg.FETCH_START_MS,
                           cfg.FETCH_START_MS + step * 10 - 1)
    assert (tmp_path / "BTCUSDT_1h.parquet").exists()
    monkeypatch.setattr(m_data, "_binance_klines_raw",
                        lambda *a, **k: pytest.fail("快取命中時不得再打網路"))
    b = m_data.load_klines("BTCUSDT", "1h", cfg.FETCH_START_MS,
                           cfg.FETCH_START_MS + step * 10 - 1)
    pd.testing.assert_frame_equal(a, b)
