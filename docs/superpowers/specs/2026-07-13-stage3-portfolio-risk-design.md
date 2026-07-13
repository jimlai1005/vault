# Stage 3 組合層風控設計（sub-project K · Task 6 交付物）

**狀態：設計交付。不實作、不判定、不跑任何數字。**
執行（回測與 verdict）另需依 §6 紀律以修正案 commit 預註冊後才准開始。
本檔是 K 與 L 兩份平行預註冊中 Stage 3 段落的收斂點（裁決記錄見 §2）。

來源文件：
- K 設計 §Stage 3：`docs/superpowers/specs/2026-07-13-position-framework-design.md:49-55`
- K plan Task 6：`docs/superpowers/plans/2026-07-13-position-framework-phase1-plan.md:77-83`
- L spec §5：`docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md:154-165`
- K v1 verdict §3（煞車層限縮）：`reports/momentum-vt-v1-verdict.md:36-45`

## 1. 觸發條件（未觸發前，本設計不得進入實作）

vault 內存在 ≥2 條「驗證過的報酬流」——經 verdict GO、或 forward-test 存活
（≥6 個月真 OOS 且 owner 認可）的 sleeve（採 L §5 定義）。
**截至 2026-07-13：未觸發**（現況見 §4）。

## 2. K/L 落差裁決（此後以本檔為準）

| 項目 | K（§Stage 3） | L（§5） | 裁決 |
|---|---|---|---|
| fractional Kelly 係數 | 0.25–0.5× 範圍 | 固定 0.25× | **固定 0.25×**——範圍是可調面＝資料窺探面；取保守端 |
| 觸發條件 | 「≥2 條驗證過 sleeve」，未定義「驗證」 | GO 或 ≥6 個月 forward-test 存活＋owner 認可 | **採 L**（可判定） |
| sleeve 清單 | 具體四項（momentum/CTA/gridbot/lending） | 通用「驗證過的報酬流」 | 通用定義＋本檔 §4 現況表落地 |

K 與 L 原互不引用（平行預註冊）。此後 Stage 3 的一切細節以本檔及其修正案為
單一參考點；L §5 其餘條款（rebalance 時點、Ledoit-Wolf、gates 形狀、修正案紀律）
原樣繼承，不改寫、不放寬。

## 3. 方法與介面定義（回測原型）

**輸入**：每 sleeve 一條**日頻淨報酬序列**（USD 計價，扣費用與 funding 後）。
硬性要求（全域工程原則 #1）：
- 單一 sleeve 的序列必須同源產生，不得混拼多個端點或欄位；
- 每條序列須與 venue UI 顯示權益對帳通過才算合格輸入；
- 「實盤短窗」與「proxy 回算長窗」混餵同一協方差矩陣時，advisory 報告必須
  逐 sleeve 標註來源等級（live / proxy / summary-derived）。

**估計**：每週一 00:00 UTC，以 trailing 90d 日報酬重估 vol 與相關；
協方差用 Ledoit-Wolf 收縮（`src/hlvault/weights.py:60,65` 已有
`risk_parity_weights()` 與 `fractional_kelly_weights()`，來自 trader-selection-pipeline）。

**配置**：主案 = risk parity（ERC）；對照案 = fractional Kelly 固定 0.25×；
baseline = equal-weight。

**組合層 vol-target**：cap-only（只縮 gross、不放大）。依 K v1 verdict §3：
煞車層是「回撤圍堵層」可複用預設，**非報酬中性 drop-in**；與各 sleeve 報酬的
交互必須在執行期逐一重測。

**輸出**：週初目標權重 advisory 報告——建議配置 vs 現況、觸發原因、
每 sleeve 資料來源等級標註。只建議、不執行。

## 4. Sleeve 候選現況表（2026-07-13）

| sleeve | 驗證狀態 | 報酬序列現況 | 合格時點估計 |
|---|---|---|---|
| CTA short book | forward-test 2026-07-04 起（引擎在遠端，本地無同步歷史） | 無現成序列；可由 `data/cache/cta_proxy/*.parquet`（2020–2026）回算，繼承 `reports/cta_proxy_layer2b_verdict.md` 的 proxy 極限 | 最早 ~2027-01（滿 6 個月）或提前 GO |
| lending（compound/Bitfinex） | 回測 verdict＋實盤 2026-07-04 起 | 只有逐年 APR 摘要（`compound/reports/backtest_verdict.md`）；底層利率資料 `compound/data/candles_1D_p2.csv`（2016–2026）可回算日序列 | 是否已算「驗證過」由 owner 裁決 |
| gridbot | **不進配置**（`compound/reports/cycle_allocation_verdict.md:62-63`：單幣證據＋2-3 天 pilot，等級不足；同檔 :97-99 定性為「未驗證」而非「已否決」，pilot 可繼續攢證據） | 僅 3 天成交流水（`logs/gridbot.log`，07-01→07-04），無 PnL 序列 | pilot 攢足證據後重評 |
| conditional momentum | v1 NO-GO 收檔（2026-07-13） | — | 僅可經 v2 重開，前置條件見 `reports/momentum-vt-v1-verdict.md:47-56` |

**結論：觸發條件未滿足，Stage 3 停留在設計。**
觸發後的實作前置工作：逐 sleeve 建「日淨報酬序列 builder」＋venue 對帳檢查
（今日三個 sleeve 皆無現成序列，這是最大缺口）。

## 5. 紅線

- 本層產出永遠是 advisory；任何實盤 sizing 變更逐次 owner 核准；自動化另案。
- 執行期不得放寬 L §5 gates（DSR on difference vs equal-weight ≥0.95、
  folds 多數、成本、端點敏感度）；只能加嚴。

## 6. 執行紀律（繼承 L §5）

sleeves 實際身分、資料窗、目標波動等一切執行細節，跑任何數字**之前**必須
以本檔修正案形式 commit（同預註冊紀律）。Stage 3 的試驗數自首次執行起累計，
不歸零。

## 7. 誠實條款

1. 今日三個 sleeve 皆無現成日報酬序列；任何「回測將顯示⋯」的預期都是推測。
2. CTA 序列若以 proxy 回算，繼承 layer2b「量級偏弱」極限；「實盤短窗 × proxy
   長窗」的相關性估計本質上不同源，此 basis 風險必須在 advisory 報告中明示
   （工程原則 #1 的組合層版本）。
3. lending 的 6–10% 保守帶（cycle_allocation_verdict）是年化摘要非序列；
   用摘要造常數日報酬序列會低估相關性與尾部，**不得**用於 gates 判定，只可示意。
4. 方法選擇（ERC、0.25×、90d、週頻）是 ex-ante 判斷不是校準——模型判斷，
   信心有限；執行期若敏感度組與主配置方向矛盾，verdict 必須降級敘述。
