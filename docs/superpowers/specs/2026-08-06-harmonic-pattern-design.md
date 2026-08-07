# Sub-project M — 諧波形態策略設計

**日期**：2026-08-06（v3：2026-08-07，經兩輪獨立審查，累計修訂 24 + 25 項）
**狀態**：設計已核可，待實作
**基準**：TradingView `Elite Auto Harmonic Patterns Trader [Alex]`（script id `DSk4XN5m`，invite-only）

---

## 0. 一句話

把一支會 repaint、統計表不可信的 TradingView 諧波指標，重建成**零 look-ahead、R-multiple 記帳、預註冊 GO/NO-GO gate** 的可證偽策略，並在 point-in-time 幣種宇宙 × 3 個週期 × 2020–2026 上判定諧波形態是否具備可交易的 edge。

**成功的定義是「得到可信的判定」，不是「得到 GO」。** 證據先驗指向 NO-GO（見 §1.2），NO-GO 是合法且有價值的產出。

### 修訂沿革

| 版本 | 事件 |
|---|---|
| v1 | 初稿。fresh-context 審查提出 24 個 finding，全數成立 |
| v2 | 修訂 24 項。三項核心更正：SL 檔位改為形態常數（原階梯規則被 fixture 反證，6 筆只中 2）、Shark TP 例外恢復（原判定「不吻合」是幾何重建錯誤）、M-G2/G3/G4 統一序列與年化基準 |
| **v3** | 第二輪審查提出 4 HIGH + 15 MEDIUM + 6 LOW，全數修訂。四項核心更正見下 |
| **v3.3** | Stage 1 final review（opus，含事件表抽樣對帳）提出 2 HIGH + 1 MEDIUM，全數修訂：**(F1)** 事件須套 PIT 季度成員資格——聯集跑全歷史會讓 60.5% 的 1h 事件來自「該幣當季不在宇宙」的期間（含 20.6% 早於首次入選），重新引入 PIT 要消滅的選擇偏誤；預註冊為「事件只在其 symbol 於 as_of 所屬季度在宇宙內時計入統計與 gate」，事件表加 `in_universe` 欄、宇宙 schedule 落檔 `data/cache/harmonic_m/universe_schedule.json`，Stage 2 不得重打 exchangeInfo。**(F2)** 外包/插針棒同時成為 pivot high 與 low 時產生零時距腿（t_B==t_C，退化 BC 中位 0.51 XA）與重複列；規則釘死為「一根 bar 至多貢獻一個 pivot 至交替序列，後到的異型 pivot 丟棄」（棒內高低先後在 OHLC 粒度不可知）。**(F3)** `t_confirm` 實作誤用開盤時間；已修為 §4.1 原文的 `close_time(i+L)`（= 開盤 + bar_ms − 1，Binance 慣例），消除 Stage 2 把 as_of 當收盤時間用時的一根 bar look-ahead |

**v3 的四項核心更正**：

1. **`lower_95` 從未定義**（H1）。四個 gate 用它卻沒說是第 5 還是第 2.5 百分位、用哪種 method——與 2026-07-13 L 案的 MDD 分母事故同構。已釘死並附數值錨例（§6.1）。
2. **primary 沒有指定 interval**（H2）。TOL／模式／出場／形態層全部凍結，唯獨 `interval` 三選一留白，等於在最關鍵維度保留 1/3 的事後挑選權。已凍結為 **1h**。
3. **pivot 合併規則本身引入 look-ahead**（H3）。「合併連續同型段」需要知道該段何時結束，而那是 `as_of` 之後才知道的事；且 M-G1 的斷言方向錯誤（只假設截斷後事件變少），結構上抓不到。已改為因果式合併，M-G1 斷言改寫。
4. **5-0 形態剔除**（M13）。它沒有基準 SL 錨點，fallback 檔位使其風險距離達 **0.690–1.000 XA**，是其餘形態（0.142–0.386）的 **2–7 倍**，結構性 RR1 ≈ 0.5；加上 5 點偵測器無法表達其原文約束。留著會以與諧波 edge 無關的理由拖垮合併層。**形態集合由 9 種縮為 8 種**。

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

使用者在看過上述證據後，明確選擇**把範圍鎖在諧波形態本身**（而非轉向有文獻支持的 swing-failure／liquidity-sweep 路線）。本 spec 遵照該決策。「Fib 是否有增量資訊」降級為專案內的**形態篩選診斷**，不另闢策略路線。

---

## 2. 範圍

**在範圍內**：諧波形態偵測器（8 種，§4.2）與形態事件表、事件回測（兩種進場模式）、匹配隨機對照組、預註冊 GO/NO-GO gate 評估、verdict 報告。

**不在範圍內**：實盤引擎與部署（照 repo 慣例做到 verdict 為止）、swing failure／liquidity sweep／訂單流策略、L2 orderbook／清算流／OI／funding 等額外資料源、Pine Script 版本輸出。

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

1. **`as_of` 是一個欄位，不是一個慣例。** look-ahead 因此變成可以寫斷言的東西（§6.2 M-G1），而不是靠實作者自律。原版的 repaint 就是因為沒有這條線。對應全域工程原則第 5 條：**把正確性做成結構性的，不是記憶性的**。
2. **消融實驗幾乎免費。** 同一張事件表可反覆切片，不必重跑偵測。**但消融本身也是試驗，必須計入 `N_TRIALS_DECLARED`（§6.4）**——不能因為便宜就免費做。
3. **可以先不談交易就回答有沒有 edge。** 直接做 event study：形態確認後 N 根的報酬分布 vs 匹配隨機時點的報酬分布。

（已否決的替代方案：傳統 bar-by-bar 回測——消融要全部重跑、look-ahead 只能靠自律；套用 vectorbt／backtesting.py——形態偵測本來就得自己寫，還把時序控制權交給黑盒。）

### 3.2 事件表 schema

`data/cache/harmonic_m/events_{interval}.parquet`，一列一個形態實例：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `event_id` | str | `{symbol}_{interval}_{direction}_{L}_{t_C}_{pattern}`。用 **`t_C` 時間戳**而非 bar 索引（索引隨資料起點漂移），含 `direction` 以免多空碰撞 |
| `xabc_group_id` | str | `{symbol}_{interval}_{direction}_{L}_{t_X}_{t_A}_{t_B}_{t_C}`——**同一組 XABC 可能同時滿足多個形態的前置過濾**（§4.2 末段），此欄用於統計重複率 |
| `symbol` | str | Binance USDT 永續 symbol（如 `BTCUSDT`） |
| `interval` | str | `15m` / `1h` / `4h` |
| `pattern` | str | 形態名（§4.2 的 8 種之一） |
| `direction` | int | `+1` = bullish（做多）／`-1` = bearish（做空） |
| `pivot_length` | int | 偵測到它的 pivot 尺度 L |
| `t_X,t_A,t_B,t_C` | int64 | 四點的 bar 開盤時間（ms，UTC） |
| `p_X,p_A,p_B,p_C` | float | 四點價格 |
| `as_of` | int64 | **本形態在真實時間軸上最早可知的時刻**（= C 的 pivot 確認收盤時間，ms） |
| `ratio_ab_xa`,`ratio_bc_ab`,`ratio_xc_xa` | float | `as_of` 前即可算的實際比例（診斷與消融用） |
| `prz_low`,`prz_high` | float | 潛在反轉區（§4.3） |
| `sl` | float | 止損價。**由形態常數表與 X/A 決定，不吃 D**（§4.5.2） |
| `tp1_planned`,`tp2_planned` | float | 以 PRZ 觸發邊界當 D 推導的目標，僅供診斷 |
| `dedup_merged` | int | 去重時被本列吸收掉的重複事件數（§4.6） |
| `tol_used` | float | 產生本列所用的容差 |

回測層輸出獨立的 trades 表（含 `fill`、`exit_reason`、`R_net`、`term_date`），不回寫事件表。

---

## 4. 偵測器規格

### 4.1 Pivot 與 `as_of`

- 給定 pivot length `L`：bar `i` 是 **pivot high** ⟺ `high[i] == max(high[i-L .. i+L])`；平手時取最早的 `i`。pivot low 對稱。
- **邊界**：只有 `L <= i <= n-1-L` 的 bar 可以是 pivot（頭尾各 `L` 根視窗不完整，不判定）。
- **確認時間** `t_confirm(i) = close_time(i + L)`。
- **多尺度**：`L ∈ {5, 10, 20, 40}`（預註冊）。每個 L 各自產生獨立的 pivot 序列。
  - 不採用原版的 10–500 連掃：(a) 相鄰 L 的 pivot 高度重疊，連掃主要製造重複偵測；(b) 試驗數必須可控且可宣告。

#### 4.1.1 交替序列的建構——因果式合併（H3）

pivot high 與 pivot low 是兩個**互相獨立**的定義，合併後的序列**不保證高低交替**（上升趨勢中兩個相距 > L 的 pivot high 之間可以沒有 pivot low）。必須正規化，但**正規化本身不得使用未來資訊**。

v2 的規則（「合併連續同型的一段，取較極端者」）**引入了 look-ahead**：一段 pivot high 何時結束，是由它之後第一個 pivot low 界定的，而那件事發生在 `as_of` 之後。後果是留下的事件系統性地偏向「C 之後價格真的轉下去」那一批。

**v3 的因果式規則**：

```
對候選 X → A → B → C（在 as_of = t_confirm(idx_C) 判定）：

X, A, B 所屬的同型段在 as_of 時【必然已封閉】（因為它們之後都出現了異型 pivot），
        故取該段的極值（pivot high 取價高者、pivot low 取價低者；平手取較早者）。

C 所屬的同型段在 as_of 時【尚未封閉】，
        故取【截至 as_of 為止該段的 running extreme】。

若該段之後出現更極端的同型 pivot C'，則產生一個【新的候選】（t_C' ≠ t_C，as_of' > as_of）。
【絕不回頭修改已發出的事件。】新舊候選由 §4.6 去重層以 as_of 最早者保留。
```

此規則為預註冊，不得更改。它是完全因果的：所有輸入在 `as_of` 時皆已知。

#### 4.1.2 候選與 `as_of`

- **形態候選**：在正規化後的交替序列中取**連續**的四個 pivot `X → A → B → C`。bullish 為 `low, high, low, high`；bearish 相反。「連續」= 在該序列中相鄰，**不允許跳過 pivot**。
  - 原版的 `Optimize A, B & C Points` 開關暗示它會挑選最合適的點位，那正是 look-ahead 的來源。禁止跳點使候選集合由資料唯一決定。
- **`as_of` = `t_confirm(idx_C)`**。形態的全部欄位只能由 `close_time <= as_of` 的 K 線算出。

### 4.2 形態的 Fibonacci 比例定義

> 本節數值於實作時凍結於 `scripts/m_config.py` 的 `HARMONIC_RATIOS` / `CYPHER_RATIOS`，跑任何回測前不得修改。查證過程、來源 URL 與分歧分析見 [`scripts/m_pattern_ratios_research.md`](../../../scripts/m_pattern_ratios_research.md)。

**計算約定**（一律用線段長度絕對值）：

```
XA=|A−X|   AB=|A−B|   BC=|C−B|   CD=|C−D|   AD=|A−D|   XC=|C−X|

AB/XA   B 對 XA 段的回撤
BC/AB   C 對 AB 段的回撤
CD/BC   D 對 BC 段的延伸（Carney 稱 "BC projection"）
AD/XA   D 對 XA 段的回撤(<1)或延伸(>1)  ← 各形態的識別鍵
```

> **術語陷阱**：Carney 原文的「a 1.618 BC projection」指 `CD/BC = 1.618`，**不是** `BC/AB`。這是最常見的一階誤讀，本表已全部正規化。

#### 主表（7 種走統一四比例）

| 形態 | AB/XA | BC/AB | CD/BC | **AD/XA**（識別鍵） | 交叉驗證 |
|---|---|---|---|---|---|
| Gartley | 0.618 | 0.382–0.886 | 1.13–1.618 | **0.786** | 4 源 |
| Bat | 0.382–0.50 | 0.382–0.886 | 1.618–2.618 | **0.886** | 4 源 |
| Alternate Bat | 0.382 ⚠️ | 0.382–0.886 | 2.0–3.618 | **1.13** | 2 源 |
| Butterfly | 0.786 | 0.382–0.886 | 1.618–2.618 | **1.27** ⚠️ | 4 源（AD/XA 有分歧） |
| Crab | 0.382–0.618 | 0.382–0.886 | 2.24–3.618 ⚠️ | **1.618** | 4 源（CD/BC 下界有分歧） |
| Deep Crab | 0.886 | 0.382–0.886 | 2.24–3.618 ⚠️ | **1.618** | 3 源（CD/BC 下界有分歧） |
| Shark | *無此約束* ⚠️ | 1.13–1.618 | 1.618–2.24 | **0.886–1.13** | 5 源（AB/XA 三說互斥） |

⚠️ 標記處有來源分歧，處置見下方裁決表。

#### Cypher 走自己的基準（塞進上表必錯）

| 約束 | 值 |
|---|---|
| AB/XA | 0.382–0.618 |
| **XC/XA** | **1.272–1.414** — C 相對 **XA** 段，自 X 起算 |
| **CD/XC** | **0.786** — D 相對 **XC** 段 |

Cypher **不套用 `BC/AB` 約束**：研究 §3.2 的 `BC/AB ∈ [1.44, 2.08]` 是由上述三條**推導**出來的，不是獨立約束。

Cypher 的等效 `AD/XA` 是**推導值 0.697–0.728**，**不是**通說的 0.786。

**此點取得獨立交叉驗證（主對話實跑）**：原版腳本洩漏的 Cypher 樣本實測 `XC/XA = 1.234`、`CD/XC = 0.7763`、`AD/XA = 0.724`。代入恆等式

```
AD/XA = 1 − (XC/XA)·(1 − CD/XC) = 1 − 1.234 × (1 − 0.7763) = 0.72395   （洩漏值 0.724）
```

且 0.724 落在標準定義推得的 `[0.6974, 0.7278]` 內，通說的 0.786 落在區間外。**兩條互相獨立的證據鏈——文獻查證與原版腳本的實際輸出——一致指向 Cypher 的基準是 XC 而非 XA。** 市面上以 `AD/XA = 0.786` 實作 Cypher 的指標（研究指出兩大開源實作皆如此）測的根本不是 Cypher。

#### Shark 的點位映射

Shark 原文使用 `0-X-A-B-C` 命名，映射為**整體右移一位**（`0→X, X→A, A→B, B→C, C→D`）。於是 Carney 的「AB 是 XA 的 1.13–1.618」變成本表的 `BC/AB`，「C 是 0X 的 0.886–1.13」變成本表的 `AD/XA`。

#### 裁決表

| 待決項 | 裁決 | 理由 |
|---|---|---|
| **5-0 是否納入** | **剔除** | 無基準 SL 錨點；fallback 檔位使風險距離達 0.690–1.000 XA（其餘形態 0.142–0.386，差 2–7 倍），結構性 RR1 ≈ 0.5；且 5 點偵測器無法表達其原文的「C 對 0X」約束。留著會以與諧波 edge 無關的理由拖垮合併層 |
| Cypher 是否納入 | **納入**，獨立記帳、verdict 分開列 | 兩條證據鏈已釐清其真實基準；它正是「市面說法建立在錯誤比例上」的最佳案例 |
| Butterfly `AD/XA` 取 1.27 或 1.27＋1.618 | **只取 1.27** | 1.618 變體與 Crab 的識別鍵重疊 |
| Shark 是否加 `AB/XA` 約束 | **不加**（`None`） | 三個來源說法互斥；已由 `BC/AB` 與 `AD/XA` 界定 |
| Alternate Bat `AB/XA`（原文「0.382 或更小」） | **凍結為單點 0.382** 套容差 | 「或更小」無下界。此為**刻意收窄**，verdict 須註明 |
| Crab／Deep Crab 的 `CD/BC` 下界（2.24 vs 2.618） | **取 2.24**（較寬） | `CD/BC` 只作 sanity check 而非判別鍵，取寬者避免因分歧而系統性刪樣本 |
| 原版的 Shark TP 例外（0.5／0.886） | **採用** | v1 判定「不吻合」是幾何重建錯誤。正確解出 `extreme = C` 後 `RR1 = 2.2560` vs 洩漏 `2.26`，通過 M-G0（§6.2） |

**形態集合 = 8 種**：Gartley、Bat、Alternate Bat、Butterfly、Crab、Deep Crab、Shark、Cypher。

#### 一組 XABC 可對應多個形態（M7）

研究實跑的「28 組 pairwise 四軸全重疊為 0」用到了 `AD/XA`——**而 `AD/XA` 涉及 D，在 `as_of` 時不可知**。只看 `as_of` 前可驗的兩軸（`AB/XA`、`BC/AB`），Bat 與 Crab 完全重疊、Gartley 與 Crab 也重疊。

**這是預期行為，不是 bug**：同一組 XABC 對不同形態預測**不同的 D 區**，因此是不同的交易（不同 PRZ、不同 SL、不同 TP）。處置：

- 允許同一 XABC 產生多個形態事件；§4.6 的去重**以 `pattern` 分組，不跨形態合併**。
- 事件表加 `xabc_group_id` 欄。**verdict 必須報告**：多形態 XABC 的比例、以及合併層中來自同一 `xabc_group_id` 的事件佔比。
- §6.5 的 `n_events_IS(p)` 計**事件數**（非唯一 XABC 數），定義見該節。

**判別鍵的結構性事實**（研究 §5）：`CD/BC` 幾乎被其他三條決定，真自由度只有三個。故 `AD/XA` 為主判別鍵（容差收緊），`CD/BC` 設寬區間僅作 sanity check。

### 4.3 PRZ（潛在反轉區）計算

以 bullish 為例（`X` 低、`A` 高、`B` 低、`C` 高，預期 `D` 為低點）：

```
XA = p_A − p_X   AB = p_A − p_B   BC = p_C − p_B   XC = p_C − p_X
```

**`as_of` 前即可檢驗的過濾條件**：

| 形態 | 套用的過濾條件 |
|---|---|
| Shark | 只有 `BC/AB`（`AB/XA` 為 `None`） |
| Cypher | `AB/XA` 與 `XC/XA`（**不套 `BC/AB`**） |
| 其餘 6 種 | `AB/XA` 與 `BC/AB` |

**定義 PRZ 的約束**：

```
由 AD/XA ∈ [ad_lo, ad_hi]  →  D ∈ [p_A − ad_hi·XA , p_A − ad_lo·XA]
由 CD/BC ∈ [cd_lo, cd_hi]  →  D ∈ [p_C − cd_hi·BC , p_C − cd_lo·BC]
Cypher 專用：CD/XC ∈ tol_band(0.786) → D ∈ [p_C − 0.786(1+τ)·XC , p_C − 0.786(1−τ)·XC]

PRZ = 上述所有適用區間的交集
```

| 形態 | PRZ 來源 |
|---|---|
| Gartley、Bat、Alt Bat、Butterfly、Crab、Deep Crab、**Shark** | `AD/XA` ∩ `CD/BC` |
| Cypher | 僅 `CD/XC`（`CD/BC` 無標準約束） |

**若交集為空 → 候選作廢，不產生事件。**

**空交集比例的處置（M11——v2 留了一條事後排除通道）**：逐形態統計空交集比例，**在 IS 上計算**，**寫進 verdict 作為強制揭露**。此數字**不影響任何 gate、不使任何形態退出任何序列**。v2 寫的「> 50% 則排除於總體 `E[R_net]` 之外」已刪除——那會讓人在跑完後把某個形態移出合併層而把 M-G2 從 FAIL 轉成 PASS，完全符合條文字面。

### 4.4 容差

只對**單點目標**加對稱百分比帶，區間型約束不另加容差：

```
單點目標 v      → [v·(1−τ) , v·(1+τ)]
區間目標 [lo,hi] → 原樣使用，不展開
```

| 參數 | 值 | 適用 |
|---|---|---|
| `TOL` | **0.05** | `AB/XA`、`BC/AB`、`CD/BC` 的單點目標 |
| `TOL_AD_XA` | **0.03** | `AD/XA`（及 Cypher 的 `CD/XC`）——**主判別鍵，收緊** |

- 敏感度分析跑 `TOL ∈ {0.03, 0.05, 0.08, 0.10}`（`TOL_AD_XA` 同步取 `0.6 × TOL`），**作為穩健性檢查，不作為最佳化旋鈕**。

**容差判讀規則（數值化）**：令 `ρ_win = Spearman(TOL, 勝率)`、`ρ_R = Spearman(TOL, E[R_net])`（4 個檔位）。

```
若 ρ_win > 0.8 且 ρ_R <= 0  →  記為「容差證偽訊號 = TRUE」
```

依 Tsinaslanidis et al. (2022)，這正是「放寬容差必然拉高勝率而不改善績效」的簽名。此旗標**不改變 gate 判定**，但 verdict **必須**列出這張 4×2 表格與旗標值。（n=4 時 Spearman ρ 只能取少數離散值，「ρ > 0.8」實質等於「單調或只差一次相鄰對調」——作為揭露旗標可接受。）

### 4.5 進場、止損、目標

#### 4.5.1 掛單與成交（bullish；bearish 鏡射）

**前置守門**：若 `close(as_of) <= prz_high`，事件標記 `prz_already_breached`，**不掛單**，納入統計（`R_net = 0`，終止日 = `as_of` 當日）。

> **守門的目的是避免掛單模型退化成無條件市價單**：若 `as_of` 當下價格已在 PRZ 之下，「掛限價買單於 `prz_high`」等同於次棒無條件市價成交，那不是本設計要測的東西。
> 條文只看 `as_of` 收盤價——確認延遲期間 V 型穿越再收回的樣本**不排除**，這是正確的：活的系統在 `as_of` 之前根本不知道這個形態存在，錯過那一段不是偏誤。**不得**改用 `min(low over (t_C, as_of])`，那會多排掉一大批合法樣本。

通過守門者，自 `as_of` 之後第一根 bar 起，於 `prz_high` 掛限價買單，TTL = `TTL_BARS = 30` 根。逐根判定：

```
若 bar.open <= prz_high:                      # 跳空進入或穿越 PRZ
    若 bar.open <= sl: 標記 invalidated_by_gap，不進場，事件終結
    否則: fill = bar.open，進場腿計為 taker（含滑價）
否則若 bar.low <= prz_high:                    # 盤中觸及
    fill = prz_high，進場腿計為 maker（無滑價）
否則: TTL 遞減，繼續等待

TTL 耗盡仍未成交 → 標記 no_fill，事件終結（終止日 = TTL 最後一根的收盤日）
```

跳空成交計 taker 是刻意的保守選擇：那一子集正是「價格已跑過 PRZ」的樣本，多半是輸家。

**成交棒參與出場判定（M10）**：`fill` 所在的那一根 bar **立即納入**出場檢查，優先序同 §4.5.4。若同一根的 `low <= sl`，該筆記為 `sl`（悲觀，−1R 減成本），不論該棒後續是否反彈。

**允許同幣同時多倉（M9）**：本專案是**事件研究**而非組合模擬，每個事件獨立記帳，不套用「一幣一倉」規則。重疊部位在 §6.1 的日報酬序列中相加。**不得**因重疊而丟棄任何事件。

#### 4.5.2 止損：形態常數檔位表

v2 之前的階梯規則 `min{s ∈ S : s > ad_ratio}` **被 fixture 自身反證**（6 筆只中 2 筆）。任何 `ad_ratio` 的單調函數都不可能同時滿足 `0.898 → 1.13`（跳過只差 11% 的 1.0）與 `1.947 → 2.0`（接受只差 2.7% 的 2.0）。能解釋全部 6 筆的假設是：**SL 檔位是形態的常數，與該筆的實際 `ad_ratio` 無關**。

**凍結表** `SL_LEVEL_OVER_XA`：

| 形態 | 檔位 | 出處 | 風險距離（XA 單位） |
|---|---|---|---|
| Cypher | **1.0** | 觀測（`elite_cypher_bullish`） | 0.272–0.303 |
| Bat | **1.13** | 觀測（`base_bat_bullish`） | 0.244 |
| Shark | **1.272** | 觀測（`base_shark113_bearish`） | **0.142–0.386** |
| Butterfly | **1.618** | 觀測（`ultimate_butterfly_bullish`） | 0.348 |
| Deep Crab | **2.0** | 觀測（`elite_deep_crab_bearish` 與 `base_deep_crab_bearish` **兩筆一致**） | 0.382 |
| Gartley | 1.0 | 推導 | 0.214 |
| Alternate Bat | 1.272 | 推導 | 0.142 |
| Crab | 2.0 | 推導（與 Deep Crab 同 `AD/XA`，得同檔位，內部一致） | 0.382 |

**fallback 規則**（僅用於無觀測值的 3 個形態）：

```
S = [1.0, 1.13, 1.272, 1.618, 2.0]
r_sl = min{ s ∈ S : s > 該形態的名目 AD/XA 上界 }      # 1.27 與 1.272 視為相等
```

**該 fallback 對已觀測形態的重現率為 4/5**：Cypher(0.728→1.0)✓、Shark(1.13→1.272)✓、Butterfly(1.27≈1.272→1.618)✓、Deep Crab(1.618→2.0)✓、**Bat(0.886→1.0)✗（觀測 1.13）**。Bat 是已知例外，表中直接採觀測值。此 4/5 是 M-G0d 的斷言目標——防止事後修改 fallback 規則。

**止損價**（**不吃 D**）：

```
sl = p_A − SL_LEVEL_OVER_XA[pattern] × (p_A − p_X)        # bullish；bearish 為加
```

SL 由 `X`、`A` 與形態常數唯一決定，**與成交價無關**。這使得：模式 A 與模式 B、實驗組與對照組的 R 分母**結構性同源**（工程原則 #1），且 v2 的 `sl_planned` / `sl_actual` 二元性消失——事件表只有一個 `sl` 欄。

#### 4.5.3 目標

```
extreme = max(p_X, p_A, p_B, p_C)          # bullish；bearish 取 min
leg     = |extreme − D|                     # D = fill
tp1 = D + f1 · leg ;  tp2 = D + f2 · leg    # bullish；bearish 為減

(f1, f2) = (0.382, 0.618)                   # 標準
(f1, f2) = (0.500, 0.886)                   # Shark 例外（M-G0 已驗證）
```

**注意 `extreme` 常常不是 A**：當 `BC/AB > 1`（Shark）或 `XC/XA > 1`（Cypher）時，C 越過 A 成為極值。v1 因未解出這一點而誤判 Shark 不吻合。實作與測試都必須用幾何重建而非直覺假設。

#### 4.5.4 出場、終局與分批變體

**出場優先序**（棒內，悲觀）：`SL → TP → time-stop`。gap-through 取較差價。`MAX_HOLD_BARS = 100`。

**主設定**：TP1 全出，單一目標。自由度最低；且原版自己承認 Shark 必須 TP1 全平。

**分批變體的 R 記帳（H4——v2 完全沒定義，卻佔 480 格中的 240 格）**：

```
兩腿各 50%。
leg1：出場於 tp1，出場腿 taker。
leg2：TP1 觸及後 SL 移至【損益兩平價】
      breakeven = P_entry · (1 + direction·(fee_in + fee_out + slip_out))
      出場於 tp2 / breakeven / time_stop / censored 之先到者，出場腿 taker。

R_net = 0.5·R_gross(leg1) + 0.5·R_gross(leg2) − cost_R_total

  R_gross(leg_i) = direction · (P_exit_i − P_entry) / |P_entry − sl|
  cost_abs_total = fee_in · P_entry                       ← 進場只收一次，【全額】
                 + 0.5·(fee_out + slip_out) · P_exit1     ← 每個出場腿按其半額收
                 + 0.5·(fee_out + slip_out) · P_exit2
  cost_R_total   = cost_abs_total / |P_entry − sl|

【不得】先把 fee_in 按 50/50 分攤到兩腿、再對每腿的 R_net 各加權 0.5
——那會把 fee_in 乘 0.5 兩次，成本少算一半。
（「每腿各扣【全額】成本再加權 0.5」在數學上等於上式，是合法的等價寫法。）

若 TP1 未觸及即 SL/time_stop/censored → 兩腿同時終結，退化為單一終局（與主設定相同）。
```

**數值錨例（必過的單元測試）**：`P_entry = 100`、`sl = 98`、`P_exit1 = 101`、`P_exit2 = 102`，maker 進場、兩腿皆 taker 出場：

```
gross    = 0.5·(1/2) + 0.5·(2/2) = 0.750000
cost_abs = 0.00015·100 + 0.5·0.00055·101 + 0.5·0.00055·102 = 0.070825
R_net    = 0.750000 − 0.070825/2 = 0.7145875
```

（誤讀成「進場費先 50/50 分攤到每腿、再各加權 0.5」會得 `0.7183375`，差 `0.00375 R`。此錨例即為擋住該誤讀而設——這個變體佔 480 格中的 240 格，沒有錨例的話測試會照實作者自己的讀法寫，抓不到。）

**八種終局**（互斥且窮盡；分批變體的複合終局記為 `(leg1_reason, leg2_reason)` 對）：

| 終局 | `R_net` | 終止日 `term_date` |
|---|---|---|
| `tp1` / `tp2` / `sl` / `time_stop` | 依 §5.3 計算 | 出場日 |
| `no_fill`（TTL 耗盡未成交，**或資料截止時 TTL 未耗盡仍未成交**） | `0` | TTL 最後一根、或資料最後一根的收盤日 |
| `invalidated_by_gap` | `0` | 跳空當日 |
| `prz_already_breached` | `0` | `as_of` 當日 |
| `censored`（資料截止時仍在倉） | 以最後一根收盤 mark-to-market，出場腿 taker | 最後一根收盤日 |

**不得丟棄任何樣本。** `censored` 佔比須寫進 verdict；若 `> 5%` 須另附「排除 censored」的敏感度數字（該敏感度計為一次試驗）。

### 4.6 多尺度去重

**分組規則**（明確為等價關係）：

```
1. 相鄰關係 ~：兩事件 symbol/interval/pattern/direction 相同，
   且 (t_X, t_A, t_B, t_C) 四個時間戳中至少 3 個相同。
2. ~ 不具傳遞性，故取其【連通分量】（transitive closure）作為分組單位。
3. 每組保留一列，tie-break 依序：(a) as_of 最小 (b) pivot_length 最小 (c) event_id 字典序最小。
4. 其餘併入該列的 dedup_merged 計數。
```

**不跨形態合併**（見 §4.2 末段）。去重在事件表層做，先於任何統計。去重前後的事件數都須寫進 verdict。

---

## 5. 回測與記帳

### 5.1 兩種進場模式

| 模式 | 說明 | 成本 |
|---|---|---|
| **A：PRZ 限價（主）** | §4.5.1 的掛單模型 | 進場 maker（跳空則 taker），出場 taker |
| **B：確認後市價** | 等 D 點自身的 pivot 確認後以下一根開盤市價進場 | 兩腿皆 taker |

**模式 B 的 D 點認定**：在同一個 `L` 的正規化交替序列中，取 `C` 之後**第一個**方向正確且價格落在 `[prz_low, prz_high]` 內的 pivot。進場時刻 = `t_confirm(idx_D)`，成交於其後第一根 bar 的開盤。若 TTL 內不存在這樣的 pivot → `no_fill`。**不允許挑選最合適的 D**。

**兩模式的 SL 相同**（`sl` 由 §4.5.2 決定，不吃成交價），故兩者的差距可以乾淨地歸因到「等待確認的代價」，不被記帳基準汙染。

**不沿用 `scalp_backtest_lib.simulate()`**（M9）：該函式是「次棒開盤市價成交」模型、P&L 以 bps 計、兩腿同費率、且強制一幣一倉不重疊——三項都與本設計牴觸。本專案自行實作 `m_backtest.simulate_event()`，只**借用其悲觀慣例**（棒內 SL 優先於 TP、gap-through 取較差價），不借用程式碼。

### 5.2 成本

```
taker = 0.00045   # 4.5 bps/side   — scripts/scalp_fee_check.py:18
maker = 0.00015   # 1.5 bps/side   — scripts/scalp_fee_check.py:19
slip  = 0.0001    # 1 bp/side，僅在 taker 腿支付 — scripts/cta_l_stage1.py:68
壓力情境：fee ×1.5、slip ×1.5（scripts/cta_l_stage1_runs.py:57-60 慣例）
```

**註**：`data/scalp/fees.json` 的 `"source": "default"`——這是預設費率而非實測帳戶費率，verdict 須註明。

### 5.3 R-multiple

```
R_gross = direction · (P_exit − P_entry) / |P_entry − sl|
cost_abs = fee_in · P_entry + (fee_out + slip_out) · P_exit        # 各腿乘各自成交價
cost_R   = cost_abs / |P_entry − sl|
R_net    = R_gross − cost_R
```

**數值錨例（必過的單元測試）**：bullish，`P_entry = 100`、`sl = 98`、`P_exit = 103`，模式 A 盤中成交：

```
R_gross  = 3 / 2 = 1.5
cost_abs = 0.00015·100 + (0.00045 + 0.0001)·103 = 0.015 + 0.05665 = 0.07165
cost_R   = 0.07165 / 2 = 0.035825
R_net    = 1.464175
```

**兩個指標都要報**：`E[R_net]`（無條件，三種 R=0 終局計入分母）與 `E[R_net | filled]`。**但 gate 只認 §6.1 的 `r_d`**——兩者不是同一個量，verdict 引用時不得混用。勝率只是附註。

### 5.4 匹配隨機對照組

**只為通過 §4.5.1 前置守門的事件生成對照**（M3）。被 `prz_already_breached` 排除的事件不進入 M-G3 的任一臂（但仍計入 M-G2 與 `E[R_net]`）——這使兩臂的事件集合同源。

對每個合格事件 `e` 生成 `K = 5` 個對照：

- 同 `symbol`、`interval`、`direction`、`pattern`
- **`as_of' = as_of + δ`，`δ` 自 `{131 .. 300}` 根 bar 均勻抽樣（只取正向）**
  - 下界 `131 = TTL_BARS(30) + MAX_HOLD_BARS(100) + 1`，確保完整曝險窗不與原事件重疊
  - **只取正向**以消除前視：負 δ 的對照，其價格比值取自 `as_of`（在 `as_of'` 之後）
- 觸發價、`sl`、`tp` 按**相對距離**平移：以 `close(as_of')` 為錨，保持 `prz_high / close(as_of)`、`sl / close(as_of)`、`tp / close(as_of)` 三個比值不變
- **成交後不重算 SL/TP**；實驗組的 `sl` 同樣不依賴 `fill`——**兩臂 R 分母構造規則同源**
- TTL、成交規則（含跳空計 taker、成交棒參與出場判定）、終局、成本、記帳全部相同
- 窗口超出資料範圍則重抽，最多 10 次；仍失敗則捨棄，**該事件的對照權重改用 `1/K_actual`**（M3），捨棄數寫進 verdict

隨機種子 `SEED = 20260806` 寫死於 `scripts/m_config.py`。

**日曆對齊（M4）**：對照事件的日報酬記在 **`term_date − δ_e`**（`δ_e` 換算為日數），使對照臂與其配對的實驗事件落在**同一條日曆**上。兩臂序列因此等長且逐日對齊，可直接餵配對 stationary bootstrap。**不得**用 union 補零或 intersection 截斷——那會系統性壓低或抬高對照臂的均值。

---

## 6. 預註冊 GO/NO-GO gate

> 本節在跑任何回測**之前**凍結。所有門檻寫成顯式方程式並附**可機器驗證的數值錨例**——2026-07-13 的 L 案事故（MDD 分母兩種合法讀法使同一份結果 PASS/FAIL 相反，劣定義活過四道審查）就是散文式定義造成的。

### 6.1 共用序列與統計量定義（所有 gate 的唯一輸入）

**M-G2、M-G3、M-G4 全部在同一條日報酬序列上計算。**

```
RISK_PER_TRADE = 0.01                       # 每筆固定承擔權益 1%
r_d = 0.01 × Σ{ R_net(e) : term_date(e) = d }
      當日無事件終止者 r_d = 0
序列範圍：該設定第一個 term_date 至最後一個 term_date（UTC 日曆日，連續填滿）
```

**三種** `R_net = 0` 的終局（`no_fill`、`invalidated_by_gap`、`prz_already_breached`）**照樣進入序列**（貢獻 0），故 `r_d` 與 `E[R_net]` 的分母一致。

**對照臂的序列**用同一條式子，但每筆對照的貢獻乘 `1/K_actual(e)`（§5.4），使兩臂的每日總曝險可比。

**隨機性**：stationary bootstrap 的 RNG 以 `SEED = 20260806`（§5.4 同一常數）初始化，每個 gate 各自以 `(SEED, gate_id)` 衍生子種子，確保可複現且各 gate 互不干擾。

**`lower_95` 的定義（H1）**：

```
lower_95(θ) := numpy.percentile(boot, 5.0)
               boot = 對 θ 做 B = 10000 次 stationary bootstrap 得到的統計量分布
               單尾 95%（第 5 百分位），percentile method，numpy 預設線性插值
```

**數值錨例（必過的單元測試）**：

```
boot = numpy.arange(10000)/10000 - 0.2
lower_95 = numpy.percentile(boot, 5.0) = -0.150005      # 絕對誤差 < 1e-9
```

- **Sharpe 一律用未年化的日 Sharpe** `sr = mean(r_d) / std(r_d, ddof=1)`，與 [`scripts/k_gates_eval.py:90`](../../../scripts/k_gates_eval.py) `deflated_sharpe` 內部的 `daily_sr`（同樣 `ddof=1`、未年化）同基準。
  - **不得餵年化 Sharpe**：該函式內部用未年化日 SR，餵年化值會讓 `sr_star` 大 √365 ≈ 19 倍 → M-G4 恆定 FAIL，與策略好壞無關（工程原則 #1）。
  - 年化 Sharpe（`× √365`，crypto 24/7）**僅供 verdict 敘述**，不進入任何 gate。報告時須註明年化因子為 365 而非 [`src/hlvault/metrics.py:9`](../../../src/hlvault/metrics.py) 的 252。
- **stationary bootstrap**：`B = 10000`，`expected_block = 20`（日），沿用 [`scripts/cta_l_stage1_gates.py:148`](../../../scripts/cta_l_stage1_gates.py) `stationary_bootstrap_indices(n, B, expected_block, seed)`（`p = 1/expected_block`，重抽單位即傳入序列）。

### 6.2 前置條件（不過 = 實作有 bug，不是策略結論）

#### M-G0 基準忠實度

**fixture 實況**（兩輪審查各自實跑確認）：6 個樣本中僅 2 個有完整 XABCD 絕對價格，且**沒有任何樣本印出絕對 SL/TP 值**。故不能用「重算 SL/TP 與 `expected` 比對」——那些欄位全為 `null`。

**幾何重建**（正規化到單位座標；bullish，bearish 鏡射後比例相同）：

```
X = 0 , A = 1                              (XA = 1)
B = 1 − ab_xa
C = B + bc_ab · ab_xa                      (若樣本有 xc_xa 則 C = xc_xa)
D = 1 − ad_xa
extreme = max(0, 1, B, C)
risk = |SL_LEVEL_OVER_XA[pattern] − ad_xa|
leg  = |extreme − D|
RR1  = f1 · leg / risk ,  RR2 = f2 · leg / risk
```

**fixture 標籤 → 形態鍵對照**（L2）：`"Shark 113" → "shark"`、`"Deep Crab" → "deep_crab"`、`"Cypher" → "cypher"`、`"Bat" → "bat"`、`"Butterfly" → "butterfly"`。

**四項斷言**：

| ID | 斷言 |
|---|---|
| **M-G0a** | `scripts/m_config.py` 的 `SL_LEVEL_OVER_XA` 中標為「觀測」的 5 個條目，逐一等於 fixture 對應樣本的 `sl_level_over_xa`。**測試必須 `import` `m_config`，不得複製常數**（L1；否則 guard 形同虛設） |
| **M-G0b** | **捨入區間重疊判準**（M2）：對每個 leaked 比例輸入施加 `±0.0005`（3 位小數）擾動求 RR 的可能區間 `[RR_min, RR_max]`；對 leaked 的 RR 施加 `±0.005`（2 位小數）得 `[RR_lk_lo, RR_lk_hi]`。要求**兩區間重疊**。全部 6 個樣本、9 項 RR 檢定皆須通過 |
| **M-G0c** | 2 個有座標的樣本，從 `points` 的**絕對價格**推導：`|ad_xa_calc − ad_xa_leaked| < 0.002` 且 `|risk%_calc − risk%_leaked| < 0.01`。**這是唯一端到端、不依賴洩漏中間量的驗算，必須實作** |
| **M-G0d** | §4.5.2 的 fallback 規則對 5 個觀測形態的重現率**恰為 4/5**（Bat 為已知例外） |

**為什麼 M-G0b 不能用絕對容差 0.01**：`base_deep_crab_bearish` 的止損距離趨近零（D 在 1.947 XA、SL 檔位 2.000 XA），輸入第 3 位小數的捨入即讓 RR1 在 **13.8984 – 14.1704** 之間移動（半寬 0.136）。忠實的重實作會從自己偵測到的座標算 `ad_xa`，幾乎不可能落在 `14.04 ± 0.01`——會誤判「公式逆向工程有誤」而作廢一個正確的實作。

**基線已驗證通過（9/9 項 RR 檢定，區間重疊判準）**：

| 樣本 | extreme | (f1,f2) | RR1 重建區間 | RR1 洩漏 | 結果 |
|---|---|---|---|---|---|
| `elite_cypher_bullish` | C | (0.382, 0.618) | [1.3221, 1.3297] | 1.33 | PASS |
| `elite_deep_crab_bearish` | A | (0.382, 0.618) | [1.1756, 1.1788] | 1.18 | PASS |
| `base_bat_bullish` | A | (0.382, 0.618) | [1.4746, 1.4826] | 1.48 | PASS |
| `base_deep_crab_bearish` | A | (0.382, 0.618) | **[13.8984, 14.1704]** | 14.04 | PASS |
| `base_shark113_bearish` | **C** | **(0.500, 0.886)** | [2.2503, 2.2617] | 2.26 | PASS |
| `ultimate_butterfly_bullish` | A | (0.382, 0.618) | [1.3915, 1.3966] | 1.39 | PASS |

M-G0c 的絕對驗算亦通過：cypher `ad_xa` 0.7239/0.724（d=0.00012）、`risk%` 0.8559/0.86（d=0.00412）；deep crab `ad_xa` 1.5103/1.51（d=0.00032）、`risk%` 2.6153/2.62（d=0.00469）。

**Shark 的更正紀錄**：v1 判定 Shark「在任一組係數下都不吻合」，實為幾何重建錯誤——Shark 的 `bc_ab = 1.721 > 1` 使 C 越過 A（與 Cypher 的 `xc_xa = 1.234 > 1` 同構），`extreme` 必須是 C。四種組合實跑：`(A,0.382)→1.2651`、`(A,0.500)→1.6559`（v1 誤採）、`(C,0.382)→1.7235`、**`(C,0.500)→2.2560 = PASS`**。

M-G0 任一項不過 → 公式逆向工程有誤，作廢重來。

#### M-G1 無前視

`tests/test_m_nolookahead.py` 全綠。**截斷式斷言**（H3：v2 的版本方向錯誤，假設「截斷後事件必然變少」，而合併規則的 look-ahead 恰好會讓事件**復活**）：

```
對任意截斷時刻 T：把 close_time > T 的所有 K 線刪除，重跑【偵測 + 回測】。

斷言 1（偵測層，在【去重前】的事件表上評估）：
    兩次執行中【所有 as_of <= T 的事件】構成的集合完全相同，且每一列逐欄位相同。
    不得有事件消失，【也不得有事件出現】。

斷言 2（回測層）：對【term_date <= T】的交易（term_date 取【完整跑】的值），
    fill / sl / exit_reason / R_net / term_date 逐欄位相同。
```

**為什麼斷言 1 必須在去重前評估**：去重的連通分量會因截斷而裂開，使事件「憑空出現」——例如 `E_a=(x,a,b,c1)`、`E_b=(x,a,b,c2)`、`E_c=(x,a,b2,c2)` 三者由 `E_b` 串成一個分量，若 `as_of(E_c) <= T < as_of(E_b)`，截斷後 `E_b` 消失、分量裂成兩個，原本被合併掉的 `E_c` 就會出現。**那是去重的預期行為，不是 look-ahead。**

**為什麼斷言 2 只涵蓋 `term_date <= T`**：曝險窗達 `TTL + MAX_HOLD = 130` 根，`term_date > T` 的交易在截斷跑裡必然變成 `censored` 或未成交——對它們斷言相同會讓**正確的實作必然失敗**，逼實作者去追不存在的 bug 或自行放寬斷言。

T 取序列的 25% / 50% / 75% 分位各測一次。對照組平移（§5.4）套用同一組斷言。

### 6.3 判定 gate

**每個 gate 恰好對 M-G2 變動一個維度**（期間／幣種／成本／對照），評估樣本逐格寫明、無「見各 gate」這類循環定義：

| ID | 判準（方程式） | 期間 | 幣種 | 成本 |
|---|---|---|---|---|
| **M-G2** 絕對期望 | `lower_95(mean(r_d)) > 0` | **全期** `2020-07-01 ~ 2026-06-30` | 全部 | 標準 |
| **M-G3** 優於隨機 | `lower_95(mean(r_d^pattern) − mean(r_d^control)) > 0`，配對 stationary bootstrap，日曆對齊見 §5.4 | **全期** | 全部 | 標準 |
| **M-G4** 試驗數校正 | `deflated_sharpe(sr_list, primary_returns, N_TRIALS_DECLARED)["psr"] >= 0.95`（[`scripts/k_gates_eval.py:238`](../../../scripts/k_gates_eval.py) 的實際 gate） | **OOS**（`sr_list` 與 `primary_returns` 皆取 OOS，沿用 K 案先例） | 全部 | 標準 |
| **M-G5** 時間樣本外 | M-G2 的式子成立 | **OOS** `2024-01-01 ~ 2026-06-30`（IS 為 `2020-07-01 ~ 2023-12-31`）。**OOS 只跑一次** | 全部 | 標準 |
| **M-G6** 幣種樣本外 | M-G2 的式子成立 | 全期 | **`hash%2 == 1` 的 holdout 半** | 標準 |
| **M-G7** 成本壓力 | M-G2 的式子成立 | 全期 | 全部 | **fee ×1.5、slip ×1.5** |

**M-G4 的 `sr_list` 組成（必須釘死）**：

```
sr_list = §6.4 主網格 480 個 cell 各自的【OOS 未年化日 Sharpe】
N_OBSERVABLE_TRIALS = 480      # 產生可觀測 Sharpe 的 cell 數
N_TRIALS_DECLARED   = 487      # 含 7 個不產生獨立 cell Sharpe 的重跑
實作須 assert len(sr_list) == N_OBSERVABLE_TRIALS == 480
```

[`scripts/k_gates_eval.py:92-96`](../../../scripts/k_gates_eval.py) 的 docstring **明文允許** `len(sr_list) != n_trials`，K 案為此另立 `N_OBSERVABLE_TRIALS` 常數與 assert，本專案照辦。

**為什麼這條不能留白**：`sr_star = 3.0446 × sd(sr_list)`（`n_trials = 487` 實算）。只放 48 個合併層 cell（`sd ≈ 0.008`）→ `sr_star ≈ 0.024`；放全部 480 個（`sd ≈ 0.040`）→ `sr_star ≈ 0.122`。**而日 Sharpe 本身就是 0.03–0.06 量級——`sr_list` 的組成直接把 M-G4 從必過變成必不過**，卻完全不涉及策略好壞。

**primary 設定（H2，完整凍結，無留白）**：

```
interval = 1h        # ← v2 遺漏的維度，現凍結
TOL      = 0.05  (TOL_AD_XA = 0.03)
進場模式 = A
出場     = TP1 全出
形態層   = 全 8 形態合併
```

`interval = 1h` 的理由（預註冊）：4h 在單幣上形態過於稀少；15m 的 Binance/HL 波幅保真度最差且對成本假設最敏感；1h 是樣本數與雜訊的折衷。**此為在看到任何結果之前的選擇。**

### 6.4 `N_TRIALS_DECLARED = 487`

```
主網格： 10 × 4 × 3 × 2 × 2 = 480
         └ 10 = 8 個形態 + 1 個「全形態合併」層（primary 本身）+ 1 個 selected 子集層（§6.5）
         └  4 = TOL ∈ {0.03, 0.05, 0.08, 0.10}
         └  3 = interval ∈ {15m, 1h, 4h}
         └  2 = 進場模式 A / B
         └  2 = 出場變體（TP1 全出 / 分批）
消融：   + 2   （在 primary 設定的事件表上做兩組切片，於此明確定義：
                 (i)  只留實際 |ratio_ad_xa − 名目值| / 名目值 <= 0.03 的事件
                 (ii) 只留 D 落在 X 之外的形態（AD/XA > 1：Alt Bat、Butterfly、Crab、Deep Crab）
                      對照 D 落在 X 之內者（AD/XA < 1：Gartley、Bat、Cypher；Shark 跨界，歸「之外」）
穩健性： + 2   （§6.7 端點 ±7 天）
         + 2   （M-G6 的兩個幣種半樣本）
         + 1   （M-G7 的 fee×1.5 重跑）
─────────────────────────────
合計     487
```

不計入的項目：M-G3 的隨機對照組（那是對照，不是候選策略）。

**事後新增任何設定都必須重新宣告並重跑 M-G4**——這正是原版讓使用者自由轉旋鈕卻不計代價的地方。

### 6.5 IS/OOS、分半與「選擇」

**歸屬鍵**：事件依 **`as_of`** 歸屬 IS 或 OOS。`as_of` 在 IS 而終止在 OOS 的事件**屬 IS**。此規則凍結，改動一次等同偷跑一次 OOS。

**幣種分半**：`int(sha256(symbol.encode("utf-8")).hexdigest(), 16) % 2`，`symbol` 是 **Binance 的 USDT 永續 symbol 字串**（如 `"BTCUSDT"`、`"1000PEPEUSDT"`），編碼固定 UTF-8。**`== 1` 的那一半是 holdout**（M-G6 在其上評估），`== 0` 的那一半僅供診斷。

**「選擇」的定義**：§4 與 §5 的**所有參數已在本文件凍結**，IS 階段**不做任何參數選擇**。唯一允許的「選擇」是形態子集，規則預註冊且可機器執行：

```
n_events_IS(p) := 該形態在 IS 上【去重後】的事件數，
                  【包含三種 R_net = 0 的終局】
                  （no_fill / invalidated_by_gap / prz_already_breached）

selected = { p : n_events_IS(p) >= 30  且  lower_95(mean(r_d^{p,IS})) > 0 }
```

OOS 上**同時**評估並**都寫進 verdict**：(a) 全 8 形態合併；(b) `selected` 子集。**判定以 (a) 為準**，(b) 僅作為「篩選是否有效」的診斷。這杜絕了「跑完 IS 挑贏家再宣稱 OOS 通過」。

### 6.6 判定表

| 結果 | verdict |
|---|---|
| M-G2 ~ M-G7 全過 | **GO** |
| M-G2 過、**M-G3 不過** | **NO-GO** — 形態不優於隨機進場。這正是 Tsinaslanidis et al. (2022) 對 Fib 成分的預測 |
| M-G2、M-G3 過，**M-G4 不過** | **NO-GO（多重檢定未通過）** — 487 個試驗的搜尋規模下，單一設定的正期望值無法與運氣區分 |
| M-G2、M-G3、M-G4 過，**M-G5 或 M-G6 不過** | **NO-GO（過擬合）** |
| M-G2~G6 過，**M-G7 不過** | **NO-GO（成本邊際）** — edge 存在但被交易成本吃掉 |
| M-G2 不過 | **NO-GO** |
| M-G0 或 M-G1 不過 | 非結論——修 bug 後重跑 |

**任何 gate 失敗都不得由作者裁量覆蓋。** 上表沿 `G2 → G3 → G4 → (G5|G6) → G7` 逐層分支，窮盡且互斥。若出現表中未列的組合，視為 spec 缺陷，須在 verdict 記錄並停止判定，不得自行補規則。

### 6.7 硬性規定

- **回測窗口兩端都硬編**於 `scripts/m_config.py`（M14）：資料抓取終點固定 `2026-06-30T23:59:59Z`，**不得使用 `datetime.now()`**；事件過濾 `2020-07-01T00:00:00Z <= as_of <= 2026-06-30T23:59:59Z`。（2026-07-12 momentum 教訓：端點差 9 天使兩年 Sharpe 從 0.57 掉到 0.18。v2 只釘了左端點。）
- **端點敏感度**：GO 級結論前把 IS/OOS 分界點移動 ±7 天各跑一次。**評估的是 M-G5 的 OOS 序列**（分界點移動只改變 OOS 的組成，M-G2 的全期序列不受影響）。**「翻盤」的定義**：`lower_95(mean(r_d^OOS))` 在 ±7 天的任一設定下**變號**。翻盤 → verdict 由 GO 降為 NO-GO（厚尾雜訊，非 edge）。
- 所有凍結參數在**第一次跑回測之前**定案。任何事後修改必須在 verdict 揭露並重新計算 `N_TRIALS_DECLARED`。

---

## 7. 資料層

### 7.1 幣種宇宙：point-in-time 季度輪換

**沿用 [`scripts/k_data_layer.py:157`](../../../scripts/k_data_layer.py) `build_pit_universe()` 的邏輯，但不直接呼叫該函式**（M8）——它的門檻硬編（`min_volume = 100e6`、`[:8]`）、季度迴圈止於 2026-Q1、且讀 `data/k_framework/klines/*_1d.csv.gz`。本專案在 `scripts/m_data.py` 實作 `build_pit_universe_m()`，複製其邏輯並：

- 門檻參數化為 **trailing 90 日中位 quote volume ≥ $50M、上市 ≥ 180 天、每季 top 30**
- 季度迴圈延伸至 **2026-Q2**（否則 OOS 尾端三個月無幣單，而 verdict 卻宣稱涵蓋到 2026-06-30）
- **1d K 線自行抓取**至 `data/cache/harmonic_m/{SYMBOL}_1d.parquet`（PIT 篩選需要，v2 未交代來源）

**必要性**：直接取「今天還活著且流動性好的幣」跑 2020–2026 會吃到嚴重**倖存者偏誤**。PIT 宇宙只用每季開始**之前**的資料決定當季幣單。

（K 案用 $100M / top 8；本專案放寬是為了樣本數——諧波形態在單幣單週期上稀少。此為預註冊選擇。放寬會納入滑價較差的中小幣，故 M-G7 對本專案格外關鍵。）

流動性以 **quote volume（USDT 名目）** 計，非幣本位 volume——見 [`scripts/k_data_layer.py:53`](../../../scripts/k_data_layer.py) `binance_rows_to_df_qv()` 的踩坑註記。

**事件成員資格（v3.3 預註冊，final review F1）**：事件只在「其 symbol 於 `as_of` 所屬季度在宇宙內」時計入普查統計與所有 gate。聯集跑全歷史會讓約六成事件來自幣種不在宇宙的期間（含早於首次入選者）——那些歷史因幣種後來入選而被觀察到，帶有選擇偏誤。事件表全量保留並附 `in_universe` 欄供診斷；宇宙 schedule 落檔 `data/cache/harmonic_m/universe_schedule.json`，Stage 2 由此重建成員資格，**不得重打 exchangeInfo**（現存 symbol 清單隨時間漂移，重打會引入新的時點污染）。普查報告須同時揭露全量與宇宙內兩組數字。

### 7.2 K 線資料

- 來源：**Binance USDT 永續**（HL candleSnapshot 每 interval 僅保留最近 ~5000 根，1h ≈ 208 天，拿不到 2020 年）
- interval：`15m` / `1h` / `4h`（回測）＋ `1d`（PIT 宇宙）
- **抓取窗口硬編 `2020-01-01T00:00:00Z ~ 2026-06-30T23:59:59Z`**；PIT 篩選需要 2020 上半年的 trailing 窗，但**事件與統計只計 `as_of >= 2020-07-01`**。
- 抓取：沿用 [`scripts/cta_proxy_pull_data.py:79`](../../../scripts/cta_proxy_pull_data.py) `pull_klines(symbol, interval)` 的分頁邏輯，但**終點必須傳入固定時間戳**，不得沿用其模組級的 `datetime.now()`
- 幣名映射：[`scripts/scalp_lib.py:121-127`](../../../scripts/scalp_lib.py)，含 `kPEPE → 1000PEPEUSDT` 等 override
- 快取：`data/cache/harmonic_m/{SYMBOL}_{interval}.parquet`（`data/cache/` 已在 `.gitignore`）
- HL 的角色：僅用 [`scripts/scalp_lib.py:77`](../../../scripts/scalp_lib.py) `universe_ctxs()` 界定「HL 實際可交易」，以及保真度交叉驗證

---

## 8. 測試策略

全部**離線、零網路**（工程原則第 4 條）。沿用 [`tests/test_scalp_backtest.py`](../../../tests/test_scalp_backtest.py) 的 `sys.path.insert(0, "scripts")` + 合成 bar 慣例。

| 測試檔 | 驗什麼 |
|---|---|
| `tests/test_m_patterns.py` | 比例完美的 Gartley 必須被偵測；`AD/XA` 偏離 20% 必須不被偵測；PRZ 交集為空必須作廢；同一 XABC 同時滿足 Bat 與 Crab 前置過濾時**必須產生兩個事件**（§4.2 末段） |
| `tests/test_m_pivots.py` | §4.1.1 因果式合併：X/A/B 取封閉段極值；C 取 running extreme；同段後續出現更極端 pivot 時**產生新候選而非修改舊事件**；頭尾 `L` 根不判定 pivot |
| `tests/test_m_nolookahead.py` | **M-G1 截斷式斷言**（§6.2）：三個分位點各測一次。偵測層在**去重前**的事件表上比對 `as_of <= T` 的事件集合（**不得有增有減**）；回測層**只對 `term_date <= T`**（取完整跑的值）的交易斷言欄位全同 |
| `tests/test_m_baseline_formula.py` | **M-G0 四項斷言 a/b/c/d**。必須 `import scripts.m_config` 取 `SL_LEVEL_OVER_XA`（不得複製常數）；M-G0b 用捨入區間重疊；**M-G0c 必須從 `points` 絕對座標推導**（不得吃洩漏的 `ad_xa`） |
| `tests/test_m_rmultiple.py` | §5.3 單腿錨例 `R_net == 1.464175` 與 **§4.5.4 分批錨例 `R_net == 0.7145875`**（皆絕對誤差 < 1e-9）；分批須另驗「fee_in 只全額收一次」——把它 50/50 分攤再各加權 0.5 會得 `0.7183375`，測試必須拒絕該值；**三種** R=0 終局計入分母且有 `term_date`；`censored` mark-to-market；breakeven 定義 |
| `tests/test_m_dedup.py` | §4.6 連通分量：`e1~e2`、`e2~e3` 但 `e1≁e3` → 併為一列且 `dedup_merged == 2`；tie-break 三段各一例；**不同 `pattern` 不得合併** |
| `tests/test_m_stats.py` | §6.1 `lower_95` 錨例 `-0.150005`（絕對誤差 < 1e-9）；`sr` 用 `ddof=1`；對照臂日曆對齊後兩序列等長 |

---

## 9. 交付物

| 檔案 | 內容 |
|---|---|
| `scripts/m_config.py` | **全部凍結參數**：比例表、兩級容差、pivot 尺度、TTL、MAX_HOLD、`SL_LEVEL_OVER_XA`、TP 係數、primary 設定（含 `interval = 1h`）、時間窗兩端、成本、SEED、`N_TRIALS_DECLARED = 487` |
| `scripts/m_data.py` | `build_pit_universe_m()` + K 線抓取與快取（含 1d） |
| `scripts/m_detect.py` | 因果式 pivot 正規化 + 偵測器 → 事件表 |
| `scripts/m_backtest.py` | `simulate_event()` → trades → R-multiple → 日報酬序列 |
| `scripts/m_control.py` | 匹配隨機對照組（含日曆對齊） |
| `scripts/m_gates.py` | M-G0 ~ M-G7 評估與判定表輸出 |
| `tests/test_m_*.py` | §8 七個測試檔 |
| `reports/harmonic-m-verdict.md` | 最終判定 |
| `reports/m-baseline-tv-script-analysis.md`、`reports/m-harmonic-evidence-review.md`、`scripts/m_pattern_ratios_research.md`、`tests/fixtures/m_tv_baseline_samples.json` | 已落檔 |
| `scripts/m_verify_baseline.py` | M-G0 參考實作（**須依 §8 補上 M-G0c 並改為 import m_config**） |

---

## 10. 風險與已知限制

**必須寫進 verdict 的限制**：

1. **先驗為負**。證據回顧指向 NO-GO。成功定義是取得可信判定。verdict 措辭須區分「已被實測否定」與「基於成分證偽的先驗」。
2. **Binance proxy 保真度未實測**。CLAUDE.md 記載 HL/Binance **1m** 波幅保真比 0.7–0.9、小幣更低，對訊號幅度是樂觀偏差。15m/1h/4h 應更高但**未實測**。
3. **PIT 宇宙以 Binance 資料定義**，與 HL 實際可交易幣種不完全重合；top 30 / $50M 的放寬會納入滑價較差的中小幣。
4. **TP/SL 公式來自對閉源腳本的逆向工程**。錨點強度已量化（§6.2）：6 個樣本、9 項 RR 檢定全數通過（捨入區間重疊判準），2 個另有絕對價格可驗。**但 SL 檔位表只有 5 個形態有觀測值，另 3 個是 fallback 推導**；fallback 本身對觀測值只重現 4/5。verdict 不得宣稱「完全複製原版」。
5. **Shark 的 SL 常數只在其 `AD/XA` 區間的一端被驗證**（M12）。Shark 的 `AD/XA` 是**區間** 0.886–1.13，風險距離因此在 **0.142–0.386 XA** 之間變動（差 2.7 倍）；唯一的錨點樣本 `ad = 0.977` 落在中間。且 Shark 的 PRZ 寬度約是單點型形態的 3–5 倍，實際成交多落在 `prz_high`（`ad` 最小、風險最大）那一端——**錨點對實際被回測的 Shark 樣本不具代表性**。
6. **比例表本身是假設，不是事實**。§4.2 的數值即使多來源交叉驗證，仍可能與原版腳本實際使用的比例不同（原版頁面完全沒有出現任何 Fibonacci 數字）。本專案測的是**教科書定義的諧波形態**，不是「原版腳本的複製品」——verdict 不得宣稱「已證明原腳本無效」。
7. **M-G0 的最鋒利錨點落在回測不會進入的區域**（O5）。`base_deep_crab_bearish` 的 RR=14.04 來自 `ad = 1.947`，而容差把 Deep Crab 的 `ad` 鎖在 `1.618 ± 3%`，風險距離恆 ≥ 0.33 XA。該錨點驗證的是公式，不是回測會遇到的情境。
8. **形態稀少性**。若去重後某些形態在 OOS 上樣本數 < 30，該形態的個別結論不成立，只能併入總體判定；verdict 必須逐形態列出樣本數。
9. **一級來源未取得**。Carney 的《Harmonic Trading》Vol. 1–3 原文未取得；Shark 的完整比例靠 5 個二級來源交叉確認。
10. **Alternate Bat 的定義被刻意收窄**（原文「0.382 或更小」→ 單點 0.382 加容差），Crab／Deep Crab 的 `CD/BC` 下界取較寬的 2.24。兩者皆為 §4.2 的預註冊選擇。
11. **5-0 已剔除**（§4.2 裁決表）。這使本專案的結論不涵蓋 5-0；verdict 不得宣稱「所有諧波形態皆無效」。
12. **對照組只用正向 δ**。這消除了負向平移的前視污染，但對照組在時間上系統性晚於實驗組（1h 下 5.5–12.5 天）；若市場 regime 有強趨勢，兩臂可能落在不同 regime。verdict 須報告兩臂的日期分布重疊度。
13. **對照組未匹配波動率 regime**（O7）。低波期的對照成交率會系統性偏低，與 M3 是同一機制的另一面。verdict 須報告兩臂的成交率。
14. **同一 XABC 可產生多個形態事件**（§4.2 末段）。合併層對同一段行情可能重複記帳；verdict 必須報告多形態 XABC 佔比與同 `xabc_group_id` 事件在合併層的佔比。

---

## 附錄：與原版的逐項對照

| 原版缺陷 | 本設計 | 章節 |
|---|---|---|
| repaint：D 成形後回頭改寫點位 | 前瞻式 PRZ 掛單；`as_of` 欄位 + 截斷式 mutation test | §4.1、§4.3、M-G1 |
| pivot 序列非交替時的合併未定義 | 因果式合併（X/A/B 用封閉段極值、C 用 running extreme、後續更極端者另發新候選） | §4.1.1 |
| 多 pivot length 重複計數 | 連通分量去重 + 三段 tie-break | §4.6 |
| `TP1%+SL%=100%`，丟棄未結案樣本 | 八種終局全數納入，`censored` 亦 mark-to-market；R=0 事件有 `term_date` 進入日序列 | §4.5.4、§6.1 |
| 等權計次，R:R 0.12~14.04 混算 | R-multiple 記帳，各腿手續費乘各自成交價；分批變體有明確的兩腿加權定義 | §5.3、§4.5.4 |
| 容差是可轉的旋鈕，表用最寬端產生 | 兩級容差凍結；容差證偽訊號以 Spearman ρ 數值化並強制揭露 | §4.4 |
| 無樣本外、無試驗數校正 | 時間 OOS + 幣種 OOS（holdout 指定為 hash==1）+ DSR（487 試驗，含 primary、selected 層、消融與穩健性重跑） | §6.3~6.5 |
| 無成本 | taker/maker/滑價 + ×1.5 壓力；跳空成交計 taker | §5.2、M-G7 |
| 單幣單週期數百筆樣本 | PIT 宇宙 30 幣 × 3 週期 × 6 年 | §7.1 |
| 倖存者偏誤 | PIT 季度輪換宇宙，季度延伸至 2026-Q2 | §7.1 |
| 無對照組，只跟 0 比 | 匹配隨機對照組為核心判準，兩臂 R 分母與事件集合同源、日曆對齊 | §5.4、M-G3 |
| 使用者可事後轉旋鈕挑好結果 | 全參數凍結（含 primary 的 `interval`）；IS 不做參數選擇；判定表窮盡且禁止裁量覆蓋；空交集比例改為純揭露 | §6.3、§6.5、§6.6、§4.3 |
