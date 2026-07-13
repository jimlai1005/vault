# CTA Staged Sizing（sub-project L）Stage 2 Verdict

**狀態：定稿（2026-07-14）。**
**判定：三個預註冊 ablation（A1 事件日曆、A2 訊號強度、A3 regime）全部未過 gate、
全部收檔、皆不併入 baseline。Stage 2 結束，存活 baseline 維持 B1
（Stage 1 的 per-position vol-target）不變。依協議判定語義（單一因子失敗不終止、
不重試變體），本 verdict 為機械判讀；opus 二審見 §5。**

協議（凍結 `c329dd2`，兩輪對抗審查）：`docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md`。
前置：事件日曆 PIT `692754e`、引擎 `71009d3`（六 guard 全過）。
Stage 1 verdict（B1 的來源與其繼承條款）：`reports/cta-l-stage1-verdict.md`。

## 1. 三 ablation × 四 gate 總表

| Gate（門檻） | A1 事件日曆（N=11） | A2 訊號強度（N=14） | A3 regime（N=17） |
|---|---|---|---|
| G-A·1 DSR(d_t) ≥0.95 | **FAIL** 0.494 | **FAIL** 0.012 | **FAIL** 0.005 |
| G-A·2 折 ΔMAR ≥4/6 | PASS 4/6（邊緣） | **FAIL** 1/6 | **FAIL** 2/6 |
| G-A·3 cost×1.5 Sharpe(d_t)>0 | PASS 0.761 | PASS 0.085 | PASS 0.025 |
| G-A·4 三端點 Sharpe(d_t)>0 | PASS（0.74/0.75/0.75） | PASS（0.14/0.06/0.05） | **FAIL**（−0.079/−0.080/−0.080） |
| **判定** | **收檔** | **收檔** | **收檔** |

主窗 ΔSharpe bootstrap（呈報項，非 gate）：A1 +0.180，CI [+0.059, +0.303]；
A2 +0.031，CI [−0.043, +0.102]；A3 +0.074，CI [−0.131, +0.248]。
d_t 非零日：A1 63/2116（3.0%）、A2 215/2116（10.2%）、A3 338/2116（16.0%）。

## 2. 逐 ablation 解讀（含反面證據）

- **A1（FOMC＋CPI 事件窗降倉）**：三者中唯一留下「值得未來重訪」痕跡的因子——效果方向
  一致為正（ΔSharpe CI 不含零、成本 ×1.5 與三端點全穩健、4/6 折），敗在 N=11 的 DSR
  試驗數校正（0.494 << 0.95）。注意協議 §9.5 的偏差方向：d_t 僅 3% 非零，DSR 在稀疏
  序列上**偏樂觀**，連樂觀方向的估計都過不了門檻——FAIL 的方向可信。依預註冊紀律
  收檔、不重試；其定義（含 PIT 日曆）完整封存，任何未來重訪需帶新 OOS 與累計試驗數。
- **A2（crowd 百分位訊號強度縮放）**：K 案 verdict 先驗最看好的機制家族（A2a 對位
  「趨勢持續性」），移植到 CTA short book **不成立**——結構原因在進場條件本身：
  進場已要求 ≥p90，76.7% 的進場落在 ramp 頂端（m=1.0，與 B1 無異），因子只差異化了
  23% 的 trades，且方向不利（1/6 折、CI 含零）。這不是「訊號強度無資訊」的普遍結論，
  是「在已被 p90 門檻截斷的分佈上，殘餘百分位深度無增量資訊」。
- **A3（BTC-200SMA regime 降倉）**：唯一方向為負的因子（三端點 Sharpe(d_t) 全負）。
  當年 K 案擔心的「錯砍 2022 空側」**沒有發生**（2022 全年 BTC 在 SMA 下方，F2 ΔMAR
  恰為 0）；傷害來自 2023-2025 的 above-SMA 期——被砍半的空單其實在賺錢。
  「短邊優勢是 regime 特有」（crowd-ablation 三源印證）仍可能為真，但**以 BTC-200SMA
  定義的 risk-on/off 不是那個 regime 變數**。opus 二審補充（採納）：A3 的 2/6「PASS」
  折都是 regime 全折未觸發的退化平手（ΔMAR 恰為 0、variant 逐位＝baseline）——
  **A3 在六折中沒有任何一折嚴格贏過 baseline**。

## 3. 驗證紀錄（與 Stage 1 對照）

- 三張 gate 表全部經 fresh-context 盲測驗證者依協議公式獨立重算，**逐格一致
  （1e-12 級，遠優於 1e-6 容差）**——Stage 2 零分歧事件。
- Stage 1 的 MDD 慣例事故後引入的「顯式公式＋數值錨」制度全程有效：每次 gate 計算
  先重現六錨（rel_err ~1e-12）才准輸出；錨機制還實際消歧了一次年化常數的潛在雙讀
  （√365 vs metrics.py 內建 252——盲測者以錨反向驗證，並代數確認 DSR 內部該常數抵消）。
- 引擎完整性：泛化 gate 腳本每次改動後對已判定 ablation 重跑 diff 為空；A2/A3 的
  ledger 恆等（與 B1 的 759 筆 trade 三元組集合相等）與退化自查（因子關閉時逐位退回
  v1）全部通過。執行期唯一裁決（A1 出場×restore 時序）已帶日期戳記入協議 §4。

## 4. 誠實條款（繼承協議 §9 全部）

1. **三個全收檔不等於「sizing 條件化無效」的普遍結論**——它是「這三個預先指定的
   條件變數，在此資料窗、此試驗數預算下，無一達到預註冊證據門檻」。A1 的正向痕跡
   與 A2 的結構性解釋（分佈截斷）都是資訊，寫明留檔。
2. proxy 極限（funding≠持倉、volume≠OI）與 funding accrual 未建模，全部繼承。
3. 資料窗已被 Stage 1＋Stage 2 反覆使用；任何未來重訪這三個因子，2020-2026 窗的
   檢定力已受污染，需以新 OOS 為主。
4. Stage 1 繼承條款不變：B1 的 G-L2 是邊緣 PASS、MDD 慣例經 owner post-hoc 裁決
   （與證據鏈方向相反）——引用 B1 或本 verdict 時，Stage 1 verdict §4 的另一讀法
   揭露不可省略。
5. 順序效應條款本輪未實際生效（無因子併入，A2/A3 實際上都是對 B1 的獨立判定）——
   opus 二審：因此本輪不存在順序效應混淆，是一次乾淨的空手。
6. **G-A·3 的結構性弱點（opus 二審發現，採納）**：對「純降曝險」型 overlay，
   成本 ×1.5 下 Sharpe(d_t) 近乎自動為正（曝險少→省費是機械效果，連主窗 d_t 為負的
   A3 都翻正）。三 ablation 全過 G-A·3 **不構成任何正向證據**；未來協議若沿用此 gate，
   應對 gross 下降型 variant 改用成本中性化的差序列設計。

## 5. opus 二審

依 plan T9：opus 只看六張數字表（實作者三張＋盲測三張）獨立判定。結果（2026-07-14）：
- 三個 ablation 的判定**全部確認機械正確**；六表交叉最大差異 1e-12 級，零不一致；
  折天數加總、trade 數（A1 716 因禁新倉、A2/A3 759）、錨定重現皆內部一致。
- Red flags 兩項，均已採納入 §2/§4：A3 的退化平局、G-A·3 對 de-risker 的近自動 PASS。
- opus 獨立結論（引述）：「這不是差之毫釐的近敗而是清楚的空手」（最高 DSR 僅 A1 的
  0.494 vs 門檻 0.95）；三連敗因無 p-hacking 空間而可信，但外部效度受限於單一 proxy
  資料窗；任何一個 PASS gate 都不應被誤讀為正向證據。與機械判讀一致，無需呈 owner 裁決。

## 6. sub-project L 收檔狀態與資產

- **L 案最終交付：B1**（per-position vol-target，σ_target 60%、span 180、clip 0.25、
  cap-only）——研究層 baseline，MDD 圍堵 −33.6%→−15.2%（固定基底）。
  **本 verdict 不構成任何實盤變更**：live CTA 維持 fixed-notional $300/筆（紅線；
  若 owner 未來要把 B1 sizing 應用到實盤，屬獨立決策、逐次核准）。
- Stage 3（組合層）不因 Stage 2 結果開啟或關閉——其觸發條件（≥2 條驗證過報酬流）
  獨立判定，現況見 `docs/superpowers/specs/2026-07-13-stage3-portfolio-risk-design.md` §4。
- 可複用資產：Stage 2 引擎（veto／事件窗縮放／m 組合，`scripts/cta_l_stage2.py`＋
  selftest）、PIT 事件日曆（`data/events/us_macro_calendar.csv`，FOMC/CPI 2020-2026，
  任何未來事件研究直接取用）、三對 gate/verify 腳本、全部 manifests。

## 7. 追溯

- Runs：`scripts/cta_l_stage2_runs_a1.py`／`_a2.py`／`_a3.py` → `data/cache/cta_l2/`
  （gitignored 可重生；manifests 記引擎 commit 與日曆 blob hash）。
- Gates：`scripts/cta_l_stage2_gates.py`（泛化，公式凍結）；盲測
  `scripts/cta_l_stage2_verify_a1.py`／`_a2.py`／`_a3.py`。
- Gate 表與盲測表：`data/cache/cta_l2/{a1,a2,a3}_gates.md`＋`*_gates_verify.md`。
- opus 二審全文（逐字存檔）：`reports/cta-l-stage2-opus-review.md`。
