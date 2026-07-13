# Momentum-VT v1 執行協議（sub-project K，owner 修訂版）

日期：2026-07-13｜狀態：預先註冊——commit 後才准跑正式數字
本檔取代 K spec 的 Stage 1/2 執行細節（三個條件變數 ablation **封存不刪**，v1 判定後另案）；
K spec 的誠實聲明（死案不改判、GO 掛新策略名）與 Stage 3 設計不變。

## 1. 策略定義（owner 規格的可執行化）

- **Signal：零改動**——既有 20/60/120 日多尺度 momentum composite（`src/hlvault/momentum/signals.py`）。
- **Universe（兩種，入格）**：
  - U-fixed：BTC/ETH/SOL/HYPE（HYPE 自 Binance 上市日 2024-11 起納入）。
  - U-PIT：point-in-time 流動性過濾——每季初重建：Binance USDT-perp 中 trailing 90d
    日中位名目成交 ≥ $100M 且上市 ≥180 天者，取前 8 名。無前視（只用季初前資料）。
- **Sizing 疊層（自內而外，全部機械）**：
  1. 訊號 → 名目權重（沿用原引擎）。
  2. **單資產風險占比 cap**：以 rolling 共變異（lookback＝該格 vol lookback）算 ex-ante
     風險貢獻 RC_i；任一 |RC_i| > 35% → 該權重等比降至 35%，釋出部分不再分配
     （cap-and-shrink，迭代至收斂或 10 輪）。
  3. **相關叢集 cap**：BTC/ETH/SOL 的 |RC| 合計 > 75% → 三者等比縮至 75%。
  4. **Portfolio vol-target**：ex-ante 組合年化波動縮放至該格 target；gross ≤ 3x。
  5. **Drawdown 階梯**（相對全程 running peak，peak 不重置）：
     DD ≤ -10% → target 降至 10%；DD ≤ -15% → 只准減倉不准加倉；
     DD ≤ -18% → 全平＋冷卻 20 交易日 → 以 10% target 復駛 → DD 回升至 -10% 以上
     才恢復該格 target。
- **成本**：fee 5bps＋slip 1bps（單邊，計於換手）；**funding 逐 interval 計入**——
  全期用 Binance fundingRate 史（8h，與價格同源，2019 起可得）；2024+ 窗以 HL
  fundingHistory 交叉對照一次落檔。

## 2. 預先登記的 8 格（不再擴充；無其他可調參數）

| 格 | target vol | vol/cov lookback | universe |
|---|---|---|---|
| 1 | 15% | 20d | U-fixed |
| 2 | 15% | 40d | U-fixed |
| 3 | 20% | 20d | U-fixed |
| 4 | 20% | 40d | U-fixed |
| 5 | 15% | 20d | U-PIT |
| 6 | 15% | 40d | U-PIT |
| 7 | 20% | 40d | U-PIT |
| 8 | 20% | 20d | U-PIT |

**主格＝格 2（15%/40d/U-fixed）**（owner 規格：15% primary、20% challenger；lookback
取 40d——申報：40d 在審計窗曾顯示較優，此偏好已計入 DSR 試驗數）。
其餘 7 格為 challenger／鄰域證據，禁止事後改選主格。

## 3. 視窗與運行紀律

- 資料：Binance 日線 2020-01-01 → 2026-07-02（proxy，日線保真高；佐證一次落檔）。
- **無擬合參數聲明**：8 格皆固定參數，模擬全程無任何 IS 選擇；「每季重校準」僅指
  U-PIT 宇宙重建與風險模型快照，非參數擬合。
- **開發窗**：2024-07-02→2026-07-02（已挖窗）——除錯、機械驗證限此窗。
- **正式運行（每格一次）**：2020-01-01 → 2025-12-31，OOS 報酬以「非重疊季度塊」
  記帳（2020-Q3 起，暖機 6 個月）。跑一格、commit 一格。
- **Untouched holdout：2026-01-01 → 2026-07-02**——只有 G-K1~K5 全過才准跑，
  全 8 格一次跑完即封存。
- **證據分層（預先聲明）**：2020-Q3→2024-Q2 段（乾淨，含牛/熊/震盪）承重；
  2024-Q3→2025-Q4 段（已挖窗）降權為佐證。gate 數字以全 OOS 段計，
  但 G-K3 的市場階段判定必須含乾淨段。

## 4. 上線 Gates（owner 提案採納＋房規補強；判定對主格）

| Gate | 判準 |
|---|---|
| G-K1 | 主格 OOS 淨 Sharpe ≥ 0.6，且 DSR ≥ 0.95（**申報試驗數 N=16**＝本 8 格＋歷史動能嘗試 8）＋ HAC t 一併呈報 |
| G-K2 | OOS 串接 equity 的 MDD ≤ 20% |
| G-K3 | 五個日曆市場階段（2020-21 牛／2022 熊／2023 震盪／2024-25 牛尾／2025-26 熊）中 ≥3 段淨報酬為正，其中至少 2 段在乾淨窗內 |
| G-K4 | 鄰域一致性：主格的 3 個相鄰格（格1/格4/格6）至少 2 格 OOS Sharpe ≥ 0.3 且同號 |
| G-K5 | 端點 ±10 天敏感度不翻盤＋OOS 段 split-half 各半 Sharpe > 0＋成本×1.5 後 Sharpe ≥ 0.45 |
| G-K6 | （前五關全過才跑）holdout：Sharpe > 0 且 MDD ≤ 20%，與 OOS 期望的落差如實呈報 |
| G-K7 | paper/live shadow **90 天**：年化 tracking error ≤ 8% 且 realized Sharpe > 0；過 → owner 裁決實盤（紅線必問） |

判定語義：G-K1~K6 全過＝conditional GO（進 G-K7 paper）；任一關不過＝Momentum-VT v1
NO-GO 入檔，8 格結果全數呈報（含不利格），本線收檔——**沒有 v1.1 參數微調輪**；
若 owner 屆時要開 v2，必須是新假說（如封存中的條件變數），不是新參數。

## 4b. 執行期裁決修訂（2026-07-13，實作發現，owner 代決者裁定）

1. **RC/cluster cap 實作**：字面的 `w_i *= sqrt(cap/RC_i)` 因分母同縮而漸進不達 cap——
   改為對含分母效應的聚合 RC 函數**二分搜尋**求根；協議意圖以後置條件為準
   （max|RC_i| ≤ 35%、叢集 ≤75%），數學推導在 `scripts/k_vt_engine.py` docstring。
2. **疊層資料流**：DD 階梯先行決定當日 target，再進 rc_cap → cluster_cap →
   vol_scale(target)，最後套 NO_ADD/FLAT 約束——§1 圖示的層序依此解讀。
3. **HYPE 起點**：Binance HYPEUSDT perp 實際 2025-05-30 上市（非 HL 的 2024-11）；
   U-fixed 中 HYPE 自 2025-05-30 納入，如實申報。
4. **滯後慣例釘死**：標準無前視語義＝「t 日收盤用 ≤t 資料決策、賺 t+1 日報酬」；
   訊號、Σ、階梯狀態一律照此，不額外多滯後一天。
5. **小活躍集的 cap 語義**（dev 窗發現：≤2 個活躍資產時 RC 合計恆 100%，35% cap
   數學不可行 → 引擎歸零整簿）：有效單資產 cap = **max(35%, 1/N_active)**（N_active＝
   當日非零訊號資產數；N≥3 時 35% 原樣、N=2 時 50%、N=1 時不作用——總風險仍由
   vol-target 與 DD 階梯管束）；叢集 cap 僅在當日存在叢集外活躍資產時生效。
   owner 的 35%/75% 於 N≥3 完整保留。
6. **G-K5 端點檢查適配**：右端 ±10 天會窺入 holdout——改為 OOS 記帳起點 ±10 天
   ＋視窗終點單側 −10 天，如實標注。
7. **紀律違規申報與補救**（2026-07-13）：runner 煙測誤將格 2 成本×1.5 腿執行於
   formal 視窗（資料不完整＋cap 修訂前，數字作廢隔離、未入任何檔案）。補救：
   (a) DSR 申報試驗數 **16 → 17**；(b) formal 視窗加機械鎖 `FORMAL_UNLOCKED`
   （與 holdout 同款），由主對話在正式運行時刻才建立。

## 5. 工程與驗證

- 引擎基於 `scripts/research_momentum_voltarget.py`（已驗無前視）擴建：RC caps、
  DD 階梯、PIT 宇宙、季度 OOS 記帳。**新增邏輯必須有單元測試**（RC cap 收斂、
  階梯狀態機轉移、PIT 無前視、冷卻期行為）。
- 正式運行由主對話逐格下指令即刻 commit；fresh verifier 從逐日 csv 重算全部 gate；
- opus 二審只看數字。verdict 落 `reports/momentum-vt-v1-verdict.md`。
