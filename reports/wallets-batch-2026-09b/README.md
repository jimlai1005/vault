# 300 顆錢包批次分析（2026-09-25）

使用者一次給 300 個 Hyperliquid 地址（`addrs_raw.txt`），要求照 skill `hl-wallet-forensics` 分析並出報告，
已有報告的地址跳過。去重後 **287 顆新錢包**（`addrs.txt`；13 顆已有報告 → `addrs_skipped.txt`），
**284 份報告**寫進 pandora `~/projects/obsidian/pandora/wallets/`，索引與跟單評分排名在該目錄 `INDEX.md`。
`0x4d21e561`、`0x58e1b0e6`、`0x83ffcfb1` 三顆全歷史零成交，不出報告。

## 結論五條

1. **跟單評分只有 1 顆通過門檻：`0x973d…486d`（44 分）**——固定名目（約 $200k／$400k 檔位）多幣 maker 階梯接刀、
   市價一次出場，多方賺、空方虧，勝率逐季下滑（55%→16%），手續費吃掉毛利 40.6%。它通過是因為槓桿極低（0.01×）、
   最差日 −7.2%，**不是因為賺得多**；跟單可複製性子分 0（延遲後保留率只剩 0.08–0.22）。分數高的（74、73、72…）
   全部卡在 G2（槓桿尖峰 >3×）或 G3（拿掉最好 3 天就轉負）。批次 A 的 `0x1883…1c49`（44）仍是另一顆通過者。
2. **賺錢的錢包，PnL 幾乎都集中在一兩個幣或一兩天。** 反覆出現的形態：ZEC／NEAR／PUMP 單一波段貢獻全部淨利
   （如 `0xbf73` 的 ZEC 貢獻超過全期淨利 100%、`0xf21d` 的 PUMP 單筆佔 66.9%）；或**一次性的 HYPE 創世空投現貨出貨**
   把永續長期虧損蓋掉（`0x9e26`、`0x8ac3`、`0x7031`、`0xd4af`、`0xee15`、`0xc41b` 等，扣掉 @107 後其餘交易全是負的）。
   這些都是選幣／擇時／一次性事件，**不是可外化的執行層規則**。報告第 5 章都標了「信心有限」。
3. **無停損＋逆勢攤平＋清算當停損，是這批最常見的形態。** 284 份 `analysis.txt` 中有 **232 份**出現清算成交；
   大量錢包權益曲線峰值後回撤 −90% 以上、靠再入金續命。好幾顆的停損單設在清算價**之外**（`0x60f5`、`0xddfc`、`0xe4ca`），
   形同虛設。純吃單高頻帳戶常見「手續費 > 毛利」（`0xef94` 手續費是毛利 2.5 倍、`0xef4d` 9.4 倍）。
4. **ZEC 仍是最擁擠的幣**：287 顆中 53 顆持有 ZEC（其次 BTC 50、NEAR 32、HYPE 30），延續批次 A 的 ZEC 群組觀察；
   `cohort.py` 的開倉日顯示大多是追同一波公開行情，沒有協同證據。
5. **注資來源依舊沒有證據力。** 192/284 份 `analysis.txt` 的轉帳對手含提款熱錢包 `0x6b9e7731…`（見 memory
   `hl-funder-address-is-hot-wallet`），不代表同一操作者；`0xf70da978…` 出現在 37 份裡，它本身有成交，值得另外追但本批未做。

## 評分規格變更（v0.6，本批觸發）

- **樣本充足性**：perp 事件 <50 或 |leader 淨損益| < max($500, 1%·E₀) → 標「樣本不足」，分數照算但排在未通過者之後
  （起因：`0x1c3f1168` 只有 43 個 perp 事件、總分 83，獲利其實全在現貨）。本批 4 顆樣本不足、4 顆無法評分。
- **純現貨錢包**也輸出 `copyscore.json`（`unscorable: true`），不再只留 rc=1。
- **修掉一個會吃掉報告內容的 bug**：`apply_scores.py` 原本刪 `## 0` 區塊時一路刪到下一個 `## `，
  把報告的「一句話」也刪了——重跑過的報告都中招（批次 A 22 份、批次 B 23 份）。現在評分區塊有結束標記
  `<!-- /跟單評分 -->`，重跑冪等；45 句一句話已從 builder 的寫檔紀錄逐一重放還原。

## 腳本

| 腳本 | 做什麼 |
|---|---|
| `fetch_wallet.py` / `fetch_twap.py` / `fetch_funding_recent.py` | 同批次 A：fills（分頁＋tid 去重）、TWAP 分片（必抓）、近期 funding |
| `equity_recon.py` / `triage.py` / `analyze.py` / `cohort.py` | 同批次 A；`analyze.py` 修了「無已平倉回合除以零」與 `#NNNN` 已下架幣視為 stale |
| `copyscore.py <addr10>` | 跟單評分模擬（spec v0.6），輸出 `data/<addr10>/copyscore.{json,txt}`；`--backfill-sample` 從既有 JSON 回填樣本欄位 |
| `rank.py` | 四層排序 PASS → FAIL → 樣本不足 → 無法評分 → `data/_ranking.{txt,json}` |
| `apply_scores.py [--dry-run] [addr10…]` | 把評分寫成報告「## 0」區塊與 frontmatter `copy_score*`（冪等） |
| `check_drafts.py` | 草稿機械驗收（六章、檔名、地址、信心有限、數字可追溯率） |
| `strip_markers.py --all` | 剝除 `[A]`～`[E]` 出處標記並寫進 pandora，附三道防護（殘留標記／遺失括號／殘樁） |
| `index_table.py <batch_dir…>` | 重建 pandora INDEX 報告表：依評分排序、自動替新報告加列 |

流程：`run_fetch.sh` → `run_stage2.sh`（TWAP＋analyze）→ `triage.py`／`cohort.py` → `run_copyscore.sh` → `rank.py`
→ 派 builder 寫 `drafts/`（`DISPATCH_BRIEF.md`＋`REPORT_TEMPLATE.md`，派工帳 `dispatched.txt`）→ `check_drafts.py`
→ `apply_scores.py` → `strip_markers.py --all` → `index_table.py`。

## 資料極限

- `userFillsByTime` 只回最近一段成交，高頻錢包窗口常被截斷；窗口內已實現與交易所 allTime pnl 對不起來是正常，
  報告照實標註。少數錢包兩者**方向相反**（`0xbab0`、`0xe611`），原因未查明。
- 資金費一律是**下界**（`userFunding` startTime=0 只回前 500 筆）。
- TWAP 分片已全部併入；全部 284 顆 `analyze.py` `[E]` 皆為 `0 real DRIFT`（stale/settled 為到期或下架幣）。
- **權益 basis 對帳有未解異常**：`0x660f` +61.1%、`0xde1d` +60.6%、`0xcc26` +41.9%、`0x6e8f` +23.9%、`0xa2e3` −31.8%
  等，報告改以交易所自報值為準並標註，成因（unified account 重複計入、vault／質押桶）未逐一查證。
- 跟單評分的延遲分布、滑價、漏單恢復都是**模型假設**（spec v0.5/v0.6 的 ⚙ 參數），不是實盤跟單紀錄；
  價格序列部分用 Binance 1m proxy。
- 報告由 builder 依 `analysis.txt` 撰寫、主線程只做機械驗收（`check_drafts.py`、strip 防護、檔名／H1 核對）與抽查，
  **未逐份人工審閱敘事品質**；本批手動修正過數份檔名尾碼（builder 取錯末 4 碼）與 190 份 H1 的地址格式。
