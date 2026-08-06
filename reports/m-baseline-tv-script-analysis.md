> **Sub-project M 背景研究**｜產出日期：2026-08-06｜作者：Claude subagent（Opus 5）
> 本報告為 sub-project M（諧波形態策略）的證據基礎，非最終 verdict。
> 研究方法與來源見內文；所有結論以內文標註的來源為準，未標來源者為推論。

# `<Elite> Auto Harmonic Patterns [Trader-Alex]` — 規格調查

調查日期 2026-08-06。目標 URL：
https://www.tradingview.com/script/DSk4XN5m-Elite-Auto-Harmonic-Patterns-Trader-Alex/

**證據標記約定**：`【頁面】` = 腳本頁 description 原文；`【洩漏】` = 從頁面內嵌的
chart snapshot JSON（`<script type="application/prs.init-data+json">`）抽出的機器資料，
非作者敘述、非我推論；`【推論】` = 我從洩漏數據反推，附算式；`【未找到】` = 查不到。

---

## 0. 結論摘要

1. **原始碼不公開**：`access=3`（invite-only）、`script.content=""`、`has_access=false`。
   三支同系列腳本全部 invite-only，TradingView 官方標示「通常需付費才會獲得授權」。
2. **它是 indicator（study），不是 strategy**：`script_type="study"`，`plots=[]`，
   無 Pine Strategy Tester。所謂「回測」是腳本自算的一張 8-10 列統計表。
3. 但頁面內嵌的 chart snapshot **洩漏了完整參數 schema、Pine 編譯警告、
   以及已繪製的 XABCD 座標＋統計表數值**——足以反推出精確的 TP/SL 公式與掃描機制。

---

## 1. 身分與商業模式

| 項目 | 值 | 來源 |
|---|---|---|
| 作者 | Trader-Alex（TW，簡介為繁中） | 【頁面】profile |
| 追蹤者 | 2.6K；會員自 2019-11-18 | 【頁面】profile |
| 本腳本 | likes 571 / comments 23 / views 8675 | 【洩漏】`likes_count` 等 |
| 首發 | 2025-12-27；最後更新 2026-04-12 | 【洩漏】`created_at`/`updated_at` |
| 腳本版本 | `version_maj=9`（Pine v6 語法，metainfo `pine.version=23.0`） | 【洩漏】`script` |
| 導流 | Telegram/IG `@TraderAlex66`、`cryptotradersclub.org`、**BingX 推薦連結** `bingx.com/invite/VBXORPQC` | 【頁面】signature |

**同系列三支腳本（全部 invite-only、全部 study、content 皆空）**：

| 腳本 | uuid | 首發 | ver | likes/comments/views | 快照商品 |
|---|---|---|---|---|---|
| `Auto Harmonic Patterns`（基本版） | wXe6JvAX | 2025-12-15 | 18 | 526/78/9196 | COINBASE:BTCUSD 1H |
| `<Elite>`（本案） | DSk4XN5m | 2025-12-27 | 9 | 571/23/8675 | BINANCE:BTCUSDT 4H |
| `<Ultimate>` | 3eidBGOL | 2026-01-11 | 17 | 683/82/13093 | BINANCE:BTCUSDT 1H |

Elite 的 2026-03-23 release note 寫「Partial Ulitimate ---> Elite」（原文錯字），
即 Ultimate 是最高階、Elite 是把 Ultimate 部分功能下放的中階版。**分級販售。**

Pine 編譯警告洩漏了三支的原始碼行號：基本版 pivot 在 1147/1148 行、
Elite 在 1230/1231、Ultimate 在 1365/1366 → 同一套 code base，約 1150–1400 行。

---

## 2. a. 偵測哪些 pattern？Fib 比例與容差？

### 2.1 pattern 清單【洩漏 input schema】

Elite（8 種，各有獨立開關＋顏色）：
Gartley / Bat / Alt Bat / Butterfly / Crab / Deep Crab / Shark / Cypher

Ultimate 多 2 種：**Deep Gartley**、**5-0 Pattern**（共 10 種）。
基本版與 Elite 同為 8 種，但標籤上會細分變體，快照裡出現 `[Bearish] Shark 113`
（= D 落在 1.13 XA 的 Shark 變體）。

### 2.2 各 pattern 的 Fib 比例 —— **頁面完全沒寫**

【頁面】description 全文（英＋中雙語）**沒有出現任何一個 Fibonacci 數字**
（grep `0.382|0.618|0.786|0.886|1.13|1.27|1.618|2.0|2.24|3.618` → 0 命中）。
作者只寫「基於數學幾何比例計算」。**這是行銷話術層，不是規格。**

### 2.3 但從洩漏的 XABCD 座標可實測出實際比例【洩漏＋推論】

Elite 快照（BTCUSDT 4H）繪製了兩個完整型態，座標精確到小數點後 5 位：

**Bullish Cypher**：X=108393.39 A=111782.21 B=110528.71 C=112575.27 D=109329.12
- AB/XA = 0.370（教科書 Cypher B：0.382–0.618）
- XC/XA = 1.234（教科書 C：1.272–1.414）
- CD/XC = **0.7763**（教科書 Cypher D = 0.786）← 定義腿，吻合

**Bearish Deep Crab**：X=113485.9 A=107255 B=113384.62 C=109977 D=116665.63
- AB/XA = 0.984（教科書 Deep Crab B = 0.886）← **超標 11%**
- BC/AB = 0.556（教科書 0.382–0.886）✓
- AD/XA = **1.510**（教科書 Deep Crab D = 1.618）← **少 6.7%**

基本版快照另有 3 個樣本：
| 型態 | AB/XA | BC/AB | AD/XA | 教科書 D |
|---|---|---|---|---|
| Bat (L) | 0.542 | 0.782 | **0.898** | 0.886 ✓ |
| Deep Crab (S) | 0.952 | 0.561 | **1.947** | 1.618 ← 超標 20% |
| Shark 113 (S) | 0.491 | 1.721 | **0.977** | 0.886–1.13 ✓ |
| Butterfly (L, Ultimate) | 0.812 | 0.864 | **1.270** | 1.27 ✓ |

**關鍵觀察**：兩個都被標成「Deep Crab」的樣本，AD/XA 分別是 **1.510 與 1.947**——
圍繞 1.618 散佈 ±20%，遠寬於名目設定的 `Tolerance % = 10`。
【推論】容差不是對 D 的單點比例做 ±10%，而是（a）對多條腿各自套用、
或（b）D 只要落進由多個比例交集出來的 PRZ 區間即可，導致實際幾何自由度遠大於 10%。
**單憑頁面無法確定容差的施加方式**——這是複製時必須自己重新定義的關鍵空白。

### 2.4 容差參數【洩漏】
- Elite：`Tolerance % (容錯率 %)`，default **10**，min 0.1（頁面建議 3~10%）
- Ultimate 另有 `Strict Tolerance % (嚴格容錯率 %)`，default **3** → 雙層容差
- 【頁面】自承：「誤差大小與型態止盈**不見得呈正向關係**」（= 作者自己也沒有
  「容差越嚴越賺」的證據）

---

## 3. b. swing/pivot 怎麼定義？repaint 風險

### 3.1 pivot 機制【洩漏 — Pine 編譯警告，最硬的證據】

Elite metainfo `warnings` 欄位原文：
```
line 1230: The function 'ta.pivothigh' should be called on each calculation
           for consistency. It is recommended to extract the call from this scope
line 1231: The function 'ta.pivotlow'  ... (同上)
line 1277: The function 'process_scanner' ... (同上)
```
→ **不是 ZigZag，是 `ta.pivothigh` / `ta.pivotlow`**，而且被放在**迴圈/條件 scope 裡呼叫**。
Ultimate（1365/1366）與基本版（1147/1148）有同樣兩條警告。

### 3.2 「Dynamic Global Scanning」的真面目【洩漏 — 基本版 input schema】

基本版把掃描引擎攤開寫成 5 組固定長度：
```
Enable Group 1 + Length = 2
Enable Group 2 + Length = 10
Enable Group 3 + Length = 20
Enable Group 4 + Length = 40
Enable Group 5 + Length = 80
```
→ 所謂「動態全域掃描」＝**跑 5 個不同 pivot length 再合併結果**。

Elite 改成連續掃描區間：`Start Length` default 10（min 5, step 5）、
`End Length` default 500（min 20, step 10）。
Ultimate 再加 `Range Step (掃描週期間隔)` default 2、Start 1、End 50
→ Ultimate 實際是 length ∈ {1,3,5,…,49} 共 25 組掃描。

**注意 Elite 與 Ultimate 的預設掃描域完全不重疊**（10–500 vs 1–50），
兩支「同系列」腳本在同一根 K 線上會給出不同的型態集合。

### 3.3 repaint 證據盤點

| 證據 | 來源 | 強度 |
|---|---|---|
| `historyCalculationMayChange: true` | 【洩漏】三支腳本全為 true | 強 |
| `ta.pivot*` 在非全域 scope 呼叫（Pine 官方警告會造成歷史值不一致） | 【洩漏】warnings | 強 |
| 基本版有明確 input `Optimize A, B & C Points (自動優化 A, B, C)` = true | 【洩漏】in_42 | 強 |
| 2025-12-29 release note 自承：演算法「搜尋更佳價格極值」時會**改寫已定型態的點位價格與時間戳**，曾出現 A 點懸空 | 【頁面】release notes | 強 |
| `Real-time Sensitivity` default ON，「包含極短線微小波動掃描」 | 【頁面】+【洩漏】in_0 | 中 |
| Potential Pattern / PRZ 本質上預測尚未發生的 D 點 | 【頁面】 | 設計如此 |

【推論】此腳本**至少有兩種歷史改寫**：
(i) *結構性 lag*——`ta.pivothigh(len)` 需要右側 len 根才確認，length 最大 500 時，
   一個型態可能在 D 之後 500 根才「出現」在歷史圖上。這是 lag，不是造假，但
   **會讓統計表的樣本包含當時根本看不到的型態**。
(ii) *真 repaint*——`Optimize A,B,C` 會回頭把已標記的點移到更好的極值，
   型態比例、PRZ、Entry/TP/SL 因此全部跟著變。

**我無法實測驗證 repaint**（無原始碼、無腳本存取權、無法跑 bar replay）。
上述是靜態證據推論，不是實跑結果。

### 3.4 一個直接的異常【洩漏】
Elite 快照裡，Bullish Cypher 的 D 點畫在 bar index 57、價格 109329.12；
但同一根 bar 57 也是 Deep Crab 的 A 點、價格 **107255**。
→ 一個 bullish 型態的 D（應為低點）竟高於同 bar 的實際低點 2074 點（1.9%）。
【推論】D 點不是貼在 K 線實際極值上，而是某種投影/優化後的價位。

---

## 4. c. 進出場、SL/TP 規則 —— **已從洩漏座標精確反推**

### 4.1 頁面說法【頁面】
- Entry：PRZ 內的建議進場價（白線），**強烈建議等 PRZ 內出現反轉 K
  （吞噬、長影線）再進**；4H 型態看 1H 反轉 K、1H 看 15M。
- TP1 平倉 50–60%，TP2 再平 25–50%（**Shark 例外：TP1 必須 100% 平倉**）。
- **無移動停損**（頁面與參數表都沒有 trailing stop）。
- 「型態共振」：新潛在型態的 D 可當原單的 TP3（手動判斷，非自動）。
- PRZ 寬度可用 `PRZ Extra Padding %`（default 0）擴張。

### 4.2 實際公式【推論 — 6 個樣本，數值吻合到小數 4 位】

令 X,A,B,C,D 為型態五點，`ext` = 型態在獲利方向上的極值
（做多取 `max(X,A,B,C)`，做空取 `min(X,A,B,C)`），`leg = |D − ext|`。

**Entry = D**（無緩衝、無確認條件；6/6 樣本 Entry 恰等於 D 點價）

**TP（一般型態，5/6 樣本精確吻合）**
```
TP1 = D ± 0.382 × leg
TP2 = D ± 0.618 × leg
```
**TP（Shark 例外，1/1 樣本）**
```
TP1 = D ± 0.500 × leg
TP2 = D ± 0.886 × leg
```
（這解釋了作者為何說「鯊魚必須 TP1 全平」——Shark 用的是 0.5/0.886 而非 0.382/0.618。）

**SL = XA 的固定 Fib 延伸位，且是「D 所在延伸位的下一檔」**（6/6 樣本）
| 型態 | D 的 AD/XA | SL 的 (SL−A)/XA |
|---|---|---|
| Cypher | 0.724 | **1.000**（= X 點本身） |
| Bat | 0.898 | **1.130** |
| Shark 113 | 0.977 | **1.272** |
| Butterfly | 1.270 | **1.618** |
| Deep Crab | 1.510 / 1.947 | **2.000** |

即 SL 檔位序列 = {1.0, 1.13, 1.272, 1.618, 2.0}，教科書 harmonic 慣例。

### 4.3 實測風險/報酬【洩漏標籤原文】
| 樣本 | 風險 %（Entry→SL） | R:R (TP1) | R:R (TP2) |
|---|---|---|---|
| Elite Cypher L | 0.86% | 1.33 | 2.14 |
| Elite Deep Crab S | 2.62% | 1.18 | 1.91 |
| Ultimate Butterfly L | 2.72% | 1.39 | 2.26 |
| 基本版 Bat L | — | 1.48 | — |
| 基本版 Shark 113 S | — | 2.26 | — |
| 基本版 Deep Crab S | — | **14.04** | — |

**最後一列是重大警訊**：該 Deep Crab 的 D 落在 1.947 XA，而 SL 檔位固定在 2.000 XA，
兩者只差 0.053 XA → 停損距離趨近於零 → R:R 爆到 14:1。
**這是公式的結構性缺陷**：當 D 逼近 SL 檔位，風險→0、R:R→∞，
而統計表把這種一觸即死的單子與正常單子**等權計為一筆**。

Ultimate 另有一個 label 顯示更荒謬的組合：
`🟢 [Bullish Butterfly] SL: -7.09% | RR1: .12 | RR2: .19` —— R:R 0.12 的設定也照樣顯示。

---

## 5. d. 作者宣稱的績效

### 5.1 沒有 strategy tester 截圖，沒有 PF、沒有 MDD、沒有 Sharpe【頁面】
`script_type = "study"`，`plots = []` → **沒有 Pine Strategy Tester**，因此
不可能有 TradingView 官方認證的績效報表。作者也**從未在文字中宣稱任何具體績效數字**。
【未找到】：勝率宣稱、profit factor、最大回撤、淨利、樣本區間、手續費假設。

### 5.2 唯一的績效載體：腳本自算的統計表【洩漏 — 快照實際數值】

**Elite，BINANCE:BTCUSDT 4H（2026-04-12 快照，Tolerance=10, Min Profit=1）**
| Pattern | Total | TP1 % | TP2 % | SL % |
|---|---|---|---|---|
| Gartley | **3** | 33.3% | 33.3% | 66.7% |
| Bat | 23 | 78.3% | 52.2% | 21.7% |
| Alt Bat | 4 | 75.0% | 50.0% | 25.0% |
| Butterfly | 78 | 67.9% | 57.7% | 32.1% |
| Crab | 16 | 75.0% | 56.3% | 25.0% |
| Deep Crab | 65 | 84.6% | 72.3% | 15.4% |
| Shark | 47 | 76.6% | 59.6% | 23.4% |
| Cypher | 56 | 58.9% | 50.0% | 41.1% |
| **合計** | **292** | | | |

**Ultimate，BINANCE:BTCUSDT 1H**
| Pattern | Total | TP1 % | TP2 % | SL % |
|---|---|---|---|---|
| Gartley | 197 | 72.6% | 50.3% | 27.4% |
| Deep Gartley | 152 | 76.3% | 55.3% | 23.7% |
| Bat | 124 | 64.5% | 48.4% | 35.5% |
| **Alt Bat** | **0** | .0% | .0% | .0% |
| Butterfly | 181 | 70.7% | 48.1% | 29.3% |
| Crab | 73 | 68.5% | 50.7% | 31.5% |
| Deep Crab | 174 | 71.3% | 50.0% | 28.7% |
| Shark | 174 | 71.3% | 39.1% | 28.7% |
| Cypher | 38 | 71.1% | 57.9% | 28.9% |
| 5-0 | 215 | 55.8% | 38.6% | 44.2% |

**基本版，COINBASE:BTCUSD 1H**
| Pattern | Total | TP1 % | TP2 % | SL % |
|---|---|---|---|---|
| Gartley | **6** | **100.0%** | 100.0% | .0% |
| Bat | 28 | 75.0% | 53.6% | 25.0% |
| Alt Bat | 6 | 83.3% | 66.7% | 16.7% |
| Butterfly | 65 | 73.8% | 64.6% | 26.2% |
| Crab | 22 | 54.5% | 40.9% | 45.5% |
| Deep Crab | 60 | 76.7% | 61.7% | 23.3% |
| Shark | 46 | 73.9% | 60.9% | 26.1% |
| Cypher | 36 | 69.4% | 50.0% | 30.6% |

### 5.3 這張表的統計問題（逐條）

1. **`TP1% + SL% = 100%` 是作者明說的**【頁面】。代表**沒有「未結案」桶**——
   到現在還沒碰 TP1 也沒碰 SL 的型態被整批丟掉。這是 look-ahead 式的樣本篩選。
2. **作者自承還會再剔除一批贏家**：「少數型態會在觸發 PRZ 後，因為並未 SL 且達成
   TP1 以上，但 D 點過份偏移，而無法計入勝率」【頁面】。剔除規則是**事後**判定的。
3. **勝率不是期望值**。TP1 的 R:R 實測落在 0.12–14.04 之間，表格等權計次，
   完全無法反推期望值。作者的判準「TP1% > 60% 即可操作」在 R:R 未知時毫無意義。
4. **無成本假設**：沒有手續費、滑價、資金費率。Entry = D 點掛限價，
   但真實情況是價格觸及 D 後可能直接穿越（尤其 SL 距離 0.86% 的 Cypher）。
5. **樣本量崩壞**：Elite 的 Gartley 只有 3 筆（33.3% = 1/3），
   Ultimate 的 Alt Bat 是 **0 筆**，基本版 Gartley 6 筆卻是 100%。
   這些數字仍照樣被印在「歷史回測數據」表上，沒有最低樣本量門檻
   （Ultimate 才有 `Min Sample Size to Draw` = 3，且僅用於畫路徑，不是統計表）。
6. **跨版本不一致**：同為 BTC，Elite 4H 的 Gartley 只找到 3 個，
   Ultimate 1H 的 Gartley 找到 197 個。即使算上 4 倍 K 線數，仍差 ~65 倍。
   Elite 的 2026-04-12 release note 是「**Fix Gartley = 0**」——
   即 Gartley 偵測在 2026-04 之前根本壞掉，而快照顯示修完後也只有 3 筆。
7. **統計表是「當前商品×當前週期」即時重算**，會隨 Tolerance、Start/End Length
   等參數變動。**沒有任何參數凍結或樣本外機制**——使用者可以直接調參數把勝率調高。
   這是 in-sample 參數挑選的教科書範例。

---

## 6. e. 使用者評論指出的問題

**【未找到】。** Elite 有 23 則、Ultimate 82 則、基本版 78 則留言，但：
- TradingView 留言區為 client-side 載入，未 server-render；
  `/comments/` 頁面 HTML 內 0 命中（`ssrComments`、`comments":[` 皆 0）。
- 試過 5 個 API 端點（`/api/v1/comments/?idea_id=`、`/api/v1/idea/<id>/comments/`、
  `/api/v1/publication/<uuid>/comments/` 等），全部 404，需登入。
- 站外搜尋（英文＋繁中，含 repaint/scam/心得/PTT/Dcard 等關鍵字）**零命中**：
  沒有任何第三方評測、論壇討論、YouTube 說明、Reddit 討論。

**這件事本身是一項發現**：一支 8675 views / 571 likes 的付費腳本，
在 TradingView 站外**完全沒有獨立聲量**。所有正面訊號都在作者自己控制的通道內
（腳本頁 likes、Telegram 群、cryptotradersclub.org、FB 粉專）。

---

## 7. f. indicator 還是 strategy？

**Indicator（study）**，證據三重：
- 【洩漏】`script.script_type = "study"`
- 【洩漏】metainfo `plots: []`、`is_price_study: true`、`hasAlertFunction: true`
- 【洩漏】`pineFeatures` = `{indicator:1, str:1, array:1, ta:1, math:1, alert:1,
  line:1, box:1, label:1, table:1, type:1}` → 有 `indicator`，**沒有 `strategy`**

**沒有內建 backtest**（無 Strategy Tester）。唯一的「回測」是 §5.2 那張自算統計表。
`usesPrivateLib: false` → 沒有引用私有 library，邏輯全在這 ~1230 行內。

---

## 8. 完整參數表（Elite，【洩漏 input schema】43 個 input）

```
in_0   bool   true            Real-time Sensitivity (K線即時靈敏度)
--- Scan Period Settings ---
in_1   int    10   min5  step5   Start Length (掃描週期下限)
in_2   int    500  min20 step10  End Length   (掃描週期上限)
--- Pattern Visibility & Colors ---  (每個 pattern = bool + color)
in_3/4   Gartley   #4CAF50      in_5/6   Bat       #007bdf
in_7/8   Alt Bat   #3F51B5      in_9/10  Butterfly #FF9800
in_11/12 Crab      #9C27B0      in_13/14 Deep Crab #E53935
in_15/16 Shark     rgba(0,234,251,1)   in_17/18 Cypher #ff5f94
--- Style & TP/SL Settings ---
in_19-21  [Bullish] Entry/TP/SL  #FFFFFF / #00E676 / #FF5252
in_22-24  [Bearish] Entry/TP/SL  #FFFFFF / rgba(22,231,231,1) / rgba(235,7,251,1)
in_25  int   6   1..50    Line Length Multiplier
in_26  int   1   0..50    History TP/SL/Entry Lines Count
in_27  bool  true         Show Potential Patterns
in_28  int   5   1..20    Max Potential Count
in_29  float 0   step0.01 PRZ Extra Padding %
--- Statistics Table Settings ---
in_30  bool  true                     Show Statistics Table
in_31  text  'Bottom Right'           Table Position (4 corners)
in_32  text  'Normal'                 Text Size (Tiny/Small/Normal/Large)
in_33-35 colors                       Header/Cell BG, Header Text
--- Core Logic ---
in_36  float 10  min0.1 step0.1   Tolerance % (容錯率 %)
in_37  float 1   min0   step0.1   Min Profit % (最小獲利 %)   ← 頁面完全沒提到
```

**`Min Profit %` (default 1) 是頁面未文件化的參數。**【推論】它應是過濾掉
TP1 距 Entry < 1% 的型態——但這只擋 TP 太近，**不擋 SL 太近**（見 §4.3 的 R:R 14 案例）。

發布快照實際使用的設定【洩漏 `state.inputs`】：
`Start=10, End=500, Real-time Sensitivity=ON, Tolerance=10, Min Profit=1,
PRZ Padding=0, History Lines=50`。
→ **統計表是在 Tolerance = 10（建議區間最寬的一端）下產生的。**

---

## 9. 最可能的弱點（複製時不要抄的部分）

1. **統計表不是回測，是有 look-ahead 篩選的計次器**（§5.3）。
   `TP1%+SL%=100%` 排除未結案、事後再排除「D 點偏移」的贏家、
   等權計次而不看 R:R（實測 0.12–14.04）、無成本、無最低樣本量、in-sample 調參即可拉高。
   **這是整支腳本最不可信的部分，也是最主要的行銷武器。**
2. **SL 檔位固定 → 風險不受控**。SL 綁在 XA 的固定 Fib 延伸位，
   當 D 恰好逼近該檔位時停損距離趨近 0（實測 R:R 14.04），
   反之 Deep Crab 的 2.62% 對 Cypher 的 0.86%，同一張表裡每筆交易的風險差 3 倍以上，
   卻沒有任何 position sizing 層把它們正規化。→ **違反「被比較的兩個值必須同源同基準」。**
3. **Repaint / look-ahead 疑慮未澄清**：`historyCalculationMayChange=true`、
   `ta.pivot*` 在非全域 scope（Pine 官方警告）、明確的 `Optimize A,B,C Points` 開關、
   作者自承會回頭改寫已定型態的點位與時間戳。加上 `End Length=500` 造成的確認延遲
   （型態最晚可能在 D 之後 500 根才被畫出來）——歷史統計表裡有多少樣本
   「在當下根本看不到」，作者從未回答。
4. **pattern 定義鬆散到失去意義**：兩個都叫 Deep Crab 的樣本，AD/XA 是 1.510 與 1.947
   （教科書 1.618），Deep Crab 的 AB/XA 實測 0.984 vs 教科書 0.886。
   名目 Tolerance 10% 顯然不是這樣施加的。若「Deep Crab」實際涵蓋 1.5–1.95 的 D 延伸，
   它與 Crab、Butterfly 的判別邊界就是模糊的，「哪個 pattern 勝率高」的表也就沒有意義。
5. **偵測器有已知 bug 且持續存在**：Elite 2026-04-12 才「Fix Gartley = 0」，
   修完後 BTC 4H 仍只有 3 筆；Ultimate 的 Alt Bat 至今 Total = 0。
   壞掉的偵測器照樣把 33.3%、.0% 印在「回測數據」表上。
6. **無 trailing stop、無部位管理、無多商品組合視角**。分批出場比例（50-60% / 25-50%）
   是散文建議，不是可執行規則，也沒進統計表。
7. **同系列三支腳本預設掃描域互不相容**（Elite 10–500、Ultimate 1–50、基本版 {2,10,20,40,80}），
   同一根 K 線會給不同答案。作者從未說明哪一個才是「對的」。
8. **站外零獨立驗證**（§6）。

## 10. 它可能真的做對的地方（值得抄的部分）

1. **多尺度掃描（multi-scale pivot sweep）是對的方向**。單一 ZigZag depth 是
   大多數 harmonic 指標的死穴——形態尺度本來就不是單一的。跑 N 個 pivot length
   再合併，等於自動做尺度搜尋。這個設計可以留，但要加**去重與重疊處理**
   （同一個 D 被多個 length 重複偵測 → 快照裡確實看到同一個 Bat 被印 4 次、
   同一個 Shark 印 4 次，重複計數會直接汙染統計表）。
2. **「PRZ 先於 D 點出現」的預測式設計有實務價值**。在 D 尚未成形前就把
   潛在反轉區與 Entry/SL/TP 算出來，讓使用者能提前掛單——這比等型態完成再進場
   有意義（等完成才進場的 harmonic 指標通常已經錯過反轉）。
   **但這正是 repaint 的來源**，所以複製時要做的是：把「潛在型態」與「已確認型態」
   分成兩條完全獨立的資料流，統計只用後者，且必須帶 as-of 時間戳。
3. **把每個 pattern 分開統計，而不是報一個總勝率**。承認不同商品/週期適合不同型態
   （「黃金 vs 比特幣適合的型態不同」）——這個觀念是對的，而且是可檢驗的假設。
   我們的版本應該保留這個切面，但換成有 out-of-sample 的做法。
4. **固定的、可機器驗證的 TP/SL 公式**（§4.2）。不管好壞，它是**確定性的**：
   給定 XABCD 就能算出唯一的 Entry/SL/TP1/TP2，沒有任何自由裁量。
   這讓它可以被嚴格回測——**這正是我們該做而它沒做的事**。
5. **雙層容差（Ultimate 的 Tolerance 10% + Strict 3%）** 概念上可用來做
   訊號分級（嚴格型態 vs 寬鬆型態），若真能分出勝率差異就是可用的 feature。
   作者自己說「誤差大小與止盈不見得呈正向關係」——這正好是一個現成的、
   值得我們實測的假設。

---

## 11. 複製時的關鍵空白（頁面查不到、必須自己定義）

1. 各 pattern 的完整 Fib 比例區間（B、C、D 三腿）——【未找到】，只有 6 個實測樣本可反推。
2. Tolerance 的施加方式（乘法 / 加法 / 對哪幾條腿 / 是否為 PRZ 交集）——【未找到】。
3. 多 length 掃描結果的去重與優先序規則——【未找到】。
4. 「D 點過份偏移」的排除判準——【未找到】（作者只在說明統計表時提過一句）。
5. `Optimize A,B,C Points` 的實際演算法——【未找到】，只有 release note 的描述。
6. 型態失效條件（進場後多久沒到 TP 就放棄）——**不存在**，公式只有 TP/SL 二擇一。

---

## 附：資料抽取方法（可復現）

```bash
curl -sSL -A "Mozilla/5.0 ..." \
  "https://www.tradingview.com/script/DSk4XN5m-Elite-Auto-Harmonic-Patterns-Trader-Alex/" \
  -o tv_raw.html
# 頁面內嵌 6 個 <script type="application/prs.init-data+json"> blob，
# 其中含 DSk4XN5m 的那個 -> ssrIdeaData
#   .script              -> access / script_type / content（原始碼，此處為空）
#   .content (JSON字串)  -> charts[0].panes[*].sources[*]
#        .state.inputs                      -> 發布快照實際參數
#        .data.graphics.dwglines/dwglabels  -> XABCD 座標、Entry/TP/SL 標籤
#        .data.graphics.dwgtablecells       -> 統計表全部數值
#   .content.studyMetaInfoMap["Script$..."]
#        .inputs      -> 完整參數 schema（名稱/型別/預設/min/max/step/options/group）
#        .warnings    -> Pine 編譯警告（洩漏原始碼行號與函式名）
#        .historyCalculationMayChange
```
同法可套用於 `3eidBGOL`（Ultimate）與 `wXe6JvAX`（基本版）。
中間檔（同目錄）：`tv_raw.html`（原始頁）、`tv_text.txt`（description 全文，英中雙語）、
`idea.json`（ssrIdeaData）、`metainfo.json`（含完整 input schema 與 Pine 警告）、
`g_dwglines.json` / `g_dwglabels.json` / `g_dwgtablecells.json`（Elite 快照幾何與統計表）、
`s_3eidBGOL.html`（Ultimate）、`s_wXe6JvAX.html`（基本版）。
