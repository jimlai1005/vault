# 三階段倉位框架 Phase 1-2 Implementation Plan（sub-project K）

> **For agentic workers:** 主對話派工、subagent 執行、fresh verifier 驗收；執行型派工
> prompt 末尾必加「你必須親自執行全部步驟，不得使用 Agent 工具再委派」。
> 機械任務 haiku、實作 sonnet、判定二審 opus。Spec（法律）：
> `docs/superpowers/specs/2026-07-13-position-framework-design.md`。

**Goal:** 驗收 vol-target 煞車層（Stage 1）→ 三個條件變數逐一掙門票（Stage 2）→
組合模型在乾淨 OOS 窗（2020-01→2024-06）判定 conditional momentum 是否 GO。

**紀律紅線：** 乾淨窗每條線只跑一次、跑前 gate 已鎖死；ablation 單點無網格；
失敗不回收；momentum 原案不改判。

---

## Task 0: 資料底座（haiku）

**Files:** Create `scripts/k_data_layer.py`；`data/k_framework/`（gitignore 已涵蓋模式照加）

- [ ] Binance 日線拉取：BTCUSDT/ETHUSDT/SOLUSDT 自 2020-01-01（或上市日）→ 2026-07-02、
  HYPEUSDT 自上市日（沿用 `scripts/scalp_lib.py` 的 binance_klines，interval "1d"）；
  存 `data/k_framework/<COIN>_1d.csv.gz`。時間戳硬編。
- [ ] HL fundingHistory 拉取（可得期，缺洞申報天數）。
- [ ] proxy 佐證：抽 2026-06 的 30 天，Binance 日線 vs HL 日線收盤相關性與範圍比，落檔。
- [ ] 事件日曆：`data/k_framework/macro_calendar.csv`（2020-01→2026-07 的 FOMC 決議日
  ＋CPI 發布日，公開排程）；抽 10 個日期人工可驗（附來源 URL 於檔頭註解）。
- [ ] 驗收：fresh agent read-back（筆數、無 gap、日曆抽驗）。

## Task 1: 引擎移植與 Stage 1 風險交付驗收（sonnet）

**Files:** Create `scripts/research_k_stage1.py`（基於 `scripts/research_momentum_voltarget.py`
改造：資料源換 Task 0 底座、宇宙按上市日動態、其餘引擎邏輯零改動）

- [ ] 開發窗（2024-07-02→2026-07-02）重現昨日主配置數字（Sharpe 0.182±1%）——
  證明移植無損，作為機械基準。
- [ ] 兩窗 Stage 1 gate 表：實現年化波動 ∈[15%,25%]、MDD ≤20%、換手成本年化 ≤3%。
  注意：**乾淨窗在此只准輸出風險指標三項，報酬/Sharpe 欄位遮蔽不落檔**（防止
  開發期偷看乾淨窗報酬——這是 spec §2「只跑一次」的配套；遮蔽由腳本硬編）。
- [ ] fresh verifier：無前視審＋風險指標從 csv 重算。
- [ ] Gate S1 判定入檔。不過 → 停，回報 owner。

## Task 2: 先行搜尋——confidence-weighted sizing 舊作（haiku, Explore）

- [ ] 搜 repo（含 compound/、docs/）與 pandora：confidence-weighted / signal-strength
  sizing 的既有實作或研究結論；找到 → 摘要教訓給 A2a 實作參考；找不到 → 回報「無」。

## Task 3: Stage 2 ablation 實作與開發窗機械驗證（sonnet ×3 可平行）

**Files:** Create `scripts/research_k_ablation_a.py`（A2a 訊號強度縮放）、`_b.py`（A2b
regime 閘門）、`_c.py`（A2c 事件降倉）——共用 stage1 引擎，各自只加一個條件變數

- [ ] 每個 ablation：實作照 spec §1 單點定義（無參數可調）；在**開發窗**跑通、
  機械驗證（交易數合理、條件觸發率印出：A2b 的 bull/bear 天數比、A2c 的事件日覆蓋率）。
- [ ] fresh verifier：逐一確認條件變數實作與 spec 定義一致、無前視（regime 用 t-1 收盤、
  日曆日期無錯位）。
- [ ] **此階段全程不接觸乾淨窗。**

## Task 4: 乾淨窗判定（主對話直接執行，每線一次）

- [ ] 主對話依序下指令：baseline → A2a → A2b → A2c 各在乾淨窗跑**一次**，
  stdout＋csv 即刻落檔；每跑完一線立即 commit（防重跑）。
- [ ] Gate S2 逐線判定：ΔSharpe>0（DSR 校正 N=4）且 MDD 不惡化 >2pp。
- [ ] 存活 ablation 組合成 combined model → 乾淨窗跑一次 → Gate S2-final
  （原三關＋DSR≥0.95＋端點±10d 敏感度＋split-half）。
- [ ] fresh verifier 從 csv 重算全部 gate 數字。

## Task 5: Verdict＋二審（主對話＋opus）

**Files:** Create `reports/conditional-momentum-verdict.md`

- [ ] 主對話綜合：S1/S2/S2-final 全表、試驗數申報、倖存者偏差與 proxy 標注、
  「原案不改判」聲明；判定=conditional GO / NO-GO。
- [ ] opus 二審（只給數字表與 spec gate 定義）；分歧呈 owner。
- [ ] conditional GO → 下一步=引擎實作＋paper ≥4 週（另立 plan）；NO-GO → 收檔，
  Stage 1 煞車層與資料底座作為框架資產保留。

## Task 6: Stage 3 設計文件（主對話，~40 行）

**Files:** Create `docs/superpowers/specs/2026-07-13-stage3-portfolio-risk-design.md`

- [ ] 週頻 risk parity＋fractional Kelly 的介面定義（輸入：各 sleeve 日報酬序列；
  輸出：週初目標權重 advisory 報告）；sleeve 候選現況表；紅線聲明（動實盤 sizing
  逐次 owner 核准）。不實作。

## 執行成本與時程

Task 0-3 約半天（可高度平行）；Task 4-5 半天（乾淨窗運行本身分鐘級，紀律成本在流程）；
合計 ~1 天。API 全公開唯讀。
