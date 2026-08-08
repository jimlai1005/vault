"""Sub-project N — 逐筆成交資料層（Binance 公開歷史 dump）。

來源：https://data.binance.vision/data/futures/um/{monthly,daily}/trades/
欄位（6）：id, price, qty, quote_qty, time(ms), is_buyer_maker

═══════════════════════════════════════════════════════════════════════════
【為什麼用 trades 而不是 aggTrades】（2026-08-09，N-G0 失敗後的資料源修正）

初版用 aggTrades，N-G0 跨源對帳在 4 個 symbol 全部失敗（最大相對誤差
1.2e-4 ~ 5.8e-4，門檻 1e-9）。逐層診斷後機制決定性證實：

  aggTrades 把「同一 taker 單、同一價格」的連續成交聚合成一列，
  但【只給一個時戳，取第一筆的時間】。當被聚合的原始成交跨越棒邊界時，
  整筆量會被歸到較早的那根棒，而 Binance 的 kline 是按原始成交各自的
  時間拆開的。

  實例（GALAUSDT 2023-03-07 11:00/12:00 邊界）：
    原始 id 478638628  qty  2,813  time ...399969  → 11:00 棒
    原始 id 478638629  qty 41,980  time ...400045  → 12:00 棒
    兩者被聚合為 agg_trade_id 219378372（qty 44,793），時戳取 ...399969
    → aggTrades 把 41,980 錯歸到 11:00，恰好等於觀測到的差額。

  影響有界（738/744 棒仍逐位相符、全月總量精確守恆 0.000e+00），
  但這是格式的固有性質，無法用解析層修正。

  改用 trades（逐筆原始，每筆有自己的時戳，與 kline 語意一致）後，
  同一天 24 根棒【24/24 逐位相符，最大相對誤差 0.000e+00】，N-G0 PASS。

  修法選擇：**換資料集，不放寬 gate**。門檻維持 spec §8 預註冊的 1e-9。
═══════════════════════════════════════════════════════════════════════════

【其他已驗證的事實，勿憑印象改】
1. 符號約定：is_buyer_maker=True → 掛單方是買方 → 主動方是【賣方】→ sign = -1。
   跨源對帳：GALAUSDT 2023-03-07 全 24 根 1h 棒，trades 重建的主動買量與
   kline sidecar 的 takerBuyVolume 逐位相同。
2. header 行的有無在不同時期不同（aggTrades 於 2022-08 中旬才出現，
   daily/monthly 切換點不同步）。trades 亦同——一律 sniff 第一行，
   固定 skiprows 會無聲錯位。
3. `quote_qty` 由 Binance 直接提供，與 `qty × price` 的相對差為 2.22e-16
   （float64 epsilon）。一律用 quote_qty，省一次浮點乘法。
4. 每個 .zip 旁有 .zip.CHECKSUM（SHA-256），一律校驗。
5. 筆數 = 列數（trades 是逐筆原始，不聚合）。無需 id 範圍還原。

本模組只負責【下載、校驗、轉 parquet】，不做任何特徵計算——特徵定義屬
spec 的預註冊範圍（docs/superpowers/specs/），不得在資料層偷跑。
"""
import calendar
import hashlib
import io
import pathlib
import time
import zipfile

import numpy as np
import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um"
CACHE = pathlib.Path("data/cache/orderflow_n")
COLUMNS = ["id", "price", "qty", "quote_qty", "time", "is_buyer_maker"]
SLEEP = 0.2
DTYPES = {"id": "int64", "price": "float64", "qty": "float64",
          "quote_qty": "float64", "time": "int64", "is_buyer_maker": "bool"}


def _get(url, expect_404_ok=False):
    """單次 GET。429/5xx 指數退避重試；語意錯誤不重試（工程原則 #2）。"""
    for attempt in range(5):
        r = requests.get(url, timeout=180)
        if r.status_code == 200:
            return r.content
        if r.status_code == 404:
            if expect_404_ok:
                return None
            raise RuntimeError(f"404 not found: {url}")
        if r.status_code in (429, 418) or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"{r.status_code} {url}: {r.text[:200]}")
    raise RuntimeError(f"retries exhausted: {url}")


def _parse_zip(blob, url):
    """zip → DataFrame。sniff 第一行決定有無 header（見檔頭事實 2）。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            raw = fh.read()
    head = raw[:200].split(b"\n", 1)[0].decode("utf-8", "replace")
    first_field = head.split(",")[0].strip()
    has_header = not first_field.lstrip("-").isdigit()
    df = pd.read_csv(io.BytesIO(raw),
                     header=0 if has_header else None,
                     names=None if has_header else COLUMNS)
    df.columns = [c.strip() for c in df.columns]
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise RuntimeError(f"schema drift {url}: 缺欄位 {missing}")
    df["is_buyer_maker"] = (df["is_buyer_maker"].astype(str)
                            .str.strip().str.lower().isin(["true", "1"]))
    return df[COLUMNS].astype(DTYPES), has_header


def _fetch_day(symbol, day, verify_checksum=True):
    """單日 trades。回傳 DataFrame；該日無檔（404）回 None。"""
    stem = f"{symbol}-trades-{day}.zip"
    url = f"{BASE}/daily/trades/{symbol}/{stem}"
    blob = _get(url, expect_404_ok=True)
    if blob is None:
        return None
    if verify_checksum:
        chk = _get(url + ".CHECKSUM", expect_404_ok=True)
        if chk:
            want = chk.decode().split()[0].strip()
            got = hashlib.sha256(blob).hexdigest()
            if want != got:
                raise RuntimeError(f"checksum 不符 {stem}: {got} != {want}")
    df, _ = _parse_zip(blob, url)
    if len(df) > 1 and not bool((np.diff(df["time"].to_numpy()) >= 0).all()):
        raise RuntimeError(f"{stem}: 單日檔的 time 未排序（異常，需人工查看）")
    time.sleep(SLEEP)
    return df


def fetch_month(symbol, year, month, verify_checksum=True):
    """下載該月【每一個 daily 檔】、串接後落成一個 parquet。

    ═══ 為什麼不用 monthly 封存（2026-08-09 實測，spec §3.2.2 修訂 A2）═══
    Binance 的 monthly trades 封存【不保證時間排序】。實測 BTCUSDT 2023-01：
    8,237 萬列中有 3,040 萬處時間倒退——原始文字就是兩段各自連號的 id 序列
    【逐列交錯】（第 0 列 2023-01-25、第 1 列 2023-01-01、第 2 列又 01-25…），
    且該檔的 SHA-256 與 Binance 公布的 CHECKSUM 相符 → 不是傳輸損壞，
    是 Binance 自己的封存產製過程就是壞的。awk 獨立統計與 pandas 一致。

    同期的 daily 檔（BTCUSDT 2023-01-15、GALAUSDT 2023-03-07）與部分 monthly
    檔（GALAUSDT 2023-03）皆正常——故問題是【部分 monthly 檔】，無法事前預知
    哪些壞。daily 檔已驗證正確且對帳精確，一律改用 daily。
    ═══════════════════════════════════════════════════════════════════════

    【逐日落檔】而非串成一個月檔：BTC 單月約 8,200 萬列，串接時峰值記憶體
    約 7 GB。逐日檔（單日約 270 萬列）可安全處理，且事件級查詢只需載入
    掃單棒所在的那一天。

    回傳 (已落檔天數, 總列數, 缺檔天數)。
    """
    ym = f"{year:04d}-{month:02d}"
    n_days = calendar.monthrange(year, month)[1]
    CACHE.mkdir(parents=True, exist_ok=True)
    done, total, missing = 0, 0, 0
    for d in range(1, n_days + 1):
        day = f"{ym}-{d:02d}"
        out = day_path(symbol, day)
        if out.exists():
            done += 1
            continue
        df = _fetch_day(symbol, day, verify_checksum)
        if df is None:
            missing += 1
            continue
        df.to_parquet(out, index=False, compression="zstd")
        done += 1
        total += len(df)
    return done, total, missing


def day_path(symbol, day):
    """day 格式 'YYYY-MM-DD'。"""
    return CACHE / f"{symbol}_trades_{day}.parquet"


def load_day(symbol, day):
    return pd.read_parquet(day_path(symbol, day))


def load_month(symbol, year, month):
    """整月串接（記憶體吃重，僅用於小幣或診斷；生產路徑請用 load_day）。"""
    ym = f"{year:04d}-{month:02d}"
    n_days = calendar.monthrange(year, month)[1]
    frames = [pd.read_parquet(day_path(symbol, f"{ym}-{d:02d}"))
              for d in range(1, n_days + 1)
              if day_path(symbol, f"{ym}-{d:02d}").exists()]
    if not frames:
        raise RuntimeError(f"{symbol} {ym}: 無已落檔的日資料")
    df = pd.concat(frames, ignore_index=True)
    if not bool((np.diff(df["time"].to_numpy()) >= 0).all()):
        raise RuntimeError(f"{symbol} {ym}: 串接後 time 未排序")
    return df


def signed_notional(df):
    """帶號主動成交額（USDT）。is_buyer_maker=True → 主動方是賣方 → -1。

    用 Binance 直接提供的 quote_qty（檔頭事實 3），不自行 qty × price。
    """
    return df["quote_qty"].to_numpy() * (1.0 - 2.0 * df["is_buyer_maker"].to_numpy())
