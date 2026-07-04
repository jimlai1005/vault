import time
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from hlvault.cta import data
from hlvault.io.source import SemanticError, TransientError


def _kline_row(open_ms, o, h, l, c):
    # Binance kline array shape (only indices 0-6 used)
    return [open_ms, str(o), str(h), str(l), str(c), "1.0", open_ms + 4 * 3600_000,
            "0", 0, "0", "0", "0"]


def _klines(n, start_ms, price0=100.0):
    return [_kline_row(start_ms + i * 4 * 3600_000, price0 + i, price0 + i + 1,
                       price0 + i - 1, price0 + i) for i in range(n)]


def _coinalyze_hist(n, start_s, kind):
    rows = []
    for i in range(n):
        t = start_s + i * 4 * 3600
        if kind == "oi":
            rows.append({"t": t, "o": "10", "h": "11", "l": "9", "c": str(10 + i)})
        else:  # lsr
            rows.append({"t": t, "r": "1.0", "l": str(50 + i), "s": str(50 - i)})
    return [{"symbol": "BTCUSDT_PERP.A", "history": rows}]


def test_parse_klines_builds_ohlc_frame_indexed_by_open_time():
    df = data.parse_klines(_klines(3, 1_700_000_000_000))
    assert list(df.columns) == ["open", "high", "low", "close"]
    assert len(df) == 3
    assert isinstance(df.index, pd.DatetimeIndex)


def test_parse_coinalyze_oi_and_lsr_seconds_to_naive_ts():
    oi = data.parse_coinalyze_oi(_coinalyze_hist(3, 1_700_000_000, "oi"))
    lsr = data.parse_coinalyze_long_pct(_coinalyze_hist(3, 1_700_000_000, "lsr"))
    assert len(oi) == 3 and len(lsr) == 3
    assert oi.iloc[-1] == 12.0        # 10 + 2
    assert lsr.iloc[0] == 50.0        # long %


def test_build_frame_joins_klines_with_oi_and_long_pct():
    start_ms, start_s = 1_700_000_000_000, 1_700_000_000
    kl = data.parse_klines(_klines(60, start_ms))
    oi = data.parse_coinalyze_oi(_coinalyze_hist(60, start_s, "oi"))
    lp = data.parse_coinalyze_long_pct(_coinalyze_hist(60, start_s, "lsr"))
    frame = data.build_frame(kl, oi, lp, rule="4h")
    assert {"open", "high", "low", "close", "oi_level", "long_pct"} <= set(frame.columns)
    assert frame["oi_level"].notna().any()
    assert frame["long_pct"].notna().any()


def test_data_age_hours_measures_last_point_staleness():
    now_ms = int(time.time() * 1000)
    fresh = data.parse_klines(_klines(3, now_ms - 3 * 4 * 3600_000))
    assert data.data_age_hours(fresh) < 6.0
    stale = data.parse_klines(_klines(3, now_ms - 100 * 3600_000))
    assert data.data_age_hours(stale) > 24.0


def test_is_stale_flags_old_data_beyond_threshold():
    now = pd.Timestamp.utcnow().tz_localize(None)
    assert data.is_stale(now - pd.Timedelta(hours=2), staleness_hours=8) is False
    assert data.is_stale(now - pd.Timedelta(hours=20), staleness_hours=8) is True
    assert data.is_stale(None, staleness_hours=8) is True  # no data at all -> stale


def test_fetch_klines_retries_transient_then_raises_semantic():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("429")
        return _klines(2, 1_700_000_000_000)

    with patch("hlvault.cta.data._http_get_json", side_effect=lambda *a, **k: flaky()):
        rows = data.fetch_klines("BTCUSDT", "4h", 1_700_000_000_000,
                                 1_700_100_000_000, limit=1500)
    assert calls["n"] == 3 and len(rows) == 2

    def semantic():
        raise SemanticError("400 bad symbol")

    with patch("hlvault.cta.data._http_get_json", side_effect=lambda *a, **k: semantic()):
        with pytest.raises(SemanticError):
            data.fetch_klines("NOPE", "4h", 1, 2, limit=1500)


def test_ctadata_caches_within_instance(monkeypatch):
    calls = {"kl": 0, "oi": 0, "lp": 0}
    monkeypatch.setattr(data, "fetch_klines",
                        lambda *a, **k: (calls.__setitem__("kl", calls["kl"] + 1),
                                         _klines(60, 1_700_000_000_000))[1])
    monkeypatch.setattr(data, "fetch_coinalyze",
                        lambda endpoint, symbol, start_s, end_s: (
                            calls.__setitem__("oi", calls["oi"] + 1),
                            _coinalyze_hist(60, 1_700_000_000, "oi"))[1]
                        if "open-interest" in endpoint else (
                            calls.__setitem__("lp", calls["lp"] + 1),
                            _coinalyze_hist(60, 1_700_000_000, "lsr"))[1])
    monkeypatch.setattr(data, "resolve_coinalyze_symbol", lambda coin: "BTCUSDT_PERP.A")

    d = data.CtaData(coins=["BTC"], lookback_bars=200)
    f1 = d.frame_for("BTC")
    f2 = d.frame_for("BTC")
    assert f1 is f2                    # cached, not refetched
    assert calls["kl"] == 1 and calls["oi"] == 1 and calls["lp"] == 1


def test_is_coin_stale_flags_coin_when_a_source_is_old(monkeypatch):
    """Spec-critical: if any single source's last point exceeds the staleness
    threshold, the coin is flagged stale so live.py skips new entries."""
    # Fresh klines + fresh OI, but LSR is old -> coin must be stale.
    now_ms = int(time.time() * 1000)
    fresh_start = now_ms - 60 * 4 * 3600_000
    old_start_s = int(time.time()) - (60 + 30) * 4 * 3600  # last LSR point ~20h+ old

    monkeypatch.setattr(data, "fetch_klines",
                        lambda *a, **k: _klines(60, fresh_start))
    monkeypatch.setattr(
        data, "fetch_coinalyze",
        lambda endpoint, symbol, start_s, end_s:
            _coinalyze_hist(60, int(time.time()) - 60 * 4 * 3600, "oi")
            if "open-interest" in endpoint
            else _coinalyze_hist(60, old_start_s, "lsr"))
    monkeypatch.setattr(data, "resolve_coinalyze_symbol", lambda coin: "BTCUSDT_PERP.A")

    d = data.CtaData(coins=["BTC"], lookback_bars=200)
    d.frame_for("BTC")
    # klines + OI are fresh (< 8h); LSR last point is ~20h old -> stale.
    assert d.is_coin_stale("BTC", staleness_hours=8) is True
    # A generous threshold that covers the LSR age -> not stale.
    assert d.is_coin_stale("BTC", staleness_hours=1000) is False


def test_is_coin_stale_flags_coin_with_no_data():
    """A coin never fetched (no freshness record) is treated as stale."""
    d = data.CtaData(coins=["BTC"], lookback_bars=200)
    assert d.is_coin_stale("BTC", staleness_hours=8) is True
