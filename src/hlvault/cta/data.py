"""Live data layer for the CTA engine: Binance 4h klines (trend/price) +
Coinalyze OI and long-% (crowding/fuel), both through the single read
resilience boundary (io.source.resilient_read — CLAUDE.md #2/#5: 429/5xx are
transient and retried, 4xx are semantic and surfaced).

Cross-venue staleness (spec requirement): the signal comes from Binance-venue
data while execution is on Hyperliquid. If either source is stale (its most
recent point is older than DATA_STALENESS_HOURS) the live engine must NOT open
new positions on that coin this cycle — but it still manages existing HL
positions and runs the drawdown breaker. data_age_hours / is_stale expose the
freshness the loop needs; the skip decision itself lives in live.py.

Coinalyze specifics reused from scripts/pull_coinalyze_data.py: header
`api_key`, 40 req/min -> 1.6s throttle, from/to in unix SECONDS, `t` in
history rows is unix SECONDS, response is a one-item list with a `history`
list, OI close field `c`, LSR long-% field `l`, Binance `.A` symbols end
`USDT_PERP.A` with base_asset = coin."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from hlvault.io.source import SemanticError, TransientError, resilient_read

from . import config as cfg

_last_coinalyze_call = [0.0]  # module-level throttle clock (40 req/min)


def _http_get_json(url: str, headers: dict | None = None, timeout: int = 25):
    """Single HTTP GET returning parsed JSON, classifying failures for the
    resilience boundary. 429/5xx -> TransientError; other 4xx -> SemanticError."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status >= 500:
                raise TransientError(f"5xx {r.status}")
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code >= 500 or e.code == 429:
            raise TransientError(str(e))
        raise SemanticError(str(e))
    except (TimeoutError, ConnectionError) as e:
        raise TransientError(str(e))
    except urllib.error.URLError as e:
        raise TransientError(str(e))


def _throttle_coinalyze() -> None:
    elapsed = time.time() - _last_coinalyze_call[0]
    if elapsed < cfg.COINALYZE_THROTTLE_SECONDS:
        time.sleep(cfg.COINALYZE_THROTTLE_SECONDS - elapsed)
    _last_coinalyze_call[0] = time.time()


# ---------------------------------------------------------------- fetch
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                 limit: int = 1500) -> list:
    params = urllib.parse.urlencode({"symbol": symbol, "interval": interval,
                                     "startTime": start_ms, "endTime": end_ms,
                                     "limit": limit})
    url = f"{cfg.BINANCE_KLINES_URL}?{params}"
    return resilient_read(lambda: _http_get_json(url), max_attempts=6, base_delay=1.0)


def fetch_coinalyze(endpoint: str, symbol: str, start_s: int, end_s: int) -> list:
    _throttle_coinalyze()
    params = urllib.parse.urlencode({"symbols": symbol, "interval": "4hour",
                                     "from": start_s, "to": end_s})
    url = f"{cfg.COINALYZE_BASE_URL}{endpoint}?{params}"
    headers = {"api_key": cfg.COINALYZE_API_KEY}
    return resilient_read(lambda: _http_get_json(url, headers=headers),
                          max_attempts=6, base_delay=2.0)


def resolve_coinalyze_symbol(coin: str) -> str:
    """Find the Binance (.A) USDT-perp Coinalyze symbol for a coin, matching
    pull_coinalyze_data.get_future_markets (base_asset == coin, symbol ends
    USDT_PERP.A)."""
    _throttle_coinalyze()
    url = f"{cfg.COINALYZE_BASE_URL}/future-markets"
    markets = resilient_read(
        lambda: _http_get_json(url, headers={"api_key": cfg.COINALYZE_API_KEY}),
        max_attempts=6, base_delay=2.0)
    for m in markets:
        if m.get("base_asset") == coin and str(m.get("symbol", "")).endswith("USDT_PERP.A"):
            return m["symbol"]
    raise SemanticError(f"no Binance .A Coinalyze symbol for {coin}")


# ---------------------------------------------------------------- parse
def parse_klines(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df = pd.DataFrame(rows)
    idx = pd.to_datetime(df[0].astype("int64"), unit="ms")
    out = pd.DataFrame({
        "open": pd.to_numeric(df[1]), "high": pd.to_numeric(df[2]),
        "low": pd.to_numeric(df[3]), "close": pd.to_numeric(df[4]),
    })
    out.index = idx
    return out.sort_index()


def _coinalyze_series(payload: list, field: str) -> pd.Series:
    if not payload or not payload[0].get("history"):
        return pd.Series(dtype=float)
    hist = payload[0]["history"]
    idx = pd.to_datetime([int(r["t"]) for r in hist], unit="s")  # seconds -> naive UTC
    s = pd.Series([float(r[field]) for r in hist], index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def parse_coinalyze_oi(payload: list) -> pd.Series:
    return _coinalyze_series(payload, "c")     # OI close (base-asset units)


def parse_coinalyze_long_pct(payload: list) -> pd.Series:
    return _coinalyze_series(payload, "l")     # long % of accounts


# ---------------------------------------------------------------- assemble
def build_frame(klines: pd.DataFrame, oi: pd.Series, long_pct: pd.Series,
                rule: str) -> pd.DataFrame:
    """Join klines with per-bar OI (last-of-period) and long-% (mean-of-period),
    keeping only bars covered by Coinalyze data — matches the backtest's
    bar_frame. Returns a frame with columns open/high/low/close/oi_level/
    long_pct indexed by bar open time."""
    bars = klines.copy()
    if not oi.empty and not long_pct.empty:
        cov_start = max(oi.index.min(), long_pct.index.min())
        bars = bars[bars.index >= cov_start]
    # Aggregate each source per kline bar (last-of-period OI, mean-of-period
    # long-%) and align onto the bar-open index. Coinalyze points that fall
    # inside a bar are grouped by the bar's open time; if a source is finer
    # than the bar it collapses, if it is exactly one point per bar (the live
    # 4h case) the group is a no-op — either way the result is indexed by the
    # kline bar-open timestamps (not an arbitrary wall-clock 4h grid, which
    # would not line up with the bar index).
    def _per_bar(series: pd.Series, how: str) -> pd.Series:
        if series.empty:
            return series
        # Snap each source timestamp back to the latest bar-open at or before it.
        pos = bars.index.searchsorted(series.index, side="right") - 1
        keep = pos >= 0
        grouped = series[keep].groupby(bars.index[pos[keep]])
        return grouped.last() if how == "last" else grouped.mean()
    oi_bar = _per_bar(oi, "last")
    lp_bar = _per_bar(long_pct, "mean")
    bars["oi_level"] = oi_bar.reindex(bars.index) if not oi.empty else np.nan
    bars["long_pct"] = lp_bar.reindex(bars.index) if not long_pct.empty else np.nan
    return bars


# ---------------------------------------------------------------- freshness
def data_age_hours(frame_or_series) -> float:
    """Hours between now (UTC) and the most recent index timestamp. Empty ->
    +inf (treated as maximally stale)."""
    if frame_or_series is None or len(frame_or_series) == 0:
        return float("inf")
    last = frame_or_series.index.max()
    now = pd.Timestamp.utcnow().tz_localize(None)
    return (now - last).total_seconds() / 3600.0


def is_stale(last_ts, staleness_hours: float) -> bool:
    """True when the last data point is older than the threshold (or missing).
    last_ts may be a pandas Timestamp or None."""
    if last_ts is None:
        return True
    now = pd.Timestamp.utcnow().tz_localize(None)
    return (now - last_ts).total_seconds() / 3600.0 > staleness_hours


# ---------------------------------------------------------------- per-cycle cache
class CtaData:
    """One instance per rebalance cycle. Fetches and caches each coin's joined
    frame + per-source freshness so the loop pulls each source once per cycle
    (respecting the 40 req/min Coinalyze budget)."""

    def __init__(self, coins: list, lookback_bars: int):
        self.coins = coins
        self.lookback_bars = lookback_bars
        self._frames: dict[str, pd.DataFrame] = {}
        self._freshness: dict[str, dict] = {}
        self._symbols: dict[str, str] = {}

    def _coinalyze_symbol(self, coin: str) -> str:
        if coin not in self._symbols:
            self._symbols[coin] = resolve_coinalyze_symbol(coin)
        return self._symbols[coin]

    def frame_for(self, coin: str) -> pd.DataFrame:
        if coin in self._frames:
            return self._frames[coin]
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - self.lookback_bars * 4 * 3600_000
        start_s, end_s = start_ms // 1000, now_ms // 1000

        klines = parse_klines(fetch_klines(cfg.BINANCE_SYMBOLS[coin], cfg.TIMEFRAME,
                                           start_ms, now_ms, limit=1500))
        sym = self._coinalyze_symbol(coin)
        oi = parse_coinalyze_oi(fetch_coinalyze("/open-interest-history", sym, start_s, end_s))
        lp = parse_coinalyze_long_pct(fetch_coinalyze("/long-short-ratio-history", sym, start_s, end_s))

        frame = build_frame(klines, oi, lp, rule=cfg.TIMEFRAME)
        self._frames[coin] = frame
        self._freshness[coin] = {
            "klines_last": klines.index.max() if len(klines) else None,
            "oi_last": oi.index.max() if len(oi) else None,
            "long_pct_last": lp.index.max() if len(lp) else None,
        }
        return frame

    def is_coin_stale(self, coin: str, staleness_hours: float) -> bool:
        """True if ANY of the coin's three sources is stale/missing — a stale
        signal on any leg means we must not open new exposure on it."""
        f = self._freshness.get(coin, {})
        if not f:
            return True
        return any(is_stale(f.get(k), staleness_hours)
                   for k in ("klines_last", "oi_last", "long_pct_last"))
