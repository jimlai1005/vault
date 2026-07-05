# compound — Bitfinex USD 自動放貸引擎

把 Bitfinex 融資錢包裡的 USD 自動放貸出去（margin funding, `fUSD`），以階梯策略
（短天期保持出借＋高利率時鎖長天期）最大化長期淨 APR。目標樓地板 12% 淨年化
（扣除 Bitfinex 約 15% 利息抽成後）——注意這是**有條件的模型估計，不是保證**，
詳見下方「風險與誠實聲明」。

**目前狀態（2026-07-05）**：live-test 模式。引擎只管理 `capital_budget = 328 USD`，
且受程式碼強制的測試上限約束（每筆 ≤300 USD、期限 ≤2 天、同時 ≤2 筆掛單）。
同一帳戶內另有約 4,000 USD 由舊系統／手動管理——本引擎**絕不碰**不屬於它的掛單與貸出。

## 快速開始

### 安裝

需 Python 3.9+：

```bash
cd compound
python3 -m venv .venv
.venv/bin/pip install -e .        # 相依只有 requests
.venv/bin/pip install pytest      # 跑測試用
```

### 設定

**憑證**只從專案根目錄的 `.env` 讀（權限建議 600，已在 .gitignore）：

```
BFX_API_KEY=你的key
BFX_API_SECRET=你的secret
```

**策略／引擎參數**只從 JSON overrides 或程式內預設值來（`src/compound/config.py`），
secrets 永遠不會出現在 JSON 裡。用 `--params` 傳入，例如：

```bash
echo '{"capital_budget": 500.0}' > params.json
.venv/bin/python scripts/run_engine.py --dry-run --once --params params.json
```

全部設定欄位（即 `Config` dataclass 的欄位與預設值）：

| 欄位 | 預設 | 說明 |
|---|---|---|
| `api_key` / `api_secret` | `""` | 只從 `.env` 讀（`BFX_API_KEY` / `BFX_API_SECRET`），JSON 給了也會被丟棄 |
| `symbol` | `"fUSD"` | 融資市場代碼 |
| `fee` | `0.15` | Bitfinex 對賺得利息的抽成 |
| `min_offer` | `150.0` | 交易所最小掛單金額（USD） |
| `max_period` | `120` | 使用者授權的最長鎖定天數 |
| `tick_seconds` | `300` | 引擎 tick 週期（秒） |
| `max_mutations_per_tick` | `10` | 每 tick 最多下/撤單數 |
| `journal_dir` | `"journal"` | JSONL 日誌與所有權登記檔目錄 |
| `capital_budget` | `328.0` | 本引擎可管理的資金上限（自己的掛單＋自己的貸出合計） |
| `live_test_mode` | `true` | live-test 護欄總開關 |
| `live_test_max_offer` | `300.0` | live-test：單筆上限（USD） |
| `live_test_max_period` | `2` | live-test：期限上限（天） |
| `live_test_max_concurrent` | `2` | live-test：同時掛單數上限 |

未知的 JSON key 會直接報錯（防打錯字靜默失效）。

### 指令一覽

| 要做什麼 | 指令 |
|---|---|
| 跑測試（全離線，網路被 fixture 封鎖） | `.venv/bin/pytest` |
| 冒煙測試（打真實公開 API，唯讀、免憑證） | `.venv/bin/python scripts/smoke_public.py`（可加 `--symbol fUSD`） |
| Dry-run 單次 tick（讀真帳戶、計畫但不下單） | `.venv/bin/python scripts/run_engine.py --dry-run --once` |
| Dry-run 常駐 | `.venv/bin/python scripts/run_engine.py --dry-run --daemon` |
| 實盤單次 tick（**會真的下單**） | `.venv/bin/python scripts/run_engine.py --live --once` |
| 實盤常駐 | `.venv/bin/python scripts/run_engine.py --live --daemon` |
| 回測（離線，讀 data/ 的 CSV，輸出 verdict 報告） | `.venv/bin/python scripts/run_backtest.py`（可加 `--out 路徑`） |
| 抓歷史資料（公開端點；請求間隔 2.5s，全量可能要 10–30 分鐘） | `.venv/bin/python scripts/fetch_history.py`（可加 `--only candles\|snapshots\|stats`） |
| 看目前狀態 | `.venv/bin/python scripts/status.py`（帳戶＋掛單＋市場一頁式）；更多細節看當日日誌：`tail -1 journal/$(date -u +%F).jsonl \| python3 -m json.tool` |

`run_engine.py` 的 mode（`--dry-run`/`--live`）與 cadence（`--once`/`--daemon`）
都是必選、互斥的。時間戳一律 UTC（journal 檔名也是 UTC 日期）。

## 架構速覽

深入設計見 `docs/architecture.md`（系統）與 `docs/backtest-design.md`（回測誠實規則）。

```
src/compound/
  config.py        設定：frozen dataclass，.env 憑證 + JSON 參數 overrides
  rates.py         日利率 <-> APR、fee 淨值換算——全 repo 唯一的換算點
  bfx/
    transport.py   HTTP + 簽章，唯一碰網路的模組
    boundary.py    resilience boundary：每個呼叫宣告 read/write、冪等、可否重試
    models.py      v2 陣列 payload 的型別化視圖（Ticker/Book/Offer/Credit/Wallet）
    public.py      公開端點        private.py  認證端點
  strategy/
    base.py        MarketState / AccountState / TargetOffer 協定
    ladder.py      生產策略 v1（純函式，參數來自回測，不是拍腦袋）
  engine/
    state.py       抓帳戶＋市場狀態；每 tick 做 equity 恆等式檢查
    reconcile.py   目標掛單 vs 實際掛單 -> 最小 cancel/place 計畫；護欄在這強制執行
    loop.py        tick 迴圈；dry-run 與 live 模式
    journal.py     JSONL 日誌 + 掛單所有權登記（owned.json，crash-safe）
  backtest/        離線回測：data.py 載入 CSV、sim.py 成交模型、strategies.py 候選策略
scripts/           run_engine / run_backtest / smoke_public / fetch_history
tests/             pytest；autouse fixture 封鎖所有真實網路
```

## 安全設計摘要

- **Live-test caps 在程式碼裡強制**（`reconcile.py`），不靠操作紀律：
  `live_test_mode=true` 時每筆 ≤`live_test_max_offer`、期限 ≤`live_test_max_period`、
  同時 ≤`live_test_max_concurrent` 筆。
- **Capital budget**：引擎出借總額（自己的掛單＋歸因到自己的貸出）永不超過
  `capital_budget`；預算之外的目標單被 journal 記為 `plan_skipped`。
- **所有權隔離**：引擎在 `journal/owned.json` 登記自己下過的每個 offer id，
  只撤自己的單；別人的掛單與貸出只回報、絕不動。`cancel_all_offers` 存在於
  `private.py` 但引擎**禁止使用**（僅供手動維運）。
- **Resilience boundary**（`bfx/boundary.py`）：每個外呼宣告分類——transient 錯誤
  只在讀取或冪等寫入（撤單）時退避重試；下單（非冪等）失敗**絕不盲重試**，
  下一 tick 從交易所真相重新推導目標，自癒式對帳。Semantic 錯誤（參數被拒、
  餘額不足）不重試、大聲報錯。
- **Equity 恆等式**：每 tick 驗證 `錢包餘額 = 可用 + 掛單中 + 貸出中`（同一次快照、
  每桶恰好算一次），差距 >1 USD 記 `identity_mismatch` 事件並 ERROR 告警。

## 風險與誠實聲明

回測結論全文見 `reports/backtest_verdict.md`。摘要（勝出參數 `T-C/S-02-04-08/l7`）：

- 全歷史（2021→now）base 成交模型：淨 APR **11.68%**（悲觀 10.76%／樂觀 12.98%）。
- 但 **out-of-sample（2025→now）只有約 9.7%**，近期低利率 regime（2024→now）
  base 平均約 **10.0%**——**12% 樓地板在低利率環境下沒有保證**，需要利率尖峰年
  或未建模的 taker/FRR 上行空間才達得到。
- 模型的重要假設（原文照列，不隱藏）：成交模型是 bar-based、真實排隊位置不可知；
  >7 天貸出的提前還款率是假設值（無公開資料集）；模擬用連續複利而 Bitfinex 實際
  按日計息；30/120 天市場用日線資料（比 2 天市場的小時線粗）；FRR 掛鉤單與隱藏單
  未建模；taker 機會（直接吃長天期高利 bid）未建模——這是尚未計入的上行，待實盤量測。
- 結論的定位：**這是信心有限的模型估計，不是收益承諾。**

## 擴大資金的路徑（328 → 漸進 → 25 萬）

擴大規模是**設定變更，不是程式碼變更**，且每一步都應由人審核：

1. **先觀察**：live-test 至少跑到有成交，比對 journal 裡的實際成交利率／頻率
   vs 回測模型假設（realized vs model）。模型明顯高估就先修模型，不加錢。
2. **鬆開 live-test 護欄**：確認行為正常後，`--params` 設 `live_test_mode: false`
  （解除 300 USD/2 天/2 筆的測試上限，回到 `min_offer`/`max_period`/預算約束）。
3. **漸進調高 `capital_budget`**：328 → 1k → 5k → …，每一級觀察一段時間再上一級。
   舊系統管理的資金要先從舊系統撤出、確認回到可用餘額，引擎才看得到。
4. **多租戶階段（未來）**：策略層已是純函式（`decide(market, account, cfg)` 無 IO），
   為「一個策略行程服務多組客戶 API key」的架構預留了空間；屆時再展開設計。

部署到 AWS Lightsail 的完整步驟見 `docs/deploy-lightsail.md`。
