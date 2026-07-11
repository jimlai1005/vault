# Audit: compound（Bitfinex USD 放貸）— 「11.68% vs 12%」近失判定 + 六假設研究審計

**Date:** 2026-07-12
**Auditor:** fresh-context adversarial audit agent（無委派，全程本人執行）
**Scope:** `compound/reports/*.md`、`compound/docs/*.md`、`compound/src/compound/{rates.py,backtest/}`、
`compound/scripts/run_backtest.py`、`compound/tests/test_backtest_sim.py`
**Verdict under audit:** compound-lending（12% 淨年化目標：基準情境 11.68%，判定「未達」；
六份研究報告：rate_cycles / rate_drivers / market_regimes / strategy_evidence / strategy_phases / leverage_phases）
**紅線遵守：** 全程唯讀；未讀取/印出 `.env`；僅執行 `scripts/run_backtest.py`（離線讀 CSV，無網路、無下單，
`docs/backtest-design.md` 確認其為純模擬）與 `pytest`（autouse fixture 封鎖 socket）；未跑 `run_engine.py`、`status.py`。

---

## 結論先行

獨立重跑 `scripts/run_backtest.py`（24 組參數網格，離線 CSV），輸出與 `reports/backtest_verdict.md`
逐位元組一致（11.68% / 10.76% / 12.98%、全部年度 APR、OOS 排行榜）——**原始數字無捏造、可重現**。
六份研究報告的自我審查密度異常高（每份都有獨立的「反面證據與資料極限」節，n=2-3 的警語、
data snooping 承認、regime 混淆的明確拆解），逐一核對後**未發現能推翻「條件性可行、基準情境未達
12%」判定的可重現 bug**。找到的問題集中在方法論邊際與出處追溯，且方向上多半使現有報告**偏樂觀**而非
偏悲觀——也就是說，若這些點有影響，它們會讓「未達 12%」的結論更站得住，不是相反。

---

## Findings

### F1 — 12% 目標的出處在 repo 內不可追溯（品味／目標值本身，僅列不判對錯）

- **位置**：`compound/docs/strategy-research.md:3`（「目的：為放貸策略引擎（目標淨年化 ≥12%）提供有證據的策略基礎」）、
  `compound/README.md:4-6`、`compound/docs/backtest-design.md:46`（"Target check: strategy net APR ≥ 12%"）。
  三處都把 12% 當作既定輸入，沒有一處交代這個數字從何而來。
- **查證**：獨立 repo `~/projects/compound` 的 git 歷史只有 23 個 commit，最早一筆是
  `5cd8825 Project skeleton + architecture decision doc`——沒有更早的歷史記錄原始使用者需求文字；
  chat prompt 本身不進 git，故無法在任何已提交檔案中找到「12%」的原始授權來源。
- **性質**：這是 gate/目標值本身，依審計守則列出即可，不需要（也無法）證明它對錯。但既然子專案的
  headline 判定（「未達 12%」）完全錨定在這個數字上，讀者應該知道：這個門檻的權威性目前無法在 repo
  內部驗證，可能来自使用者原始 prompt（未留存）也可能是自主開發階段的自我設定。
- **direction**：N/A（品味類）。**verdict_changing**：no。

### F2 — Winner 選擇法仍有殘留的多重比較／winner's-curse 偏誤（假設，低重要性）

- **位置**：`compound/scripts/run_backtest.py:54-59`。選法：先取 train APR 前 25%（24 組中 6 組），
  再從這 6 組裡選 OOS APR 最高者當 winner。程式碼註解說明這是為了修一個更嚴重的舊 bug
  （直接選 train 冠軍會獎勵 regime-fit，冠軍永遠篩不掉）——這個修正本身是對的方向
  （對應獨立 repo 的 commit `5d97001 Fix winner selection (best OOS among top-quartile train) + align all report numbers`）。
- **問題**：即使限縮在 top-quartile，"從候選中挑 OOS 分數最高者" 本質上仍是用 OOS 資訊做選擇——
  這讓被報告的 winner 之 OOS（9.72%）與全歷史數字（11.68%）相對於「完全不看 OOS、只憑 train 選一組」
  的做法，帶有輕微的樂觀選擇偏誤（winner's curse）。
- **量化重跑**：我重新執行了完整網格（見下方重現指令），top-quartile 6 組的 OOS 分佈落在
  9.31%/9.31%/9.72%/9.72%/9.45%/9.45%——**波動範圍僅 0.4pp**，同時全部 24 組的 OOS 範圍是
  8.97%–9.84%（0.87pp）。用這個離散度估計，選擇偏誤的量級大約在 0.1–0.2pp，遠小於前述
  12%-11.68%=0.32pp 的 gap，**不足以推翻「未達 12%」的結論**。
- **direction**：過寬（如果這個偏誤有影響，它會讓現有報告的數字比誠實的無偏估計更高，也就是
  對策略更有利，不是對策略不利）——這與審計任務原先假設的「是否被冤殺」方向相反：
  若有誤差，方向上是讓「未達」的結論看起來比實際更接近達標，而非更遠。
- **verdict_changing**：no。
- **重現路徑**：
  ```
  cd /Users/jim/projects/vault/compound
  .venv/bin/python scripts/run_backtest.py --out /tmp/repro.md
  ```
  本次審計實跑輸出與 `reports/backtest_verdict.md` 除時間戳外逐字一致（已核對全部 24 組
  train/OOS 數字、三檔 fill regime 的 net APR/utilization/worst-90d、逐年 APR）。

### F3 — 「未達 12%」的敘述是點估計，模型自身的情境帶（10.76%–12.98%）整段橫跨 12%（觀察，非 bug）

- **位置**：`compound/reports/backtest_verdict.md:13,69`；生成邏輯 `compound/scripts/run_backtest.py:137,140-141`
  （`tgt_base = base.net_apr >= 0.12`，只用 base 情境判定）。
- **檢查結果**：base(11.68%) 與 12% 只差 0.32pp，但同一張表的 pessimistic(10.76%)–optimistic(12.98%)
  情境帶寬達 2.22pp，完整涵蓋 12%。單看這一點容易誤以為判定「灌水」了確定性。
- **但這不是 bug**：`compound/docs/backtest-design.md:29`（"Params are picked on the **base** regime...
  If a strategy only beats 12% under optimistic fills, it does NOT pass."）是**在跑網格之前**就寫好的
  預註冊規則，目的正是防止事後挑樂觀情境灌水判定——用 base 判「未達」是誠實、保守、依規則行事，
  不是隨意選了一個對結論有利的門檻。
- **direction**：中性（這是呈現方式可以更清楚標註「點估計 vs 情境帶」的建議，不是計算錯誤）。
  **verdict_changing**：no。

### 已檢查、未發現問題的項目（逐條列出，避免被誤讀為「沒查」）

1. **年化慣例一致性**：`rates.py:8-13` 全 repo唯一換算點，`daily_to_apr = daily × 365`（simple，非複利，
   與 Bitfinex UI 報價慣例一致），`backtest-design.md:53` 明文同一慣例；`sim.py` 的 `net_apr` property
   （`net_interest / avg_capital / years`）用解析法驗證：在固定利率、連續複利近似下精確收斂回
   `daily_rate × 365`，與慣例自洽——**未發現 365 vs 360、複利 vs 單利的混用**。
2. **Look-ahead bias（30 天期市場廣播到小時級）**：`src/compound/backtest/data.py:62-67` 明確用「前一個
   UTC 日」的 p30 K 線廣播到當天每小時，程式碼註解直接寫明這是為了修一個先前抓到的 review finding
   （對應獨立 repo commit `6210faa fix backtest p30 look-ahead`）——目前版本因此是嚴格因果的（有一天
   staleness 的代價，方向保守）。已核對 `strategies.py` 的視窗切片與此一致，**未發現殘留 look-ahead**。
3. **分母 bug 迴歸測試**：`tests/test_backtest_sim.py:136-138` 專門守著「用初始本金而非平均權益當分母」
   這個已修過的 bug；`compound/.venv/bin/pytest` 全數 60 個測試通過（離線，`conftest.py` autouse fixture
   封鎖 socket）。
4. **利率環境 regime 檢查（審計任務假設 (c)：量測窗恰逢低利率段，11.68% 是地板不是常態）**：
   實際資料方向與假設相反。`reports/research_rate_cycles.md:103-106` 的跨週期整週期中位數
   2016 週期 12.5% → 2020 週期 7.1% → 2024 週期至今 5.0%，顯示**現在正處於史上最低的利率
   regime**；全歷史 11.68% 之所以還能拉到接近 12%，是被 2021-2022 那段較高利率（13.6%/11.2%，
   `reports/backtest_verdict.md:18`）向上拉抬——若這段結構性衰減（stablecoin 供給、carry
   工業化、槓桿遷移至 perp，`reports/research_rate_drivers.md` 全文）不可逆，**11.68% 若有偏誤，
   偏誤方向是偏樂觀（相對於未來），不是偏悲觀**。這一點報告本身已在
   `reports/cycle_allocation_verdict.md:30` 與 `research_rate_cycles.md` 第 6 節誠實揭露，不是新發現，
   但值得重申：審計任務原先假設的方向（窗口太苛刻、冤殺了策略）在資料上不成立，證據指向相反方向。
5. **cycle_allocation 對放貸配置的關鍵數字有無被推翻**：唯一標記的矛盾（外部「top-50% 放貸人
   30 日均值 12-14%」vs 自己回測「8.8%」）已在 `reports/cycle_allocation_verdict.md:158-161`
   當日就自我揭露為「未決矛盾」，來源可疑（`research_rate_drivers.md` 子問題 6 表格把
   「自算＋earn-usd.com」混合標註，population 定義不明——top-50% 放貸人可能是不同統計口徑，
   不是同一策略的直接可比基準）。這是既有的已知未決項，不是被「後續資料」新推翻，
   compound 匯入後（2026-07-06 至今）沒有新資料或新 commit 更新這個矛盾。
6. **六份研究報告逐一核對** data window／統計方法／成本假設：
   `research_rate_cycles.md`（十年利率×週期回測）、`research_rate_drivers.md`（六個子問題：機制／
   供給／需求／套利／前瞻／2024-25 收息比較）、`research_market_regimes.md`（形態分類）、
   `research_strategy_phases.md`、`research_leverage_phases.md`（槓桿 Kelly／爆倉模擬）——
   每份都已有 n=2-3 樣本警語、閾值敏感性測試、data snooping 自陳（H+18 月切點後見之明）、
   funding 情境常數非實測資料的揭露。**未發現這些報告中有未揭露的統計方法錯誤或成本假設遺漏**。

---

## 附帶觀察（非 finding，僅供決策參考）

`reports/cycle_allocation_verdict.md` 的放大路線圖（第 2 項：「持續：自營放貸系統按閘門放大…
每級用實盤成交率校準模型」）依賴 live engine 持續運轉以累積 realized-vs-model 對帳資料。但根據
`CLAUDE.md` 紅線與 `docs/superpowers/plans/2026-07-06-compound-integration.md`，引擎自匯入（07-06）
起已停止；兩筆探測用 2 天期貸款已於約 07-07 到期回籠，此後沒有新的實盤成交可用於校準。這代表
「條件性可行、待實盤驗證」的判定至今（07-12）沒有新證據可以推進或推翻——這是進度狀態，不是
研究方法問題，但值得提醒使用者：若要真正解決「12% 能否達到」的不確定性，需要重啟引擎累積資料，
而重啟屬於紅線動作，需使用者明確同意。

---

## 總評

三個 finding 全部 **verdict_changing: no**。最強的兩個可驗證論點（F1 目標出處不可追溯、F2 winner
選擇法的殘留樂觀偏誤）都不足以撼動「基準情境未達 12%、且處於史上最低利率 regime」的核心判定；
F2 若有影響，方向是讓現有數字比無偏估計更好看，等於現有「未達」判定其實還算保守。整體而言，
compound 團隊自己的研究紀律（預註冊 base-fill 判準、look-ahead 修正、分母 bug 迴歸測試、六份報告
一致的反面證據節）在這次對抗審計中通過了驗證。
