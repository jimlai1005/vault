# HL 錢包 0xe4c0…d02d 策略解剖（2026-09-21 複查快照）

地址：`0xe4c0f75521c93a8c8a14e3770ca891c9a10ed02d`。9/12 已在 `reports/wallet-trio-2026-09/` 分析過一次；
本次多 9 天資料、換用重疊分頁抓取器、補階梯結構量化，並修正 9/12 兩處描述。

完整報告（章節：一句話／帳戶概況／交易機制／大波動日／持倉時間／可複製性／資料極限／對 9/12 的修正）在 pandora：
`~/projects/obsidian/pandora/wallets/hl-0xe4c0...d02d-階梯掛單多頭波段.md`。

## 結論

- 只做多、84% maker 的階梯接刀：一幣 15–20 張遞減買單跨約 2%（ZEC 目前 100 張跨 20.8%），出場是 1–2 張止盈掛單，大部位分天出。
- 4k → 147k（+143k，178 天）；8/19 起 33 天賺 123k。PUMP 一趟 +50.9k（36%），BTC/HYPE/ZEC +55k。3–7 月只 +16k。
- 持倉 p50 6.0h、p75 1.3d、p90 5.4d、最長 12.9d；贏單 7.2h vs 輸單 1.5h；8 月 p50 1.0d。
- |日實現| ≥5k 有 12 天（11 天在 8/19–9/20）；≥10k 5 天；唯一大虧 9/20 CASHCAT −12.6k（階梯接滿 767k 顆遇 −30%，反彈用掛單砍）。
- 無停損單、毛曝險到權益 3.5 倍、零對沖。**執行層可借，選幣與抱單不可抄；PnL 是山寨多頭 beta。**

## 資料與腳本

`scripts/fetch_wallet.py <address>`（HL info API 唯讀；重疊分頁＋tid 去重）→ `data/0xe4c0f755/`。
`scripts/fetch_funding_recent.py <address>`：`userFunding` 從 2026-03-01 分頁重抓（startTime=0 只回最早 500 筆）。

分析（依序執行，後者依賴前者輸出）：

| 腳本 | 輸出 | 內容 |
|---|---|---|
| `overview.py 0xe4c0f755` | `data/overview.txt`、`trips.json`、`daily.json` | 帳戶狀態、成交剖面、日損益、flat→flat 回合 |
| `positions.py 0xe4c0f755` | `data/positions.txt`、`episodes.json` | 翻倉切段回合與持倉時間（分期／多空／名目加權）、PUMP/HYPE/BTC/ZEC 逐日部位、目前持倉開倉時點、UTC 時段、多空並行 |
| `exposure.py 0xe4c0f755` | `data/exposure.txt`、`exposure_daily.json` | 重建部位 vs 交易所核對、逐日多空美元曝險、ledger 全流、PUMP 8/22–24 與 ZEC 9/9–12 逐時 |
| `events.py` | `data/events.txt` | 前 20 大 |日淨損益| 日的市場背景與當日行為 |
| `deep.py 0xe4c0f755` | `data/deep.txt` | portfolio 全期週點權益曲線與大變動點 |
| `ladder.py 0xe4c0f755` | `data/ladder.txt`、`ladder_rows.json` | 目前掛單階梯結構、每回合建倉／出場的掛單數・跨度・maker 比例・深度、最差回合的出場方式、CASHCAT 9/18–20 逐時與 9/20 逐分鐘 |

## 資料極限

- 成交完整（10,343 筆）；重建部位四個幣 DRIFT=0（`exposure.txt` (a) 段）。
- 日損益 UTC 切、只含已實現；portfolio 點含未實現。
- `@334` = KNTQ/USDC 現貨對。
- 9/12 快照掛單 tif：181 張 Gtc、29 張 Alo（PUMP）；本次 153 張全 Gtc。
