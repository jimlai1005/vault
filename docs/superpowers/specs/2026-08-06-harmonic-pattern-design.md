# Sub-project M — 諧波形態策略設計

**日期**：2026-08-06（v2：2026-08-07，經獨立審查後修訂 24 項）
**狀態**：設計已核可，待實作
**基準**：TradingView `Elite Auto Harmonic Patterns Trader [Alex]`（script id `DSk4XN5m`，invite-only）

---

## 0. 一句話

把一支會 repaint、統計表不可信的 TradingView 諧波指標，重建成**零 look-ahead、R-multiple 記帳、預註冊 GO/NO-GO gate** 的可證偽策略，並在 point-in-time 幣種宇宙 × 3 個週期 × 2020–2026 上判定諧波形態是否具備可交易的 edge。

**成功的定義是「得到可信的判定」，不是「得到 GO」。** 證據先驗指向 NO-GO（見 §1.2），NO-GO 是合法且有價值的產出。

### v2 修訂摘要

v1 經 fresh-context 獨立審查，24 個 finding 全數確認並修訂。三項最重要的更正：

1. **SL 檔位不是 `ad_ratio` 的函數，是形態的常數**（F1）。v1 的階梯規則被 fixture 自身反證（6 筆只中 2 筆）。已改為凍結的 per-pattern 表（§4.5.2）。
2. **Shark 的 TP 例外係數 `(0.5, 0.886)` 實際吻合**（F2）。v1 判定「不吻合」是幾何重建錯誤（未正確解出 Shark 的 `extreme = C`）。例外係數已恢復，M-G0 由 5/5 改為 **6/6**。
3. **M-G2/G3/G4 統一在同一條日報酬序列上計算**（F5、F12、F13）。v1 讓三個 gate 用不同的序列與年化基準，其中 M-G4 因單位錯配會恆定 FAIL——這正是工程原則 #1 的違反，出現在一份引用該原則的文件裡。

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
- 同一篇直接量化了容差問題：**放寬容差會單調且顯著地提高「命中率」，但交易績效不論容差寬窄都一樣差**。這是所有高勝率宣稱的製造機制，也意味著**容差是一個純粹的自欺旋鈕**——本設計因此把容差預註冊凍結（§4.4），並把「勝率隨容差上升」列為證偽訊號而非利多。
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
PIT 幣種宇宙   →   多尺度 pivot   →   一列 = 一個形態      →   PRZ 掛單     →   日報酬序列
Binance K 線       XABCD 候選         含 as_of 時間戳          出場模擬         bootstrap
                   Fib 約束過濾       含 PRZ/SL/TP             R-multiple       對照組 / DSR
                   去重                     ↑
                                    唯一介面，可反覆切片
```

### 3.1 為什麼是這個架構

1. **`as_of` 是一個欄位，不是一個慣例。** look-ahead 因此變成可以寫斷言的東西（§8 的 mutation test），而不是靠實作者自律。原版的 repaint 就是因為沒有這條線。這對應全域工程原則第 5 條的精神：**把正確性做成結構性的，不是記憶性的**。
2. **消融實驗幾乎免費。** 同一張事件表可以反覆切片，不必重跑偵測。這是決定哪些形態該留該砍的工具。**注意**：消融本身也是試驗，必須計入 `N_TRIALS_DECLARED`（§6.4），不能因為「便宜」就免費做。
3. **可以先不談交易就回答有沒有 edge。** 直接做 event study：形態確認後 N 根的報酬分布 vs 匹配隨機時點的報酬分布。這一問不受出場規則影響，是最乾淨的證據。

（已考慮並否決的替代方案：傳統 bar-by-bar 回測——消融要全部重跑、look-ahead 只能靠自律、統計檢定難做；套用 vectorbt／backtesting.py——形態偵測本來就得自己寫、框架幫不上忙，還把時序控制權交給黑盒。）

### 3.2 事件表 schema

`data/cache/harmonic_m/events_{interval}.parquet`，一列一個形態實例：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `event_id` | str | `{symbol}_{interval}_{direction}_{L}_{t_C}_{pattern}`。用 **`t_C` 時間戳**而非 bar 索引，索引會隨資料起點漂移；含 `direction` 以免多空同點碰撞 |
| `symbol` | str | Binance USDT 永續 symbol（如 `BTCUSDT`） |
| `interval` | str | `15m` / `1h` / `4h` |
| `pattern` | str | 形態名（§4.2） |
| `direction` | int | `+1` = bullish（做多）／`-1` = bearish（做空） |
| `pivot_length` | int | 偵測到它的 pivot 尺度 L |
| `t_X,t_A,t_B,t_C` | int64 | 四點的 bar 開盤時間（ms，UTC） |
| `p_X,p_A,p_B,p_C` | float | 四點價格 |
| `as_of` | int64 | **本形態在真實時間軸上最早可知的時刻**（= C 的 pivot 確認收盤時間，ms） |
| `ratio_ab_xa`,`ratio_bc_ab`,`ratio_xc_xa` | float | `as_of` 前即可算的實際比例（診斷與消融用）。`ratio_xc_xa` 是 Cypher 的識別鍵，全形態都存以便事後比較 |
| `prz_low`,`prz_high` | float | 潛在反轉區（§4.3） |
| `sl_planned` | float | 以 PRZ 觸發邊界當 D 推導的止損（§4.5）——**僅用於 gap 作廢判定**，不用於記帳 |
| `tp1_planned`,`tp2_planned` | float | 同上推導的目標，僅供診斷 |
| `dedup_merged` | int | 去重時被本列吸收掉的重複事件數（§4.6） |
| `tol_used` | float | 產生本列所用的容差 |

回測層輸出獨立的 trades 表（含 `sl_actual`、`fill`、`exit_reason`、`R_net`），不回寫事件表。

---

## 4. 偵測器規格

### 4.1 Pivot 與 `as_of`

- 給定 pivot length `L`：bar `i` 是 **pivot high** ⟺ `high[i] == max(high[i-L .. i+L])`；平手時取最早的 `i`。pivot low 對稱。
- **確認時間** `t_confirm(i) = close_time(i + L)`。這是該 pivot 最早可被知道的時刻。
- **多尺度**：`L ∈ {5, 10, 20, 40}`（預註冊）。每個 L 各自產生獨立的 pivot 序列。
  - 不採用原版的 10–500 連掃，兩個理由：(a) 相鄰 L 產生的 pivot 高度重疊，連掃主要是製造重複偵測而非增加資訊；(b) 試驗數必須可控且可宣告（§6.4 的 DSR 需要 `N_TRIALS_DECLARED`）。

#### 4.1.1 交替序列的建構（F7）

pivot high 與 pivot low 是兩個**互相獨立**的定義，合併後的序列**不保證高低交替**（可能連續兩個 pivot high）。必須先正規化：

```
1. 把該 L 的所有 pivot high 與 pivot low 依 bar 索引合併排序。
2. 掃描序列，遇到連續同型的一段（連續 pivot high 或連續 pivot low）時，
   合併為一個：pivot high 取「價格最高者」，pivot low 取「價格最低者」；
   價格平手時取「bar 索引最小者」（較早）。
3. 合併後的序列必然高低交替。
```

此規則為**預註冊**，不得更改。（「取較極端者」是 ZigZag 慣例；此處明文釘死是因為「取較早者」也是合理讀法，兩者會產生不同的候選集合，直接影響所有 gate 的數字。）

#### 4.1.2 候選與 `as_of`

- **形態候選**：在正規化後的交替序列中取**連續**的四個 pivot `X → A → B → C`。bullish 為 `low, high, low, high`；bearish 相反。「連續」= 在該序列中相鄰，**不允許跳過 pivot**。
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

#### 主表（8 種走統一四比例）

| 形態 | AB/XA | BC/AB | CD/BC | **AD/XA**（識別鍵） | 交叉驗證 |
|---|---|---|---|---|---|
| Gartley | 0.618 | 0.382–0.886 | 1.13–1.618 | **0.786** | 4 源 |
| Bat | 0.382–0.50 | 0.382–0.886 | 1.618–2.618 | **0.886** | 4 源 |
| Alternate Bat | 0.382 ⚠️ | 0.382–0.886 | 2.0–3.618 | **1.13** | 2 源 |
| Butterfly | 0.786 | 0.382–0.886 | 1.618–2.618 | **1.27** ⚠️ | 4 源（AD/XA 有分歧） |
| Crab | 0.382–0.618 | 0.382–0.886 | 2.24–3.618 ⚠️ | **1.618** | 4 源（CD/BC 下界有分歧） |
| Deep Crab | 0.886 | 0.382–0.886 | 2.24–3.618 ⚠️ | **1.618** | 3 源（CD/BC 下界有分歧） |
| Shark | *無此約束* ⚠️ | 1.13–1.618 | 1.618–2.24 | **0.886–1.13** | 5 源（AB/XA 三說互斥） |
| 5-0 | 1.13–1.618 | 1.618–2.24 | **0.50** | *無此約束* | 3 源 |

⚠️ 標記處有來源分歧，處置見下方裁決表。分歧全文見研究 §6。

#### Cypher 走自己的基準（塞進上表必錯）

| 約束 | 值 |
|---|---|
| AB/XA | 0.382–0.618 |
| **XC/XA** | **1.272–1.414** — C 相對 **XA** 段，自 X 起算 |
| **CD/XC** | **0.786** — D 相對 **XC** 段 |

Cypher **不套用 `BC/AB` 約束**（F24）：研究 §3.2 的 `BC/AB ∈ [1.44, 2.08]` 是由上述三條**推導**出來的區間，不是獨立約束，當成硬 gate 會重複計算同一個限制。

Cypher 的等效 `AD/XA` 是**推導值 0.697–0.728**，**不是**通說的 0.786。

**此點取得獨立交叉驗證（2026-08-06 主對話親跑）**：原版腳本洩漏的 Cypher 樣本實測 `XC/XA = 1.234`、`CD/XC = 0.7763`、`AD/XA = 0.724`。代入恆等式

```
AD/XA = 1 − (XC/XA)·(1 − CD/XC)
      = 1 − 1.234 × (1 − 0.7763) = 0.72395     （洩漏值 0.724，吻合）
```

且 0.724 落在標準定義推得的區間 `[0.6974, 0.7278]` 內，通說的 0.786 落在區間外。**兩條互相獨立的證據鏈——文獻查證與原版腳本的實際輸出——一致指向 Cypher 的基準是 XC 而非 XA。** 這也意味著市面上以 `AD/XA = 0.786` 實作 Cypher 的指標（研究指出兩大開源實作皆如此）測的根本不是 Cypher。

#### Shark 與 5-0 的點位映射

兩者原文使用 `0-X-A-B-C` 命名，映射方式**不同**（研究 §3.1）：

- **Shark**：整體右移一位（`0→X, X→A, A→B, B→C, C→D`）。於是 Carney 的「AB 是 XA 的 1.13–1.618」變成本表的 `BC/AB`，「C 是 0X 的 0.886–1.13」變成本表的 `AD/XA`。
- **5-0**：原文是 6 點（`0,X,A,B,C,D`），**直接丟棄最前面的 `0` 點**、其餘不移位。代價是原文「C 對 0X = 0.886–1.13」這條約束在 5 點偵測器裡**無法表達**——列為已知限制（§10）。

#### 本專案對分歧與待決項的裁決

| 待決項 | 裁決 | 理由 |
|---|---|---|
| Cypher 是否納入 | **納入**，獨立記帳、verdict 分開列 | 兩條證據鏈已釐清其真實基準；且它正是「市面說法建立在錯誤比例上」的最佳案例 |
| Butterfly `AD/XA` 取 1.27 或 1.27＋1.618 兩變體 | **只取 1.27** | 1.618 變體與 Crab 的識別鍵重疊；砍掉可少一個自由度與一整組試驗 |
| Shark 是否加 `AB/XA` 約束 | **不加**（`None`） | 三個來源說法互斥；形態已由 `BC/AB` 與 `AD/XA` 唯一界定 |
| Alternate Bat `AB/XA` 原文為「0.382 或更小」 | **凍結為單點 0.382**（套 §4.4 容差） | 「或更小」無下界，會與 Bat 的 0.382–0.50 產生不對稱的開放區間。此為**刻意收窄**，verdict 須註明 |
| Crab / Deep Crab 的 `CD/BC` 下界（2.24 vs 2.618） | **取 2.24**（較寬） | `CD/BC` 依 §4.2 末段只作 sanity check 而非判別鍵，取寬者可避免因這條分歧而系統性刪樣本 |
| 是否採用原版的 Shark TP 例外（0.5／0.886） | **採用** | v1 判定「不吻合」是幾何重建錯誤。正確解出 `extreme = C` 後，該例外係數給出 `RR1 = 2.2560` vs 洩漏 `2.26`，通過 M-G0 判準（§6.2） |

**形態集合 = 9 種**：Gartley、Bat、Alternate Bat、Butterfly、Crab、Deep Crab、Shark、Cypher、5-0。

**形態互斥性已由研究實跑驗證**：走統一四欄的 8 種形態、28 組 pairwise，在 `ε = 0.02 / 0.03 / 0.05` 三個容差下**四軸全重疊的配對數皆為 0**，因此偵測器不需定義形態優先序。（Cypher 未納入該檢定，因其不走這四欄；實作時須另行驗證 Cypher 與其餘 8 種互斥，列為 §8 的驗收項。）

實測附帶印證：Gartley 與 Crab 的 `AB/XA` 確實重疊（0.587–0.618），兩者**全靠 `AD/XA` 分開**。

**判別鍵的結構性事實**（研究 §5）：`CD/BC` 在數學上幾乎被其他三條比例決定，真正的自由度只有三個。因此實作採取：**`AD/XA` 為主判別鍵**（容差收緊，§4.4），`CD/BC` 設寬區間僅作 sanity check。這降低了有效自由度，直接對應本專案的抗過擬合目標。

### 4.3 PRZ（潛在反轉區）計算

以 bullish 為例（`X` 低、`A` 高、`B` 低、`C` 高，預期 `D` 為低點）：

```
XA = p_A − p_X   (> 0)
AB = p_A − p_B   (> 0)
BC = p_C − p_B   (> 0)
XC = p_C − p_X
```

**`as_of` 前即可檢驗的過濾條件**（只涉及 X/A/B/C）：

| 形態 | 套用的過濾條件 |
|---|---|
| Shark | 只有 `BC/AB`（`AB/XA` 為 `None`） |
| Cypher | `AB/XA` 與 `XC/XA`（**不套 `BC/AB`**，見 §4.2） |
| 其餘 7 種 | `AB/XA` 與 `BC/AB` |

**定義 PRZ 的約束**（涉及 D，故產出區間而非單點）：

```
由 AD/XA ∈ [ad_lo, ad_hi]  →  D ∈ [p_A − ad_hi·XA , p_A − ad_lo·XA]
由 CD/BC ∈ [cd_lo, cd_hi]  →  D ∈ [p_C − cd_hi·BC , p_C − cd_lo·BC]
Cypher 專用：CD/XC ∈ tol_band(0.786) → D ∈ [p_C − 0.786(1+τ)·XC , p_C − 0.786(1−τ)·XC]

PRZ = 上述所有適用區間的交集
```

**逐形態的 PRZ 來源**（F19：Shark 的 `CD/BC` 是實打實的 `(1.618, 2.24)`，不是 `None`）：

| 形態 | PRZ 由誰決定 |
|---|---|
| Gartley、Bat、Alt Bat、Butterfly、Crab、Deep Crab、**Shark** | `AD/XA` ∩ `CD/BC` 兩條的交集 |
| 5-0 | 僅 `CD/BC`（`AD/XA` 為 `None`） |
| Cypher | 僅 `CD/XC`（`CD/BC` 無標準約束） |

`AD/XA` 與 `CD/BC` 同時為 `None` 的形態不存在於本集合；實作須以斷言強制此前提。

**若交集為空 → 候選作廢，不產生事件。** 空交集比例須逐形態統計並寫進 verdict。**門檻（F23）**：任一形態的空交集比例 `> 50%` 時，該形態的比例表視為內部不自洽，須在 verdict 單獨標記並排除於總體 `E[R_net]` 之外（仍逐一列出其數字）。

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

**容差判讀規則（F23，數值化）**：令 `ρ_win = Spearman(TOL, 勝率)`、`ρ_R = Spearman(TOL, E[R_net])`（皆取 4 個 TOL 檔位）。

```
若 ρ_win > 0.8 且 ρ_R <= 0  →  記為「容差證偽訊號 = TRUE」
```

依 Tsinaslanidis et al. (2022)，這正是「放寬容差必然拉高勝率而不改善績效」的簽名。此旗標**不改變 gate 判定**（gate 只認 §6 的 M-G2~G7），但 verdict **必須**列出這張 4×2 的表格與旗標值。這是強制揭露，不是自由裁量。

### 4.5 進場、止損、目標

沿用從原版逆向工程出的確定性公式（M-G0 已驗證 6/6，§6.2）。

#### 4.5.1 掛單與成交（bullish；bearish 鏡射）

**前置守門（F8）**：若 `close(as_of) <= prz_high`（價格在 C 被確認之前就已跌進或跌穿 PRZ），事件標記 `prz_already_breached`，**不掛單**，納入統計（`R_net = 0`）。

> 理由：`L` 最大 40 根，價格完全可能在 C 確認前就走完 PRZ。若照字面在 `as_of` 後第一根「成交」，掛單模型會退化成無條件市價進場，且這批樣本方向偏誤是系統性的（集中在急跌行情）。排除它們是保守且可稽核的做法，比例須寫進 verdict。

通過守門者，自 `as_of` 之後第一根 bar 起，於 `prz_high` 掛限價買單，TTL = `TTL_BARS = 30` 根（預註冊）。逐根判定：

```
若 bar.open <= prz_high:                      # 跳空進入或穿越 PRZ
    若 bar.open <= sl_planned: 標記 invalidated_by_gap，不進場，事件終結
    否則: fill = bar.open，成交腿計為 taker（含滑價）      # F22
否則若 bar.low <= prz_high:                    # 盤中觸及
    fill = prz_high，成交腿計為 maker（無滑價）
否則: TTL 遞減，繼續等待

TTL 耗盡仍未成交 → 標記 no_fill，事件終結
```

跳空成交計 taker 是刻意的保守選擇：那一子集正是「價格已跑過 PRZ」的樣本，多半是輸家，若計 maker 會系統性低估其成本，且偏誤恰好集中在 M-G7 最該抓到的地方。

#### 4.5.2 止損：形態常數檔位表（F1，v1 的階梯規則已作廢）

**v1 的規則 `r_sl = min{s ∈ S : s > ad_ratio}` 被 fixture 自身反證**：6 個洩漏樣本只中 2 筆。任何 `ad_ratio` 的單調函數都不可能同時滿足 `0.898 → 1.13`（跳過只差 11% 的 1.0）與 `1.947 → 2.0`（接受只差 2.7% 的 2.0）。能解釋全部 6 筆的假設是：**SL 檔位是形態的常數，與該筆的實際 `ad_ratio` 無關**。

**凍結表**（`SL_LEVEL_OVER_XA`）：

| 形態 | 檔位 | 出處 |
|---|---|---|
| Cypher | **1.0** | 觀測（fixture `elite_cypher_bullish`） |
| Bat | **1.13** | 觀測（`base_bat_bullish`） |
| Shark | **1.272** | 觀測（`base_shark113_bearish`） |
| Butterfly | **1.618** | 觀測（`ultimate_butterfly_bullish`） |
| Deep Crab | **2.0** | 觀測（`elite_deep_crab_bearish` 與 `base_deep_crab_bearish` **兩筆一致**） |
| Gartley | 1.0 | 推導（fallback 規則） |
| Alternate Bat | 1.272 | 推導 |
| Crab | 2.0 | 推導（與 Deep Crab 同 `AD/XA`＝1.618，得同檔位，內部一致） |
| 5-0 | 1.0 | 推導（無 `AD/XA`，取階梯最低檔） |

**fallback 規則**（僅用於無觀測值的 4 個形態）：

```
S = [1.0, 1.13, 1.272, 1.618, 2.0]
r_sl = min{ s ∈ S : s > 該形態的名目 AD/XA 上界 }      # 1.27 與 1.272 視為相等
5-0 無 AD/XA → r_sl = 1.0
```

**該 fallback 規則對已觀測形態的重現率為 4/5**：Cypher(0.728→1.0)✓、Shark(1.13→1.272)✓、Butterfly(1.27≈1.272→1.618)✓、Deep Crab(1.618→2.0)✓、**Bat(0.886→1.0)✗（觀測為 1.13）**。Bat 是已知例外，表中直接採觀測值。此 4/5 重現率是 M-G0d 的斷言目標——防止有人事後修改 fallback 規則。

**止損價**（`D = fill`，即實際成交價）：

```
sl_actual = p_A − SL_LEVEL_OVER_XA[pattern] × (p_A − p_X)        # bullish
```

**記帳一律使用 `sl_actual`**（F9）。`sl_planned` 只出現在 §4.5.1 的 gap 作廢判定中，不進入任何 R 計算。由於檔位現在是形態常數，`sl_actual` 與 `sl_planned` 實際上恆等——這是採用形態常數表的附帶好處，F9 的歧義因此結構性消失。

#### 4.5.3 目標

```
extreme = max(p_X, p_A, p_B, p_C)          # bullish；bearish 取 min
leg     = |extreme − D|
tp1 = D + f1 · leg
tp2 = D + f2 · leg                          # bullish；bearish 為減

(f1, f2) = (0.382, 0.618)                   # 標準
(f1, f2) = (0.500, 0.886)                   # Shark 例外（M-G0 已驗證，§6.2）
```

**注意 `extreme` 常常不是 A**：當 `BC/AB > 1`（Shark）或 `XC/XA > 1`（Cypher）時，C 會越過 A 成為極值。v1 因為未正確解出這一點而誤判 Shark 不吻合。實作與測試都必須用幾何重建而非直覺假設。

#### 4.5.4 出場與終局

**出場優先序**（棒內，悲觀）：`SL → TP → time-stop`，沿用 [`scripts/scalp_backtest_lib.py:39`](../../../scripts/scalp_backtest_lib.py) `simulate()` 既有契約（訊號收盤決定、下一棒開盤成交、gap-through 取較差價）。

- **主設定**：TP1 全出，單一目標。理由：自由度最低；且原版自己承認 Shark 必須 TP1 全平。
- **次要變體**：TP1 出 50%／TP2 出 50%，TP1 觸及後 SL 移至成本。計入試驗數。
- **time-stop**：`MAX_HOLD_BARS = 100`（預註冊）。

**每個事件恰好有一種終局**（F15，七種，互斥且窮盡）：

| 終局 | `R_net` |
|---|---|
| `tp1` / `tp2` / `sl` / `time_stop` | 依 §5.3 計算 |
| `no_fill`（TTL 耗盡未成交） | `0` |
| `invalidated_by_gap`（跳空穿越 PRZ 與 SL） | `0` |
| `prz_already_breached`（`as_of` 時已破 PRZ） | `0` |
| `censored`（資料截止時仍在倉） | **以最後一根收盤價 mark-to-market 出場記帳**，出場腿計 taker |

**不得丟棄任何樣本**——這正是原版 `TP1% + SL% = 100%` 的造假機制。`censored` 佔比須寫進 verdict；若 `> 5%` 須另附「排除 censored」的敏感度數字。

### 4.6 多尺度去重

同一個形態會被多個 `L` 重複偵測（原版快照中同一個 Bat 被印了 4 次，重複計數會直接汙染統計）。

**分組規則（F14，明確為等價關係）**：

```
1. 定義相鄰關係 ~：兩事件 symbol/interval/pattern/direction 相同，
   且 (t_X, t_A, t_B, t_C) 四個時間戳中至少 3 個相同。
2. ~ 不具傳遞性，故取其【連通分量】（transitive closure）作為分組單位。
3. 每組保留一列，tie-break 依序：
   (a) as_of 最小者
   (b) 仍平手 → pivot_length 最小者
   (c) 仍平手 → event_id 字典序最小者
4. 其餘併入該列的 dedup_merged 計數。
```

v1 寫的「`as_of` 最早者（即 `L` 最小者）」是**假恆等式**：不同 `L` 的 `idx_C` 不同，`L` 較小並不蘊含 `as_of` 較早。上述三段 tie-break 已消除此歧義。

去重在事件表層做，先於任何統計。去重前後的事件數都必須寫進 verdict。

---

## 5. 回測與記帳

### 5.1 兩種進場模式

| 模式 | 說明 | 成本 |
|---|---|---|
| **A：PRZ 限價（主）** | §4.5.1 的掛單模型 | 進場 maker（跳空則 taker），出場 taker |
| **B：確認後市價** | 等 D 點自身的 pivot 確認後以下一根開盤市價進場 | 兩腿皆 taker |

**模式 B 的 D 點認定**：在同一個 `L` 的正規化交替序列中，取 `C` 之後**第一個**方向正確（bullish 取 pivot low）且價格落在 `[prz_low, prz_high]` 內的 pivot。進場時刻 = `t_confirm(idx_D) = close_time(idx_D + L)`，成交於其後第一根 bar 的開盤。若 TTL 內不存在這樣的 pivot → `no_fill`。**不允許在候選中挑選最合適的 D**——那正是原版 `Optimize A, B & C Points` 的 look-ahead 來源。

**模式 B 的 SL 基準（F11）**：與模式 A **完全相同**——`sl_actual = p_A − SL_LEVEL_OVER_XA[pattern] × XA`。由於檔位是形態常數（§4.5.2），SL 不依賴 `fill`，兩個模式的 R 分母因此結構性同源。兩模式的差距可以乾淨地歸因到「等待確認的代價」，不被記帳基準汙染。

模式 B 是誠實但劣化的對照：D 確認要再等 `L` 根，價格早已跑掉。**兩者的差距本身就是有價值的發現**，且模式 B 完全不依賴 PRZ 預測正確性。

### 5.2 成本（沿用 repo 既有慣例，不自編）

```
taker = 0.00045   # 4.5 bps/side   — scripts/scalp_fee_check.py:18
maker = 0.00015   # 1.5 bps/side   — scripts/scalp_fee_check.py:19
slip  = 0.0001    # 1 bp/side，僅在 taker 腿支付 — scripts/cta_l_stage1.py:68
壓力情境：fee ×1.5、slip ×1.5（scripts/cta_l_stage1_runs.py:57-60 慣例）
```

**註（O7）**：`data/scalp/fees.json` 的 `"source": "default"`——這是預設費率而非實測帳戶費率。verdict 引用成本假設時須註明此點。

### 5.3 R-multiple

```
R_gross = direction · (P_exit − P_entry) / |P_entry − P_SL|

cost_abs = fee_in · P_entry + (fee_out + slip_out) · P_exit        # 各腿乘各自的成交價
cost_R   = cost_abs / |P_entry − P_SL|

R_net    = R_gross − cost_R
```

其中 `P_SL = sl_actual`（§4.5.2），`fee_in` 依成交方式取 maker 或 taker（§4.5.1），`fee_out` 恆為 taker。

**數值錨例（必須通過的單元測試）**：bullish，`P_entry = 100`、`P_SL = 98`、`P_exit = 103`，模式 A 盤中成交（maker 進場、taker 出場、滑價僅出場腿）：

```
R_gross  = (103 − 100) / 2 = 1.5
cost_abs = 0.00015·100 + (0.00045 + 0.0001)·103 = 0.015 + 0.05665 = 0.07165
cost_R   = 0.07165 / 2 = 0.035825
R_net    = 1.5 − 0.035825 = 1.464175
```

（v1 的錨例把兩腿手續費都乘 `P_entry`，對長距離出場有系統性低估——已修正，見 O1。）

**兩個指標都要報**：`E[R_net]`（無條件，未成交／作廢事件記 0）與 `E[R_net | filled]`（條件，診斷用）。勝率只是附註，不是判準。

### 5.4 匹配隨機對照組

對每個真實事件 `e`，生成 `K = 5` 個對照事件：

- 同 `symbol`、同 `interval`、同 `direction`、同 `pattern`
- **`as_of' = as_of + δ`，`δ` 自 `{131 .. 300}` 根 bar 均勻抽樣（只取正向）**
  - 下界 131 = `TTL_BARS(30) + MAX_HOLD_BARS(100) + 1`，確保對照的完整曝險窗與原事件不重疊（O3；v1 只避開 TTL，δ=±31 的對照與原事件持有期幾乎完全重疊）
  - **只取正向**是為了消除 O4 指出的前視：負 δ 的對照，其價格比值取自 `as_of`（在 `as_of'` 之後），對照臂會內含未來資訊
- 進場觸發價、SL、TP 按**相對距離**平移：以 `close(as_of')` 為錨，保持 `prz_high / close(as_of)`、`sl_actual / close(as_of)`、`tp / close(as_of)` 三個比值不變
- **成交後不重算 SL/TP**（F10）。實驗組因採用形態常數檔位，SL 同樣不依賴 `fill`——**兩臂的 R 分母構造規則因此同源**，M-G3 的差值不會混入純記帳差異
- TTL、成交規則（含跳空計 taker）、出場優先序、七種終局、成本、記帳全部相同
- 若平移後的窗口超出該 symbol 的資料範圍則重抽，最多 10 次；仍失敗則該對照樣本捨棄並計數（捨棄數須寫進 verdict）

隨機種子 `SEED = 20260806` 寫死於 `scripts/m_config.py`。

**K 個對照如何塌縮（F13）**：不在事件層平均。對照組的 `K × N` 筆交易**依 §6.1 的同一規則獨立聚合成一條日報酬序列**，權重每筆 `1/K`（使兩臂的每日總曝險可比）。M-G3 對兩條日報酬序列做配對 stationary bootstrap。

---

## 6. 預註冊 GO/NO-GO gate

> 本節在跑任何回測**之前**凍結。所有門檻寫成顯式方程式並附可機器驗證的數值錨例——2026-07-13 的 L 案事故（MDD 分母兩種合法讀法使同一份結果 PASS/FAIL 相反，劣定義活過四道審查）就是散文式定義造成的。

### 6.1 共用序列定義（所有 gate 的唯一輸入）

**M-G2、M-G3、M-G4 全部在同一條日報酬序列上計算**，以消除 v1 的單位／基準錯配（F5、F12）。

```
RISK_PER_TRADE = 0.01                       # 每筆固定承擔權益 1%
r_d = 0.01 × Σ{ R_net(e) : e 的【出場日】= d }
      當日無出場者 r_d = 0
序列涵蓋：該設定第一筆【進場】日 至 最後一筆【出場】日（UTC 日曆日）
```

- **Sharpe 一律用未年化的日 Sharpe** `sr = mean(r_d) / std(r_d)`，與 [`scripts/k_gates_eval.py:90`](../../../scripts/k_gates_eval.py) `deflated_sharpe` 內部的 `daily_sr` 同基準。
  - **v1 規定餵年化 Sharpe 是錯的**：該函式內部用未年化日 SR，餵年化值會讓 `sr_star` 大 √365 ≈ 19 倍 → M-G4 恆定 FAIL，與策略好壞無關。這是工程原則 #1 的違反。
  - 年化 Sharpe（`× √365`，crypto 24/7）**僅供 verdict 敘述時報告**，不進入任何 gate 計算。報告時須註明年化因子為 365 而非 [`src/hlvault/metrics.py:9`](../../../src/hlvault/metrics.py) 的 252。
- **stationary bootstrap**：`B = 10000`，`expected_block = 20`（日，預註冊）。被重抽的是**日報酬序列**，不是交易列表——這消除了 v1「block 單位與被重抽序列不匹配」的歧義，也自動處理 30 個幣在日曆時間上的橫斷面重疊。

### 6.2 前置條件（不過 = 實作有 bug，不是策略結論）

#### M-G0 基準忠實度

以 `tests/fixtures/m_tv_baseline_samples.json` 的洩漏樣本檢定 §4.5 的公式。

**fixture 實況**（已由主對話與獨立審查各自實跑確認）：6 個樣本中僅 2 個有完整 XABCD 絕對價格，且**沒有任何樣本印出絕對 SL/TP 值**。因此不能用「重算 SL/TP 與 `expected` 比對」——那些欄位全為 `null`，用公式回推填值等於自己驗自己。

改用**尺度不變的幾何重建 + 風報比錨點**。正規化到單位座標（bullish；bearish 鏡射後比例相同）：

```
X = 0 , A = 1                              (即 XA = 1)
B = 1 − ab_xa
C = B + bc_ab · ab_xa                      (若樣本有 xc_xa 則 C = xc_xa)
D = 1 − ad_xa
extreme = max(0, 1, B, C)
risk = |SL_LEVEL_OVER_XA[pattern] − ad_xa|
leg  = |extreme − D|
RR1  = f1 · leg / risk ,  RR2 = f2 · leg / risk
```

**四項斷言**：

| ID | 斷言 |
|---|---|
| **M-G0a** | `SL_LEVEL_OVER_XA` 中標為「觀測」的 5 個條目，逐一等於 fixture 對應樣本的 `sl_level_over_xa`（regression guard，防止凍結表被改動） |
| **M-G0b** | **全部 6 個樣本**滿足 `|RR1_calc − RR1_leaked| < 0.01`；有 `rr2` 的樣本另需 `|RR2_calc − RR2_leaked| < 0.01` |
| **M-G0c** | 2 個有座標的樣本另需 `|ad_xa_calc − ad_xa_leaked| < 0.002` 且 `|risk%_calc − risk%_leaked| < 0.01` |
| **M-G0d** | §4.5.2 的 fallback 規則對 5 個觀測形態的重現率**恰為 4/5**（Bat 為已知例外）——防止事後修改 fallback 規則 |

**基線已驗證通過（6/6）**：

| 樣本 | extreme | (f1,f2) | RR1 算／洩漏 | RR2 算／洩漏 | 結果 |
|---|---|---|---|---|---|
| `elite_cypher_bullish` | C | (0.382, 0.618) | 1.3259 / 1.33 | 2.1451 / 2.14 | PASS |
| `elite_deep_crab_bearish` | A | (0.382, 0.618) | 1.1772 / 1.18 | 1.9044 / 1.91 | PASS |
| `base_bat_bullish` | A | (0.382, 0.618) | 1.4786 / 1.48 | — | PASS |
| `base_deep_crab_bearish` | A | (0.382, 0.618) | **14.0331 / 14.04** | — | PASS |
| `base_shark113_bearish` | **C** | **(0.500, 0.886)** | **2.2560 / 2.26** | — | **PASS** |
| `ultimate_butterfly_bullish` | A | (0.382, 0.618) | 1.3941 / 1.39 | 2.2553 / 2.26 | PASS |

有座標樣本的絕對驗算亦通過：cypher `ad_xa` 0.7239/0.724、`risk%` 0.8559/0.86；deep crab `ad_xa` 1.5103/1.51、`risk%` 2.6153/2.62。

`base_deep_crab_bearish` 的 **RR1 = 14.04** 是最鋒利的單一錨點——D 落在 1.947 XA 而 SL 檔位固定在 2.000 XA，止損距離趨近零使 RR 爆炸。忠實重建必須重現這個退化值。

**Shark 的更正紀錄**：v1 判定 Shark「在任一組係數下都不吻合」，實為幾何重建錯誤——Shark 的 `bc_ab = 1.721 > 1` 使 C 越過 A（與 Cypher 的 `xc_xa = 1.234 > 1` 同構），`extreme` 必須是 C 而非 A。四種組合實跑：`(A, 0.382)→1.2651`、`(A, 0.500)→1.6559`（v1 誤採此值）、`(C, 0.382)→1.7235`、**`(C, 0.500)→2.2560 = PASS`**。v1 據錯誤結論刪除的 Shark TP 例外已於 §4.2 恢復。

（`ad_xa = 0.977` 與「Shark 113」標籤的矛盾仍然成立，但那是 `ad_xa` 的量測基準問題，與 TP 係數是否吻合是兩件事。）

M-G0 任一項不過 → 公式逆向工程有誤，作廢重來。

#### M-G1 無前視

`tests/test_m_nolookahead.py` 全綠。**兩層斷言**（O2：v1 只覆蓋偵測器）：

- **偵測層**：把某事件 `as_of` 之後的所有 K 線改成 `NaN`，重跑偵測。**該事件對應的那一列必須逐欄位完全相同**（截斷後總事件數必然變少，故不是整表相等）。
- **回測層**：把某筆交易出場 bar 之後的 K 線改成 `NaN`，重跑回測。該筆的 `fill`、`sl_actual`、`exit_reason`、`R_net` 必須完全相同。對照組平移（§5.4）套用同一斷言。

### 6.3 判定 gate

| ID | 判準（方程式） | 說明 |
|---|---|---|
| **M-G2** 絕對期望 | `lower_95(bootstrap_{B=10000}(mean(r_d))) > 0` | 序列與 block 定義見 §6.1 |
| **M-G3** 優於隨機 | `lower_95(bootstrap_{B=10000}(mean(r_d^pattern) − mean(r_d^control))) > 0` | 配對 stationary bootstrap，兩條序列日期對齊；對照組定義見 §5.4。**這是核心判準——不是跟 0 比，是跟隨機比** |
| **M-G4** 試驗數校正 | `deflated_sharpe(sr_list, primary_returns, N_TRIALS_DECLARED)["psr"] >= 0.95` | 沿用 K 案實際 gate（[`scripts/k_gates_eval.py:239`](../../../scripts/k_gates_eval.py)）。`sr_list` 為 482 個設定各自的**未年化日 Sharpe** |
| **M-G5** 時間樣本外 | OOS 上 M-G2 仍成立 | IS `2020-07-01T00:00:00Z ~ 2023-12-31T23:59:59Z`；OOS `2024-01-01T00:00:00Z ~ 2026-06-30T23:59:59Z`。**OOS 只跑一次** |
| **M-G6** 幣種樣本外 | `1` 半上 M-G2 仍成立 | 分半規則見 §6.5 |
| **M-G7** 成本壓力 | fee ×1.5、slip ×1.5 後 M-G2 仍成立 | 沿用 CTA 慣例 |

### 6.4 `N_TRIALS_DECLARED = 482`

```
主網格： 10 × 4 × 3 × 2 × 2 = 480
         └ 10 = 9 個形態 + 1 個「全形態合併」層（primary 本身也是一次試驗）
         └  4 = TOL ∈ {0.03, 0.05, 0.08, 0.10}
         └  3 = interval ∈ {15m, 1h, 4h}
         └  2 = 進場模式 A / B
         └  2 = 出場變體（TP1 全出 / 分批）
消融：   + 2  （§3.1 列出的「只留容差 ≤3%」與「只留 D 超出 X」兩組切片）
                「Fib 約束換隨機門檻」不計——那是 M-G3 的對照組，不是候選策略
─────────────────────────────
合計     482
```

v1 宣告 432 漏掉了 primary 所在的合併層與兩組消融——這與所沿用的 K 案慣例（`sr_list = HISTORICAL + 所有 cell`，primary 是其中一個 cell）相反，會讓 `sr_star` 偏低、gate 偏鬆。

**事後新增任何設定都必須重新宣告並重跑 M-G4**——這正是原版讓使用者自由轉旋鈕卻不計代價的地方。

### 6.5 IS/OOS 與分半的歸屬規則（F3、F16、F17）

**歸屬鍵**：事件依 **`as_of`** 歸屬 IS 或 OOS。`as_of` 在 IS 而出場在 OOS 的事件**屬 IS**，其 `r_d` 記在出場日但只計入 IS 序列。這條規則凍結，改動一次等同偷跑一次 OOS。

**幣種分半**：`int(sha256(symbol.encode("utf-8")).hexdigest(), 16) % 2`，其中 `symbol` 是 **Binance 的 USDT 永續 symbol 字串**（如 `"BTCUSDT"`、`"1000PEPEUSDT"`），非 HL 幣名。編碼固定 UTF-8。

**「選擇」的定義（F3——v1 最大的預註冊漏洞）**：v1 說「IS 做完全部選擇」卻從未定義選什麼、怎麼選。本 spec 的處置是**把選擇完全消除**：

- §4 與 §5 的**所有參數已在本文件中凍結**（比例表、兩級容差、pivot 尺度、TTL、MAX_HOLD、SL 檔位表、TP 係數、成本、seed）。IS 階段**不做任何參數選擇**。
- 唯一允許的「選擇」是**形態子集**，且規則預註冊、可機器執行：

  ```
  selected = { p : n_events_IS(p) >= 30  且  lower_95(bootstrap(mean(r_d^p_IS))) > 0 }
  ```

- OOS 上**同時**評估兩個結果並**都寫進 verdict**：(a) 全 9 形態合併；(b) `selected` 子集。
  兩者不一致時（例如 (b) 過 (a) 不過），verdict 判定以 **(a) 全形態**為準，(b) 僅作為「篩選是否有效」的診斷。這杜絕了「跑完 IS 挑贏家再宣稱 OOS 通過」。

### 6.6 判定表（F4：v1 未覆蓋 M-G4／M-G7 單獨失敗）

| 結果 | verdict |
|---|---|
| M-G2 ~ M-G7 全過 | **GO** |
| M-G2 過、**M-G3 不過** | **NO-GO** — 形態不優於隨機進場。這正是 Tsinaslanidis et al. (2022) 對 Fib 成分的預測 |
| M-G2、M-G3 過，**M-G4 不過** | **NO-GO（多重檢定未通過）** — 在 482 個試驗的搜尋規模下，單一設定的正期望值無法與運氣區分 |
| M-G2、M-G3、M-G4 過，**M-G5 或 M-G6 不過** | **NO-GO（過擬合）** |
| M-G2~G6 過，**M-G7 不過** | **NO-GO（成本邊際）** — edge 存在但被交易成本吃掉，且對費率上升無耐受度 |
| M-G2 不過 | **NO-GO** |
| M-G0 或 M-G1 不過 | 非結論——修 bug 後重跑 |

**任何 gate 失敗都不得由作者裁量覆蓋。** 上表窮盡所有分支；若出現表中未列的組合，視為 spec 缺陷，須在 verdict 明確記錄並停止判定，不得自行補規則。

### 6.7 硬性規定

- **回測窗口硬編時間戳**於 `scripts/m_config.py`，**禁止**「從今天回推 N 天」（2026-07-12 momentum 教訓：端點差 9 天使兩年 Sharpe 從 0.57 掉到 0.18）。
- **端點敏感度**：GO 級結論前跑 IS/OOS 分界點 ±7 天。**「翻盤」的定義（F23）**：`lower_95(bootstrap(mean(r_d)))` 在 ±7 天的任一端點設定下**變號**。翻盤 → verdict 由 GO 降為 NO-GO（厚尾雜訊，非 edge）。
- 所有凍結參數在**第一次跑回測之前**定案。任何事後修改必須在 verdict 中明確揭露並重新計算 `N_TRIALS_DECLARED`。

---

## 7. 資料層

### 7.1 幣種宇宙：point-in-time 季度輪換

沿用 [`scripts/k_data_layer.py:157`](../../../scripts/k_data_layer.py) `build_pit_universe()` 的邏輯。

**必要性**：直接取「今天還活著且流動性好的幣」跑 2020–2026 會吃到嚴重**倖存者偏誤**——死掉、下市、流動性枯竭的幣被自動排除。PIT 宇宙只用每季開始**之前**的資料決定當季幣單。

**門檻（預註冊）**：trailing 90 日中位 quote volume ≥ **$50M** 且上市 ≥ **180 天**，每季取 top **30**。
（K 案用 $100M / top 8；本專案放寬是為了樣本數——諧波形態在單幣單週期上稀少。此為預註冊選擇，非事後調整。放寬會納入滑價較差的中小幣，故 M-G7 的成本壓力測試對本專案格外關鍵。）

流動性以 **quote volume（USDT 名目）** 計，非幣本位 volume——見 [`scripts/k_data_layer.py:53`](../../../scripts/k_data_layer.py) `binance_rows_to_df_qv()` 的踩坑註記。

### 7.2 K 線資料

- 來源：**Binance USDT 永續**（HL candleSnapshot 每 interval 僅保留最近 ~5000 根，1h ≈ 208 天，拿不到 2020 年）
- interval：`15m` / `1h` / `4h`
- **窗口：`2020-07-01T00:00:00Z ~ 2026-06-30T23:59:59Z`**
  - 起點由 PIT 宇宙決定（F21）：`build_pit_universe()` 的季度自 **2020-Q3** 起，因為每季需要「季度開始前」的 trailing 90 日成交量與上市滿 180 天。v1 寫 2020-01-01 會讓前兩季得到空的或退化的宇宙，而 verdict 卻宣稱涵蓋該期間。
  - K 線本身仍自 `2020-01-01` 抓取（PIT 篩選需要 trailing 窗），但**事件與統計只計 `as_of >= 2020-07-01` 者**。
- 抓取：沿用 [`scripts/cta_proxy_pull_data.py:79`](../../../scripts/cta_proxy_pull_data.py) `pull_klines(symbol, interval)`（interval 已參數化，1500 根/頁，含無限迴圈防護）
- 幣名映射：[`scripts/scalp_lib.py:121-127`](../../../scripts/scalp_lib.py) `binance_perp_symbols()` / `binance_symbol()`，含 `kPEPE → 1000PEPEUSDT` 等 override 表
- 快取：`data/cache/harmonic_m/{SYMBOL}_{interval}.parquet`（`data/cache/` 已在 `.gitignore`）
- HL 的角色：僅用 [`scripts/scalp_lib.py:77`](../../../scripts/scalp_lib.py) `universe_ctxs()` 界定「HL 實際可交易」，以及保真度交叉驗證

---

## 8. 測試策略

全部**離線、零網路**（全域工程原則第 4 條）。沿用 [`tests/test_scalp_backtest.py`](../../../tests/test_scalp_backtest.py) 的 `sys.path.insert(0, "scripts")` + 合成 bar 慣例。

| 測試檔 | 驗什麼 |
|---|---|
| `tests/test_m_patterns.py` | 手工構造比例完美的 Gartley → 必須被偵測；`AD/XA` 偏離 20% → 必須不被偵測；PRZ 交集為空的候選 → 必須作廢；**Cypher 與其餘 8 種形態的互斥性**（§4.2 的實作階段驗收項） |
| `tests/test_m_pivots.py` | §4.1.1 的交替序列正規化：連續兩個 pivot high → 合併為價高者；價格平手 → 取較早者 |
| `tests/test_m_nolookahead.py` | **M-G1 的兩層 mutation test**（偵測層 + 回測層），見 §6.2 |
| `tests/test_m_baseline_formula.py` | **M-G0 的四項斷言 a/b/c/d**，見 §6.2。使用 §6.2 的幾何重建式，**不與 fixture 的 `expected.sl/tp1/tp2` 比對**（那三欄全為 `null`）；容差為 RR 的 `0.01`、`ad_xa` 的 `0.002`、`risk%` 的 `0.01` |
| `tests/test_m_rmultiple.py` | §5.3 數值錨例：`entry=100, SL=98, exit=103` → `R_net == 1.464175`（絕對誤差 < 1e-9）；三種未成交終局 `R_net == 0` 且計入分母；`censored` 以最後收盤 mark-to-market |
| `tests/test_m_dedup.py` | §4.6 連通分量分組：構造 `e1~e2`、`e2~e3` 但 `e1≁e3` 的三元組 → 必須併為一列且 `dedup_merged == 2`；tie-break 三段規則各一例 |

---

## 9. 交付物

| 檔案 | 內容 |
|---|---|
| `scripts/m_config.py` | **全部凍結參數**：比例表、兩級容差、pivot 尺度、TTL、MAX_HOLD、`SL_LEVEL_OVER_XA`、TP 係數、時間窗、成本、SEED、`N_TRIALS_DECLARED = 482` |
| `scripts/m_data.py` | PIT 宇宙 + K 線抓取與快取 |
| `scripts/m_detect.py` | pivot 正規化 + 偵測器 → 事件表 |
| `scripts/m_backtest.py` | 事件表 → trades → R-multiple → 日報酬序列 |
| `scripts/m_control.py` | 匹配隨機對照組 |
| `scripts/m_gates.py` | M-G0 ~ M-G7 評估與判定表輸出 |
| `tests/test_m_*.py` | §8 六個測試檔 |
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
3. **PIT 宇宙以 Binance 資料定義**，與 HL 實際可交易幣種不完全重合；GO 情境下部署前須重新對齊。此外 top 30 / $50M 的放寬會納入滑價較差的中小幣。
4. **TP/SL 公式來自對閉源腳本的逆向工程**，非官方文件。錨點強度已量化（§6.2）：6 個洩漏樣本**全數**在尺度不變的 R:R 檢定上吻合，其中 2 個另有絕對價格可驗 `risk%` 與 `ad_xa`。**但 SL 檔位表只有 5 個形態有觀測值，另 4 個（Gartley、Alt Bat、Crab、5-0）是 fallback 推導，未經基準驗證**；且 fallback 規則本身對觀測值只重現 4/5（Bat 為例外）。verdict 不得宣稱「完全複製原版」。
5. **比例表本身是假設，不是事實**。§4.2 的數值即使有多來源交叉驗證，仍可能與原版腳本實際使用的比例不同（原版頁面完全沒有出現任何 Fibonacci 數字）。因此本專案測的是**教科書定義的諧波形態**，不是「原版腳本的複製品」——verdict 不得宣稱「已證明原腳本無效」，只能宣稱「已證明標準定義的諧波形態在本測試條件下無效／有效」。
6. **形態稀少性**。若去重後某些形態在 OOS 上樣本數 < 30，該形態的個別結論不成立，只能併入總體判定；verdict 必須逐形態列出樣本數。
7. **一級來源未取得**。Carney 的《Harmonic Trading》Vol. 1–3 原文未取得；Shark 與 5-0 的完整比例是靠 3–5 個二級來源交叉確認，非一級來源直證。若日後取得原文而比例有出入，本專案的 Shark／5-0 結論須重跑。
8. **5-0 的偵測比原文寬鬆**。原文的「C 對 0X = 0.886–1.13」約束在 5 點偵測器中無法表達（§4.2 映射說明），故 5-0 會納入部分原文不認可的樣本。這是**偏向多納入**的偏差，對 NO-GO 結論無害，對 GO 結論則須加註。
9. **Alternate Bat 的定義被刻意收窄**（原文「0.382 或更小」→ 單點 0.382 加容差），Crab／Deep Crab 的 `CD/BC` 下界取較寬的 2.24。兩者皆為 §4.2 裁決表的預註冊選擇，verdict 須列出。
10. **對照組只用正向 δ**（§5.4）。這消除了負向平移的前視污染，但也意味著對照組在時間上系統性地晚於實驗組；若市場 regime 有強趨勢，兩臂可能落在不同 regime。verdict 須報告兩臂的日期分布重疊度。

---

## 附錄：與原版的逐項對照

| 原版缺陷 | 本設計 | 對應章節 |
|---|---|---|
| repaint：D 成形後回頭改寫點位 | 前瞻式 PRZ 掛單；`as_of` 欄位 + 兩層 mutation test 強制 | §4.1、§4.3、M-G1 |
| pivot 序列非交替時的合併未定義 | 明文釘死「取較極端者，平手取較早」 | §4.1.1 |
| 多 pivot length 重複計數 | 事件表層連通分量去重 + 三段 tie-break | §4.6 |
| `TP1%+SL%=100%`，丟棄未結案樣本 | 七種終局全數納入，`censored` 亦 mark-to-market 記帳 | §4.5.4 |
| 等權計次，R:R 0.12~14.04 混算 | 一律 R-multiple 記帳，各腿手續費乘各自成交價 | §5.3 |
| 容差是可轉的旋鈕，表用最寬端產生 | 兩級容差凍結；容差證偽訊號以 Spearman ρ 數值化並強制揭露 | §4.4 |
| 無樣本外、無試驗數校正 | 時間 OOS + 幣種 OOS + DSR（482 試驗，含 primary 與消融） | §6.3~6.5 |
| 無成本 | taker/maker/滑價 + ×1.5 壓力；跳空成交計 taker | §5.2、M-G7 |
| 單幣單週期數百筆樣本 | PIT 宇宙 30 幣 × 3 週期 × 6 年 | §7.1 |
| 倖存者偏誤（今日幣單回測歷史） | PIT 季度輪換宇宙，窗口起點對齊宇宙可用期 | §7.1、§7.2 |
| 無對照組，只跟 0 比 | 匹配隨機對照組為核心判準，兩臂 R 分母同源 | §5.4、M-G3 |
| 使用者可事後轉旋鈕挑好結果 | 全參數凍結；IS 不做參數選擇；判定表窮盡分支且禁止裁量覆蓋 | §6.5、§6.6 |
