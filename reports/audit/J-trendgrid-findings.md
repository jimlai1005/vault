# Audit: trend-filtered grid NO-GO（sub-project E，2026-07-03 判定）對抗審計

**Date:** 2026-07-12
**Auditor:** fresh-context adversarial audit agent（無委派，全程本人執行；無 Agent 工具呼叫）
**Scope:** `reports/trend-filtered-grid-verdict.md`、`scripts/research_trend_filtered_grid.py`、
其依賴的 `src/hlvault/gridbot/{strategy.py,volatility.py}`、對照組
`reports/gridbot2-coin-selection.md` 與 `scripts/select_gridbot2_coins.py`（同一組 live-engine
預設參數的來源）。
**Verdict under audit:** trend-filtered grid — NO-GO（1h/208d 與 4h/730d 兩個 bar config，
過濾後聚合 PnL 皆為負；不通過所有四道預註冊 gate）。
**紅線遵守：** 全程唯讀，未修改任何既有檔案；未讀取/印出任何 `.env*`；重現腳本全部使用
`data/cache/candles_multi/` 下既有的、與原始判定同時間點（2026-07-03 01:17）寫入的快取
parquet，**沒有任何新的網路請求**（未觸發 Hyperliquid candleSnapshot API），故不受其保留期限制
影響；重現腳本落在 `/private/tmp/claude-501/.../scratchpad/`，未寫回 repo。

---

## 結論先行

獨立重跑 `scripts/research_trend_filtered_grid.py`（原始快取資料，未變動任何參數），輸出與
`reports/trend-filtered-grid-verdict.md` 逐位元組一致——**原始數字無捏造、完全可重現**。
六維度通掃 + 五個重點問題逐一驗證後：找到 **4 個可重現的方法論/計算問題**，但用替代假設
重新實跑後，**沒有一個能翻轉「NO-GO」這個聚合結論**（PnL-positive 與 60%-non-negative 兩道
gate 在所有替代假設下都仍然決定性地失敗）。其中最值得留意的不是聚合數字對不對，而是
**verdict 文字的敘事（「filter 全面降低虧損」）在個別幣種層級站不住腳**——TAO（1h）與
TON（4h）兩個幣種是過濾器主動把獲利/接近打平的結果變差的具體反例，這件事在目前的 verdict
報告裡完全看不到（因為報告只放聚合兩列，個別幣種的 14 列輸出只印在 console，沒有落檔）。

---

## Findings

### F1 — 個別幣種數據顯示濾波器對特定幣種是「幫倒忙」，verdict 敘事只講聚合面（結構性完整度問題，非聚合判定 bug）

- **位置**：`reports/trend-filtered-grid-verdict.md:21`（"The filter cuts the bleed
  substantially but never flips the candidates positive"）；重現的逐幣輸出（未落檔於任何
  report，只在 script stdout）。
- **問題**：聚合層面「filter 降低虧損」是真的，但這是平均效果，不是每個幣都成立。重新執行
  完整 17 幣 × 4 濾波長度矩陣後，發現至少兩個明確反例：
  - **TAO（1h/208d）**：unfiltered **+$10.5**（14 個候選幣裡少數 unfiltered 為正的案例之一）
    → f90 **-$50.7** → f120 **-$87.4** → f150 **-$214.9**。濾波長度越長，虧損單調惡化，
    在最嚴格濾波下把一個原本獲利的幣變成單幣虧損 $215（budget 只有 $333.33，等於單幣
    -64.5%）。
  - **TON（4h/730d）**：unfiltered **-$13.0**（14 幣中最接近打平的案例）→ f90 **-$121.9**
    → f120 **-$89.5** → f150 **-$136.2**，全部濾波變體都比 unfiltered 差 9-10 倍。
- **重現指令**（用 repo 既有快取，零網路請求）：
  ```
  cd /Users/jim/projects/vault
  .venv/bin/python scripts/research_trend_filtered_grid.py
  ```
  直接看 console 表格的 TAO（1h 區塊）與 TON（4h 區塊）兩列即可核對上述數字（與本次審計
  的獨立重跑輸出逐字一致）。
- **判斷**：這不影響聚合判定——聚合面 unfiltered 本身已經是負的（-$1645 / -$3149），filter
  在聚合層面確實把虧損收斂（-$514~-$290 / -$1249~-$1043），所以 verdict 把失敗歸因給
  「grid 在這些 alt 上沒有 edge」而非「filter 搞壞了一個原本可行的東西」，這個**聚合層級的
  歸因方向是對的**（審計任務點 3 擔心的「unfiltered 正、filtered 負卻怪 grid」情境，在聚合數字
  上並不成立）。但 verdict 報告完全沒有揭露「filter 對部分幣種是負貢獻」這個事實，若未來有人
  想把這個濾波器套用在 TAO 或 TON 這類幣上（例如當作風險疊加層），現有報告不會給出任何警訊。
- **direction**：中性偏過寬（verdict 的聚合結論沒錯，但敘事完整度不足，隱藏了濾波器本身的
  幣種級別副作用）。
- **verdict_changing**：no（聚合判定不受影響，兩個反例的幅度不足以扭轉 14 幣聚合的負值）。

### F2 — 聚合 MDD 的分母基準與聚合 PnL 的資金基礎不一致（可證明的計算基準錯配）

- **位置**：`scripts/research_trend_filtered_grid.py:37`（`BUDGET = 1000.0 / 3`，每一幣獨立
  配置 $333.33）、`:151-157`（`eq = pd.concat(agg.values(), ...).sum(axis=1)` 把 **14 個候選幣**
  各自的 $333.33 預算 PnL 曲線加總，再用 `abs(mdd)/1000.0` 除以固定的 $1000）。
- **問題**：若 14 個候選幣「同時」各自跑一份 $333.33 的網格（這正是 `agg` 加總的隱含前提），
  實際部署所需總資金是 14 × $333.33 ≈ **$4,666.67**，不是 $1,000。$1,000 這個分母是從姊妹
  專案 `gridbot2-coin-selection.md`（該案只選 3 個幣、每幣 $333.33、總計 $1,000）直接沿用過來
  的常數，套用到這裡「同時跑 14 個幣」的聚合情境時分子分母不同源——違反全域工程原則第 1 條
  （比較的兩個值必須同源同基準）。這使得報告裡 65.2% / 265.7% 的 MDD 數字被放大約 4.67 倍。
- **量化重跑**（沿用原始快取與原始程式邏輯，只換算分母）：
  - 1h/208d：原始 MDD $-651.6 / $1000 = 65.2%（報告數字）；若除以真實聚合曝險 $4,666.67，
    則為 **13.96%**——**低於 20% 的 gate 門檻，這一條腿其實會 PASS**。
  - 4h/730d：原始 MDD $-2657.4 / $1000 = 265.7%；除以 $4,666.67 為 **56.9%**——仍然 FAIL。
- **verdict 影響評估**：即使 1h 的 MDD 這條腿在正確基準下轉為 PASS，1h 的其餘兩條腿
  （聚合 PnL 需為正、≥60% 幣非負）依然決定性失敗（f120 聚合 PnL -$425.2，non-negative 僅
  7-50%，從未達到 60%）。四道 gate 是 AND 關係，任一失敗即整體 NO-GO，所以這個基準錯配
  **不影響最終 verdict**，但會誤導讀者以為風險比實際誇張約 4.7 倍（"265.7% of $1000" 這種
  超過 100% 的數字本身就該是一個警訊，指向分母選錯，而不是「風險真的超過本金 2.6 倍」）。
- **direction**：過寬（誇大了風險指標，若有人只看 MDD 欄位可能誤判濾波後的下行風險比實際
  嚴重得多；不影響聚合 PnL 判定的方向）。
- **verdict_changing**：no（PnL 與 non-negative 兩腿獨立決定 NO-GO，與 MDD 分母選擇無關）。

### F3 — 波動率回看窗長度未按 bar 週期換算，4h 分支實際用了 56 天而非設計意圖的 14 天（可重現的實作 bug；修正後結果更負，非更正）

- **位置**：`scripts/research_trend_filtered_grid.py:78`（
  `atr_pct(candles, lookback=min(len(candles), 24 * 14))`）——`24 * 14` 這個運算式的命名
  意圖明顯是「24 小時 × 14 天 = 14 天的小時數」，只有在 `candles` 是 **1h** bar 時才等於 14
  天；當同一行程式碼被 4h 分支呼叫時（`run_config("4h", 730, cooldown=6)`），336 根 candle
  變成 336 × 4 小時 = **56 天**，是原意的 4 倍長。對照姊妹腳本 `select_gridbot2_coins.py:84`
  （只跑 1h，同樣寫 `lookback=24*14`）可以確認這個寫法是從純 1h 情境直接複製過來、沒有為新增
  的 4h 分支調整比例——script 其實在別處（cooldown：1h 用 24、4h 用 6）有正確處理過同樣的
  換算問題，代表開發者知道要按 bar 週期換算，唯獨這一處漏掉。
- **量化重跑**（用真正的「14 天」等效回看窗：4h bar 下應為 84 根而非 336 根，其餘完全不變，
  同一份快取資料）：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/audit_fixed_lookback.py
  ```
  結果（4h/730d，f120）：聚合 PnL 從報告的 **-$1086.5** 變成 **-$1518.4**（更負）；unfiltered
  聚合從 -$3148.5 變成 -$4577.2；non-negative 比例從 14% 降到 7%。**修正這個 bug 讓結果更差，
  不是更好**——原本（as-coded，56 天窗）算出的步長普遍比正確的 14 天窗更寬（例如 TAO
  1.795%→1.340%、HYPE 1.646%→1.543%、XRP 0.985%→0.830%，BTC 幾乎不變 0.721%→0.720%），
  步長修窄後成交更頻繁、手續費侵蝕更多，PnL 進一步惡化。
- **direction**：過寬（原始報告的數字其實比「正確換算後」更有利於策略，即該 bug 是在幫
  策略說話，不是在冤枉它）。
- **verdict_changing**：no（本來就是 NO-GO，修正後 NO-GO 更決定性）。

### F4 — 波動率回看窗本身用了「視窗尾端」（最接近今天）而非逐時點正確（point-in-time）校準，屬前視偏誤；經替代校準測試後對聚合結論無實質影響

- **位置**：`src/hlvault/gridbot/volatility.py:8-17`（`atr_pct` 對傳入的整段 `candles` 取
  `tail(lookback)`）+ `scripts/research_trend_filtered_grid.py:78`（`candles` 傳入的是
  **整個 208 天或 730 天窗口的全部資料**，`stp` 只算一次，貫穿整個回測）。這代表 grid 的步長
  參數，是用「抓資料當下（即 2026-07-03，約等於窗口最尾端）」前 14 天的波動率去校準，然後
  套用到 208 天或 730 天前就已經開始的整段回測——對回測初期的時間點而言，這是使用了尚未
  發生的未來資訊（審計任務點 1 明確要查的「有無前視」，這裡查到的是**步長校準**層級的前視，
  不是濾波觸發本身——濾波觸發的 point-in-time 正確性我已核對過，`day - pd.Timedelta(days=1)`
  的切片手法是嚴格因果的，沒有問題）。
- **量化測試**（1h/208d 分支沒有 F3 的比例 bug，適合單獨隔離「前視」這個變因）：改用「窗口
  最開頭 336 根 candle」（即回測起點當下實際可得的波動率）取代「窗口尾端 336 根」重新校準
  步長，其餘完全不變：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/audit_pointintime_step.py
  ```
  結果（f120）：聚合 PnL 從 -$425.2 變成 **-$420.3**（幾乎相同）；unfiltered 從 -$1645.2 變成
  -$1432.3（仍決定性為負）；non-negative 比例 7%→14%（仍遠低於 60% 門檻）。個別幣的步長確實
  有變動（HYPE 0.776%→1.001%、TAO 0.644%→0.838%，變動 20-30%），但對聚合結論沒有實質影響。
- **direction**：中性（bug 存在但經驗證對此 verdict 的聚合結論沒有可觀測影響；如果未來要
  把這個回測方法用在對步長更敏感的策略上，建議修成逐期滾動校準）。
- **verdict_changing**：no（已用替代假設實跑驗證）。

### F5 — 測試窗口是規模性的 altcoin 下跌 regime，NO-GO 具 regime 依賴性（品味／gate 本身，僅列，report 文字已部分揭露）

- **位置**：`reports/trend-filtered-grid-verdict.md:24-26`（已寫「HYPE stays strongly
  positive... i.e. the grid's edge remains coin/regime-specific, not a universal harvest」，
  算是部分揭露，但沒有量化）。
- **量化**：用快取的日線資料計算窗口報酬，1h/208d 窗口 14 個候選幣中 **13/14 下跌**，
  中位數 **-44.6%**；4h/730d 窗口同樣 **13/14 下跌**，中位數 **-40.1%**（連 BASELINE 的 BTC
  也是 -31.0% / -0.2%；唯一大漲的是 HYPE +109% / +386%）。兩個窗口都被單邊下跌行情主導，
  即使 730 天窗口號稱「涵蓋多個 regime」（verdict 原文用語），候選幣層級的價格走勢其實高度
  一致地是下跌。
- **判斷**：這件事本身不是計算錯誤，是市場歷史的事實，依審計守則屬於 gate/品味類，只列出、
  不判對錯。但值得指出：即使在濾波器 point-in-time 正確、成本模型正確（F1-F4 都驗證過）的
  前提下，一個「趨勢濾波器理論上該保護你」的持續下跌環境，最後仍然沒能讓多數 alt 轉正——
  這代表失敗模式不只是「沒濾波器所以死在下跌」，更包含「濾波器本身在震盪下跌（非單邊直線
  下跌）中頻繁反覆觸發（見下方觀察），每次來回都在top附近進場、底部附近停損/出場」的
  SMA 交叉系統經典弱點。這個 regime caveat 意味著：若未來要在真正的 alt season（多頭輪動）
  重新測試，不應該直接引用這份 NO-GO 當作永久結論。
- **direction**：中性。**verdict_changing**：no。

---

## 附帶觀察（非 finding）

- `scripts/research_trend_filtered_grid.py:74-116` 的 `replay()` 有回傳 `flips`（濾波觸發的
  開關次數），但 `run_config()` 從未印出或使用它——目前 verdict 報告完全看不到濾波器實際
  觸發頻率。我重新計算後發現 1h/f120 濾波器觸發次數普遍很低（多數幣 2-11 次 / 208 天），
  但 4h/f120 觸發次數明顯偏高（15-43 次 / 730 天，多數幣「on」的時間佔比在 30-50% 之間）——
  這不是同一段歷史的兩種取樣頻率比較（1h 測 208 天、4h 測 730 天，本來就是不同曆史區間，
  不是同一段期間換算 bar 週期，所以觸發次數不可直接比較），但如果未來想診斷「濾波器是不是
  在震盪段來回打臉」，建議把 flips 與 on% 一併寫進報告。

---

## 已檢查、未發現問題的項目

1. **濾波觸發方向與逐日切片是否有前視**：`day - pd.Timedelta(days=1)` 的切片手法正確地只用
   「今天以前」的每日收盤與 SMA，觸發方向（`price > SMA` 才開倉）與宣稱的假設一致，未發現
   濾波觸發本身的前視或方向錯誤（前視問題出在步長校準，已列為 F4）。
2. **平倉/重建網格成本模型**：`replay()` 在濾波關閉瞬間對所有未平倉 lot 做 mark-to-market
   平倉並扣手續費（`cum -= float(row["c"]) * lot.size * FEE`），與 `strategy.step()` 內部
   TP/停損的手續費計算慣例（只在出場端收費）一致，未發現漏算或重複計算平倉成本。開倉端
   （濾波重新開啟）正確地沒有立即成本，因為真實網格開倉本身不產生費用，只有實際成交才收費，
   這點與其餘程式碼一致。
3. **對照組（unfiltered）是否同源同參數**：`unfiltered` 是同一個 `replay()` 函式在 `fd=0`
   分支跑出來的，與濾波變體共用完全相同的 `GridConfig`（含 F3/F4 提到的步長，兩者一致，
   不構成濾波 vs 非濾波之間的差異來源），確認是嚴格的 apples-to-apples 對照，不是另外一套
   backtest 拼湊出來的數字。
4. **網格/濾波參數是否預先註冊**：核對 `src/hlvault/gridbot/config.py:46-51` 的 live-engine
   環境變數預設值（`NUM_LEVELS=6, VOL_K=0.5, MIN_STEP_PCT=0.003, MAX_STEP_PCT=0.03,
   STOP_BUFFER_PCT=0.15, COOLDOWN_HOURS=24`），與研究腳本裡的硬編碼常數逐一比對，**完全一致**
   ——不是為了讓這次測試好看/難看而臨時調的參數。濾波長度 {90,120,150} 在腳本 docstring 開頭
   即宣告為「declared in advance」，三個值都被完整跑過、要求 sign 一致才算穩健，沒有看到
   只挑對結論有利的單一濾波長度報告的跡象。
5. **可重現性**：本次獨立重跑（原始程式、原始快取）與 `reports/trend-filtered-grid-verdict.md`
   的表格逐位元組一致，快取檔案時間戳（2026-07-03 01:17）與 verdict commit 時間
   （2026-07-03 01:20，commit `7421a8b`）吻合，排除「報告數字與目前程式碼行為已經不同步」
   的疑慮。

---

## 總評

五個 finding 全部 **verdict_changing: no**。四個可量化的方法論問題（F1 敘事完整度、F2 MDD
分母錯配、F3 timeframe-scaling bug、F4 步長前視）逐一用替代假設重新實跑後，**沒有一個能把
NO-GO 翻成 GO**，其中 F3 修正後甚至讓結果更負（bug 原本對策略有利，不是不利）。最值得使用者
留意的不是任何單一計算錯誤，而是 F1+ F5 合起來指出的完整度落差：verdict 報告目前只保留了
聚合兩列數字，遺失了「濾波器對哪些幣有害、測試窗口有多集中於單邊下跌」這兩件對「這個 NO-GO
在什麼條件下才成立」很重要的脈絡。建議：若之後要重啟這條研究線（例如換一個涵蓋 alt season
的窗口重測），把逐幣明細與 flips/on% 一併存檔，而不是只存聚合摘要。
