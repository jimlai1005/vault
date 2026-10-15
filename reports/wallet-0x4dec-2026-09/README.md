# HL vault `pmalt`（0x4dec…27f6）策略解剖（2026-09-19 快照）

地址：`0x4dec0a851849056e259128464ef28ce78afa27f6`——**Hyperliquid vault**，名稱 `pmalt`，自述「pair trading (mostly)」，
leader `0x526178b96c8c5d7a4e4f76f298ec0170aa0d1d2a`，2024-10-12 以 500 USDC 建立。

完整報告（章節：一句話／帳戶概況／交易機制／大波動日／持倉時間／可複製性／資料極限）在 pandora：
`~/projects/obsidian/pandora/wallets/hl-0x4dec...27f6-pmalt金庫多HYPE空山寨.md`。

## 結論

- 多 HYPE（＋BTC、PAXG）／空 ETH、BNB、山寨的多空書，淨曝險 −2.3M～+0.8M，不是市場中性。HYPE 佔 64% 成交、每天刷幾萬顆存貨。
- 勝率 92%、均贏 1.3k／均輸 −23.7k；輸單抱 22.6h 中位、贏單 2.6h。無停損、逆勢攤平。
- 2026-05-13 AV 高點 1.39M（追隨者 3–4 月淨入 668k）。5/15 翻空 HYPE、加到 40.8k 顆（2.24M 名目、零多單），5/20–21 HYPE 47→62.6 軋空，5/21 單日實現 −482k；追隨者當日提 323k。累計 PnL 兩週內 +287k → −187k。
- 現在 AV 430k，抱 SOL（105 天、逆行 80%）、JUP（100 天、逆行 80%）、SUI、ETH 空單，掛回本止盈單，無停損。
- 82/99 可見追隨者虧錢；APR −10%。**不建議複製、不建議跟單。**

## 資料與腳本

`scripts/fetch_wallet.py <address>`（HL info API，唯讀；分頁用重疊續抓＋tid 去重）→ `data/0x4dec0a85/`。
`scripts/fetch_funding_recent.py`：`userFunding` 從 startTime=0 只回最早 500 筆，另從 2026-03-01 分頁重抓。

分析（依序執行，後者依賴前者輸出）：

| 腳本 | 輸出 | 內容 |
|---|---|---|
| `overview.py 0x4dec0a85` | `data/overview.txt`、`trips.json`、`daily.json` | 帳戶狀態、成交剖面、日損益、flat→flat 回合 |
| `positions.py 0x4dec0a85` | `data/positions.txt`、`episodes.json` | 含翻倉切段的回合與持倉時間、HYPE 逐日部位軌跡、目前持倉開倉時點、分期、UTC 時段 |
| `exposure.py 0x4dec0a85` | `data/exposure.txt`、`exposure_daily.json` | 重建部位 vs 交易所核對、逐日多空美元曝險、5 月追隨者存提、5/19–21 HYPE 逐時 |
| `events.py` | `data/events.txt` | 前 16 大 |日淨損益| 日的市場背景與當日行為 |
| `deep.py 0x4dec0a85` | `data/deep.txt` | portfolio 全期週點權益曲線與月級大變動點 |

`data/0x4dec0a85/vaultDetails.json`：vault 名稱、leader、追隨者（上限 100）、APR。

## 資料極限

- 成交只回到 2026-03-09（57,680 筆）；之前只有 `portfolio` 週點。
- 第一次抓漏 864 筆（同一毫秒跨頁），已修；重建部位與 `clearinghouseState` 逐幣吻合（`exposure.txt` (a) 段 DRIFT=0）。
- 同一毫秒內 `tid` 順序 ≠ 執行順序，重建沿用 API 回傳順序。
- `vaultWithdraw` 金額欄位是 `requestedUsd`。
- 日損益 UTC 切、只含已實現；7/29、8/21、9/18 的大週點是未實現浮虧。
- HYPE 5/20 催化（ETF 上市、軋空）來源：Santiment 經 bitcoinworld.co.in 報導，未核實第二來源。
