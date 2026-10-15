# 22 顆錢包批次分析（2026-09-21）

使用者一次給 22 個 Hyperliquid 地址要求完整分析。本目錄是資料與工具鏈；**報告在 pandora**
`~/projects/obsidian/pandora/wallets/`（22 份，索引見該目錄 `INDEX.md`）。

## 結論五條

1. **這不是 22 顆無關的錢包，是一個 ZEC 群組。** 20/22 交易過 ZEC，**14 顆此刻持有**（13 多 1 空），
   合計名目 **$21.4M**、未實現 **+$8.58M**、已實現 **+$3.50M**。ZEC 從 2026-08-15 的 $488 漲到
   09-21 的 $1,528（+213%），關鍵日 8/19（+11.1%）、8/21（+29.1%）、9/6（+19.6%）、9/16（+20.4%）。
2. **是同一個公開訊號，不是協同。** 14 顆現有部位中有 6 顆開在 **8/19–8/21**——也就是突破當天與
   +29% 那天，**不是事先佈局**。沒有任何證據支持協同；`cohort.py` 的開倉日對照 ZEC 日線即是依據。
3. **「共用注資來源」被推翻為無證據力。** 15/22 由 `0x6b9e7731…5390a24` 注資（$22.2M，只進不出），
   但實測該地址單一 25 天切片就有 **583 個不同收款地址、自己零成交、殘額 $7.7k** → 提款熱錢包。
   這同時**修正了 INDEX 裡對 0x9264/0x9046/0xe4c0/0xf97a 的舊假設**。真正值得追的關聯是
   `0xf70da978…3dbef`（注資 3 顆，**自己有 1,653 筆成交**）。
4. **機制可複製性：多數不值得抄。** 機制最可外化的是 `0xa8b9…6098`（789 回合、秒級、近全 maker、
   111 幣輪動），但 2,780 萬名目只換到約 1.5 萬淨利，且被單一幣 BRENTOIL −1.02 萬幾乎抵消
   ——規則抄得動，抄了大概率接近零和。賺最多的幾顆（0x9e2c +3.18M、0x456f +2.17M）PnL 都集中在
   單一幣或少數幾天，屬於選幣／擇時，不是可搬移的執行層。**唯一有明確借鑑價值的零件**：
   `0x4cf7…552e` 的不對稱出場（贏單限價分批停利、輸單市價一次砍）與 TWAP 分片建倉。
5. **反面教材密度很高**：`0xa183` 單日 −8.43M（2,155 筆清算）、`0x5cca` 生涯 −1.28M（無一致停損）、
   `0xbd69` 1,439 筆清算靠注資撐、`0xec87` 資金費就吃掉現有權益的 46%、`0xcbc6` 的停損單設在
   清算價**下方**＝無效保護。共通形態：無停損 ＋ 逆向加碼 ＋ 名目遠超權益。

## 腳本

| 腳本 | 做什麼 |
|---|---|
| `fetch_wallet.py <addr>` | 抓 perpDexs／各 dex clearinghouseState／spot／掛單／portfolio／fills（分頁＋tid 去重）／ledger／funding；現貨手續費換算 USD |
| `fetch_twap.py <addr>` | **分頁抓 TWAP 分片成交**（`userFillsByTime` 不含），同樣做手續費換算 |
| `fetch_funding_recent.py <addr>` | 近期 funding（startTime=0 只回前 500 筆） |
| `equity_recon.py` | 五桶權益對帳：spot free／perp AV（全 dex）／staked HYPE／vault，與交易所 portfolio 末點比對 |
| `triage.py` | 每顆 10 行指紋表 → `data/_triage.txt`（批次先看這個） |
| `analyze.py <addr10>` | 五題分析，**參數全自動推導**（eras 四等分、追蹤幣取 \|PnL\| 前四、大波動日自動選視窗）→ `data/<addr10>/analysis.txt` |
| `cohort.py [COIN]` | 跨錢包：誰擠在同一個幣、現有部位何時開的、對照該幣日線 → `data/_cohort.txt` |
| `check_drafts.py` | 報告機械驗收：六章齊全、frontmatter、檔名格式、信心有限、數字可追溯率 |

流程：`run_fetch.sh`（N=4）→ `run_stage2.sh`（TWAP＋analyze）→ `triage.py`／`cohort.py` →
派 builder 寫 `drafts/` → `check_drafts.py` → 搬進 pandora。
已固化成 skill：`~/.claude/skills/hl-wallet-forensics/`。

## 資料極限

- **`userFillsByTime` 不含 TWAP 分片成交**（本批最嚴重的陷阱）。11/22 顆有 TWAP，其中 7 顆原本卡在
  2000 筆上限。補齊後 `0x41c6` 多出 7,762 筆（總量 31%），**進場 taker 從 13% → 51%**，
  「掛單流」的初判整個翻掉；`0x39c3` 有 79% 的活動藏在 TWAP 裡。
  硬閘門：`analyze.py` `[E]` 必須是 `0 real DRIFT`（22/22 已通過）。
- **權益 basis 依帳戶模式而異**：unifiedAccount 的保證金從 spot `hold` 扣（要用 `total − hold`）；
  portfolioMargin 的 `hold` 可為負值＝借貸（`0x4860` 借了 124 萬、對 UBTC 隱含 LTV 85%）；
  **staked HYPE 是獨立的桶**（`0x9e2c` 的 98% 權益、$3.74M 在裡面，漏了就整顆看錯）。
- `userFunding` startTime=0 只回前 500 筆 → 資金費一律是**下界**。
- fills 窗口常被截斷（`0xa183`、`0x9b86`、`0xec87`、`0x41c6`、`0x5cca`、`0x9e2c`）：窗口內已實現與
  交易所 allTime pnl 對不起來是**正常**，報告一律照實標註，不硬湊。
- 現貨賣出的 `closedPnl` 是對歷史平均成本的會計數，不是當日市場損益。
- `stale/settled` 不等於資料漏洞：HIP-3 股票／商品永續會到期結算（`0xec87` 16 個、`0x39c3` 14 個）。
- **未做**：ZEC 已實現 PnL 中「beta vs 執行貢獻」的美元級拆分（需要逐筆對齊價格序列），
  各報告以集中度與逐日方向一致性間接論證，並都標了信心有限。
