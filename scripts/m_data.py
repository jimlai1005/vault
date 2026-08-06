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
