# sub-project N — 訂單流／掛單簿／清算資料可得性勘查

**日期**：2026-08-09
**目的**：判定「liquidity sweep + 訂單流確認」策略在 Binance USDT 永續上是否有足夠的歷史資料可做嚴謹回測。
**查證方式**：全部為實地 curl（S3 目錄列表、HEAD content-length、實下載小檔案解壓看欄位）。無憑印象的數字；推測處已標「推測」。

---

## 結論（三句話）

1. **真 CVD：拿得到。** `futures/um/*/aggTrades` 與 `trades` 都含 `is_buyer_maker` 欄位，逐筆成交、毫秒時戳，BTCUSDT 回溯至 2019-12-31（aggTrades）／2019-09-08（trades），至今每日更新。
2. **Resting liquidity（價位級掛單簿）：拿不到。** 公開 dump **沒有** depth update（增量）資料集；`bookDepth` 只是 ±0.2/1/2/3/4/5% 共 12 條累計深度帶、約 30 秒一張快照；唯一的 L1 逐筆 `bookTicker` **已於 2024-03-30 全symbol停更**。
3. **建議最小可行資料集**：`aggTrades`（12 幣 × 24 個月，monthly 檔，約 25–30 GB zip）＋ `bookDepth`（同組，約 4 GB）＋ `metrics`（同組，約 0.05 GB）。這組足以檢定「掃單後是否出現吸收／CVD 背離」的核心假設，且**不依賴任何已停更或不存在的資料集**。

---

## 摘要表：dataset × 起點 × 體積 × 是否含 isBuyerMaker

（span 以 BTCUSDT 為準；體積為實測 zip content-length）

| dataset | 粒度 | span (BTCUSDT) | daily | monthly | 體積 | `is_buyer_maker` |
|---|---|---|---|---|---|---|
| **aggTrades** | 逐筆聚合成交，ms | 2019-12-31 → 2026-08-07 | ✅ | ✅ | BTC 均 18.25 MB/日；SOL 6.61；GALA 2.53 | **✅ 有** |
| **trades** | 逐筆原始成交，ms | 2019-09-08 → 2026-08-07 | ✅ | ✅ | BTC 27.03 MB/日（2026-06-15 實測） | **✅ 有**（另有 quote_qty） |
| **bookDepth** | 12 條 %-深度帶，~30s | 2023-01-01 → 2026-08-07 | ✅ | ❌ | **0.47 MB/日，與幣種無關** | n/a |
| **bookTicker** | L1 最佳買賣價量，逐筆 | 2023-05-16 → **2024-03-30（已停更）** | ✅ | ✅ | BTC 均 164 MB/日（2024 年 242） | n/a |
| **metrics** | OI＋多空比，5 分鐘 | 2020-09-01 → 2026-08-07 | ✅ | ❌ | 0.01 MB/日 | n/a |
| **klines / markPriceKlines / indexPriceKlines / premiumIndexKlines** | OHLCV | — | ✅ | ✅ | — | — |
| **fundingRate** | 8 小時 | — | ❌ | ✅ | — | — |
| **liquidationSnapshot** | — | **um 完全不存在**；cm 為 2023-06-25 → 2024-10-14 | cm only | ❌ | cm 約 2 KB/日 | — |

---

## A. data.binance.vision

### A1. futures/um 底下實際有哪些 dataset

實跑 S3 ListBucket（`https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/{daily,monthly}/`）：

**daily（9 個）**：`aggTrades`、`bookDepth`、`bookTicker`、`indexPriceKlines`、`klines`、`markPriceKlines`、`metrics`、`premiumIndexKlines`、`trades`

**monthly（8 個）**：`aggTrades`、`bookTicker`、`fundingRate`、`indexPriceKlines`、`klines`、`markPriceKlines`、`premiumIndexKlines`、`trades`

差集很重要：
- **`bookDepth` 與 `metrics` 只有 daily，沒有 monthly** → 要抓兩年就是 730 個 HTTP 請求／幣，無法用月檔省請求數。
- **`fundingRate` 只有 monthly。**
- **`um` 沒有 `liquidationSnapshot`。** 對照 `data/futures/cm/daily/` 確實有 `liquidationSnapshot/`，所以不是我查錯路徑——是 USDT 本位真的沒有。
- 頂層只有 `data/spot/`、`data/futures/`、`data/option/`；`futures` 下只有 `cm/`、`um/`。

### A2. 各 dataset 的欄位（實下載解壓第一行）

**aggTrades**（`GALAUSDT-aggTrades-2026-06-15.zip`）：
```
agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker
316751043,0.002737,24479.0,879771161,879771162,1781481600220,false
```
→ **`is_buyer_maker` 存在**。`false` = 買方是 taker（主動買）。CVD = Σ qty·(is_buyer_maker ? −1 : +1)，這是真 CVD，不是 kline 聚合的 proxy。
→ `first_trade_id`/`last_trade_id` 可還原被聚合掉的原始成交筆數（本例 1 筆 agg = 2 筆 raw）。

**trades**（`GALAUSDT-trades-2026-06-15.zip`）：
```
id,price,qty,quote_qty,time,is_buyer_maker
```
→ 同樣有 `is_buyer_maker`，且多了 `quote_qty`（USDT 名目）。同日 GALA：trades 116,320 行 vs aggTrades 34,460 行（3.4×），zip 1.40 MB vs 0.55 MB。BTC 2026-06-15：trades 27.03 MB vs aggTrades 16.64 MB。

**bookDepth**（`BTCUSDT-bookDepth-2026-06-15.zip`）：
```
timestamp,percentage,depth,notional
2026-06-15 00:00:04,-5.00,6851.68200000,439751940.22480000
```
→ **這不是掛單簿。** 實測該日：
- `percentage` 只有 12 個相異值：`-5 -4 -3 -2 -1 -0.2 0.2 1 2 3 4 5`（％ 距中價）
- 相異 timestamp 數 = **2880**（= 86400/30），相鄰間隔直方圖：30s×1164、29s×696、31s×694、28s×145、32s×143 → **約 30 秒一張快照，且抖動 ±2 秒**
- `depth` = 該帶內累計張數，`notional` = 累計名目金額
→ 只能回答「距中價 X% 以內總共有多少量」，**無法回答「某個價位有多少掛單」**。時戳精度到秒，無毫秒。

**bookTicker**（`GALAUSDT-bookTicker-2024-03-01.zip`，38.9 MB）：
```
update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time
```
→ 真正的 L1 逐筆（該日 GALA 2,969,315 行）。這是唯一接近「resting liquidity」的資料——**但只有 L1，且已停更（見 A3）**。

**metrics**（`BTCUSDT-metrics-2026-06-15.zip`）：
```
create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio
```
→ 5 分鐘一筆（該日 288 行＋header）。等同 FAPI `/futures/data/` 那組，但**有完整歷史**（見 B7 對比）。

**有沒有真正的逐筆掛單簿增量（depth update）？沒有。** um 與 cm 的 daily/monthly 清單裡都不存在任何 depth-diff / depthUpdate 資料集。想要價位級 book 只能自行接 WebSocket 從今天開始錄，或買第三方（Tardis.dev 等，付費）。

### A3. 歷史起點（S3 lexicographic 首鍵，日期字串可直接排序）

| dataset | BTCUSDT 最早 | 最新 |
|---|---|---|
| daily/trades | **2019-09-08** | 2026-08-07 |
| daily/aggTrades | **2019-12-31** | 2026-08-07 |
| daily/metrics | **2020-09-01** | 2026-08-07 |
| daily/bookDepth | **2023-01-01** | 2026-08-07 |
| daily/bookTicker | **2023-05-16** | **2024-03-30** |
| monthly/aggTrades | 2020-01 | 2026-07 |
| monthly/trades | 2019-09 | — |
| monthly/bookTicker | 2023-05 | **2024-04** |

**bookTicker 停更已跨 symbol 確認**（每個都恰好 320 個檔、span 完全相同）：

| symbol | n | span | total |
|---|---|---|---|
| BTCUSDT | 320 | 2023-05-16..2024-03-30 | 52.58 GB |
| ETHUSDT | 320 | 2023-05-16..2024-03-30 | 43.27 GB |
| SOLUSDT | 320 | 2023-05-16..2024-03-30 | 23.51 GB |
| GALAUSDT | 320 | 2023-05-16..2024-03-30 | 7.66 GB |

不是個別幣缺檔，是**整個資料集被 Binance 停止發布**。2026-06-15 的 bookTicker URL 實測 HTTP 404（三個幣皆是）。

bookDepth 對非主流幣是「上市即有」而非全部從 2023-01 開始：MANAUSDT 2023-01-01、ORDIUSDT 2023-11-07、TIAUSDT 2023-10-31。

### A4. 體積（實測 content-length，非估算）

**單日 HEAD 實測，2026-06-15**：

| symbol | aggTrades | bookDepth | bookTicker | metrics |
|---|---|---|---|---|
| BTCUSDT | 16,643,518 B (16.6 MB) | 562,493 B | **HTTP 404** | 11,128 B |
| SOLUSDT | 4,571,390 B (4.6 MB) | 559,305 B | **HTTP 404** | 11,418 B |
| GALAUSDT | 554,484 B (0.55 MB) | 565,649 B | **HTTP 404** | 11,200 B |

**bookDepth 的體積與幣種流動性幾乎無關**（0.56 MB/日），因為行數固定＝2880 快照 × 12 帶。

**全歷史逐年平均 MB/檔（aggTrades daily）**：

| symbol | n | span | total | 2021 | 2023 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 2412 | 2019-12-31.. | 44.02 GB | 28.37 | 14.70 | 18.37 | 20.34 |
| SOLUSDT | 2155 | 2020-09.. | 14.25 GB | 6.98 | 6.88 | 7.31 | 4.55 |
| GALAUSDT | 1785 | 2021-09-18.. | 4.52 GB | 11.45 | 1.77 | 0.95 | 0.58 |

**壓縮比（實測 zip → csv）**：aggTrades 4.1–5.4×、bookDepth 3.6×、trades 4.6×。BTCUSDT 單日 aggTrades：zip 16.6 MB → csv 89.9 MB，1,354,069 列。**規劃磁碟時 zip 體積要乘約 5**（或直接轉 parquet）。

### A5. Rate limit／認證／下載方式

- **無需認證**，匿名 HTTPS 直取：`https://data.binance.vision/data/futures/um/daily/{dataset}/{SYMBOL}/{SYMBOL}-{dataset}-{YYYY-MM-DD}.zip`
- 後端是 S3（`server: AmazonS3`），支援 `accept-ranges: bytes`，可 Range 續傳
- 目錄列表：`https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=<path>&max-keys=1000&marker=<lastkey>`（分頁靠 `marker`）
- **每個 .zip 旁都有 `.zip.CHECKSUM`**（SHA-256）。實測驗過一次：
  `GALAUSDT-aggTrades-2026-06-15.zip` CHECKSUM 檔內容 `962d79e3...ffa84e`，本地 `shasum -a 256` 完全相符 → **抓取層應逐檔校驗**。
- 本次勘查連續發出約 150+ 次請求（含多次全目錄分頁列表），**未遇到任何 429／節流**。未見官方公布的 rate limit 數字（**推測**：S3 標準額度，實務上不是瓶頸）。
- **實測單流下載速度**：19,442,564 B/s ≈ **19.4 MB/s ≈ 155 Mbps**（BTCUSDT 單日 aggTrades，0.60 s）。這是這台機器的真實可用頻寬。

### A6. 解析陷阱：header 行不一致

實測 BTCUSDT aggTrades 第一行：

| 檔案 | 第一行 |
|---|---|
| daily 2020-06-15 / 2022-06-15 / 2022-07-31 / 2022-08-01 / 2022-08-10 | 資料列（**無 header**） |
| daily 2022-08-15 / 2023-01-15 / 2024-06-15 / 2026-06-15 | `agg_trade_id,price,...`（**有 header**） |
| monthly 2020-01 | 資料列（**無 header**） |
| monthly 2022-07 / 2022-08 | **有 header** |

→ 切換點約在 **2022-08-11 ~ 2022-08-15**，且 **daily 與 monthly 不同步**（monthly 2022-07 有 header，daily 2022-07 沒有）。
→ **抓取層必須 sniff 第一行**判斷有無 header，不能用固定 `skiprows`。這是會無聲汙染第一筆資料的坑。

---

## B. 清算資料

### B6. data.binance.vision 有沒有 liquidation dataset

- **`futures/um`：沒有。** `data/futures/um/daily/liquidationSnapshot/` 列表回傳空。
- **`futures/cm`：有，但已停更。** 實測：
  - `BTCUSD_PERP`：472 檔，2023-06-25 → **2024-10-14**
  - `ETHUSD_PERP`：474 檔，2023-06-25 → **2024-10-14**
  - 體積極小（合計 < 1 MB）
- 對 USDT 本位永續策略而言，**等同於沒有清算資料**（幣本位是不同市場、不同參與者結構，不能拿來當 USDT 永續的清算 proxy）。

### B7. FAPI `/futures/data/` 免費層歷史深度

實跑 `fapi.binance.com`，逐日 bisect（`startTime` 由今日回推 N 天）：

| endpoint | 29d | 30d | 31d | 32d | 35d | 45d+ |
|---|---|---|---|---|---|---|
| `openInterestHist` | OK | OK | FAIL | FAIL | FAIL | FAIL |
| `topLongShortPositionRatio` | — | OK(48) | — | — | — | FAIL |
| `topLongShortAccountRatio` | — | OK(48) | — | — | — | FAIL |
| `globalLongShortAccountRatio` | — | OK(48) | — | — | — | FAIL |
| `takerlongshortRatio` | — | OK(48) | — | — | — | FAIL |

失敗回應：`{'msg': "parameter 'startTime' is invalid.", 'code': -1130}`

→ **repo 先前記錄的 ~30 天仍然正確，且是精確的 30 天硬邊界**（30 天可、31 天起拒絕），五個 endpoint 一致。
→ 另測 `period=5m&limit=500` 只回 500 根（2026-08-07 00:15 → 2026-08-08 17:50），約 1.7 天。
→ **但這組資料 data.binance.vision 的 `metrics` dataset 有 2020-09-01 起的完整歷史**（5 分鐘粒度，欄位一一對應）。做歷史回測應該用 `metrics` dump，不要用 FAPI endpoint——FAPI 只適合實盤即時取用。

### B8. Coinalyze free tier

用 `.env.research` 的 key（header `api_key`，秒級時戳；本報告未記錄 key 內容）實跑。

**可用 endpoint（全部 HTTP 200）**：`liquidation-history`、`long-short-ratio-history`、`open-interest-history`、`funding-rate-history`、`ohlcv-history`

- `liquidation-history` 回 `{"t":秒, "l":多單清算額, "s":空單清算額}` → **有清算資料，且多空分開**
- `ohlcv-history` 回 `{t,o,h,l,c,v,bv,tx,btx}` → `bv`=buy volume、`tx`=成交筆數、`btx`=buy 筆數，是聚合級訂單流 proxy

**實測歷史深度（`liquidation-history`，BTCUSDT_PERP.A，帶重試以排除偶發空回應）**：

| interval | 可取得 | 邊界 |
|---|---|---|
| `1min` | 3d ✅ 10d ✅ / 20d ❌ 30d ❌ | **約 10–20 天** |
| `5min` | 3d ✅ 12d ✅ 20d ✅ / 40d ❌ 60d ❌ | **約 20–40 天** |
| `15min` | 20d ✅ / 40d ❌ | **約 20–40 天** |
| `1hour` | 60d ✅ 85d ✅(45) 90d ⚠️(9) / 92d ❌ | **約 91 天** |
| `daily` | 800d ✅ 1200d ✅ 1800d ✅ / 2500d ❌ | **約 5 年** |

`open-interest-history` 在 1hour 下與 liquidation 同樣約 90 天邊界。

**警告：這個 API 會偶發回空陣列。** 我第一輪 bisect 得到「5min 在 10/20/30/40 天全空」，加重試後同樣參數 12 天回 356 筆——**單次查詢的空回應不可當作「無資料」**。任何基於此 API 的抓取層都必須帶重試與「空回應 ≠ 邊界」的判定。

→ **結論：Coinalyze 對本專案不可用。** 要做 sweep 級別的分析至少需要 1–5 分鐘粒度，而該粒度只有 10–40 天歷史；有多年歷史的只有 daily，對 sweep 完全無意義。

---

## C. 實務可行性

### C9. 30 幣 × 3 年 aggTrades

**實測**（monthly 檔案 content-length 加總，2023-08 → 2026-07，30 個實際流動的 USDT 永續）：

**總計 138.6 GB（zip）**

前十大／後十大：

| symbol | GB | | symbol | GB |
|---|---|---|---|---|
| ETHUSDT | 22.58 | | ARBUSDT | 2.11 |
| BTCUSDT | 19.86 | | LTCUSDT | 2.07 |
| SOLUSDT | 9.15 | | UNIUSDT | 1.87 |
| DOGEUSDT | 6.50 | | FILUSDT | 1.70 |
| XRPUSDT | 6.03 | | NEARUSDT | 1.67 |
| WLDUSDT | 5.92 | | DOTUSDT | 1.67 |
| SUIUSDT | 5.60 | | SEIUSDT | 1.58 |
| ORDIUSDT | 5.29 | | GALAUSDT | 1.33 |
| TIAUSDT | 5.21 | | ATOMUSDT | 1.26 |
| BNBUSDT | 4.89 | | MANAUSDT | 0.72 |

**BTC+ETH 佔 42.4 GB（31%）**——排除這兩個，其餘 28 幣只要 96 GB。

**時間**：以實測 19.4 MB/s 單流計算，138.6 GB ≈ **2.0 小時**（純下載，忽略解壓）。並行 4–8 連線通常仍受家用上行/下行總頻寬限制，**推測**實際 1–2 小時。請求數只有 30 × 36 = 1,080 個月檔（用 monthly 而非 daily，省 30 倍請求數）。

**磁碟**：解壓後 CSV 約 **600–700 GB**（實測壓縮比 4.1–5.4×）。**不應落地 CSV**——應 streaming 解壓 →（重採樣／特徵化）→ parquet。

### C10. 10 幣 × 2 年 bookDepth

**實測**（daily 檔加總，2024-08-01 → 2026-07-31，BTC/ETH/SOL/BNB/XRP/DOGE/SUI/WLD/LINK/GALA）：

**總計 3.36 GB，7,296 個檔案**

各幣 310–356 MB，幾乎相同（如前述，體積與流動性無關）。

**代價不在體積在請求數**：沒有 monthly，7,296 次 HTTP 請求。以每請求 0.3–0.6 s 計，單線約 **40–70 分鐘**；並行 8 線約 10 分鐘。體積微不足道。

**補充**：`metrics` 30 幣全歷史（2020-09 起）實測 5 幣 = 104 MB → 30 幣約 **626 MB**。同樣是 daily-only，請求數 30 × ~2160 ≈ 65,000 次，這才是真正的成本。若只取 2 年則 30 × 730 ≈ 22,000 次。

---

### C11. 建議：最小可行資料集

**推薦組合（Phase 0，先做 go/no-go）**

| dataset | 範圍 | 體積 | 請求數 | 用途 |
|---|---|---|---|---|
| `aggTrades` (monthly) | 12 個中流動性幣 × 24 個月 | **35.4 GB**（實測加總） | 288 | 真 CVD、吸收、逐筆 aggressor imbalance |
| `bookDepth` (daily) | 同 12 幣 × 24 個月 | **約 4.0 GB** | 8,760 | 唯一可得的 resting liquidity 訊號（粗） |
| `metrics` (daily) | 同 12 幣 × 24 個月 | **約 0.25 GB** | 8,760 | 5 分鐘 OI 變化 = 「停損是否真的被打掉」的代理 |

合計 **約 40 GB zip、約 18,000 次請求、以實測 19.4 MB/s 單流計下載約 35 分鐘**（請求往返開銷另計，bookDepth/metrics 的 17,520 次小檔請求才是主要耗時，建議並行 8 線）。

**幣種建議**：避開 BTC/ETH 主導體積。取中流動性 12 檔（SOL, XRP, DOGE, SUI, WLD, TIA, INJ, OP, ARB, SEI, GALA, LINK）——實測 3 年 53.1 GB、2 年 **35.4 GB**；BTC/ETH 另各取 12 個月作為對照組（實測約 **14.1 GB**）。

**期間建議 2024-08 → 2026-07（24 個月）**：這是 `bookDepth`、`metrics`、`aggTrades` 三者**都完整覆蓋**的區間，避免不同 dataset 起點不一造成的樣本不對齊。若只用 aggTrades 可回到 2020。

**理由與取捨**

1. **核心假設其實只需要 aggTrades。** 「掃前高後出現吸收／CVD 背離」這句話裡，掃單由 kline/aggTrades 自身即可判定，吸收＝大量主動成交但價格位移小，CVD 背離＝簽名成交量與價格方向背離——**三者全部可由 `aggTrades` 單獨計算，且是真值不是 proxy**。這直接解決前一個專案「無法區分是 proxy 太粗還是假設錯」的問題：這次若失敗，可以確定是假設錯。
2. **bookDepth 值得抓，但要降低期待。** 它只有 4 GB，抓了不虧，能檢定「掃單前後 ±0.2% 深度是否被抽走」這種粗粒度問題。但**不要把策略設計成依賴它**（原因見下方反面證據）。
3. **metrics 是最被低估的一項。** 5 分鐘 OI 下降＝部位被平掉，是「停損／清算真的發生了」最接近的可得證據，而且有 2020 年起的完整歷史、體積可忽略。既然拿不到清算資料，這是最佳替代。
4. **明確放棄的**：bookTicker（已死）、liquidationSnapshot（um 不存在）、FAPI `/futures/data/`（30 天）、Coinalyze（分鐘級只有 10–40 天）。**策略設計不得依賴這四者中的任何一個。**

**取捨代價**：策略描述中「TP 瞄準對側未清算流動性池」這一段，**沒有資料可以直接驗證**——真實的清算池位置無從得知。只能用 swing high/low 當代理，而這恰恰又是一個未經驗證的 proxy。建議在 spec 裡把 TP 規則明確降格為「swing 級別的價格目標」而非「流動性池」，並預註冊為固定規則（如 opposite swing 或 R-multiple），**不要用它當自由參數去擬合**。

---

## 最強的反面證據（主動列出）

1. **bookTicker 是最像答案的陷阱。** 它是唯一的逐筆 L1 資料，GALA 單日就近 300 萬行——看起來完美。但它 **2024-03-30 停更且四個 symbol 完全同步**，代表這是資料集層級的終止，不是缺檔。用它做研究＝在一段已經停在兩年多前的區間上回測，之後**永遠無法用同一資料前推驗證或上線**。任何看到 bookTicker 就覺得問題解決了的方案，都應該被否決。

2. **bookDepth 看起來是掛單簿，實際不是——而且對 sweep 這個用例特別致命。**
   - **時間解析度不夠**：約 30 秒一張快照。一次掃單針從突破到收回常在 2–10 秒內完成，**整根針很可能落在兩張快照之間，一張都沒拍到**。「掃單當下掛單被抽走」這個最關鍵的觀察，在 30 秒粒度下大多數情況根本觀測不到。
   - **價格解析度不夠**：最細的帶是 ±0.2%。以 BTC 十萬美元計，±0.2% ≈ ±200 美元寬——**掃單針的幅度常常整根都在這條帶裡面**，帶內的深度分布完全不可見，無法回答「針尖那個價位有沒有牆」。
   - 兩者疊加：bookDepth 只能做「日內／小時級的整體深度環境」這種 regime 變數，**不能做事件級的吸收判定**。

3. **aggTrades 的「聚合」會誤導筆數類特徵。** 同價、同方向、同毫秒的多筆成交被併成一筆，所以 aggTrades 的**行數不是成交筆數**（實測 GALA 同日：trades 116,320 筆 vs aggTrades 34,460 筆，3.4×）。若特徵含「平均單筆大小」「大單筆數」「訂單分割程度」，用 aggTrades 會系統性偏誤。修法：用 `last_trade_id − first_trade_id + 1` 還原真實筆數，或直接用 `trades`（體積約 1.6×）。這正是全域工程原則第 1 條（同源同單位）的典型踩點。

4. **完全沒有 USDT 永續清算資料。** 策略名稱裡的「liquidity sweep」「未清算流動性池」在資料上**無法直接觀測**——um 沒有 liquidationSnapshot，cm 的也停在 2024-10-14，Coinalyze 分鐘級只有 10–40 天。這意味著假設中「掃的是停損／清算叢集」這一環**永遠只能是推論**，不能是被驗證的事實。若專案的說服力建立在「我們知道流動性池在哪」，那它建立在沙上。

5. **bookDepth 的 2023-01-01 起點造成樣本不對齊與 regime 侷限。** 任何用到深度的分析，樣本被鎖在 2023 年之後（部分幣更晚，如 ORDI 2023-11、TIA 2023-10）。這段期間大致是單一個多頭 regime，**沒有 2022 年那種下跌市可測**。而純 aggTrades 的分析可回到 2020，兩者的結論不可直接互相佐證——不同樣本期。

6. **header 行不一致會無聲汙染資料。** daily 在 2022-08 中旬切換，monthly 切換點不同（monthly 2022-07 已有 header 而 daily 2022-07 沒有）。用固定 `skiprows=0` 會把 header 當成一筆成交（price 解析失敗或變 NaN）；用固定 `skiprows=1` 會丟掉每個舊檔的第一筆真實成交。**必須 sniff。**

7. **Coinalyze 的空回應假象。** 同一組參數第一次回空、重試後回 356 筆。若抓取層把單次空回應當作「歷史邊界」或「該時段無清算」，會產生**看起來合理但完全錯誤的資料洞**。這類錯誤不會拋例外、單元測試也測不出來。

8. **磁碟與處理時間才是真瓶頸，不是下載。** 138.6 GB zip 解壓後 600–700 GB CSV。就算只做 Phase 0 的 35.4 GB，解壓後也有約 **160–190 GB**，且 BTCUSDT 單日就有 1,354,069 列——12 幣 × 24 個月推估約 **29 億列**（以實測 81,373 列/MB-zip 換算）。逐筆掃描一輪在單機上是小時級。設計時應一次 streaming 解壓就把特徵算完落 parquet，**不要打算反覆重掃原始檔**。

---

## 可重用的既有資產

- `/Users/jim/projects/vault/data/cache/harmonic_m/`：97 幣 Binance FAPI kline parquet（15m/1h/4h/1d，2020-01 → 2026-06）——sweep 偵測（前高前低）可直接建在既有 kline 上，**不需要為此重抓**。
- `/Users/jim/projects/vault/scripts/m_data.py`：既有 Binance FAPI 抓取層，可作為新 dump 抓取層的風格範本（但 dump 是 S3 zip，需另寫，注意 CHECKSUM 校驗與 header sniff）。
- 諧波專案（sub-project M）的零 look-ahead 事件回測框架——本專案的事件結構（事件時點 → 未來窗口結果）與其同型，應優先重用而非重寫。

---

## 附註：查證方法可復現

所有數字來自以下形式的實跑指令（無需認證）：

```bash
# 目錄列表 + 體積
curl -s "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data/futures/um/daily/aggTrades/BTCUSDT/&max-keys=1000"

# 單檔體積
curl -sI "https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-06-15.zip"

# 欄位
curl -s ".../GALAUSDT-aggTrades-2026-06-15.zip" -o a.zip && unzip -p a.zip | head -3

# CHECKSUM 校驗
curl -s ".../GALAUSDT-aggTrades-2026-06-15.zip.CHECKSUM"; shasum -a 256 a.zip

# FAPI 深度邊界
curl -s "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&startTime=<now-31d>&limit=10"
```

輔助腳本（stats.py / basket.py / bd.py / ca*.py）留在本次 session scratchpad，未寫入 repo。

---

## 【重要更正，2026-08-09】§C11 的「用 monthly 檔」建議已被推翻

本報告驗證了各 dataset 的**體積、欄位、歷史起點**，但**沒有驗證排序與完整性**。
實作階段的 N-G0 gate 與抓取層的排序守衛連續攔下三個問題：

| # | 問題 | 證據 | 影響 |
|---|---|---|---|
| 1 | **`aggTrades` 的單一時戳會讓跨棒邊界的聚合被錯歸** | GALAUSDT 2023-03-07 11:00/12:00 邊界：原始 id 478638628(qty 2,813, …399969) 與 478638629(qty **41,980**, …400045) 被聚合成一列、時戳取第一筆 → 41,980 錯歸到 11:00，恰等於觀測差額 | N-G0 在 4 個 symbol 全部 FAIL（相對誤差 1.2e-4 ~ 5.8e-4）。**改用 `trades` 後 24/24 棒逐位相符** |
| 2 | **部分 monthly 封存順序錯亂** | `BTCUSDT-trades-2023-01.zip`：8,237 萬列中 **3,040 萬處時間倒退**，原始文字逐列交錯兩段 id 序列；**SHA-256 與官方 CHECKSUM 相符**（非傳輸損壞） | 若未擋下，所有 `searchsorted` 事件查詢全錯 |
| 3 | **部分 monthly 封存缺資料** | `GALAUSDT-trades-2023-03`：monthly 17,631,789 列 vs 31 個 daily 檔串接 **17,759,773 列**，**少 127,984 筆（0.7%）**；daily 版本的 N-G0 對帳 744/744 棒、`max_rel_err = 0.0` | 靜默的 0.7% 資料缺漏 |

**修正後的建議**：

- 資料集用 **`trades`**（逐筆原始）而非 `aggTrades`——每筆有自己的時戳，
  與 kline 的時間語意精確一致；且 `quote_qty` 直接提供（與 `qty × price`
  相對差 2.22e-16）。代價是體積約 +48%。
- 一律走 **`daily/`** 而非 `monthly/`，**逐日落檔**。除正確性外，
  BTC 單月 8,200 萬列串接時峰值記憶體約 7 GB，逐日檔可安全處理。
- 抓取層必須有**硬性守衛**：單日檔內 `time` 非遞減、每個 `.zip` 的 SHA-256
  相符。不符即拋錯，**不靜默排序、不靜默跳過**。

**教訓（值得寫進未來所有外部資料層的檢查清單）**：
「可下載」不等於「可用」。體積與欄位對了，**順序、完整性、跨源一致性**仍須逐檔驗證，
而且官方 checksum 只能證明「你下載到的與官方發布的相同」，**不能證明官方發布的是對的**。
