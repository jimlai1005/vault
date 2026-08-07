"""Sub-project M — 資料層。spec §7。

【右端點硬編】：不得使用動態時間（spec §6.7；2026-07-12 momentum 教訓：
端點差 9 天使兩年 Sharpe 從 0.57 掉到 0.18）。
"""
import pathlib
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
SLEEP = 0.25
CACHE_DIR = pathlib.Path(cfg.CACHE_DIR)
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
COLUMNS = ["t", "o", "h", "l", "c", "v", "qv"]


def _binance_klines_raw(symbol, interval, start_ms, end_ms, limit=1500):
    """單次呼叫。429/5xx 指數退避重試，語意錯誤不重試（工程原則 #2）。"""
    url = f"{BINANCE_FAPI}/klines"
    params = dict(symbol=symbol, interval=interval, startTime=int(start_ms),
                  endTime=int(end_ms), limit=limit)
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 418) or r.status_code >= 500:
            time.sleep(2 ** attempt)          # transient：退避重試
            continue
        raise RuntimeError(f"binance {r.status_code}: {r.text[:200]}")   # semantic：不重試
    raise RuntimeError(f"binance retries exhausted: {symbol} {interval}")


def _rows_to_df(rows):
    df = pd.DataFrame([[int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                        float(r[4]), float(r[5]), float(r[7])] for r in rows],
                      columns=COLUMNS)
    return df


def pull_klines(symbol, interval, start_ms, end_ms):
    """分頁抓取 [start_ms, end_ms]。end_ms 必須由呼叫端傳入固定時間戳。"""
    step = INTERVAL_MS[interval]
    out, cursor = [], int(start_ms)
    while cursor <= end_ms:
        rows = _binance_klines_raw(symbol, interval, cursor, end_ms)
        if not rows:
            break
        df = _rows_to_df(rows)
        df = df[df["t"] <= end_ms]
        if df.empty:
            break
        out.append(df)
        last = int(df["t"].iloc[-1])
        if last < cursor:                      # 無限迴圈防護
            break
        cursor = last + step
        time.sleep(SLEEP)
    if not out:
        return pd.DataFrame(columns=COLUMNS)
    res = pd.concat(out, ignore_index=True).drop_duplicates("t").sort_values("t")
    return res.reset_index(drop=True)


def load_klines(symbol, interval, start_ms=None, end_ms=None):
    """快取優先。快取檔存在即直接讀，不打網路。"""
    start_ms = cfg.FETCH_START_MS if start_ms is None else start_ms
    end_ms = cfg.FETCH_END_MS if end_ms is None else end_ms
    path = pathlib.Path(CACHE_DIR) / f"{symbol}_{interval}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = pull_klines(symbol, interval, start_ms, end_ms)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def quarter_start_ms(year, q):
    month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
    from datetime import datetime, timezone
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def quarters(first, last):
    out, cur = [], first
    while cur <= last:
        out.append(cur)
        cur = (cur[0] + 1, 1) if cur[1] == 4 else (cur[0], cur[1] + 1)
    return out


def build_pit_universe_m(symbols, quarters=None):
    """Point-in-time 季度輪換幣種宇宙（spec §7.1）。

    複製 k_data_layer.build_pit_universe 的邏輯，但門檻參數化、季度延伸至
    2026-Q2、1d 資料由本模組自行抓取。

    每季只用【季度開始前】的資料：trailing 90 日中位 quote volume >= $50M
    且上市 >= 180 天，取 top 30。
    """
    qs = quarters if quarters is not None else globals()["quarters"](
        cfg.UNIVERSE_FIRST_QUARTER, cfg.UNIVERSE_LAST_QUARTER)
    day = 86_400_000
    universe = {}
    for (y, q) in qs:
        cutoff = quarter_start_ms(y, q)
        rows = []
        for sym in symbols:
            df = load_klines(sym, "1d")
            df = df[df["t"] < cutoff]                        # ← PIT 的核心：只看過去
            if df.empty:
                continue
            listed_days = (cutoff - int(df["t"].min())) / day
            if listed_days < cfg.UNIVERSE_MIN_LISTED_DAYS:
                continue
            trailing = df[df["t"] >= cutoff - 90 * day]
            if trailing.empty:
                continue
            med_qv = float(trailing["qv"].median())
            if med_qv < cfg.UNIVERSE_MIN_QUOTE_VOL:
                continue
            rows.append((sym, med_qv))
        rows.sort(key=lambda r: -r[1])
        universe[(y, q)] = [s for s, _ in rows[:cfg.UNIVERSE_TOP_N]]
    return universe


def binance_universe_symbols():
    """Binance USDT 永續的全部 symbol（PIT 篩選的候選池）。

    注意：exchangeInfo 只回傳【目前仍上市】的 symbol——已下市幣不在其中，
    這是候選池層級的殘餘倖存者偏誤（spec §10 限制 3），普查報告須註明。
    """
    r = requests.get(f"{BINANCE_FAPI}/exchangeInfo", timeout=30)
    r.raise_for_status()
    return sorted(s["symbol"] for s in r.json()["symbols"]
                  if s.get("quoteAsset") == "USDT"
                  and s.get("contractType") == "PERPETUAL")
