# 錢包 0x060d…81eb 行為分析 — IPO／上新事件剝頭皮（備用 alpha）

分析日期：2026-09-06。地址：`0x060d6d3136d19e69707b71b0cc78540d7c2b81eb`。
狀態：**觀察樣本，非我方策略**。列為備用 alpha 候選，尚未做任何回測或可行性判定。

## 一句話結論

這是一支在 HIP-3 股票永續（xyz / io / para / vntl dex）上，**專打「標的現股 IPO 首日」與「新合約上市」的秒級逆勢剝頭皮機器人**。
獲利極端集中在少數事件日（前 5 天佔 55%），其餘日子只是小額磨損。

## 帳戶概況（資料來源：HL info API，2026-09-06 快照）

| 項目 | 數字 |
|---|---|
| 入金 | 2026-01-18 存入 40,000 USDC，之後無再入金 |
| 目前資產 | 114,015（全現貨 USDC/USDE/USDT0，無持倉無掛單）；另有 10,000 於 6/23 橋出到 HyperEVM |
| 全期 PnL（portfolio 端點） | +83,843；1–4 月僅 +8.7k，5 月起爆發 |
| 成交（fills API 只保留到 5/14） | 19,533 筆、名目 31.3M、手續費 10,288（其中 builder fee 6,153） |
| 毛 closedPnl（5/14 起） | 72,943 |
| 完整回合 | 1,567 趟，勝率 61.5%，中位持有 48 秒，p90 7 分鐘 |
| 單筆部位 | 中位 5k，p95 30k，最大約 62k |
| 交易日 | 65 天，毛利為負僅 3 天，最差 −75，中位 +317（毛，未扣費） |
| PnL 集中度 | 前 5% 回合佔 72%，前 1% 佔 39% |

## 行為特徵（證據見 scripts/analyze2–4.py 輸出）

1. **搶新上市**：多數標的在合約上市後幾分鐘到幾小時內開始交易（SKHY 9 分鐘、GPRO 19 分鐘、PONS 56 分鐘、CXMT 3 小時）。
   SKHY / GPRO / MRNA / CBRS 的獲利 100% 來自前 48 小時，之後不再碰。
2. **只在標的現股開盤時段交易**：CXMT 集中 01–05 UTC（上海盤），美股名集中 13–17 UTC（美盤）。
   暗示訊號源是現股即時報價（現股領先永續的 lead-lag），或至少是現股開盤時的永續重定價。
3. **逆勢進、掛單出**：進場前 5 分鐘價格平均逆著它的方向走（買急跌、空急拉）；
   進場約半數用 IOC 掃穿多檔（同一毫秒吃 3–6 個價位），出場多為限價被動成交（maker 端 PnL 66k / taker 端 6.8k）。
4. **程式交易**：99.9% 成交帶 cloid，每張單平均 3.7 筆成交。
5. **多空對稱、不留庫存**：開多 4,529 vs 開空 3,913；時間加權部位僅數百美元。

## 大波動日與對應事件

| 日期 (UTC) | 毛利 | 標的 | 永續走勢 | 發生了什麼 |
|---|---|---|---|---|
| 2026-08-19 | 12,898 | xyz:UNITREE 8,252 / para:UNITREE 2,631 / xyz:MRNA 2,015 | UNITREE 01:00 UTC 一小時內 96→144（+50%）；MRNA 13:47 起 | 宇樹科技科創板掛牌首日（688836，發行價 150.8，收 845，+460%）；同日 Moderna 因黑色素瘤三期數據暴漲 177%，xyz 於 13:00 UTC 上新 MRNA 永續 |
| 2026-07-27 | 10,236 | xyz:CXMT | 01:00 UTC 一小時內 6.0→7.27，日內區間 30%，本錢包佔市場成交 2.4% | 長鑫科技科創板掛牌首日（688825，發行價 8.66，首日漲逾 500%）；xyz:CXMT 為 pre-IPO 永續，當日對真實成交價收斂 |
| 2026-09-01 | 6,913 | io:GPRO 4,607 / xyz:SHEIN 1,581 / PONS 725 | GPRO 13:00 UTC 上新後 1.87→1.14（−63%）；SHEIN 01:00–01:44 UTC | Shein 港交所掛牌首日（00625，跌 9%）；EntropyIO dex 上新 GPRO 永續（標的身分未查證，funding multiplier 0.15 與股票類不同） |
| 2026-07-15 | 6,837 | xyz:CXMT 5,732 / CASHCAT 976 | CXMT 首根 K 01:00 UTC，日內區間 44%，本錢包佔 3.6% | xyz 上新 CXMT pre-IPO 永續（正式掛牌前 12 天） |
| 2026-05-14 | 3,463 | xyz:CBRS | 17:02–18:06 UTC，290→392（+41%） | Cerebras Nasdaq 掛牌首日（CBRS，IPO 價 185，12:59 EDT 開出 350，收 311）；錢包在開盤後 3 分鐘進場 |
| 2026-07-10 | 3,427 | xyz:SKHY | 13:50 UTC 單趟 2,565 | SK hynix ADR Nasdaq 掛牌首日（IPO 價 149，開 170，收 168） |

規律：**六個大日全部是「現股 IPO 首日」或「新合約上市日」**，且 IPO 日期是事前公開的日曆事件。
這使得事件本身可預測，不可預測的只有當天的波幅與競爭者數量。

事件來源：
- Unitree：[Bloomberg](https://www.bloomberg.com/news/articles/2026-08-18/unitree-robotics-set-to-debut-after-904-million-shanghai-ipo)、[Fortune](https://fortune.com/2026/08/19/unitree-china-dancing-robots-ipo-trading-surge-valuation/)
- CXMT：[Yahoo HK](https://hk.finance.yahoo.com/news/%E4%B8%AD%E5%9C%8B%E8%A8%98%E6%86%B6%E9%AB%94%E6%99%B6%E7%89%87%E8%A3%BD%E9%80%A0%E5%95%86%E9%95%B7%E9%91%AB%E5%AD%98%E5%84%B2%E5%B0%87%E6%96%BC7%E6%9C%8827%E6%97%A5%E5%9C%A8%E4%B8%8A%E4%BA%A4%E6%89%80%E6%8E%9B%E7%89%8C%E4%B8%8A%E5%B8%82-065333532.html)、[鳳凰網](https://finance.ifeng.com/c/8v5gHjMdeBQ)
- Cerebras：[CNBC](https://www.cnbc.com/2026/05/14/cerebras-cbrs-stock-trade-nasdaq-ipo.html)、[IPOScoop](https://www.iposcoop.com/the-ipo-buzz-cerebras-cbrs-prices-ipo-at-185-25-above-range-2/)
- SK hynix：[Bloomberg](https://www.bloomberg.com/news/articles/2026-07-10/sk-hynix-indicated-to-climb-17-after-26-5-billion-adr-offering)
- Shein：[CNBC](https://www.cnbc.com/2026/09/01/shein-ipo-market-debut-hong-kong.html)
- Moderna：[Bloomberg](https://www.bloomberg.com/news/articles/2026-08-19/moderna-s-160-surge-burns-shorts-in-painful-5-billion-loss)
- EntropyIO：[Crypto Briefing](https://cryptobriefing.com/entropyio-pre-ipo-perps-hyperliquid/)

## 出場策略細節（scripts/analyze4.py 回合重建；1,567 趟）

**持倉時間**（秒）：p10 6 / p25 15 / p50 39 / p75 99 / p90 251 / p95 430 / p99 1,048。
贏家中位 34 秒、輸家 44 秒——沒有「讓獲利奔跑」的預設，例外只有事件日的幾筆大單。

**機制**：進場成交後立即掛一張限價止盈單（每趟出場單中位 1 張、2 個價位），進場完成到第一筆出場成交中位 20 秒。
止盈沒被打到就市價出場。三種出場結果：

| 出場型態 | 趟數 | 勝率 | 中位報酬 | 中位持有 | 淨利 |
|---|---|---|---|---|---|
| 全部 maker（止盈單成交） | 635 | 80% | +54 bps | 27 s | +44,210 |
| 全部 taker（市價放棄／停損） | 548 | 30% | −5 bps | 39 s | −1,724 |
| 混合（部分止盈後市價清掉） | 384 | 50% | +6 bps | 71 s | +19,033 |

**止盈距離不是固定值**：maker 出場的報酬 IQR 18–119 bps；事件日中位 +72 bps、非事件日 +44 bps，隨當下波動放大。

**停損／放棄**：taker 出場的輸家中位 −14 bps、四分位 −34 bps、十分位 −73 bps，持有中位 39 秒、75% 在 82 秒內。
看起來是「時間停損＋價格停損」並用：約 1–2 分鐘沒到止盈或逆行 30–70 bps 就市價出。最差 1% 的回合 −157 bps，全樣本從不凹單。

**大贏家的處理**（事件日才出現）：
- 分批止盈階梯：GPRO 9/1 14:00 那趟掛三張止盈 1.5022 / 1.5148 / 1.5246，剩餘部位在回落後一次出在 1.4854（淨 +2,165）。
- 順勢加碼：CXMT 7/27 01:15 那趟 6.46 進場，5 秒後 6.85 加倉、6.91、7.00 再加，止盈階梯 6.95 / 6.975 / 7.196（淨 +4,616，持有 393 秒）。
- 最大單筆 UNITREE 8/19 01:17：112.5 掛單被動接到，持有 14 分鐘，一次市價掃出在 128–129（+14%，淨 +4,318）。這筆與其他回合型態不同，可能是人工介入或追蹤停利。

**部位**：固定名目 clip，74% 的回合最大部位落在整數 $1k 的 ±3% 內（5k 最常見，其次 10k / 3k / 2k / 15k / 20k），隨權益成長逐步放大。

**事件日的時間窗**：獲利集中在標的開盤後第一小時——8/19 UNITREE 第 1 小時 $7.5k（全日 $8.3k）、7/27 CXMT 第 1 小時 $6.6k（全日 $10.2k）。
事件日的回合勝率也只有 50–70%，多數回合是小賺小賠，錢來自 2–3 趟大的。

## 可複製性評估（判斷題，信心有限）

可複製的骨架：新合約監控（輪詢各 dex meta）＋ IPO 日曆 ＋ 薄簿逆勢進場 ＋ 限價出場 ＋ 硬性時間停損 ＋ 部位上限。
尚未證實的 alpha：邊到底來自「純微結構過衝回歸」還是「現股即時報價的資訊優勢」。時段分布偏向後者，
那就需要 A 股／港股／美股低延遲報價源，並與同訊號機器人拚速度。

成本門檻：來回 6–8 bps（builder fee 2 bps 是固定成本），中位單趟毛利僅數 bps，靠尾部撐全場；勝率跌破約 55% 轉負。
報酬型態：一年幾次的事件日決定全年，錯過 5 個關鍵日少一半。

建議驗證順序（尚未執行）：
1. 挑一檔 xyz 股票永續，在現股開盤時段同步錄 HL 中間價與現股報價，量永續是否穩定落後現股數秒。
2. 落後存在 → 用下一個已知 IPO 日（HL 上有 pre-IPO 永續者）做 dry-run 記錄，不下單。
3. 有機制證據後再寫 spec / plan。

## 資料極限

- fills API 只回溯到 2026-05-14，1–4 月行為不可見。
- closedPnl 為毛利未扣費；日盈虧統計要另扣費。
- 無法確認是否有姊妹帳戶（每日 08:07 UTC 從 0x0625…3072 收 ~1 USDE，來源未查）。
- 1m/5m/15m K 線只保留最近數千根，pre/post 進場報酬分析僅涵蓋 8 月下旬以後的標的。

## 檔案

- `data/`：API 原始快照（`fills.json.gz` 為 19,533 筆成交；其餘為帳戶／帳本／portfolio）。
- `scripts/fetch_wallet.py`：重抓（唯讀 info API，不需 key），輸出到腳本同目錄的 `wallet/`。
- `scripts/analyze1.py` → `analyze4.py`：依序執行；analyze1 產生 `wallet/fills.pkl` 供後續使用。
  要用快照重跑：把 `data/*.json` 解壓到 `scripts/wallet/` 即可。
