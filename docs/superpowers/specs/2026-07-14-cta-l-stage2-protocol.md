# CTA L Stage 2 協議細化（sub-project L·預註冊——commit 後才准跑正式數字）

依 `2026-07-13-cta-staged-sizing-design.md` §4 骨架細化。上位 spec 未定義或可雙讀之處，
本檔一律寫成顯式公式＋數值錨（judgment.md 2026-07-13 教訓：散文式定義擋不住雙讀法）。
與上位 spec 衝突時以本檔為準（本檔即 §4 授權的「協議細化修正案」）。
審查記錄：2026-07-14 opus 對抗審查兩輪——第一輪（2 blocker、6 major、4 minor）全數修入；
第二輪判定全部 fixed（B2 經真實資料實跑驗證），新增 1 major（A1 resize bar 的 mtm 歸屬）
＋2 minor（G-A·4 偏離帳、resize_events schema），亦已修入本版。本版即凍結版。

## 1. Baseline、資料、數值錨

- **B1（當前 baseline）**：Stage 1 V1——per-position vol-target，σ_target 60%、EWMA
  span 180、clip [0.25, 1.0]、進場鎖定、cap-only（`scripts/cta_l_stage1.py`）。
  Stage 1 verdict：`reports/cta-l-stage1-verdict.md`（owner 裁決，G-L2 邊緣 PASS）。
- 主窗硬編 **2020-09-14 → 2026-06-30**；資料 `data/cache/cta_proxy/*.parquet`（已凍結，
  右端 2026-07-05 覆蓋）；config `4h-p10-fuel24`（short book）；成本 0.055%/side。
- **MDD 公式**：一律依上位 spec §8 修正案 1（固定基底）：
  `eq_t = 1 + Σ_{s≤t} r_s`；`MDD = min_t [eq_t − max_{s≤t} eq_s]`。
- **數值錨（gate 腳本啟動時必須先以相對容差 1e-9 重現全部六值＋trade 數，否則不得
  輸出 gate 表）**：
  | 量 | 全精度值 |
  |---|---|
  | B0 全窗 MAR | 0.108912676802 |
  | B0 全窗 MDD | −0.336189359482 |
  | B0 全窗 Sharpe | 0.306891680973 |
  | B1 全窗 MAR | 0.299355395590 |
  | B1 全窗 MDD | −0.152055268750 |
  | B1 全窗 Sharpe | 0.499956120997 |
  | B0/B1 trade 數（主窗） | 759 / 759（整數，須精確相等） |
  （來源：Stage 1 `gates_table_t6.md`；可由 `scripts/cta_l_stage1_runs.py` ＋
  `scripts/cta_l_stage1_verify_t6.py` 重生。）

## 2. 統計機器（全部顯式；Stage 2 不再有公式級裁量）

- **日報酬**：UTC 日界聚合 4h PnL ÷ $500 固定基底，非複利（上位 spec §2）。
- **MAR** = 年化 ÷ 下限化 |MDD|：`ann = Σr × 365 / n_days`（n_days＝該窗 csv 全部日數，
  含 warmup 零報酬日——Stage 1 已證比值不受影響）；`MAR = ann / max(|MDD|, 0.005)`；
  0.5% 下限統一套用所有窗（全窗、折、cost15、端點）。
- **六折硬編**：F1 2020-09-14→2021-12-31；F2 2022 曆年；F3 2023；F4 2024；F5 2025；
  F6 2026-01-01→2026-06-30。**折內公式**：eq 以該折首日重置（eq=1 起算），
  折內 `MDD = min_t [eq_t − max_{s≤t} eq_s]`（固定基底，同 §8 修正案 1；避免
  「running peak」一詞歧義，此處即為 fold 內 fixed-basis 回撤深度）。
- **Sharpe** = mean(r)/std(r, ddof=1) × √365，r 為該窗逐日報酬。
- **d_t** = r_variant − r_baseline：兩條 csv 的 DatetimeIndex 必須 **assert 完全相等**
  後才相減；禁止 align/reindex（會產 NaN 靜默污染）。端點截斷窗的 variant/baseline
  成對重跑，天數天然一致。
- **DSR**：唯一公式 `src/hlvault/metrics.py:35` 解析版；N 累計：**A1 用 N=11、A2 用
  N=14、A3 用 N=17**（上位 spec §2:60-61，Stage 1 記 8，每 ablation +3）。
- **只呈報項的 bootstrap**（非 gate）：paired stationary block bootstrap，聯合重抽對齊
  (r_V, r_B)，期望 block 20d（Geometric p=1/20）、B=10,000、`numpy.random.default_rng(42)`、
  **circular wraparound（Politis-Romano）**、CI = 重抽分佈 [5th, 95th] 百分位
  （numpy linear 插值）。此段把 Stage 1 兩份實作的 discretion 全部寫死。
- **邊緣帶條款**：任何 gate 統計量落在門檻 ±10% 帶內，verdict 不得寫「穩健」，
  必須標註邊緣性（上位 spec §6.5；G-A·2 的折計數恰為 4/6 時同樣視為邊緣）。

## 3. 乘數組合語義（上位 spec 未定義；本檔寫死）

- `m_total(coin, entry_ts) = m_vol × Π m_f`，f 遍歷「已併入 baseline 的因子＋當次受
  判定的因子」。各因子皆 ≤1.0，故 m_total ≤ 1.0（cap-only 天然成立）。
- **無額外全域下限**：各因子自帶下限（m_vol ≥0.25、A1 ≥0.5、A2 ≥0.5、A3 ≥0.5），
  乘積理論下限 0.25×0.5³=0.03125——如實接受，m_total 分佈逐 ablation 呈報。
- 進場鎖定原則不變。**唯一例外**：A1 事件窗的存續期縮放（§4，顯式定義記帳與成本）。
- 判定順序 A1→A2→A3 固定；每個 ablation 相對「當前存活 baseline」判定，過了即併入；
  順序效應是已知且接受的性質（上位 spec §4:125-127）。

## 4. A1 事件日曆降倉（主配置）

- **事件集合**：FOMC 利率決議聲明（排程會議；窗內若有非排程聲明，逐筆列入並標註）＋
  美國 CPI 發布（BLS），2020-09-14→2026-06-30。
- **時戳**：官方公布時刻，**逐筆做 ET→UTC 換算（含 DST，禁用固定偏移）**——FOMC
  聲明 14:00 ET；CPI 08:30 ET。整理成 `data/events/us_macro_calendar.csv`
  （欄位：`date_utc, ts_utc, type{fomc|cpi}, source_url`），**先 commit 才准跑數字**；
  由獨立 agent 對官方來源 spot-check ≥3 筆（含至少 1 筆 DST 切換月份）。
- **窗與 bar 對齊（顯式）**：窗 = [T−24h, T+6h]。**bar 索引為開盤時刻**（4h bar 覆蓋
  [idx, idx+4h)）；「窗內 bar」判定用**收盤時刻**：`idx + 4h ∈ [T−24h, T+6h]`。
  多事件窗以閉區間取聯集；兩窗在 4h 粒度上相鄰（中間無任何窗外 bar）視為連續，
  整段只執行一次縮放/恢復循環。
- **窗內行為（顯式）**：
  1. 禁新倉：進場訊號在窗內 bar 觸發者直接放棄（不延後）。
  2. 舊倉縮放：進入窗的第一根窗內 bar 收盤時，部位有效 notional 縮至
     `0.5 × 進場鎖定 notional`，縮放量 |Δnotional| 計**單邊**成本（標準 0.055%；
     cost-stress 見 §7 G-A·3）；窗結束後第一根窗外 bar 收盤時恢復至進場鎖定
     notional，再計一次單邊成本於 |Δnotional|。若部位於窗內觸發出場，照常出場
     （出場成本按當時有效 notional），不再恢復。
  3. **mtm 歸屬（釘死）**：resize 於 bar i 收盤執行——bar i 自身的 mark-to-market
     用 resize **前**的有效 notional，bar i+1 起用 resize 後；restore 同規則
     （restore bar 自身用恢復前的 0.5×，次一 bar 起用恢復後）。
  4. **執行期裁決（2026-07-14，T2 實作期記錄，早於任何正式 run）**：出場判定源自
     前一 bar 訊號、於當前 bar 開盤／盤中執行，時序上**先於**收盤時刻的 restore——
     故部位在窗後第一根 bar 出場時，以仍縮放的 notional 出場、restore 不執行
     （「窗內出場不恢復」規則的對稱延伸；記錄於引擎 docstring 與此處）。
- **被縮放 trade 的記帳語義（ledger schema，寫死）**：
  - `notional` 欄＝**進場鎖定值**（不因縮放改寫）；`m` 欄＝進場鎖定 m_total。
  - 新增 `resize_events` 欄：JSON list，每筆
    `{ts, prev_notional, new_effective_notional, cost}`（含 prev，讓成本手算免重建順序）。
  - `fees` 欄＝進出場成本＋**全部** resize 成本之和。
  - `pnl` 欄＝**逐段 mark-to-market 之和 − fees**：trade 生命週期被 resize 切成段，
    每段的 bar PnL 依該段有效 notional 計。
  - **恆等 guard（取代 Stage 1 單一 notional 版）**：全窗
    `Σ 逐日報酬 × 基底 == Σ trade.pnl`（容差 1e-6）；且在「無事件、無 veto、
    m_f≡1.0」路徑下，引擎輸出與 Stage 1 `simulate_l` **逐位相等**（Stage 1 selftest
    照跑全過）。
- **敏感度（只呈報）**：(i) 只禁新倉、不縮舊倉；(ii) 窗改 [T−48h, T+6h]。

## 5. A2 訊號強度縮放（主配置）

- **pct 數值來源（顯式）**：raw 幀的 `lpct_raw`（crowd 百分位原始數值，
  `cta_proxy_lib.raw_indicators` 產出）經 **`.shift(1)`**（closed-bar，與進場門同一
  shift）。注意：`shifted_signals` 的輸出只有布林 `crowd_long`（= `lpct_raw≥90` 再
  shift），**不含數值欄**——m_A2 直接讀 `frames` 的 `lpct_raw.shift(1)`，不重算
  第二份百分位。
- **同源 guard（可執行版）**：assert 逐位成立
  `crowd_long（引擎進場門用的布林） == (lpct_raw.shift(1) >= 90)`——證明布林門與
  m_A2 的數值出自同一條 `lpct_raw`、同一 shift。
- **公式（short 側）**：進場 bar 的 `pct = lpct_raw.shift(1)` 值（即前一收盤 bar 的
  百分位），`m_A2 = 0.5 + 0.5 × min(1, (pct − 90) / 7)`。防禦：若實際 pct < 90
  （理論不發生），記 log 並取 m_A2 = 0.5，事件數呈報。進場鎖定，存續期不重調。
- **聲明偏離（2）**：本書 short-only，上位 spec §4:136 的 long 側鏡像（p10/p3）
  **不實作**——無實際影響，僅為完備性聲明。
- **敏感度（只呈報）**：ramp 上端 97 改 95／99（各一組）。〔**聲明偏離（1）**：上位
  spec §4:137 的「下限 0.25」敏感度**取消**——它與 §3 組合下限交互，超出「只呈報」
  的風險預算。〕

## 6. A3 regime 降倉（主配置）

- **訊號**：BTC 4h close vs SMA(1200 bars ＝ 200d)，closed-bar、shift-by-one。
  **SMA 以 BTC 完整快取幀計算**（快取自 2019-09 起；PIT 安全，全為過去資料），
  故主窗起點 2020-09-14 時 SMA 已滿窗——warmup 條款（未滿 1200 bars 時 m_A3=1.0）
  僅為快取起點變動時的防禦，主窗內預期不觸發。
  `close_{t-1} > SMA_{t-1}`（risk-on）→ m_A3 = 0.5；否則 1.0。進場鎖定。
- **敏感度（只呈報，共 2 組）**：SMA 100d／300d。〔**聲明偏離（3）**：上位 spec
  §4:140 的「乘數 0.75」敏感度**取消不跑**（非「跑了不計數」）——保持每 ablation
  試驗計數恰為 3（主＋2 敏感度），避免 DSR 的 N 被隱性灌水。〕

## 7. Gates（每個 ablation 獨立判定；全過才併入 baseline）

| Gate | 顯式判準 |
|---|---|
| G-A·1 | DSR(d_t; N=累計試驗數) ≥ 0.95，DSR 依 §2 唯一公式 |
| G-A·2 | 六折（§2 硬編折界）中 ≥4 折 ΔMAR = MAR_variant − MAR_baseline ≥ 0（MAR 依 §2） |
| G-A·3 | 成本 ×1.5 下 Sharpe(d_t) > 0。**成本 ×1.5 適用於全部成本分量**：進出場 0.055%→0.0825%/side，A1 resize 單邊成本同步 0.055%→0.0825%；variant 與 baseline 同調重跑 |
| G-A·4 | 端點 −30/−60/−90d（截斷窗成對重跑）：**三組 Sharpe(d_t) 皆 > 0（絕對判準）**。主窗 Sharpe(d_t) 僅作敘述，不參與判準 |

**判定語義（上位 spec §4:151-152 原樣）**：全過 → 併入 baseline、判定下一個；任一不過 →
該因子收檔、不重試變體、繼續下一個 ablation。單一因子失敗不終止 Stage 2。
Stage 2 結束條件：三個 ablation 判定完畢 → Stage 2 總 verdict（含 m_total 分佈、
存活 baseline 定義、與 B1 的全窗對比）。

## 8. 工程 guards（繼承 Stage 1，新增）

1. **迴歸＋新恆等**：引擎擴充（entry veto、事件窗縮放、m 組合）後，Stage 1 兩支
   selftest 必須全過（無 veto、無事件、m_f≡1.0 時逐位退化回 B1 路徑）；含 resize 的
   路徑改用 §4 的新恆等 guard（`Σ日報酬×基底 == Σtrade.pnl`，1e-6）。
2. **A1 縮放成本＋mtm 歸屬手算**：任取一筆被縮放的 trade，手算縮放＋恢復成本對照
   ledger 的 `resize_events` 與 `fees`（<1e-9）；另建一支 **2-bar 合成情境 selftest**
   （已知價格路徑，手推 resize bar 與次一 bar 的 pnl 數值錨），證明 mtm 歸屬
   逐位符合 §4 規則——此為協議「顯式公式＋數值錨」標準對自身新機制的套用。
3. **A2 同源檢查**：§5 的可執行版 assert（布林門 == 數值源 ≥90，逐位）。
4. **A1 資料 PIT**：`data/events/us_macro_calendar.csv` 的 commit hash 必須早於任何
   正式 run 的產出；verdict 引用該 hash。
5. **驗證不自驗（Stage 1 制度原樣）**：每個 ablation 的 gate 表由 fresh-context 盲測
   verifier 依本檔公式獨立重算，逐格一致（容差 1e-6）才進 verdict；不一致 → 停下找
   唯一根因，禁取平均；opus 二審數字表；仍不一致呈 owner。

## 9. 誠實條款（繼承上位 spec §6 全部，新增）

1. **A1 時戳風險**：官方日曆的 DST 換算與少數改期事件是人工整理，spot-check 只抽驗
   ≥3 筆；錯 1-2 筆時戳對 [T−24h,T+6h] 窗的影響未建模。
2. **A2 的 pct 分佈是樣本內構造**（percentile 窗定義沿引擎既有），ramp 端點 90/97 是
   ex-ante 判斷非校準。
3. **順序效應**：A2/A3 吃殘差改善，其 FAIL 不等於「該因子單獨無效」——只證明
   「在已併入因子之上無殘差改善」。
4. m_total 乘積可低至 0.031（§3）：若實際分佈頻繁貼近下緣，等同變相空倉，verdict 必須
   呈報並討論。
5. **DSR 對 d_t 的已知偏差（樂觀方向）**：(a) A1 的 d_t 預期高度稀疏（僅事件窗日與
   resize 日非零）——skew/kurt 修正在近退化序列上數值不穩；(b) 乘數進場鎖定＋多日持有
   使 d_t 自相關，違反 DSR 的 iid 假設、低估變異。verdict 必須逐 ablation 呈報 d_t
   非零日數；G-A·1 恰好壓線通過且 d_t 非零日 <5% 時，必須標註 DSR 樂觀方向並降級敘述。
6. **A1 的 G-A·2 預期邊緣**：事件-only 效應微弱，六折投票近乎擲硬幣（Stage 1 G-L2
   同型弱點）——verdict 對 A1 必須引用 §2 邊緣帶條款。
7. Stage 1 的 G-L2 邊緣性與 MDD 慣例裁決（post-hoc）由 B1 繼承——引用 Stage 2 任何
   結論時，Stage 1 verdict §4 的另一讀法揭露不可省略。

## 10. 試驗計數與凍結

- 每 ablation 恰 3 試驗（1 主＋2 敏感度）：A1 累計 N=11、A2 N=14、A3 N=17。
  **不跑任何額外配置**（含被取消的 A2 下限、A3 乘數 0.75 敏感度——見 §5/§6 聲明偏離）。
- 對上位 spec 的聲明偏離共四處：(1) A2 下限敏感度取消（§5）；(2) long 側鏡像不實作
  （§5）；(3) A3 乘數 0.75 敏感度取消（§6）；(4) G-A·4 由「符號零翻轉」改為
  「三端點皆 >0 絕對判準」（§7）——消歧上位 spec 在主窗 Sharpe(d_t)≤0 時的自相矛盾；
  分岔區域已被 G-A·1/G-A·3 擋掉，所有可達情形結果等價，但依偏離帳紀律仍列明。
  除此之外與上位 spec 一致。
- 本檔 commit 後：主配置常數、gate 門檻、折界、公式**全部凍結**；任何改動須以修正案
  commit 並在 verdict 記錄（含改動時是否已看過數字）。
