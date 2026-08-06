# Sub-project M — 諧波形態策略設計

**日期**：2026-08-06
**狀態**：設計已核可，待實作
**基準**：TradingView `Elite Auto Harmonic Patterns Trader [Alex]`（script id `DSk4XN5m`，invite-only）

---

## 0. 一句話

把一支會 repaint、統計表不可信的 TradingView 諧波指標，重建成**零 look-ahead、R-multiple 記帳、預註冊 GO/NO-GO gate** 的可證偽策略，並在 point-in-time 幣種宇宙 × 3 個週期 × 2020–2026 上判定諧波形態是否具備可交易的 edge。

**成功的定義是「得到可信的判定」，不是「得到 GO」。** 證據先驗指向 NO-GO（見 §1.2），NO-GO 是合法且有價值的產出。

---

## 1. 背景

### 1.1 基準腳本的實況

完整分析見 `reports/m-baseline-tv-script-analysis.md`。要點：

- 原始碼**不公開**（invite-only）。它是 **indicator（study）而非 strategy，沒有任何回測**；`pineFeatures` 有 `indicator` 無 `strategy`，`plots=[]`。
- **會 repaint**，四項證據：`historyCalculationMayChange=true`；`ta.pivothigh/pivotlow` 被放在非全域 scope 呼叫（Pine 官方警告會造成歷史值不一致）；同系列基本版有明確的 `Optimize A, B & C Points` 開關；作者在 2025-12-29 release note **自承演算法會回頭改寫已成形態的點位價格與時間戳**。
- 頁面上那張「歷史數據」表**不是回測，是帶 look-ahead 篩選的計次器**：作者自陳 `TP1% + SL% = 100%`（未結案樣本整批丟棄），且自承會事後再剔除一批「D 點過份偏移」的樣本；等權計次而不看風報比——實測 R:R 分佈從 **0.12 到 14.04**。表格是在 `Tolerance = 10`（建議區間最寬那端）下產生的，使用者可以直接轉旋鈕把勝率調高，無任何凍結或樣本外機制。
- 偵測器有**已知且持續存在的 bug**：Elite 版 BTC 4H 292 筆樣本中 Gartley 只有 3 筆（2026-04-12 才「修好」，修完仍是 3 筆）；同系列 Ultimate 版的 Alt Bat `Total = 0` 卻照樣印在表上。
- 同系列三支腳本的**預設掃描域互不相容**（Elite 10–500、Ultimate 1–50、基本版 {2,10,20,40,80}），同一根 K 線會給出不同的形態集合，作者從未說明哪一個才是對的。
- 站外**零獨立聲量**：8,675 views 的付費腳本，中英文搜尋 repaint／scam／心得／論壇討論全部零命中；所有正面訊號都在作者自控通道內。

**它做對的兩件事**（值得繼承）：

1. **多尺度 pivot 掃描**方向正確——單一 ZigZag depth 是多數諧波指標的死穴。
2. **TP/SL 是完全確定性的公式**：給定 XABCD 就唯一決定 entry/SL/TP，零自由裁量。**這讓它可以被嚴格回測，而這正是它自己沒做的事。** 本專案就是去做這件事。

### 1.2 諧波形態的實證證據

完整回顧見 `reports/m-harmonic-evidence-review.md`。要點：

- **沒有任何大樣本同行評審研究測過 harmonic patterns 本身**——是「沒人做過」，不是「做過結果為負」。學術足跡僅兩篇波蘭文論文（Bednarz 2013/2014），其一的樣本是**手挑的 5 筆交易**。網路流傳的「Journal of Technical Analysis 68%」「FxGroundworks 3000 形態 80–90%」**查無原始出處**，僅在賣指標的 vendor blog 之間互抄。
- **但核心成分 Fibonacci 被嚴格證偽**：Tsinaslanidis, Guijarro & Voukelatos (2022, *Expert Systems with Applications* 187:115893)，160 檔藍籌股、1968–2019 共 51 年日線、bootstrap 500 次——價格在 Fib 位反彈機率 DOW 49.08% / DAX 51.89% / NASDAQ 49.84%，**與隨機非-Fib 位統計上無法區分**；Fib 交易規則報酬與隨機位規則無顯著差異；容差 ζ=6% 時隨機位反而顯著更好。
- 同一篇直接量化了容差問題：**放寬容差會單調且顯著地提高「命中率」，但交易績效不論容差寬窄都一樣差**。這是所有高勝率宣稱的製造機制，也意味著**容差是一個純粹的自欺旋鈕**——本設計因此把容差預註冊凍結（§4.4），並把「勝率隨容差上升」列為警訊而非利多。
- **反面證據（誠實列出）**：(a) Osler (2003, *Journal of Finance* 58(5)) 用真實委託單簿證明趨勢確實會在可預測價位反轉——諧波交易者觀察到的**現象不是幻覺，錯的可能是歸因**；(b) Lo, Mamaysky & Wang (2000) 與 Savin, Weller & Zvingelis (2007) 都在大樣本上找到圖形形態的統計資訊增量；(c) 嚴格說，**諧波的直接證據是空集合**——否定推論建立在「成分被證偽 + 複合結構放大自由度」，這是推論不是實測。

**因此本專案的先驗立場**：以「基於成分證偽的高信心負向先驗」進場，用可證偽的框架取得直接證據。verdict 措辭必須區分「已被實測否定」與「基於成分證偽的先驗」。

### 1.3 使用者決策紀錄

使用者在看過上述證據後，明確選擇**把範圍鎖在諧波形態本身**（而非轉向有文獻支持的 swing-failure／liquidity-sweep 路線）。本 spec 遵照該決策。「Fib 是否有增量資訊」降級為專案內的**形態篩選診斷**（決定哪些形態值得留），不另闢策略路線。

---

## 2. 範圍

### 在範圍內

- 諧波形態偵測器（9 種形態，§4.2）與形態事件表
- 事件回測（PRZ 限價進場 + 確認後市價進場兩種模式）
- 匹配隨機對照組
- 預註冊 GO/NO-GO gate 評估（§6）
- verdict 報告

### 不在範圍內

- **實盤引擎與部署**。照 repo 慣例，做到 verdict 為止；GO 之後另開部署討論。
- swing failure / liquidity sweep / 訂單流策略（證據回顧指向的替代路線，本次不做）
- L2 orderbook、清算流、OI、funding 等額外資料源
- Pine Script 版本輸出

---

## 3. 架構

三層，中間以**形態事件表**為唯一介面：

```
資料層              偵測器            事件表 (parquet)         回測層           統計層
────────           ────────          ─────────────────        ────────         ────────
PIT 幣種宇宙   →   多尺度 pivot   →   一列 = 一個形態      →   PRZ 掛單     →   bootstrap
Binance K 線       XABCD 候選         含 as_of 時間戳          出場模擬         對照組檢定
                   Fib 約束過濾       含 PRZ/SL/TP             R-multiple       DSR / gate
                   去重                     ↑
                                    唯一介面，可反覆切片
```

### 3.1 為什麼是這個架構

1. **`as_of` 是一個欄位，不是一個慣例。** look-ahead 因此變成可以寫斷言的東西（§8 的 mutation test），而不是靠實作者自律。原版的 repaint 就是因為沒有這條線。這對應全域工程原則第 5 條的精神：**把正確性做成結構性的，不是記憶性的**。
2. **消融實驗幾乎免費。** 同一張事件表可以反覆切片問「只留容差 ≤3% 的」「只留 D 超出 X 的」「把 Fib 約束換成隨機門檻」，不必重跑偵測。這是決定哪些形態該留該砍的工具。
3. **可以先不談交易就回答有沒有 edge。** 直接做 event study：形態確認後 N 根的報酬分布 vs 匹配隨機時點的報酬分布。這一問不受出場規則影響，是最乾淨的證據。

（已考慮並否決的替代方案：傳統 bar-by-bar 回測——消融要全部重跑、look-ahead 只能靠自律、統計檢定難做；套用 vectorbt／backtesting.py——形態偵測本來就得自己寫、框架幫不上忙，還把時序控制權交給黑盒。）

### 3.2 事件表 schema

`data/cache/harmonic_m/events_{interval}.parquet`，一列一個形態實例：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `event_id` | str | `{symbol}_{interval}_{L}_{idx_C}_{pattern}` |
| `symbol` | str | Binance USDT 永續 symbol |
| `interval` | str | `15m` / `1h` / `4h` |
| `pattern` | str | 形態名（§4.2） |
| `direction` | int | `+1` = bullish（做多）／`-1` = bearish（做空） |
| `pivot_length` | int | 偵測到它的 pivot 尺度 L |
| `t_X,t_A,t_B,t_C` | int64 | 四點的 bar 開盤時間（ms） |
| `p_X,p_A,p_B,p_C` | float | 四點價格 |
| `as_of` | int64 | **本形態在真實時間軸上最早可知的時刻**（= C 的 pivot 確認收盤時間） |
| `ratio_ab_xa`,`ratio_bc_ab` | float | as_of 前即可算的兩個實際比例（診斷用） |
| `prz_low`,`prz_high` | float | 潛在反轉區（§4.3） |
| `sl_planned` | float | 以 PRZ 觸發邊界當 D 推導的止損（§4.5） |
| `tp1_planned`,`tp2_planned` | float | 同上推導的目標 |
| `dedup_merged` | int | 去重時被本列吸收掉的重複事件數（§4.6） |
| `tol_used` | float | 產生本列所用的容差 |

回測層輸出獨立的 trades 表，不回寫事件表。

---

## 4. 偵測器規格

### 4.1 Pivot 與 `as_of`

- 給定 pivot length `L`：bar `i` 是 **pivot high** ⟺ `high[i] == max(high[i-L .. i+L])`；平手時取最早的 `i`。pivot low 對稱。
- **確認時間** `t_confirm(i) = close_time(i + L)`。這是該 pivot 最早可被知道的時刻。
- **多尺度**：`L ∈ {5, 10, 20, 40}`（預註冊）。每個 L 各自產生獨立的 pivot 序列。
  - 不採用原版的 10–500 連掃，兩個理由：(a) 相鄰 L 產生的 pivot 高度重疊，連掃主要是製造重複偵測而非增加資訊；(b) 試驗數必須可控且可宣告（§6 的 DSR 需要 `N_TRIALS_DECLARED`）。
- **形態候選**：在**單一 L 的 pivot 序列中取連續交替的四個 pivot** `X → A → B → C`。bullish 為 `low, high, low, high`；bearish 相反。「連續」= 在該序列中相鄰，**不允許跳過 pivot**。
  - 這條約束是刻意的：原版的 `Optimize A, B & C Points` 開關暗示它會挑選最合適的點位，那正是 look-ahead 的來源。禁止跳點使候選集合由資料唯一決定。
- **`as_of` = `t_confirm(idx_C)`**。形態的全部欄位只能由 `close_time <= as_of` 的 K 線算出。

### 4.2 形態的 Fibonacci 比例定義

> 本節數值於實作時凍結於 `scripts/m_config.py` 的 `HARMONIC_RATIOS` / `CYPHER_RATIOS`，跑任何回測前不得修改。查證過程、來源 URL 與分歧分析見 [`scripts/m_pattern_ratios_research.md`](../../../scripts/m_pattern_ratios_research.md)（9 種形態全部取得 ≥2 個獨立來源）。

**計算約定**（一律用線段長度絕對值，不帶方向符號）：

```
XA=|A−X|   AB=|A−B|   BC=|C−B|   CD=|C−D|   AD=|A−D|   XC=|C−X|

AB/XA   B 對 XA 段的回撤
BC/AB   C 對 AB 段的回撤
CD/BC   D 對 BC 段的延伸（Carney 稱 "BC projection"）
AD/XA   D 對 XA 段的回撤(<1)或延伸(>1)  ← 各形態的識別鍵
```

> **術語陷阱**：Carney 原文的「a 1.618 BC projection」指 `CD/BC = 1.618`，**不是** `BC/AB`。這是最常見的一階誤讀，本表已全部正規化到上述四個符號。

### 主表（8 種走統一四比例）

| 形態 | AB/XA | BC/AB | CD/BC | **AD/XA**（識別鍵） | 交叉驗證 |
|---|---|---|---|---|---|
| Gartley | 0.618 | 0.382–0.886 | 1.13–1.618 | **0.786** | 4 源 |
| Bat | 0.382–0.50 | 0.382–0.886 | 1.618–2.618 | **0.886** | 4 源 |
| Alternate Bat | 0.382 | 0.382–0.886 | 2.0–3.618 | **1.13** | 2 源 |
| Butterfly | 0.786 | 0.382–0.886 | 1.618–2.618 | **1.27** | 4 源 |
| Crab | 0.382–0.618 | 0.382–0.886 | 2.24–3.618 | **1.618** | 4 源 |
| Deep Crab | 0.886 | 0.382–0.886 | 2.24–3.618 | **1.618** | 3 源 |
| Shark | *無此約束* | 1.13–1.618 | 1.618–2.24 | **0.886–1.13** | 5 源 |
| 5-0 | 1.13–1.618 | 1.618–2.24 | **0.50** | *無此約束* | 3 源 |

### Cypher 走自己的基準（塞進上表必錯）

| 約束 | 值 |
|---|---|
| AB/XA | 0.382–0.618 |
| **XC/XA** | **1.272–1.414** — C 相對 **XA** 段，自 X 起算 |
| **CD/XC** | **0.786** — D 相對 **XC** 段 |

Cypher 的等效 `AD/XA` 是**推導值 0.697–0.728**，**不是**通說的 0.786。

**此點取得獨立交叉驗證（2026-08-06 主對話親跑）**：原版腳本洩漏的 Cypher 樣本實測 `XC/XA = 1.234`、`CD/XC = 0.7763`、`AD/XA = 0.724`。代入恆等式

```
AD/XA = 1 − (XC/XA)·(1 − CD/XC)
      = 1 − 1.234 × (1 − 0.7763) = 0.72395     （洩漏值 0.724，吻合）
```

且 0.724 落在標準定義推得的區間 `[0.6974, 0.7278]` 內，通說的 0.786 落在區間外。**兩條互相獨立的證據鏈——文獻查證與原版腳本的實際輸出——一致指向 Cypher 的基準是 XC 而非 XA。** 這也意味著市面上以 `AD/XA = 0.786` 實作 Cypher 的指標（研究指出兩大開源實作皆如此）測的根本不是 Cypher。

### Shark 與 5-0 的點位映射

兩者原文使用 `0-X-A-B-C` 命名，映射方式**不同**（研究 §3.1）：

- **Shark**：整體右移一位（`0→X, X→A, A→B, B→C, C→D`）。於是 Carney 的「AB 是 XA 的 1.13–1.618」變成本表的 `BC/AB`，「C 是 0X 的 0.886–1.13」變成本表的 `AD/XA`。
- **5-0**：原文是 6 點（`0,X,A,B,C,D`），**直接丟棄最前面的 `0` 點**、其餘不移位。代價是原文「C 對 0X = 0.886–1.13」這條約束在 5 點偵測器裡**無法表達**——列為已知限制（§10）。

### 本專案對研究待決項的裁決

| 待決項 | 裁決 | 理由 |
|---|---|---|
| Cypher 是否納入 | **納入**，獨立記帳、verdict 分開列 | 兩條證據鏈已釐清其真實基準；且它正是「市面說法建立在錯誤比例上」的最佳案例 |
| Butterfly `AD/XA` 取 1.27 或 1.27＋1.618 兩變體 | **只取 1.27** | 1.618 變體與 Crab 的識別鍵重疊；砍掉可少一個自由度與一整組試驗 |
| Shark 是否加 `AB/XA` 約束 | **不加**（`None`） | 三個來源說法互斥；形態已由 `BC/AB` 與 `AD/XA` 唯一界定 |
| 是否採用原版的 Shark TP 例外（0.5／0.886） | **不採用**，全形態統一 `(0.382, 0.618)` | 該例外僅 n=1、無絕對價格、且與樣本自身標籤互相矛盾（§6 M-G0）。刪除同時減少一個自由參數。**此為對基準的刻意偏離，verdict 必須註明** |

**形態集合 = 9 種**：Gartley、Bat、Alternate Bat、Butterfly、Crab、Deep Crab、Shark、Cypher、5-0。

**形態互斥性已由研究實跑驗證**：走統一四欄的 8 種形態、28 組 pairwise，在 `ε = 0.02 / 0.03 / 0.05` 三個容差下**四軸全重疊的配對數皆為 0**，因此偵測器不需定義形態優先序。（Cypher 未納入該檢定，因其不走這四欄；實作時須另行驗證 Cypher 與其餘 8 種互斥，列為實作階段的驗收項。）

實測附帶印證：Gartley 與 Crab 的 `AB/XA` 確實重疊（0.587–0.618），兩者**全靠 `AD/XA` 分開**——這佐證了下一段的判別鍵設計。

**判別鍵的結構性事實**（研究 §5，agent 自跑驗證）：`CD/BC` 在數學上幾乎被其他三條比例決定（教科書的「條件式 CD/BC」其實是同一套定義的另一種寫法），真正的自由度只有三個。因此實作採取：**`AD/XA` 為主判別鍵**（容差收緊，§4.4），`CD/BC` 設寬區間僅作 sanity check。這降低了有效自由度，直接對應本專案的抗過擬合目標。

### 4.3 PRZ（潛在反轉區）計算

以 bullish 為例（`X` 低、`A` 高、`B` 低、`C` 高，預期 `D` 為低點）：

```
XA = p_A - p_X   (> 0)
AB = p_A - p_B   (> 0)
BC = p_C - p_B   (> 0)
```

**as_of 前即可檢驗的過濾條件**（只涉及 X/A/B/C，不涉及 D）：

```
AB/XA ∈ tol_band(pattern.ab_xa)      # 若該形態此欄為 None（Shark）則跳過本條
BC/AB ∈ tol_band(pattern.bc_ab)
Cypher 額外： XC/XA ∈ [1.272, 1.414]  # 只涉及 X 與 C，故屬過濾條件而非 PRZ 約束
```

**定義 PRZ 的約束**（涉及 D，故產出區間而非單點）：

```
由 AD/XA ∈ [ad_lo, ad_hi]  →  D ∈ [p_A − ad_hi·XA , p_A − ad_lo·XA]
由 CD/BC ∈ [cd_lo, cd_hi]  →  D ∈ [p_C − cd_hi·BC , p_C − cd_lo·BC]

PRZ = 上述區間的交集
```

**缺約束的處理**（形態集合中實際存在的三種情況）：

| 情況 | 形態 | PRZ 由誰決定 |
|---|---|---|
| `AD/XA` 為 `None` | 5-0 | 僅由 `CD/BC` 決定 |
| `CD/BC` 為 `None`／寬區間 | Shark、Cypher | 主要由 `AD/XA`（Cypher 為 `CD/XC`）決定 |
| Cypher（自有基準） | Cypher | `D ∈ tol_band(0.786)·XC` 自 C 起算，即 `D ∈ [p_C − 0.786(1+τ)·XC , p_C − 0.786(1−τ)·XC]` |

`AD/XA` 與 `CD/BC` **同時**為 `None` 的形態不存在於本集合；實作須以斷言強制此前提。

**若交集為空 → 候選作廢，不產生事件。** 空交集比例須逐形態統計並寫進 verdict——比例異常高代表比例表內部不自洽。

bearish 為價格方向鏡射。

**這個設計是無 look-ahead 的關鍵**：PRZ 是在 C 確認時**預測**出來的價格區間，不是事後認出的 D 點。原版是後者。

### 4.4 容差

採用研究 §7 的業界主流慣例——**只對單點目標加對稱百分比帶，區間型約束不另加容差**（區間本身已是容差）：

```
單點目標 v      → [v·(1−τ) , v·(1+τ)]
區間目標 [lo,hi] → 原樣使用，不展開
```

**兩級容差（預註冊）**：

| 參數 | 值 | 適用 |
|---|---|---|
| `TOL` | **0.05** | `AB/XA`、`BC/AB`、`CD/BC` 的單點目標 |
| `TOL_AD_XA` | **0.03** | `AD/XA`（及 Cypher 的 `CD/XC`）——**主判別鍵，收緊** |

判別鍵收緊的理由見 §4.2 末段：`CD/BC` 幾乎被其他三條決定，真自由度只有三個，故把精度預算集中在唯一能區分形態的那一條。

- 敏感度分析跑 `TOL ∈ {0.03, 0.05, 0.08, 0.10}`（`TOL_AD_XA` 同步取 `0.6 × TOL`，維持兩者比例固定，避免二維搜尋擴大試驗數），**作為穩健性檢查，不作為最佳化旋鈕**。
- **判讀規則（預註冊）**：看的是 `E[R_net]` 對 TOL 的曲線，**不是勝率**。依 Tsinaslanidis et al. (2022)，放寬容差必然拉高勝率而不改善績效——因此「勝率隨 TOL 單調上升而 `E[R_net]` 未上升」應被判讀為**證偽訊號**，不是調參空間。

### 4.5 進場、止損、目標

沿用從原版逆向工程出的確定性公式（6 個洩漏樣本吻合到小數 4 位，見 §6 的 M-G0）。

**掛單與成交**（bullish；bearish 鏡射）：

自 `as_of` 之後第一根 bar 起，於 `prz_high` 掛限價買單，TTL = `TTL_BARS` 根（預註冊 30）。逐根判定：

```
若 bar.open <= prz_high:                      # 跳空進入或穿越 PRZ
    若 bar.open <= sl_planned: 標記 invalidated_by_gap，不進場，事件終結
    否則: fill = bar.open
否則若 bar.low <= prz_high:                    # 盤中觸及
    fill = prz_high
否則: TTL 遞減，繼續等待

TTL 耗盡仍未成交 → 標記 no_fill，事件終結
```

**止損**：`D = fill`

```
ad_ratio = (p_A - D) / (p_A - p_X)
S = [1.0, 1.13, 1.272, 1.618, 2.0]                     # 逆向工程所得檔位序列
r_sl = min{ s ∈ S : s > ad_ratio }
若 ad_ratio >= 2.0 → r_sl = ad_ratio * 1.1             # 預註冊 fallback
sl = p_A - r_sl * (p_A - p_X)
```

**目標**：

```
extreme = max(p_X, p_A, p_B, p_C)                      # bullish；bearish 取 min
leg     = extreme - D
tp1 = D + 0.382 * leg
tp2 = D + 0.618 * leg
```

**全形態統一用 `(0.382, 0.618)`，不採用原版的 Shark 例外 `(0.5, 0.886)`**——該例外僅有 n=1 樣本、無絕對價格、且與樣本自身標籤矛盾（§6 M-G0）。刪除它同時少掉一個自由參數。此為對基準的刻意偏離，verdict 必須註明。

**出場**（棒內優先序，悲觀）：`SL → TP → time-stop`，沿用 [`scripts/scalp_backtest_lib.py:39`](../../../scripts/scalp_backtest_lib.py) `simulate()` 既有契約（訊號收盤決定、下一棒開盤成交、gap-through 取較差價）。

- **主設定**：TP1 全出，單一目標。理由：自由度最低；且原版自己承認 Shark 必須 TP1 全平。
- **次要變體**：TP1 出 50%／TP2 出 50%，TP1 觸及後 SL 移至成本。計入試驗數。
- **time-stop**：`MAX_HOLD_BARS = 100`（預註冊）。

**每個事件都必須有終局**，六種之一：`tp1` / `tp2` / `sl` / `time_stop` / `no_fill` / `invalidated_by_gap`；資料截止時仍在倉者標 `censored` 並**納入**分析。**不得丟棄任何樣本**——這正是原版 `TP1% + SL% = 100%` 的造假機制。

### 4.6 多尺度去重

同一個形態會被多個 `L` 重複偵測（原版快照中同一個 Bat 被印了 4 次，重複計數會直接汙染統計）。

去重規則：兩個事件屬於同一形態 ⟺ `symbol`、`interval`、`pattern`、`direction` 相同，**且** `t_X, t_A, t_B, t_C` 四個時間戳中至少 3 個相同。同組保留 `as_of` 最早者（即 `L` 最小者），其餘計入該列的 `dedup_merged`。

去重在事件表層做，先於任何統計。去重前後的事件數都必須寫進 verdict。

---

## 5. 回測與記帳

### 5.1 兩種進場模式

| 模式 | 說明 | 成本 |
|---|---|---|
| **A：PRZ 限價（主）** | §4.5 的掛單模型。對應諧波交易者實際做法 | 進場 maker，出場 taker |
| **B：確認後市價** | 等 D 點自身的 pivot 確認後以下一根開盤市價進場 | 兩腿皆 taker |

**模式 B 的 D 點認定**（避免歧義）：在同一個 `L` 的 pivot 序列中，取 `C` 之後**第一個**方向正確（bullish 取 pivot low）且價格落在 `[prz_low, prz_high]` 內的 pivot。進場時刻 = `t_confirm(idx_D) = close_time(idx_D + L)`，成交於其後第一根 bar 的開盤。若 TTL 內不存在這樣的 pivot → `no_fill`。**不允許在候選中挑選最合適的 D**——那正是原版 `Optimize A, B & C Points` 的 look-ahead 來源。

模式 B 是誠實但劣化的對照：D 確認要再等 `L` 根，價格早已跑掉。**兩者的差距本身就是有價值的發現**，且模式 B 完全不依賴 PRZ 預測正確性。

### 5.2 成本（沿用 repo 既有慣例，不自編）

```
taker = 0.00045   # 4.5 bps/side   — scripts/scalp_fee_check.py:18, data/scalp/fees.json
maker = 0.00015   # 1.5 bps/side   — scripts/scalp_fee_check.py:19
slip  = 0.0001    # 1 bp/side，僅在 taker 腿支付 — scripts/cta_l_stage1.py:68
壓力情境：fee ×1.5、slip ×1.5（scripts/cta_l_stage1_runs.py:57-60 慣例）
```

### 5.3 R-multiple（主記帳單位）

```
R_gross = direction · (P_exit − P_entry) / |P_entry − P_SL|
cost_R  = (fee_in + fee_out + slip_in + slip_out) · P_entry / |P_entry − P_SL|
R_net   = R_gross − cost_R
```

**數值錨例（必須通過的單元測試）**：bullish，`P_entry = 100`、`P_SL = 98`、`P_exit = 103`，模式 A（maker 進場 1.5bps、taker 出場 4.5bps、滑價 1bp 僅出場腿）：

```
R_gross = (103 − 100) / 2 = 1.5
cost_R  = (0.00015 + 0.00045 + 0.0001) · 100 / 2 = 0.07 / 2 = 0.035
R_net   = 1.465
```

`no_fill` 與 `invalidated_by_gap` 事件記 `R_net = 0` 且**計入分母**。理由：一個大部分時候不成交的形態，其實際可交易期望值本就該被稀釋。

**兩個指標都要報**：`E[R_net]`（無條件，未成交記 0——**gate 用這個**）與 `E[R_net | filled]`（條件，診斷用）。勝率只是附註，不是判準。

### 5.4 匹配隨機對照組

對每個真實事件 `e`，生成 `K = 5` 個對照事件：

- 同 `symbol`、同 `interval`、同 `direction`
- `as_of' = as_of + δ`，`δ` 自 `{−90..−31} ∪ {31..90}` 根 bar 均勻抽樣（`|δ| > TTL_BARS = 30`，避免與原事件的掛單窗重疊）。若平移後的窗口超出該 symbol 的資料範圍則重抽，最多 10 次；仍失敗則該對照樣本捨棄並計數（捨棄數須寫進 verdict）
- 進場觸發價、SL、TP 全部按**相對距離**平移：以 `close(as_of')` 為錨，保持 `prz_high / close(as_of)`、`sl / close(as_of)`、`tp / close(as_of)` 三個比值不變
- TTL、成交規則、出場優先序、成本、記帳全部相同

除了「進場位置不是諧波 PRZ」之外一切相同。隨機種子 `SEED = 20260806` 寫死於 `scripts/m_config.py`。

---

## 6. 預註冊 GO/NO-GO gate

> 本節在跑任何回測**之前**凍結。所有門檻寫成顯式方程式並附可機器驗證的數值錨例——2026-07-13 的 L 案事故（MDD 分母兩種合法讀法使同一份結果 PASS/FAIL 相反，劣定義活過四道審查）就是散文式定義造成的。

### 前置條件（不過 = 實作有 bug，不是策略結論）

- **M-G0（基準忠實度）**：以 `tests/fixtures/m_tv_baseline_samples.json` 的洩漏樣本檢定 §4.5 的 SL/TP 公式。

  **fixture 實況**（2026-08-06 主對話親自驗算）：6 個樣本中僅 2 個有完整 XABCD 絕對價格，且**沒有任何樣本印出絕對 SL/TP 值**——來源報告只給公式。因此不能用「重算 SL/TP 與 `expected` 比對」：那些欄位全為 `null`，且用公式回推填值等於自己驗自己。

  改用**尺度不變的風報比錨點**——R:R 只依賴比例，不依賴絕對價格：

  ```
  以 XA 為單位：
    risk = |sl_level_over_xa − ad_xa|
    leg  = |extreme − D|        # extreme = max(X,A,B,C) if bullish else min(...)
    RR1  = f1 · leg / risk ,  RR2 = f2 · leg / risk
    (f1, f2) = (0.382, 0.618)
  ```

  註：此處檢定的是**原版逆向工程出的公式**。本專案的實作刻意不採用原版的 Shark 例外 `(0.5, 0.886)`（§4.2、§4.5），故 Shark 樣本在任一組係數下都不吻合。

  **判準**：**5 個非 Shark 樣本全數**滿足 `|RR_calc − RR_leaked| < 0.01`（即 5/5）；2 個有座標的樣本另需 `|risk%_calc − risk%_leaked| < 0.01` 且 `|ad_xa_calc − ad_xa_leaked| < 0.002`。`base_shark113_bearish` **已知不符、排除於判準之外**，理由記錄於下方；不得為了讓它通過而引入額外參數。

  **基線已驗證通過（5/5，Shark 排除）**：

  | 樣本 | extreme | RR1 算／洩漏 | RR2 算／洩漏 | 結果 |
  |---|---|---|---|---|
  | `elite_cypher_bullish` | C | 1.3259 / 1.33 | 2.1451 / 2.14 | PASS |
  | `elite_deep_crab_bearish` | A | 1.1772 / 1.18 | 1.9044 / 1.91 | PASS |
  | `base_bat_bullish` | A | 1.4786 / 1.48 | — | PASS |
  | `base_deep_crab_bearish` | A | **14.0331 / 14.04** | — | PASS |
  | `ultimate_butterfly_bullish` | A | 1.3941 / 1.39 | 2.2553 / 2.26 | PASS |
  | `base_shark113_bearish` | ? | 1.6559 / 2.26 | — | **FAIL** |

  有座標樣本的絕對驗算亦通過：cypher `ad_xa` 0.7239/0.724、`risk%` 0.8559/0.86；deep crab `ad_xa` 1.5103/1.51、`risk%` 2.6153/2.62。

  `base_deep_crab_bearish` 的 **RR1 = 14.04** 是最鋒利的單一錨點——D 落在 1.947 XA 而 SL 檔位固定在 2.000 XA，止損距離趨近零使 RR 爆炸。忠實重建必須重現這個退化值；重現不了代表 SL 檔位邏輯抄錯。

  **Shark 的狀態（已知未解）**：`base_shark113_bearish` 的 `ad_xa = 0.977` 與它自己的標籤「Shark 113」（D 在 1.13 XA）互相矛盾，證實 Shark 使用 0-X-A-B-C 命名、其 `ad_xa` 量的不是同一段。該形態的 TP 例外公式（0.5/0.886）僅有 **n = 1** 樣本且無絕對價格支撐，是整套逆向工程證據最弱的一環。處置見 §4.2。

  M-G0 不過（5 個非 Shark 樣本有任一不符）→ 公式逆向工程有誤，作廢重來。
- **M-G1（無前視）**：`tests/test_m_nolookahead.py` 全綠。核心斷言為 **mutation test**：把每個事件 `as_of` 之後的所有 K 線改成 `NaN`，重跑偵測，事件表必須**逐欄位完全相同**。

### 判定 gate

| ID | 判準（方程式） | 說明 |
|---|---|---|
| **M-G2** 絕對期望 | `lower_95(bootstrap_{B=10000}(mean(R_net))) > 0` | stationary bootstrap，`expected_block` = 平均持有 bar 數 |
| **M-G3** 優於隨機 | `lower_95(bootstrap_{B=10000}(mean(R_net^pattern) − mean(R_net^control))) > 0` | 配對；對照組定義見 §5.4。**這是核心判準——不是跟 0 比，是跟隨機比** |
| **M-G4** 試驗數校正 | `deflated_sharpe(trial_sharpes, primary_returns, N_TRIALS_DECLARED) > 0` 且 `p < 0.05` | `N_TRIALS_DECLARED` 事前寫死於 `scripts/m_config.py`；沿用 [`scripts/k_gates_eval.py:90`](../../../scripts/k_gates_eval.py) |
| **M-G5** 時間樣本外 | in-sample 做完全部選擇後，OOS 上 M-G2 仍成立 | IS `2020-01-01T00:00:00Z ~ 2023-12-31T23:59:59Z`；OOS `2024-01-01T00:00:00Z ~ 2026-06-30T23:59:59Z`。**OOS 只跑一次** |
| **M-G6** 幣種樣本外 | 幣依 `int(sha256(symbol).hexdigest(), 16) % 2` 分兩半，`0` 半做全部選擇，`1` 半驗證，M-G2 在 `1` 半仍成立 | 防止選擇被少數幣主導 |
| **M-G7** 成本壓力 | fee ×1.5、slip ×1.5 後 M-G2 仍成立 | 沿用 CTA 慣例 |

### M-G4 的輸入定義（避免歧義）

`deflated_sharpe` 吃的是報酬序列而非 R 序列，故須明確定義轉換：

- **每筆風險正規化**：每筆交易固定承擔權益的 **1%**（`RISK_PER_TRADE = 0.01`）。於是單筆權益報酬 = `R_net × 0.01`。
- **日報酬序列**：`r_d = 0.01 × Σ{ R_net(e) : e 的出場日 = d }`；當日無出場者 `r_d = 0`。序列涵蓋該設定第一筆進場日至最後一筆出場日。
- **年化因子 `ANN = 365`**（加密貨幣 24/7）。**不得直接沿用 [`src/hlvault/metrics.py:9`](../../../src/hlvault/metrics.py) 的 `ANN = 252`**——那是股票交易日慣例，混用會讓 Sharpe 系統性偏低約 17%。此為刻意偏離，須在 verdict 註明。
- **`primary_returns`** = 主設定（§4.4 的 `TOL = 0.05`、模式 A、TP1 全出、全形態合併）的日報酬序列。
- **`trial_sharpes`** = 每個設定各自的年化 Sharpe 所構成的集合。
- **`N_TRIALS_DECLARED = 432`**，由 §4.2 定案的設定空間唯一決定：

  ```
  |patterns| × |TOL| × |intervals| × |entry_modes| × |exit_variants|
      9      ×    4   ×      3      ×       2       ×       2        = 432
  ```

  （9 種形態、`TOL ∈ {0.03,0.05,0.08,0.10}`、`{15m,1h,4h}`、進場模式 A/B、TP1 全出／分批兩種出場變體。）**事後新增任何設定都必須重新宣告並重跑 M-G4**——這正是原版讓使用者自由轉旋鈕卻不計代價的地方。

### 判定表

| 結果 | verdict |
|---|---|
| M-G2 ~ M-G7 全過 | **GO** |
| M-G2 過、**M-G3 不過** | **NO-GO** — 形態不優於隨機進場。這正是 Tsinaslanidis et al. (2022) 對 Fib 成分的預測 |
| M-G2、M-G3 過，M-G5 或 M-G6 不過 | **NO-GO（過擬合）** |
| M-G2 不過 | **NO-GO** |
| M-G0 或 M-G1 不過 | 非結論——修 bug 後重跑 |

### 硬性規定

- **回測窗口硬編時間戳**於 `scripts/m_config.py`，**禁止**「從今天回推 N 天」（2026-07-12 momentum 教訓：端點差 9 天使兩年 Sharpe 從 0.57 掉到 0.18）。
- GO 級結論前追加**端點 ±7 天敏感度**；端點一移就翻盤的結果視為厚尾雜訊，不是 edge。
- 容差、比例表、pivot 尺度、TTL、MAX_HOLD、seed、`N_TRIALS_DECLARED` 全部在**第一次跑回測之前**凍結。任何事後修改必須在 verdict 中明確揭露並重新計算 `N_TRIALS_DECLARED`。

---

## 7. 資料層

### 7.1 幣種宇宙：point-in-time 季度輪換

沿用 [`scripts/k_data_layer.py:157`](../../../scripts/k_data_layer.py) `build_pit_universe()` 的邏輯。

**必要性**：直接取「今天還活著且流動性好的幣」跑 2020–2026 會吃到嚴重**倖存者偏誤**——死掉、下市、流動性枯竭的幣被自動排除。PIT 宇宙只用每季開始**之前**的資料決定當季幣單。

**門檻（預註冊）**：trailing 90 日中位 quote volume ≥ **$50M** 且上市 ≥ **180 天**，每季取 top **30**。
（K 案用 $100M / top 8；本專案放寬是為了樣本數——諧波形態在單幣單週期上稀少。此為預註冊選擇，非事後調整。）

流動性以 **quote volume（USDT 名目）** 計，非幣本位 volume——見 [`scripts/k_data_layer.py:53`](../../../scripts/k_data_layer.py) `binance_rows_to_df_qv()` 的踩坑註記。

### 7.2 K 線資料

- 來源：**Binance USDT 永續**（HL candleSnapshot 每 interval 僅保留最近 ~5000 根，1h ≈ 208 天，拿不到 2020 年）
- interval：`15m` / `1h` / `4h`
- 窗口：`2020-01-01T00:00:00Z ~ 2026-06-30T23:59:59Z`
- 抓取：沿用 [`scripts/cta_proxy_pull_data.py:79`](../../../scripts/cta_proxy_pull_data.py) `pull_klines(symbol, interval)`（interval 已參數化，1500 根/頁，含無限迴圈防護）
- 幣名映射：[`scripts/scalp_lib.py:121-127`](../../../scripts/scalp_lib.py) `binance_perp_symbols()` / `binance_symbol()`，含 `kPEPE → 1000PEPEUSDT` 等 override 表
- 快取：`data/cache/harmonic_m/{SYMBOL}_{interval}.parquet`（`data/cache/` 已在 `.gitignore`）
- HL 的角色：僅用 [`scripts/scalp_lib.py:77`](../../../scripts/scalp_lib.py) `universe_ctxs()` 界定「HL 實際可交易」，以及保真度交叉驗證

---

## 8. 測試策略

全部**離線、零網路**（全域工程原則第 4 條）。沿用 [`tests/test_scalp_backtest.py`](../../../tests/test_scalp_backtest.py) 的 `sys.path.insert(0, "scripts")` + 合成 bar 慣例。

| 測試檔 | 驗什麼 |
|---|---|
| `tests/test_m_patterns.py` | 手工構造一個比例完美的 Gartley → 必須被偵測；把 `AD/XA` 偏離 20% → 必須不被偵測；構造 PRZ 交集為空的候選 → 必須作廢 |
| `tests/test_m_nolookahead.py` | **M-G1 的 mutation test**：`as_of` 之後 K 線全填 NaN，事件表逐欄位不變 |
| `tests/test_m_baseline_formula.py` | **M-G0**：fixture 樣本的 SL/TP 重算吻合到小數 4 位 |
| `tests/test_m_rmultiple.py` | §5.3 數值錨例：`entry=100, SL=98, exit=103` → `R_net == 1.465`（絕對誤差 < 1e-9）；`no_fill` 事件 `R_net == 0` 且計入分母 |
| `tests/test_m_dedup.py` | 同形態 4 個 `L` 的重複事件 → 去重後剩 1 列且 `dedup_merged == 3` |

---

## 9. 交付物

| 檔案 | 內容 |
|---|---|
| `scripts/m_config.py` | **全部凍結參數**：比例表、TOL、pivot 尺度、TTL、MAX_HOLD、時間窗、成本、SEED、`N_TRIALS_DECLARED` |
| `scripts/m_data.py` | PIT 宇宙 + K 線抓取與快取 |
| `scripts/m_detect.py` | 偵測器 → 事件表 |
| `scripts/m_backtest.py` | 事件表 → trades → R-multiple |
| `scripts/m_control.py` | 匹配隨機對照組 |
| `scripts/m_gates.py` | M-G0 ~ M-G7 評估與判定表輸出 |
| `tests/test_m_*.py` | §8 五個測試檔 |
| `reports/harmonic-m-verdict.md` | 最終判定 |
| `reports/m-baseline-tv-script-analysis.md` | 原版分析（已落檔） |
| `reports/m-harmonic-evidence-review.md` | 證據回顧（已落檔） |
| `scripts/m_pattern_ratios_research.md` | 比例表查證來源（已落檔） |
| `tests/fixtures/m_tv_baseline_samples.json` | M-G0 的原版樣本 fixture（已落檔） |

---

## 10. 風險與已知限制

**必須寫進 verdict 的限制**：

1. **先驗為負**。證據回顧指向 NO-GO。成功定義是取得可信判定，不是取得 GO。verdict 措辭須區分「已被實測否定」與「基於成分證偽的先驗」。
2. **Binance proxy 保真度未實測**。CLAUDE.md 記載 HL/Binance **1m** 波幅保真比 0.7–0.9、小幣更低，對訊號幅度是樂觀偏差。15m/1h/4h 的保真度應更高但**本專案未實測**——列為限制，verdict 必須標註。
3. **PIT 宇宙以 Binance 資料定義**，與 HL 實際可交易幣種不完全重合；GO 情境下部署前須重新對齊。
4. **TP/SL 公式來自對閉源腳本的逆向工程**，非官方文件。錨點強度已量化（§6 M-G0）：6 個洩漏樣本中 **5 個非 Shark 樣本全數**在尺度不變的 R:R 檢定上吻合（含 RR=14.04 的退化案例），其中 **2 個**另有絕對價格可驗 `risk%` 與 `ad_xa`。**Shark 不吻合、點位命名未解，且本專案刻意不採用其例外公式**。verdict 必須照實引用「5/5 非 Shark 樣本 + Shark 排除」，不得宣稱「完全複製原版」。
5. **比例表本身是假設，不是事實**。§4.2 的數值即使有多來源交叉驗證，仍可能與原版腳本實際使用的比例不同（原版頁面完全沒有出現任何 Fibonacci 數字）。因此本專案測的是**教科書定義的諧波形態**，不是「原版腳本的複製品」——verdict 不得宣稱「已證明原腳本無效」，只能宣稱「已證明標準定義的諧波形態在本測試條件下無效／有效」。
6. **形態稀少性**。若去重後某些形態在 OOS 上樣本數 < 30，該形態的個別結論不成立，只能併入總體判定；verdict 必須逐形態列出樣本數。
7. **一級來源未取得**。Carney 的《Harmonic Trading》Vol. 1–3 原文未取得；Shark 與 5-0 的完整比例是靠 3–5 個二級來源交叉確認，非一級來源直證。若日後取得原文而比例有出入，本專案的 Shark／5-0 結論須重跑。
8. **5-0 的偵測比原文寬鬆**。原文的「C 對 0X = 0.886–1.13」約束在 5 點偵測器中無法表達（§4.2 映射說明），故 5-0 會納入部分原文不認可的樣本。這是**偏向多納入**的偏差，對 NO-GO 結論無害，對 GO 結論則須加註。
9. **Cypher 的互斥性未檢定**。研究實跑的 28 組 pairwise 互斥檢定只涵蓋走統一四欄的 8 種形態；Cypher 因基準不同未納入。實作階段必須補測 Cypher 與其餘 8 種的互斥性，未通過則需定義形態優先序並揭露。

---

## 附錄：與原版的逐項對照

| 原版缺陷 | 本設計 | 對應章節 |
|---|---|---|
| repaint：D 成形後回頭改寫點位 | 前瞻式 PRZ 掛單；`as_of` 欄位 + mutation test 強制 | §4.1、§4.3、M-G1 |
| 多 pivot length 重複計數 | 事件表層去重，記錄合併數 | §4.6 |
| `TP1%+SL%=100%`，丟棄未結案樣本 | 六種終局全數納入，`censored` 也算 | §4.5 |
| 等權計次，R:R 0.12~14.04 混算 | 一律 R-multiple 記帳，含成本 | §5.3 |
| 容差是可轉的旋鈕，表用最寬端產生 | 容差凍結；勝率隨容差上升判為證偽訊號 | §4.4 |
| 無樣本外、無試驗數校正 | 時間 OOS + 幣種 OOS + DSR | M-G4/5/6 |
| 無成本 | taker/maker/滑價 + ×1.5 壓力 | §5.2、M-G7 |
| 單幣單週期數百筆樣本 | PIT 宇宙 30 幣 × 3 週期 × 6.5 年 | §7.1 |
| 倖存者偏誤（今日幣單回測歷史） | PIT 季度輪換宇宙 | §7.1 |
| 無對照組，只跟 0 比 | 匹配隨機對照組為核心判準 | §5.4、M-G3 |
