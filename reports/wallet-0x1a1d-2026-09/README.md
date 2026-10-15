# HL 錢包 0x1A1d…0111 策略解剖（2026-09-21 快照）

地址：`0x1A1d5eF3256e1A7de2db2082D7A1eEb976c90111`。工具鏈從 `reports/wallet-0xe4c0-2026-09/` 複製，
本次修正 `exposure.py`／`positions.py` 只讀 default dex 的問題（HIP-3 部位在 `states["xyz"]`），並加 `extra.py`。

完整報告（一句話／帳戶概況／交易機制／大波動日／持倉時間／可複製性／資料極限）在 pandora：
`~/projects/obsidian/pandora/wallets/hl-0x1A1d...0111-五分K吃單多頭網格.md`。

## 結論

- 是程式：吃單成交 45% 落在分鐘 ≡0 (mod 5)、44% 在每分鐘前 10 秒（均勻應為 20%／17%），maker 成交秒數均勻。5 分 K 收盤輪詢下單。
- 只做多、35 幣（10 加密＋25 HIP-3）、81% 吃單、每趟單邊名目 55（HIP-3）／164（加密）美元；勝率 70.1%，均贏 2.43／均輸 −2.36，贏輸中位皆 ±170 bps。1,000 → 1,304（+30.4%，97 天），日點 MDD −3.1%。
- HIP-3 用 isolated 6–10x 小額保證金，清算＝停損（逆向 p50 −514 bps），清算後同幣重進 p50 78 秒；61 次自我清算 −165，吃掉 HIP-3 毛利六成。
- HYPE +159 佔 52%；三個 HYPE −6% 日虧 −64；名目最大 5 趟全虧。上漲市場的只做多網格 beta。
- 常駐 9 幣 69 張 Alo 買單階梯（−3%～−21%，名目 4.65 倍權益）當接崩盤網。**執行層可借（清算停損＋深階梯），訊號層看不到；信心有限。**

## 資料與腳本

`scripts/fetch_wallet.py <address>`（HL info API 唯讀；重疊分頁＋tid 去重）→ `data/0x1a1d5ef3/`。
`scripts/fetch_funding_recent.py <address>`：`userFunding` 從 2026-03-01 分頁重抓。

| 腳本 | 輸出 | 內容 |
|---|---|---|
| `overview.py 0x1a1d5ef3` | `data/overview.txt`、`trips.json`、`daily.json` | 帳戶狀態、成交剖面、日損益、flat→flat 回合 |
| `positions.py 0x1a1d5ef3` | `data/positions.txt`、`episodes.json` | 翻倉切段回合與持倉時間（分期／多空／名目加權）、HYPE/SNDK/MINIMAX/PONS 逐日、目前持倉開倉時點（全 dex）、UTC 時段、多空並行 |
| `exposure.py 0x1a1d5ef3` | `data/exposure.txt`、`exposure_daily.json` | 重建部位 vs 交易所核對（全 dex 合併）、逐日美元曝險、ledger 全流 |
| `events.py` | `data/events.txt` | 前 14 大 |日淨損益| 日的市場背景與當日行為 |
| `deep.py 0x1a1d5ef3` | `data/deep.txt` | portfolio 週點權益曲線與大變動點 |
| `ladder.py 0x1a1d5ef3` | `data/ladder.txt`、`ladder_rows.json` | 目前掛單階梯結構、每回合建倉／出場結構、最差回合出場方式 |
| `extra.py 0x1a1d5ef3` | `data/extra.txt` | 清算成交角色（自己 vs 對手）、HIP-3 vs 加密拆分、掛單名目對權益、週日剖面、建倉 maker 比例逐月、**自我清算解剖**（逆向幅度、輸單結束方式、重進延遲）、**bot 指紋**（秒數／分鐘 mod 5 分布、clip 尺寸離散度）、每趟名目分布 |

## 資料極限

- 成交完整（2,407 筆、6/16 起）；重建部位兩個幣 DRIFT=0。
- unified account：總資產用 portfolio 端點（= spot USDC total 1,304.27）；各 dex accountValue 是保證金口徑不可相加。
- 自我清算判定依 `liquidation.liquidatedUser`；ledger 只記 backstop 型那一次（9/10 CL）。
- 5 分 K 輪詢是從時間戳節拍推論，訊號本體不可見。
