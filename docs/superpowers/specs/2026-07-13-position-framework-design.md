# 三階段動態倉位管理框架＋條件化動能（sub-project K）

日期：2026-07-13｜狀態：預先註冊——本檔 commit 後才准跑正式數字
Owner 命題：「寫死槓桿＋寫死 MDD 是設計矛盾；給策略煞車，不是放寬速限，
更不是給沒有引擎的車裝煞車。Gate 維持原樣、sizing 動態化、死掉的案子維持死亡。」

## 0. 誠實聲明與假說重設（與 owner 原述的偏差，需 owner 認可）

1. **momentum 既有兩個 NO-GO 維持不變**（原判＋2026-07-12 vol-target 釘窗重測）。
   本專案**不是翻案**：無條件動能已被證明是厚尾雜訊（前半窗 Sharpe 為負、DSR 0.465）。
2. 本專案檢驗的新假說：**條件化動能**——edge 只在特定狀態存在，條件變數本身是 alpha
   的載體。House precedent：CTA crowd filter（三源印證「濾波器就是 alpha」）。
3. **偏差 A（Stage 1 gate 重定義）**：owner 原述「Stage 1 = momentum+vol-target 過
   walk-forward OOS」——但昨日釘窗重測已是這個測試且已 FAIL；原樣重跑＝窗口購物。
   重定義：Stage 1 驗收**煞車本身**（風險交付指標），報酬判定全部移到 Stage 2 的
   乾淨 OOS 窗。煞車的驗收是煞得住，不是車跑多快。
4. **偏差 B（資料窗重設）**：2024-07→2026-07 已被三輪測試污染。新資料策略見 §2。
5. Owner 提到的「confidence-weighted position sizing 系統」：其正規歸宿＝Stage 2
   的 A2a（訊號強度縮放）；執行期先搜 repo/pandora 既有實作與教訓再動工。

## 1. 三階段結構（每階段各自的預先註冊 gate，逐層掙門票）

### Stage 1：vol-target 煞車層（基礎設施驗收）
- 實作：portfolio vol-target overlay（沿用 2026-07-12 重測驗證過無前視的引擎），
  目標年化波動 20%、回看 20d、槓桿上限 3x（全部沿用，不開網格）。
- **Gate S1（風險交付，兩個資料窗都要過）**：(a) 實現年化波動 ∈ [15%, 25%]
  （目標 ±25%）；(b) MDD ≤ 20% 預算；(c) 換手成本年化 ≤ 3%；(d) 無前視
  （fresh verifier 逐位審）。不看 Sharpe/報酬。
- 過 → 煞車層成為全部後續（含未來其他策略）的標配；不過 → 框架本身回爐。

### Stage 2：條件變數逐一掙門票（本專案的科學核心）
- Baseline＝訊號原樣＋Stage 1 煞車。**三個 ablation 預先鎖定、單點、無網格、
  一次加一個、失敗不回收**：
  - **A2a 訊號強度縮放**：倉位權重 ∝ 標準化 composite score（cap 於現行上限），
    取代 sign-only。（MOP 標準做法；confidence-weighted sizing 的正規歸宿）
  - **A2b regime 閘門**：BTC 收盤 vs 200d SMA 單一二值狀態——多單只在 bull 態、
    空單只在 bear 態成立。單一規則，不試其他均線。
  - **A2c 事件日曆降倉**：FOMC＋CPI 日 ±1 天 gross 降 50%。日曆為靜態 csv
    （2020-2026 公開排程），執行期建檔並抽驗日期。
- **Gate S2（每個 ablation 獨立判）**：在乾淨 OOS 窗（§2）上，相對 baseline 的
  ΔSharpe > 0 且經 DSR 校正（申報試驗數 N=4：baseline＋三 ablation）後仍成立，
  且 MDD 不惡化超過 2pp。過 → 留下；不過 → 棄。
- **最終策略判定 Gate S2-final**：baseline＋全部存活 ablation 的組合模型，在乾淨
  OOS 窗上過**原判三關原樣**（Sharpe ≥ 0.5、總報酬 > 0、MDD ≤ 20%）＋ DSR ≥ 0.95
  ＋ 端點 ±10 天敏感度不翻盤（judgment.md 新規）＋ 窗內 split-half 各半 Sharpe > 0。
  全過 → **conditional GO（新策略「conditional momentum」，非舊案復活）** → paper。
  組合模型不過而個別 ablation 曾過 → 如實呈報，不准回頭挑組合。

### Stage 3：組合層風控（≥2 條驗證過的 sleeve 後才實作，本輪只交付設計）
- 每週週期：trailing 90d 的 vol/相關性估計 → sleeve 間 risk parity 基準
  ＋ fractional Kelly（0.25-0.5x）上限 → 週初調整目標倉位。
- Sleeve 候選：conditional momentum（若 S2-final 過）、CTA short book（實盤中）、
  gridbot、lending。**產出先為每週 advisory 報告**（建議配置 vs 現況），
  實際動實盤 sizing 屬紅線，逐次 owner 核准；自動化另案。
- 本輪交付：設計文件＋回測原型的介面定義。不實作、不判定。

## 2. 資料策略（反窗口購物的結構性設計）

- 源：Binance 日線（BTC/ETH/SOL 自 2020-01-01 或各自上市日；HYPE 自 2024-11 上市日）。
  日線尺度 proxy 保真極高（分鐘級的 0.7-0.9 問題不適用；執行期抽 30 天與 HL 日線
  對照一次落檔佐證）。funding 用 HL fundingHistory（可得期），缺洞以 0 計並申報。
- **開發窗（污染窗，允許看）**：2024-07-02 → 2026-07-02。所有實作除錯、ablation
  的機械驗證在此窗做。
- **判定窗（乾淨 OOS，只准跑一次）**：2020-01-01 → 2024-06-30（含 2020-21 牛、
  2022 熊、2023 震盪三個 regime）。本 repo 動能研究從未觸碰。**每個 ablation 與
  組合模型在此窗各只跑一次、結果直接入檔**；任何「調了再跑」自動使該線失格。
- 端點全部硬編時間戳。宇宙按上市日動態納入；倖存者偏差方向（三大幣皆倖存者）
  在 verdict 標注。
- 真 OOS 終局：S2-final 過後的 paper/forward ≥ 4 週（協議沿用 2026-07-12 重測 §5）。

## 3. 判定語義與紀律

- 「死掉的案子維持死亡」：本專案產出的任何 GO 都掛在**新策略名**（conditional
  momentum）之下；momentum 原案卷宗不改判。
- DSR 試驗數申報：本專案累計申報 N=4（S2）＋ S2-final 一次；若執行中任何額外變體
  被跑過，N 隨之上調並入檔。
- 乾淨窗只跑一次的執行保障：判定窗的執行由主對話直接下指令、輸出即刻落檔 commit，
  不給實作 agent「先看看再說」的空間。
- 全部腳本沿用：釘窗、成本（fee 5bps＋slip 1bps）、split-half、DSR 引擎
  （`scripts/research_momentum_voltarget.py` 已驗證的實作）。

## 4. 完成定義

Stage 1 gate 表＋Stage 2 四條線（baseline＋3 ablation）的乾淨窗判定＋S2-final 判定
＋`reports/conditional-momentum-verdict.md`（fresh verifier 重算＋opus 二審）＋
Stage 3 設計文件。全程 gate 數字不動、sizing 層動態化、原案卷宗不改判。
