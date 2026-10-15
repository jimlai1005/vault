# HL 錢包 0xf97a…ddd1 策略解剖（2026-09-21 初版，gridbot 原型錢包）

地址：`0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1`。2026-07-06 曾以 fills 統計做過一次（pandora `raw/target-strategy-analysis.md`，
作為 gridbot 設計依據）；本次是固定五題流程的完整初版，工具鏈自 `reports/wallet-0xe4c0-2026-09/` 複製並修了兩個資料陷阱。

完整報告在 pandora：`~/projects/obsidian/pandora/wallets/hl-0xf97a...ddd1-深度接刀階梯HYPE網格.md`。

## 結論

- 兩層打法：96% 現金＋70 張離價 3%–23% 的深度買單（HYPE/ETH/ZEC/BTC/SOL/XRP/UNI/BNB/PONS，名目 2.38M＝權益 765k 的 3.1 倍）等崩盤來填；平時在 HYPE 跑 close-heavy 網格。開倉 100% maker、出場 90% 吃單（贏單 8.5 分鐘內倒出、輸單 7 秒）。
- 12 個月（2025-09-18 → 2026-09-20）實現淨利 +676k（closedPnl 704,657 − 費 28,487；perp +846k、現貨 −141k 會計數）；portfolio 口徑 +961k。勝率 85%、均贏 1,538 / 均輸 −190。
- 2025-10-10 崩盤日一天 +160k（全期 24%）：21:13–21:17 UTC 階梯接 47k 顆 HYPE @36、21:23–21:39 @39.3 倒出 +78.8k，BNB/BTC/ETH 階梯同時被掃 +39k。正向大日全是振幅 >30% 的日子；不對應可排程事件。
- 沒有停損：2025-09-22～26 抱 30–37k 顆 HYPE 吃 −30%、五天 −175k；2025-12～2026-01 32.5k 顆抱 54 天，portfolio 兩週 −180k 未實現。
- 持倉 p50 6.1h、p90 2.9d、最長 75.8d；2026-07 起中位拉到 14.8h、每日成交 248 → 113 筆——7/6 版描述的「0.05% 間距高密度網格」已不是現況。執行層可借（gridbot 已借），PnL 是崩盤事件＋HYPE beta，信心有限。

## 資料與腳本

`scripts/fetch_wallet.py <address>`（HL info API 唯讀；重疊分頁＋tid 去重；**新增**：feeToken 非 USDC 的成交把手續費乘價換算成 USD，原值存 `feeRaw`）→ `data/0xf97ad670/`。
`scripts/fetch_funding_recent.py <address>`：`userFunding` 從 2026-03-01 分頁重抓。

| 腳本 | 輸出 | 內容 |
|---|---|---|
| `overview.py 0xf97ad670` | `data/overview.txt`、`trips.json`、`daily.json` | 帳戶狀態（各 dex）、掛單、portfolio、帳本、成交剖面、日損益、flat→flat 回合 |
| `positions.py 0xf97ad670` | `data/positions.txt`、`episodes.json` | 翻倉切段回合與持倉時間（四分期／多空／名目加權）、HYPE 2025-09/10、2026-06、2026-08–09 與 ZEC、xyz:CL 逐日、時段、多空並行 |
| `exposure.py 0xf97ad670` | `data/exposure.txt`、`exposure_daily.json` | 部位重建 vs 交易所（**跨全部 dex＋現貨餘額**）、逐日曝險、帳本月彙總＋非存提列、HYPE 9/30、10/10–11、6/13–14 與 MAX 逐時 |
| `events.py` | `data/events.txt` | 前 24 大 |日淨損益| 日的市場背景與當日行為 |
| `deep.py 0xf97ad670` | `data/deep.txt` | portfolio 全期週點權益／cumPnl 與大變動點 |
| `ladder.py 0xf97ad670` | `data/ladder.txt`、`ladder_rows.json` | 現貨對解名、目前掛單階梯、每回合建倉／出場結構（含 HYPE-only、xyz-only）、最深階梯、最差回合、10/10 逐分鐘 |

## 資料極限

- 成交 35,467 筆＝API 保留上限，最早 2025-09-18；更早只有 portfolio 週點。`data/0xf97ad670/fills_raw.json.gz` 是未換算手續費的原始檔。
- 部位核對：perp PONS、xyz:CL DRIFT=0；現貨 UETH 100.05／UBTC 2.009 的差是 6/15、8/4 的 send 轉出（`XFER?`），`exposure.txt` (b) 表在那之後多算了這兩桶。
- 現貨 closedPnl 是對歷史成本的會計數（9/30 −131k 的名目只有約 30k）；perp closedPnl 沒有這問題。
- 修正前的假象：6/13 −119k、6/14 −53k 來自 MAX 手續費 177,504 顆被當美元；換算後全期費用 206,763 → 28,487。
- 資金費率只補 2026-03 起；日損益 UTC 切、只含已實現。
