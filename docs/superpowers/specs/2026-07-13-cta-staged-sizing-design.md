# Sub-project L：CTA sizing/conditioning 分階段優化（預註冊）

**狀態：預註冊。本檔 commit 後才准產出任何正式數字。**
方法論模板：`docs/superpowers/specs/2026-07-12-momentum-voltarget-retest.md`（NO-GO 收檔，
但其預註冊紀律與 gate 結構被本檔繼承）。

## §0 定位與邊界

- **L 判定的是 sizing / conditioning 層，不是訊號**。CTA 訊號（`4h-p10-fuel24`，
  EMA20/50 趨勢＋逆向 crowd filter＋OI fuel）的 GO/NO-GO 已由 phase-2b 判定為
  **NO-GO（綁定）**，正由 owner-override live forward-test（2026-07-04 起）購買真 OOS 證據。
  **L 的任何結果都不翻轉 phase-2b 判定**。L 的產出是：若訊號在 forward-test 存活，
  屆時該用什麼 sizing/conditioning/配置層。
- **實盤 forward-test 配置凍結**。L 的成果不得中途部署到 live 引擎——中途改配置會毀掉
  正在累積的 OOS 證據。任何部署動作（含改 `NOTIONAL_PER_TRADE`）屬實盤紅線，必問 owner。
- **crowd filter 本體不可作為 ablation 對象**（不得放寬、移除、改參數）——三源印證它就是
  alpha（`reports/cta-overnight-synthesis-2026-07-06.md:12`）。Stage 2 的 ablation 一律是
  「在既有訊號之上加層」，不動核心。
- **槓桿只縮不加**：所有 sizing 層 multiplier ≤ 1.0（相對 baseline notional），全程
  gross ≤ baseline gross。依據：全周期真實 MDD 錨 −32%，無加槓桿空間
  （`reports/cta-overnight-synthesis-2026-07-06.md:14,28`）。

## §1 假說（每 stage 一句，唯一被檢驗的命題）

- **H1（Stage 1）**：在訊號零改動下，逐部位、以標的波動為分母、cap-only 的 vol-scaled
  sizing，相對 fixed-notional baseline 改善風險調整後表現（MAR），且不顯著犧牲 Sharpe。
- **H2（Stage 2）**：以下條件層各自對 Stage-1 存活 baseline 有 DSR 校正後為正的 OOS 改善：
  A1 事件日曆降倉、A2 訊號強度縮放、A3 regime 降倉。逐一判定，掙到門票才併入。
- **H3（Stage 3）**：當 vault 存在 ≥2 條驗證過的報酬流時，週頻組合層配置
  （risk parity / fractional Kelly）相對 equal-weight 有 DSR 校正後為正的改善。

## §2 資料與共同方法（全部 stage 共用，先鎖死）

- **資料**：Binance proxy（funding 代 crowd、quote-volume 代 fuel），5 幣
  （BTC/ETH/SOL/DOGE/XRP），4h bar，cache `data/cache/cta_proxy/`。
  **窗硬編：2020-09-14T00:00Z → 2026-06-30T00:00Z**。禁「從今天回推 N 天」。
- **成本**：0.045%/side taker ＋ 1bp slippage（只准比原判嚴）。停損按停損價成交、gap 開盤處理，
  與 phase-2b 引擎一致。
- **報酬基底（同源同基）**：兩邊（baseline 與 variant）皆以固定 $500 基底（5 幣 × $100）
  計算算術日報酬（UTC 日界聚合 4h PnL），非複利，MDD 同基底計算。
  **MAR 分子 = 非複利算術年化報酬（Σ日報酬 × 365 ÷ 天數）**；分母 = |MDD|，
  每折 MDD 取 max(|MDD|, 0.5%) 作下限（防除零，兩腿同規則）。年化 √365。
  B 與 V 的所有數字由**同一支 gate 腳本**從逐日報酬 csv 計算，禁止混源。
- **OOS folds（walk-forward 評估）**：F1=2020-09-14→2021-12-31、F2=2022、F3=2023、
  F4=2024、F5=2025、F6=2026-01-01→06-30。共 6 折。
  誠實標註：參數皆 ex-ante 釘死、無擬合，但此資料已被 phase2a/2b 等大量探索，
  folds 屬 **pseudo-OOS**；真 OOS 只有 live forward-test。
- **端點敏感度**：右端點 −30d／−60d／−90d 各重算一次，gate 方向不得翻轉。
- **paired bootstrap（只用於 Sharpe 類統計量）**：stationary block bootstrap，期望 block
  20 天、B=10,000、seed=`numpy.random.default_rng(42)`。重抽單位是**對齊的聯合日向量
  (r_variant,t, r_baseline,t)** 的 block；每個 resample 各腿分別算 Sharpe 再取差，得
  ΔSharpe 分佈。**MDD／MAR 不做 bootstrap 推論**——MDD 是路徑統計量，block 重排會把
  跨年回撤打碎、系統性低估 MDD（危險方向）。paired ΔMAR bootstrap CI 只呈報於附錄、
  附此 caveat、不作 gate。
- **DSR（唯一指定公式）**：`src/hlvault/metrics.py:35` 的解析版
  （e_max = √(2·lnN)·sr_std，N 為純計數，含 skew/kurt 修正的 PSR）。門檻 DSR ≥ 0.95。
  不使用 momentum retest 的跨試驗經驗變異版（該版需要每個試驗的真實 SR 序列，
  與本檔的保守餘裕計數不相容）。d_t = r_variant − r_baseline 為日頻差序列，
  Sharpe 類統計量，無路徑問題。
- **試驗計數 N（累計、預先寫死）**：Stage 1 記 N=8（1 主＋4 敏感度＋3 保守餘裕）。
  Stage 2 每個 ablation 記 3（1 主＋2 敏感度），依序累計：A1 用 N=11、A2 用 N=14、A3 用 N=17。
  訊號層歷史探索（~50 試驗）不計入——因為 L 不重判訊號；此取捨已在 §0 交代。
- **判定紀律**：每 stage/ablation 只有一個**主配置**受判定；敏感度組只呈報、不得改選。
  任一 gate 不過＝該線收檔，**不再有變體、不重試**。gate 腳本的 bug 修正不算重試，
  但「bug 修正」的認定標準先寫死：不得改動任何 §3/§4 主配置常數與 gate 門檻；
  修正後必須全表重算，並在 verdict 附修正前後 diff 說明。

## §3 Stage 1 協議：per-position vol-scaled sizing（cap-only）

### 定義

- **B0（baseline）**：現行 fixed-notional——每次進場每幣 $100。邏輯與 phase-2b 引擎
  一致（錨定見 guard 0），但成本掛載照下方定義、**產出一律出自同一個新引擎
  simulate_l（guard 1）**，不得用原始路徑產 B0 的 csv。
- **V1（variant）**：進場 notional_i = $100 × m_i,t，
  m_i,t = clip(σ_target / σ_i,t, 0.25, **1.0**)。
  - σ_i,t：幣 i 的 4h log return EWMA 波動，span=180 bars（30 天），年化 ×√2190，
    closed-bar、shift-by-one（進場當 bar 不含自身）。
  - warmup：前 180 bars m=1.0（即等同 baseline）。
  - m 在部位存續期間鎖定於進場值（不逐 bar 重調——避免引入額外換手與成本）。
  - **為什麼不是 momentum 版 overlay**：momentum 用「策略自身 trailing realized vol」做分母，
    CTA 的書常年平盤（短邊 1-3 年空窗屬正常），該分母在空窗期趨近 0 會把槓桿頂到 cap——
    病態。改用標的波動、逐部位、cap-only。
- **成本掛載**：L 的所有 run（含 B0）用 0.045%＋1bp slippage = **0.055%/side**，
  fee 與 slippage 皆按實際 notional（含 m）計。
- **結構性質（regression guards，實作驗收用）**：
  0. **引擎錨定**：新引擎在 m ≡ 1.0 且 slippage=0 之下，必須逐位元重現 phase-2b
     原始路徑（`cta_proxy_lib.run_cell` → `p2b.simulate`）的輸出——錨定到已審計引擎。
  1. **L-baseline 恆等**：B0 = 新引擎 m ≡ 1.0＋slippage 1bp；V1 與 B0 出自同一引擎。
  2. **ledger 恆等**：V1 與 B0 的 trade ledger（coin, entry_ts, exit_ts）集合恆等——
     V1 只改大小，不改進出場。
  3. **線性縮放**：強制注入常數 m ≡ 0.5 時，逐日報酬必須 = 0.5 × B0 逐日報酬
     （rtol 1e-12）——PnL、fee、slippage 必須全部隨 notional 等比縮放，此測試同時抓
     「漏乘 fee」類的靜默灌水 bug。

### 主配置與敏感度

- **主配置（唯一受判定）**：σ_target = 60%（年化）、span = 180 bars、clip 下限 0.25。
  σ_target=60% 的依據是 ex-ante 常識（BTC 長期年化波動約 50-60%、alts 80-120%，
  此值讓 BTC 平靜期大致滿倉、alts 與波動尖峰被壓縮）——**模型判斷，非市場校準，信心有限**。
- **敏感度（只呈報）**：σ_target ∈ {40%, 80%}（span 固定 180）；span ∈ {90, 360}（σ_target 固定 60%）。

### Gates（全過才算過）

| Gate | 判準 |
|---|---|
| G-L1 | 全窗 MAR(V1) ≥ 1.3 × MAR(B0)。若 MAR(B0) ≤ 0：改為 MAR(V1) > 0 且 Sharpe(d_t) > 0 |
| G-L2 | 6 折中 ≥4 折 MAR(V1) ≥ MAR(B0)（每折 MDD 下限規則見 §2） |
| G-L3 | paired bootstrap（§2 聯合重抽）ΔSharpe 90% CI 下界 > −0.15（非劣性：de-lever 可以小傷 Sharpe，不能大傷） |
| G-L4 | 成本 ×1.5（0.0825%/side，B0 與 V1 同調）下 G-L1 仍成立 |
| G-L5 | 端點 −30/−60/−90d 三組（各自截斷窗重跑，B0/V1 成對）中 G-L1 的方向（V1 ≥ B0）零翻轉 |

只呈報不作 gate：paired ΔMAR bootstrap CI（附 §2 的 MDD 碎裂 caveat）、敏感度組全表、
m 分佈摘要。設計註記：MAR 與 Sharpe 對均勻槓桿縮放不變，故 G-L1/G-L2 量測的是
vol-timing 的跨時間／跨幣**重配**效果，不是水位效果——這是刻意的。Stage 1 的採納門檻
建構為「點估計幅度（1.3×）＋逐折一致性＋Sharpe 非劣性＋成本與端點穩健」；
DSR 式推論門檻從 Stage 2 起適用。

**判定語義（先寫死）**：全過 → V1 成為 **B1 baseline**，Stage 2 開門；此結論僅適用研究層，
部署另議（§0）。任一不過 → sub-project L 全案收檔（Stage 2/3 不開門），CTA 維持
fixed-notional，verdict 記錄後不再有變體。

## §4 Stage 2 協議：預註冊 ablation，一次一個，掙門票

**前提**：Stage 1 全過。判定順序固定 A1 → A2 → A3；每個 ablation 相對「當前存活 baseline」
（B1 ＋ 已掙到門票的因子）判定；過了即併入 baseline。後判定的因子吃殘差改善——
順序效應是已知且接受的性質（防止改善被重複計數）。

### Ablation 清單（各自的主配置，敏感度只呈報）

- **A1 事件日曆降倉**：事件 = FOMC 決議＋美國 CPI 發布（2020-09→2026-06，
  官方日曆整理成 UTC csv 並 commit，spot-check ≥3 筆）。窗 = [T−24h, T+6h]。
  窗內：禁新倉，既有部位 m×0.5。敏感度：只禁新倉不縮舊倉；窗 [T−48h, T+6h]。
- **A2 訊號強度縮放**（= momentum `score_to_position` 思路的 CTA 移植；audit Finding 4
  指出該機制從未被單獨 ablation，歸宿在此）：以進場時 crowd 百分位深度縮放，
  short 側 m = 0.5 + 0.5 × min(1, (pct − 90)/(97 − 90))，long 側鏡像（p10/p3）。
  弱訊號降倉、強訊號封頂 1.0（cap-only，不放大）。敏感度：ramp 上端 p95／p99；下限 0.25。
- **A3 regime 降倉**：BTC 4h close vs 200d SMA（1200 bars，closed-bar shift-1）。
  BTC 在 SMA 上方（risk-on）→ short book m×0.5；下方 → m×1.0。
  依據：短邊優勢是 regime 特有（crowd-ablation 三源印證）。敏感度：SMA 100d／300d；乘數 0.75。

### 每個 ablation 的 gates（全過才併入）

| Gate | 判準 |
|---|---|
| G-A·1 | DSR(d_t；N=該 ablation 的累計試驗數，§2) ≥ 0.95，d_t = r_variant − r_baseline |
| G-A·2 | 6 折中 ≥4 折 ΔMAR ≥ 0 |
| G-A·3 | 成本 ×1.5 下 d_t 的 Sharpe 仍 > 0 |
| G-A·4 | 端點 −30/−60/−90d 下 d_t 的 Sharpe 符號零翻轉 |

**判定語義**：全過 → 併入 baseline，繼續下一個。任一不過 → 該因子收檔（不重試變體），
繼續判定下一個 ablation（單一因子失敗不終止 Stage 2）。

## §5 Stage 3 框架：組合層風控（觸發條件先寫死，細節屆時修正案）

- **觸發條件**：vault 內存在 ≥2 條「驗證過的報酬流」——經 verdict GO、或 forward-test
  存活（≥6 個月真 OOS 且 owner 認可）的 sleeve。在觸發前本節不得執行。
- **框架形狀（先寫死）**：週頻 rebalance（每週一 00:00 UTC）；每週以 trailing 90d 日報酬
  重估 sleeve 波動與相關（Ledoit-Wolf 收縮，`src/hlvault/weights.py` 已有）。
  主案 = risk parity（ERC）；對照案 = fractional Kelly（0.25×，weights.py 已有）；
  baseline = equal-weight。組合層 vol-target 同樣 **cap-only**（只縮 gross 不放大）。
- **Gates 形狀**：同 §4（DSR on difference vs equal-weight ≥ 0.95、folds 多數、成本、端點）。
- **紀律**：sleeves 的實際身分、資料窗、目標波動等細節，必須在跑任何數字**之前**
  以本檔修正案形式 commit（同預註冊紀律）。

## §6 誠實條款

1. **Proxy 極限**：funding ≠ 持倉、volume ≠ OI；overlap 驗證 gate PASS 但量級偏弱
   （`reports/cta_proxy_layer2b_verdict.md:43-60,153-162`）。所有 L 結論繼承此極限。
2. **pseudo-OOS**：§2 folds 的參數未擬合，但資料已被反覆探索。L 的「過」不等於訊號可上實盤；
   訊號生死由 live forward-test 決定。
3. **常數是判斷不是校準**：σ_target=60%、clip 0.25、折數門檻 4/6、非劣性邊際 −0.15
   皆 ex-ante 合理值——模型判斷，信心有限。敏感度組如與主配置方向矛盾，verdict 必須降級敘述。
4. **funding／資金費率 accrual 未建模**（與 phase-2b 同），方向與幅度未知，如實標註。
5. 若任何 gate 結果落在門檻 ±10% 邊緣帶，verdict 不得寫「穩健通過」，必須標註邊緣性。
6. **folds 的已知瑕疵（接受、不修）**：折長不均（F1 約 15.5 個月、F6 僅 6 個月）在
   G-L2 同權投票；F1 前 30 天是 σ warmup（m=1，V1=B0），天然偏向「無差異」；
   非複利固定基底在極端折可產生 |MDD|>100%（layer2b 已記錄 −148% artifact），
   折內比較因兩腿同基底仍有效，但該折的 MAR 絕對值不具尺度意義。

## §7 執行與驗證（驗證不自驗）

1. 每個 config 輸出逐日報酬 csv ＋ trade ledger csv 至 `data/cache/cta_l/`（gitignored、
   可由腳本重生）。
2. gate 腳本是唯一計算來源（B 與 V 同源同基），只從 csv 讀數、不產生新模擬；
   自比測試（variant=baseline）必須得出 ΔSharpe CI 含 0、G-L1 比值 = 1。
3. **fresh-context verifier**：只拿 csv ＋本檔 gate 定義，獨立重算全部 gate；
   與執行者的 gate 表逐格一致才可寫 verdict。
4. **opus 二審**：只看數字表做獨立 GO/NO-GO 判讀；與執行判定不一致時呈 owner，不得自行取捨。
5. Verdict 落 `reports/cta-l-stage{n}-verdict.md`，含端點敏感度全表與 §6 重述。

執行計畫（嚼碎版）：`docs/superpowers/plans/2026-07-13-cta-staged-sizing-plan.md`。
