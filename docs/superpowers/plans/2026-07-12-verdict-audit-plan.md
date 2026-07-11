# Verdict Audit Implementation Plan（sub-project J）

> **For agentic workers:** 主對話派工、subagent 逐 task 執行、fresh-context agent 驗收；
> 主對話不下場。執行型派工 prompt 末尾必加「你必須親自執行全部步驟，不得使用 Agent
> 工具再委派」。模型：機械重現用 haiku、審計推理用 sonnet、統計方法學與最終第二意見用 opus。

**Goal:** 系統性審計 vault 全部 8 個 NO-GO 判定，找出判定鏈中**可證明的錯誤**
（資料、回測機制、成本、統計、spec-實作漂移），產出「錯誤清單＋調整方向＋翻案潛力」
給 owner 確認；獲確認的項目才進入修正與重測（phase 3，屆時另立 plan）。

**Architecture:** 兩段式審計（finder 找 → verifier 重現）× 8 個 verdict ＋ 1 個跨案
成本假設審計 → 主對話綜合排序 → opus 第二意見 → owner 裁決點。
所有 finding 進統一 schema，落 `reports/verdict-audit-2026-07-12.md`。

---

## 反凌遲守則（審計的憲法，優先於一切「翻案」動機）

1. **錯誤三分類**，只有前兩類算 finding：
   - 【bug】客觀可重現的錯（程式錯、算錯、資料錯、費率抄錯）——必附重現指令＋輸出。
   - 【假設】存在有依據的替代假設（如漏算 funding 收入、Bonferroni 用在高相關 configs 上）
     ——必須同時報告兩種假設下的數字。
   - 【品味】gate 門檻高低、風險偏好（3× 還是 2×、MDD 上限多少）——**只列出、不裁決**，
     進 owner 確認清單。agent 與模型不得片面放寬任何 gate。
2. **方向對稱**：每個 finding 標注偏差方向——「冤殺」（false NO-GO 方向）或「當初過寬」
   （false GO 方向）。修了會讓結果**更差**的錯誤照樣報告。
3. **翻案的證據標準**：NO-GO → GO 需要 (a)【bug】級錯誤且修正後數字過原 gate，或
   (b)【假設】級修正 **＋新資料/新窗的樣本外確認**（同一份資料上重新達標不算翻案，
   算假說復活——寫明這個區別）。
4. **審計自身的多重檢定**：8 個 verdict × ~7 個審計維度 ≈ 56 次「找錯機會」，
   綜合報告必須聲明審計總檢定數；孤立的邊緣發現降權。
5. verdict-changing 級 finding 一律經 fresh-context verifier 重現後才進報告；
   重現失敗降級為「觀察」。

## 審計對象與優先序（P(翻案)×價值÷重測成本，主對話判斷）

| # | Verdict | Kill path | 預判翻案角度（審計假說，非結論） | 優先 |
|---|---|---|---|---|
| 1 | `reports/cta-phase2b-verdict.md` | median Sharpe 1.27 過、best config t=2.14 < 2.9 Bonferroni | Bonferroni 假設檢定獨立，但 configs 高度相關 → effective-N 修正；若部署的是 median-config/ensemble 而非 best-picked，選擇懲罰是否根本不適用；334d 樣本外部限制 | **高** |
| 2 | `reports/momentum-backtest-verdict.md` | Sharpe 0.28、-24%、MDD -65% | perp 空單 **funding 收入是否計入**；MDD 是 sizing/槓桿造成還是訊號造成（vol-targeting 反事實）；4 幣宇宙太窄；成本雙算檢查 | **高** |
| 3 | `reports/oos-verdict.md`（trader selection） | 99 選手→月均 1-4 人過 α 檢定、OOS -22~-25% | α 檢定的統計檢定力（小樣本 false negative）；選擇到跟單的時滯；月度再平衡成本假設 | 中 |
| 4 | `reports/pair-trading-verdict.md` | median Sharpe -1.63、60% 硬停損、spread 發散 | 208d 單一 regime 窗；beta 重估頻率；但機制性失敗（發散）先驗難翻 | 中 |
| 5 | `reports/trend-filtered-grid-verdict.md` | 濾波後兩個 TF 皆負 PnL | 濾波參數化是否吃掉了 grid 的本體收益；窗口 regime | 中 |
| 6 | `reports/scalp-phase1-verdict.md`（H，昨日） | 三家族＋maker round 2 全滅 | 滑價取樣只有單一 2h 窗（time-of-day 偏差）；walk-forward 選擇指標（train PF, n≥20）的雜訊；已有 opus 覆核，P(翻)低 | 低 |
| 7 | `stablepairs/reports/stablepairs-g0-verdict.md`（I，昨日） | 最佳 2.55× < 3×門檻 | 3× 是【品味】級門檻（列給 owner）；振幅量測用收盤-收盤的低估已由 opus 評過；720h 窗選擇 | 低 |
| 8 | `compound/reports/`（放貸 11.68% vs 12% 目標） | 差 0.32pp 未達標 | 目標值出處；量測窗代表性；這是目標校準問題非策略失效 | 低 |
| X | 跨案成本假設審計（不綁單一 verdict） | — | 帳戶實際費率仍未覆核（缺 owner 地址）；HL staking 折扣；`ORDER_SLIPPAGE=0.05` 是限價緩衝、有沒有任何研究腳本誤當期望滑價用；funding PnL 在各 perp 回測的處理一致性 | **高** |

範圍註記：實盤中的 gridbot/CTA override 的**反向審計**（當初是否過寬）不在本輪——
owner 若要，另開。六假設（compound）已併入 #8 與跨案 X。

## Finding schema（所有 agent 統一輸出格式，一條一物）

```
- verdict: <檔名>
  type: bug | 假設 | 品味
  direction: 冤殺 | 過寬 | 中性
  claim: <一句話>
  evidence: <檔案:行號 ＋ 重現指令 ＋ 關鍵輸出數字>
  verdict_changing: yes | maybe | no（附一句為什麼）
  proposed_adjustment: <方向，不是實作>
  rerun_cost: <小時級估計>
```

## Task 1: 審計 CTA phase-2b（統計方法學，sonnet finder）

**Files:** 讀 `reports/cta-phase2a-verdict.md`、`reports/cta-phase2b-verdict.md`、
`reports/cta-overnight-synthesis-2026-07-06.md`、`scripts/research_cta_positioning_phase2b.py`
（及其引用）；輸出 `reports/audit/J-cta2b-findings.md`

- [ ] **Step 1**（sonnet finder）：逐維度審計（判定鏈重建／資料／機制／成本／統計／spec 漂移），
  特別深挖：configs 相關結構下 Bonferroni 的 effective-N（可實際計算 config 報酬序列的
  相關矩陣與有效獨立檢定數）；「部署 median config 是否需要選擇懲罰」的論證兩面；
  334d 與 proxy 多年資料的證據合成是否被正確使用。輸出 findings（schema 格式）。
- [ ] **Step 2**（haiku verifier）：對每條 verdict_changing ∈ {yes, maybe} 的 finding
  重跑其重現指令，確認數字；失敗降級。
- [ ] **Step 3**：主對話收檔入綜合清單。

## Task 2: 審計 momentum（成本與 sizing 反事實，sonnet finder）

**Files:** 讀 `reports/momentum-backtest-verdict.md`、`reports/oos-verdict.md`（若相關）、
`src/hlvault/momentum/backtest.py`、momentum spec；輸出 `reports/audit/J-momentum-findings.md`

- [ ] **Step 1**（sonnet finder）：重點問題（逐條要有數字證據）：
  (a) 回測是否計入 perp funding PnL？空單在熊市段的 funding 收入缺席會系統性低估報酬——
  若缺席，量化影響級別（用當期 funding 資料粗估 bps/年）。
  (b) MDD -65% 發生在什麼倉位/槓桿路徑？把訊號報酬與 sizing 拆開：固定 1x、vol-target
  兩個反事實下 MDD 與 Sharpe 各多少（可實跑小腳本）。
  (c) `FEE_RATE=0.0005` 與滑價的套用次數與位置——有無雙算或漏算。
  (d) 4 幣宇宙的倖存者/選擇問題。
- [ ] **Step 2**（haiku verifier）：重現 (a)-(c) 的量化數字。
- [ ] **Step 3**：主對話收檔。

## Task 3-8: 審計 #3~#8（sonnet finder × 6，可平行）

**Files:** 各 verdict＋其腳本；輸出 `reports/audit/J-<name>-findings.md` × 6

- [ ] 每個對象一個 finder（prompt 用統一模板：判定鏈重建 → 六維度 checklist →
  schema 輸出；模板寫在派工時，含反凌遲守則全文）。#6 scalp 與 #7 stablepairs 的
  finder 特別註明：已有 opus 第二意見與 fresh 驗數，你的增量價值在「他們沒問過的問題」
  （如滑價取樣的 time-of-day 偏差、選擇指標雜訊），不要重複已驗證的算術。
- [ ] verifier 逐案重現 verdict_changing 級 findings。
- [ ] 主對話收檔。

## Task 9: 跨案成本假設審計 X（haiku 機械掃描 + sonnet 判讀）

**Files:** grep 全 repo 研究腳本的費率/滑價/funding 常數；輸出 `reports/audit/J-cross-costs-findings.md`

- [ ] **Step 1**（haiku）：機械盤點——所有研究腳本中的 fee/slippage/funding 常數與其值、
  `ORDER_SLIPPAGE` 在研究（非引擎）代碼中的誤用處、funding PnL 有算/沒算的清單。
- [ ] **Step 2**（sonnet）：判讀哪些常數已過時或錯用（對照 fee_ground_truth 與
  HL 官方檔位），影響哪些 verdict、方向與量級。
- [ ] **Step 3**：把「用 owner 錢包地址跑 `scripts/scalp_fee_check.py --user`」列入
  owner 確認清單（一直缺的地面真相）。

## Task 10: 綜合與第二意見（主對話 + opus）

**Files:** Create `reports/verdict-audit-2026-07-12.md`

- [ ] **Step 1**：主對話彙整全部 findings → 依「翻案期望值 = P(flip)×策略價值÷重測成本」
  排序；每項寫：finding 摘要、證據、建議調整、需要 owner 裁決的【品味】項單列。
  聲明審計總檢定數（守則 4）。
- [ ] **Step 2**：opus 第二意見——只給 findings 數字與 schema，不給主對話的排序結論；
  要求獨立標注「哪些站得住、哪些是審計端的過度擬合」。
- [ ] **Step 3**：合併，分歧處原樣呈現。**STOP → owner 確認清單**：勾選要修哪些、
  裁決全部【品味】項。此後才有 phase 3（逐項修正計畫，含預先註冊的修正後 gate）。

## 執行成本與時程估計

- Finder × 8（sonnet）＋ verifier × 8（haiku）＋跨案 X ＋綜合＋opus ≈ 18-20 個 agent，
  一個工作日內完成（各 task 高度可平行，git 無衝突——審計只寫 `reports/audit/` 新檔）。
- 全程唯讀既有結果＋小型重現腳本（/private/tmp 或 reports/audit/）；不改任何策略碼、
  不動任何 gate、不碰實盤。

## 完成定義（phase 1-2）

`reports/verdict-audit-2026-07-12.md` 存在，含：全部 8+1 案的 findings（經 verifier
重現）、排序後的翻案候選清單、owner 裁決清單（【品味】項＋gate 修改提案＋錢包地址請求）、
opus 第二意見與分歧標注。**到此停，等 owner 勾選。**
