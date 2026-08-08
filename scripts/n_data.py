"""Sub-project N — aggTrades 資料層（Binance 公開歷史 dump）。

來源：https://data.binance.vision/data/futures/um/{monthly,daily}/aggTrades/
欄位（7）：agg_trade_id, price, quantity, first_trade_id, last_trade_id,
          transact_time(ms), is_buyer_maker(bool)

【已驗證的事實，勿憑印象改】（2026-08-09 主對話實跑）
1. 符號約定：is_buyer_maker=True → 掛單方是買方 → 主動方是【賣方】→ sign = -1。
   跨源對帳：GALAUSDT 2023-03-15 00:00 UTC 那根 1h，aggTrades 的主動買量
   243,349,732.00 與 kline sidecar 的 takerBuyVolume 243,349,732.00 逐位相同。
2. header 行在 2022-08 中旬才出現，且 daily 與 monthly 切換點【不同步】
   （monthly 2022-07 有 header、daily 2022-07 沒有）。固定 skiprows 會無聲錯位，
   故一律 sniff 第一行。
3. 行數 != 成交筆數（aggTrades 是聚合的）。筆數要用
   last_trade_id - first_trade_id + 1 還原（實測 GALA 同日差 3.4 倍）。
4. 每個 .zip 旁有 .zip.CHECKSUM（SHA-256），一律校驗。

本模組只負責【下載、校驗、轉 parquet】，不做任何特徵計算——特徵定義屬
spec 的預註冊範圍（docs/superpowers/specs/），不得在資料層偷跑。
"""
import hashlib
import io
import pathlib
import time
import zipfile

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um"
CACHE = pathlib.Path("data/cache/orderflow_n")
COLUMNS = ["agg_trade_id", "price", "quantity", "first_trade_id",
           "last_trade_id", "transact_time", "is_buyer_maker"]
SLEEP = 0.2
# 落檔 dtype：price/quantity 用 float64（幣價跨 5 個數量級，float32 會失精度）
DTYPES = {"agg_trade_id": "int64", "price": "float64", "quantity": "float64",
          "first_trade_id": "int64", "last_trade_id": "int64",
          "transact_time": "int64", "is_buyer_maker": "bool"}


def _get(url, expect_404_ok=False):
    """單次 GET。429/5xx 指數退避重試；語意錯誤不重試（工程原則 #2）。"""
    for attempt in range(5):
        r = requests.get(url, timeout=120)
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


def fetch_month(symbol, year, month, verify_checksum=True):
    """下載並校驗單一 symbol-month，落成 parquet。回傳 (路徑, 列數, has_header)。"""
    ym = f"{year:04d}-{month:02d}"
    out = CACHE / f"{symbol}_aggTrades_{ym}.parquet"
    if out.exists():
        return out, None, None
    stem = f"{symbol}-aggTrades-{ym}.zip"
    url = f"{BASE}/monthly/aggTrades/{symbol}/{stem}"
    blob = _get(url)
    if verify_checksum:
        chk = _get(url + ".CHECKSUM", expect_404_ok=True)
        if chk:
            want = chk.decode().split()[0].strip()
            got = hashlib.sha256(blob).hexdigest()
            if want != got:
                raise RuntimeError(f"checksum 不符 {stem}: {got} != {want}")
    df, has_header = _parse_zip(blob, url)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, compression="zstd")
    time.sleep(SLEEP)
    return out, len(df), has_header


def load_month(symbol, year, month):
    return pd.read_parquet(CACHE / f"{symbol}_aggTrades_{year:04d}-{month:02d}.parquet")


def signed_qty(df):
    """主動方帶號成交量。is_buyer_maker=True → 主動方是賣方 → -1（檔頭事實 1）。"""
    return df["quantity"].to_numpy() * (1.0 - 2.0 * df["is_buyer_maker"].to_numpy())


def trade_count(df):
    """真實成交筆數（aggTrades 的行數是聚合後的，見檔頭事實 3）。"""
    return (df["last_trade_id"] - df["first_trade_id"] + 1).to_numpy()
