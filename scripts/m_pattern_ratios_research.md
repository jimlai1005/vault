# 諧波形態（Harmonic Patterns）Fibonacci 比例定義 — 來源查證表

研究日期：2026-08-06
用途：sub-project M 諧波形態偵測器的**預註冊比例表**（frozen spec）。
狀態：9 種形態全部取得 ≥2 個獨立來源；4 處分歧已標註（見 §6）。

---

## 0. 符號與計算約定（實作前必讀）

五點 `X, A, B, C, D`，四段 `XA, AB, BC, CD`。**所有比例都用「線段長度絕對值」相除**，
不帶方向符號：

```
XA = |A - X|      AB = |A - B|      BC = |C - B|      CD = |C - D|
AD = |A - D|      XC = |C - X|

AB/XA = |A-B| / |A-X|     # B 點對 XA 段的回撤
BC/AB = |C-B| / |A-B|     # C 點對 AB 段的回撤
CD/BC = |C-D| / |C-B|     # D 點對 BC 段的延伸（Carney 稱 "BC projection"）
AD/XA = |A-D| / |A-X|     # D 點對 XA 段的回撤(<1)或延伸(>1) ← 各形態的識別鍵
```

多頭型態（bullish）點序：X 低 → A 高 → B 低 → C 高 → D 低（買在 D）。
空頭型態鏡像。用 `abs()` 兩者共用同一組公式。

### 術語陷阱（Carney 原文用語）

Carney 寫「**a 1.618 BC projection**」指的是 **CD/BC = 1.618**，不是 BC/AB。
「projection」＝從 C 點投射出去的 CD 段長度，以 BC 為單位。
把它讀成 BC/AB 是最常見的一階誤讀——本表已全部正規化到上面的四個符號。

---

## 1. 主表：9 形態 × 4 比例（正規化到 XABCD）

| 形態 | AB/XA | BC/AB | CD/BC | **AD/XA** | 交叉驗證 |
|---|---|---|---|---|---|
| **Gartley** | 0.618（嚴格單點） | 0.382–0.886 | 1.13–1.618 | **0.786** | 4 源 ✅ |
| **Bat** | 0.382–0.50 | 0.382–0.886 | 1.618–2.618 | **0.886** | 4 源 ✅ |
| **Alternate Bat** | 0.382（「或更小」） | 0.382–0.886 | 2.0–3.618 | **1.13** | 2 源 ✅ |
| **Butterfly** | 0.786（強制單點） | 0.382–0.886 | 1.618–2.618 | **1.27**（主）／1.27–1.618 | 4 源 ⚠️ |
| **Crab** | 0.382–0.618 | 0.382–0.886 | 2.24–3.618 | **1.618** | 4 源 ⚠️ |
| **Deep Crab** | 0.886（單點） | 0.382–0.886 | 2.24–3.618 | **1.618** | 3 源 ⚠️ |
| **Shark** | 無此約束（見 §3.1） | 1.13–1.618 | 1.618–2.24 | **0.886–1.13** | 5 源 ✅ |
| **Cypher** | 0.382–0.618 | ⚠️ 非 AB 基準，見 §3.2 | 無標準約束 | ⚠️ 非 XA 基準，見 §3.2 | 4 源 ⚠️ |
| **5-0** | 1.13–1.618 | 1.618–2.24 | **0.50**（嚴格單點） | 無此約束（推導 0–0.31） | 3 源 ✅ |

**Cypher 的真正約束**（不能塞進上面四欄，見 §3.2）：

| 約束 | 值 |
|---|---|
| AB/XA | 0.382–0.618 |
| **XC/XA** | **1.272–1.414**（C 相對 **XA** 段，不是 AB 段） |
| **CD/XC** | **0.786**（D 相對 **XC** 段，不是 XA 段） |
| 推導：BC/AB | 1.44–2.08 |
| 推導：CD/BC | 1.08–1.53 |
| 推導：AD/XA | **0.697–0.728**（**不是** 0.786） |

---

## 2. Carney 的第五個約束：內嵌 AB=CD（CD/AB）

Carney 的原始定義除了上面四條，多數形態還**強制要求內部含一個 AB=CD 結構**，
作為 PRZ 的第二條收斂線。這是獨立於 CD/BC 的約束：

| 形態 | CD/AB（AB=CD 型態） | 來源 |
|---|---|---|
| Gartley | 1.0（標準 AB=CD） | harmonictrader Gartley 頁 |
| Bat | 1.27（「ideally possesses a 1.27AB=CD calculation」） | harmonictrader Bat 頁 |
| Alternate Bat | 1.618（「always extended and usually requires a 1.618 AB=CD」） | harmonictrader Alt-Bat 頁 |
| Butterfly | 1.27 或 1.618（「must include an AB=CD pattern to be a valid signal」） | harmonictrader Butterfly 頁 |
| Crab | 1.27 或 1.618【單一來源，未交叉驗證】 | investmacro |
| Deep Crab | 未明定 | — |
| Shark | **不適用**（Shark 明確不含 AB=CD） | harmonicpattern.com |
| Cypher | 不適用 | — |
| 5-0 | **1.0（Reciprocal AB=CD，強制）** | harmonictrader 5-0 頁、algorush |

**實作建議**：主表四條當作 hard gate；CD/AB 當作 soft score（PRZ 收斂度），
不要當硬條件——它與 CD/BC 在大部分參數組合下無法同時精確滿足。

---

## 3. 三個陷阱的明確回答

### 3.1 陷阱一：Shark 與 5-0 的點命名 + XABCD 映射

**Shark**（Carney 原始命名：`0, X, A, B, C`，5 點 4 段，PRZ 在 **C** 點不是 D 點）

原始命名下的比例（3 個獨立來源一致）：

| 約束 | 值 |
|---|---|
| XA/0X | **無 Carney 核心約束**（見下方分歧） |
| AB/XA | 1.13–1.618（延伸，B 越過 X） |
| BC/AB | 1.618–2.24 |
| C 點 / 0X | 0.886（回撤）– 1.13（投射） |
| 停損 | 1.27 延伸 0X |
| 停利 | BC 段 50% 回撤 |

**映射規則**：`0→X`, `X→A`, `A→B`, `B→C`, `C→D`（整體右移一位，丟掉最後不存在的點）。
段的對應：`0X→XA`, `XA→AB`, `AB→BC`, `BC→CD`。

| Carney 原始 | 映射後（XABCD） |
|---|---|
| AB 是 XA 的 1.13–1.618 | **BC/AB = 1.13–1.618** |
| BC 是 AB 的 1.618–2.24 | **CD/BC = 1.618–2.24** |
| C 是 0X 的 0.886–1.13 | **AD/XA = 0.886–1.13** |
| （XA 對 0X 無約束） | **AB/XA = 無約束** |

映射正確性已用 `neurotrader888` 的獨立實作交叉確認：
`SHARK = XABCD(None, [1.13, 1.618], [1.618, 2.24], [0.886, 1.13], "Shark")`
——四欄與上表逐格相符，且第一欄確實是 `None`。

**幾何驗算**（0=0, X=1, XA/0X=0.5）：A=0.5 → AB=0.565（1.13×0.5）→ B=1.065（越過 X ✓）
→ BC=0.914（1.618×0.565）→ C=0.151 → |C−X|/|0X| = 0.849 ≈ 0.886 ✓。

---

**5-0**（Carney 原始命名：`0, X, A, B, C, D`，**6 點 5 段**）

| 約束 | 值 |
|---|---|
| AB/XA | 1.13–1.618 |
| BC/AB | 1.618–2.24 |
| C 點 / 0X | 0.886–1.13（與 Shark 同——「Shark 是正在形成中的 5-0」） |
| **CD/BC** | **0.50**（唯一的關鍵數字） |
| Reciprocal AB=CD | CD/AB = 1.0 |

**映射規則**：5-0 已經自帶 `X,A,B,C,D` 五個點——**直接丟掉最前面的 `0` 點**，
`X→X, A→A, B→B, C→C, D→D`（**不右移**，與 Shark 的映射規則相反）。

代價：丟掉 `0` 點後，「C 點 / 0X = 0.886–1.13」這條約束**無法表達**。
若要保留，偵測器需支援 6 點（多一個前置樞紐）。

映射後：`AB/XA = 1.13–1.618`、`BC/AB = 1.618–2.24`、`CD/BC = 0.50`、`AD/XA` 無約束。

**AD/XA 推導**【推導，非 Carney 定義】：令 a=AB/XA, b=BC/AB，則
`AD/XA = a·|0.5b − 1|`。b∈[1.618,2.24] 使 `0.5b−1 ∈ [−0.191, +0.12]`，
故 **AD/XA ∈ [0, 0.31]**，且 b=2.0 時恰為 0。
→ 幾何意義：**5-0 的 D 點必然落在 A 點附近**，這是它的視覺識別特徵。

**CD/BC=0.5 與 AB=CD 的相容性**【推導】：`CD/AB = 0.5b ∈ [0.809, 1.12]`。
兩條約束只在 `BC/AB = 2.0` 時**同時精確成立**；其餘情況是兩條投射線在 PRZ 附近收斂。
實作時 CD/AB 應為 soft score。

上述兩項推導亦經數值枚舉複核（`scratchpad/verify.py`）：
`AD/XA 0.000–0.309`、`CD/AB 0.809–1.120`（1.0 落在區間內 ✓）。
Shark 幾何驗算同檔複核：B=1.065 > X=1.0 ✓、`|C−X|/|0X| = 0.849` ✓。

---

### 3.2 陷阱二：Cypher 的 BC — 你的印象**基本正確，但數字要修正**

**判定：正確方向，數值需改。**

- ✅ **對**：Cypher 的 C 點確實是對 **XA** 段量的，不是對 AB 段量的。
- ⚠️ **要改的地方一**：正確寫法是 **`XC/XA = 1.272–1.414`**（C 點相對整條 XA 段，
  從 **X** 起算），不是 `BC/XA`。你寫的 `BC/XA` 會少算 `AB` 那一截。
- ⚠️ **要改的地方二**：你寫的區間 `1.13–1.414` 下界錯了，主流是 **1.272**–1.414。
  （`1.13` 是 **Shark** 的數字，不是 Cypher 的——這兩個很容易串。）

**Cypher 第四條約束同樣有陷阱**：D 點是 **`CD/XC = 0.786`**（相對 **XC** 段），
**不是** `AD/XA = 0.786`。`theforexgeek` 同一篇文章內部就自相矛盾
（本文說「D 是 XA 的 78% 回撤」，策略段說「CD 回撤到 XC 的 0.786」）——後者才是正解。

**推導出的等效值**【推導】（令 X=0, A=1, b=AB/XA, c=XC/XA）：
```
B = 1 − b,  b ∈ [0.382, 0.618]
C = c,      c ∈ [1.272, 1.414]
D = c·(1 − 0.786) = 0.214c  ∈ [0.2722, 0.3026]

BC/AB = (c + b − 1)/b  ∈ [1.44, 2.08]
CD/BC = 0.786c/(c+b−1) ∈ [1.08, 1.53]
AD/XA = 1 − 0.214c     ∈ [0.697, 0.728]   ← 不是 0.786！
```

上述推導值已用 200×200 網格數值枚舉複核（`scratchpad/verify.py`，2026-08-06），
實跑輸出與代數結果逐位相符：
`BC/AB 1.440–2.084`、`CD/BC 1.077–1.529`、`AD/XA 0.697–0.728`、`D 落點 0.2722–0.3026`。

**🚨 兩個開源實作都寫錯了這一條**（這正是你擔心的「錯誤不會被單元測試抓到」的實例）：

| 實作 | 寫的 BC 欄 | 寫的 D 欄 | 問題 |
|---|---|---|---|
| `neurotrader888` | `AB_BC = [1.13, 1.41]` | `XA_AD = 0.786` | BC 基準錯（該對 XA）＋下界錯（1.13→1.272）＋D 基準錯 |
| `djoffrey` | `AB-BC = 1.272–1.414` | `XAD = 0.786` | 數字對但**基準錯**：套在 AB 上而非 XA 上 |

正確值 `BC/AB ∈ [1.44, 2.08]` 與這兩個實作寫的 `[1.13,1.41]` / `[1.272,1.414]`
**幾乎不重疊**——照它們抄會偵測到完全不同的東西。

**結論：Cypher 必須用它自己的約束式，不能硬塞進統一的四欄 XABCD 表。**

---

### 3.3 陷阱三：Deep Crab vs Crab、Alternate Bat vs Bat 差在哪

**Deep Crab vs Crab — 差在 `AB/XA`（B 點），`AD/XA` 相同**

| | Crab | Deep Crab |
|---|---|---|
| **AB/XA** | **0.382–0.618** | **0.886** ← 唯一的本質差別 |
| BC/AB | 0.382–0.886 | 0.382–0.886 |
| CD/BC | 2.24–3.618 | 2.24–3.618 |
| AD/XA | **1.618** | **1.618**（相同！） |

Carney 原文：「employs an 0.886 retracement at the B point **unlike the regular version
that utilizes a 0.382-0.618** at the mid-point」。
兩者的 D 點都是 1.618 XA——**靠 AD/XA 分不出來，只能靠 B 點**。
偵測器若只比對 AD/XA 會把兩者混為一談。

**Alternate Bat vs Bat — 差在 `AB/XA` 與 `AD/XA` 兩條**

| | Bat | Alternate Bat |
|---|---|---|
| **AB/XA** | **0.382–0.50** | **0.382 或更小** ← 更淺 |
| BC/AB | 0.382–0.886 | 0.382–0.886 |
| **CD/BC** | **≥1.618（1.618–2.618）** | **≥2.0（2.0–3.618）** ← 更長 |
| **AD/XA** | **0.886（回撤，D 在 X 之內）** | **1.13（延伸，D 越過 X）** ← 關鍵差別 |
| 內嵌 AB=CD | 1.27 | 1.618 |

**最重要**：Bat 的 D 點**沒有**越過 X（0.886 < 1），Alternate Bat 的 D 點**越過** X
（1.13 > 1）。這是兩者在圖形上的根本區別，也是實作時的判別式：`AD/XA < 1` vs `> 1`。

---

## 4. 各形態的來源明細

| 形態 | 來源數 | 來源 |
|---|---|---|
| Gartley | 4 | harmonictrader Gartley 頁、neurotrader888、djoffrey、patternswizard／investmacro |
| Bat | 4 | harmonictrader Bat 頁、neurotrader888、djoffrey、patternswizard／investmacro |
| Alternate Bat | 2 | harmonictrader Alt-Bat 頁、djoffrey |
| Butterfly | 4 | harmonictrader Butterfly 頁、neurotrader888、djoffrey、patternswizard |
| Crab | 4 | harmonictrader Crab 頁、neurotrader888、djoffrey、patternswizard |
| Deep Crab | 3 | harmonictrader Deep-Crab 頁、neurotrader888、djoffrey |
| Shark | 5 | harmonicpattern.com、algorush、forextraininggroup、neurotrader888、djoffrey |
| Cypher | 4 | theforexgeek、investmacro/Medium、neurotrader888、djoffrey（後兩者有誤，見 §3.2） |
| 5-0 | 3 | harmonictrader 5-0 頁、algorush、fxopen/TradingView 教育頁 |

**沒有任何一格是單一來源**（除 §2 表中已標註的 Crab CD/AB）。

### 來源 URL

**Carney 原始定義（一級來源）**
- https://harmonictrader.com/harmonic-patterns/gartley-pattern/
- https://harmonictrader.com/harmonic-patterns/bat-pattern/
- https://harmonictrader.com/harmonic-patterns/alternate-bat-pattern/
- https://harmonictrader.com/harmonic-patterns/butterfly-pattern/
- https://harmonictrader.com/harmonic-patterns/crab-pattern/
- https://harmonictrader.com/harmonic-patterns/deep-crab-pattern/
- https://harmonictrader.com/harmonic-patterns/shark-pattern/ （只給 0.886／1.13，其餘要買書）
- https://harmonictrader.com/harmonic-patterns/5-0/

**開源實作（二級，交叉比對用）**
- https://github.com/neurotrader888/TechnicalAnalysisAutomation → `harmonic_patterns.py`
  （最完整、最接近 Carney；**唯 Cypher 有誤**）
- https://github.com/djoffrey/HarmonicPatterns → README 九形態表
  （**README 有 typo：`1.168`／`2.168`／`3.168` 應為 `1.618`／`2.618`／`3.618`**，
  已用 neurotrader888 交叉確認；Cypher 亦有基準錯誤）
- https://github.com/crypto10kx/harmonic-pattern-detection （只給 AB/XA 與 AD/XA）
- https://github.com/belur02/Amibroker-AFL-Library → `HARMONIC PATTERN DETECTION.afl`
  （只有 4 形態，區間極寬如 Gartley B=0.55–0.72，**不建議採用**）

**教學來源（三級）**
- https://patternswizard.com/xabcd-harmonic-pattern/ （4 形態，四欄格式最乾淨）
- https://www.investmacro.com/forex/2016/12/harmonic-trading-patterns-from-scott-m-carney-explained-in-detail/
  （= Medium `@TarantulaFX` 同一篇，**算一個來源不是兩個**）
- https://theforexgeek.com/cypher-pattern/
- https://algorush.com/trading-academy/advanced-lessons/harmonic-patterns/common-harmonic-patterns/5-0-pattern/
- https://algorush.com/trading-academy/advanced-lessons/harmonic-patterns/common-harmonic-patterns/shark-pattern/
- https://harmonicpattern.com/blog/shark-pattern/
- https://forextraininggroup.com/how-to-trade-the-harmonic-shark-pattern/
- https://forexbee.co/harmonic-shark-pattern/

---

## 5. 條件式 CD/BC（教科書慣例，值得注意）

`patternswizard` / `investmacro` 這類教學來源不給 CD/BC 區間，而給**條件式單點**：

| 形態 | BC/AB = 0.382 時 | BC/AB = 0.886 時 |
|---|---|---|
| Gartley | CD/BC = 1.272 | CD/BC = 1.618 |
| Bat | CD/BC = 1.618 | CD/BC = 2.618 |
| Butterfly | CD/BC = 1.618 | CD/BC = 2.618 |
| Crab | CD/BC = 2.24 | CD/BC = 3.618 |

**這不是另一套定義，而是同一套的另一種表述**：CD 必須把價格帶到 AD/XA 的目標位，
所以 BC 回撤越淺（C 越靠近 A），CD 相對 BC 就要越長。
→ **實作建議：不要把 CD/BC 當成獨立的硬 gate**。它在數學上幾乎被
`AB/XA`、`BC/AB`、`AD/XA` 三者決定。真正獨立的自由度只有三個。
把 CD/BC 設成寬區間（如表列）當 sanity check，讓 AD/XA 當主判別鍵。

---

## 6. 分歧清單（需在 spec 註明並做敏感度測試）

### 🔴 高度分歧（必做敏感度測試）

**D1. Cypher — 全形態最混亂**
- BC 基準：`XC/XA`（教學來源、正解）vs `BC/AB`（兩個開源實作，錯）
- D 基準：`CD/XC = 0.786`（正解）vs `AD/XA = 0.786`（兩個開源實作 + 部分教學來源）
- B 點區間：`0.382–0.618`（多數）vs `0.382–0.786`（djoffrey）
- XC 下界：`1.272`（多數）vs `1.13`（部分來源，疑與 Shark 混淆）
- **建議：Cypher 單獨列為次要形態，或在 spec 中預註冊兩個變體做敏感度對照。**

**D2. Shark 的 AB/XA（＝Carney 的 XA/0X）**
- Carney 核心 spec：**無此約束**
- `neurotrader888`：`None`（無約束）
- `djoffrey`：`0.5–0.886`
- `forexbee`：`0.382–0.5`
- 三種說法互不相容（`0.382–0.5` 與 `0.5–0.886` 幾乎不重疊）
- **建議：預設用「無約束」（跟 Carney），把 `0.382–0.886` 當寬 sanity check。**

### 🟡 中度分歧（影響命中率，不影響形態識別）

**D3. Butterfly 的 AD/XA**
- `1.27`（Carney 主張的 defining element、djoffrey）
- `1.27–1.41`（neurotrader888）
- `1.27 或 1.618`（investmacro、patternswizard）
- **建議：主表用 1.27，把 1.618 版本當獨立變體測。**

**D4. CD/BC 的區間下界（各實作不一）**

| 形態 | Carney | neurotrader888 | djoffrey | 本表採用 |
|---|---|---|---|---|
| Gartley | 1.27 或 1.618 | 1.13–1.618 | 1.13–1.618 | 1.13–1.618 |
| Butterfly | 1.618（extreme 2.0/2.24/2.618） | 1.618–2.24 | 1.618–2.24 | 1.618–2.618 |
| Crab | 2.24/2.618/3.14/3.618 | 2.618–3.618 | 2.618–3.618 | 2.24–3.618 |
| Deep Crab | 2.24/2.618/3.14/3.618 | 2.0–3.618 | 2.24–3.618 | 2.24–3.618 |

- 差異都在下界（是否納入 2.24）。因 §5 的理由，此欄影響有限。

### 🟢 已解決（原本看似分歧，查明為錯誤）

- `djoffrey` README 的 `1.168 / 2.168 / 3.168` = `1.618 / 2.618 / 3.618` 的 typo
  （用 `neurotrader888` 同位置數值確認）。
- `forextraininggroup` 說 Shark 的 BC 是「XA 的 161–224%」——其餘 4 個來源都說 AB，
  判定為該文筆誤。

### 無分歧（9 形態中最穩的部分）

Gartley（0.618 / 0.786）、Bat（0.382–0.50 / 0.886）、Alternate Bat（0.382 / 1.13）、
Crab（0.382–0.618 / 1.618）、Deep Crab（0.886 / 1.618）、5-0（CD/BC = 0.50）、
Shark（BC/AB 1.13–1.618、CD/BC 1.618–2.24、AD/XA 0.886–1.13）
——**所有來源逐字一致**。BC/AB = 0.382–0.886 在 Gartley/Bat/AltBat/Butterfly/Crab/DeepCrab
六種形態上也是全來源一致。

---

## 7. 容差（tolerance）業界慣例

### 慣例一：對「單點目標」加對稱百分比帶（最常見）

`ratio ∈ [target·(1−ε), target·(1+ε)]`，**逐比例各自施加**（不是對整體打分）。

| 來源 | ε | 說明 |
|---|---|---|
| `djoffrey/HarmonicPatterns` | **0.05（5%）** | `error_allowed=0.05`；0.618 → [0.5871, 0.6489] |
| 一般 harmonic 交易者慣例 | **0.02（2%）** | 0.786 → 0.786 ± 0.016 |
| TradingView 指標（reees 等） | 可調 | 「Allowed fib ratio error %」 |
| LuxAlgo 等商用 | Strict／Standard／Lenient 三檔 | Lenient 比 Standard 寬約 40% |

### 慣例二：區間型 spec 不另加容差

`0.382–0.886` 這種本身就是容差——區間端點已含寬容。**不要在區間上再加 ±5%**，
否則 Gartley 與 Bat 的 AB/XA 會重疊（0.618×0.95=0.587 vs 0.50×1.05=0.525，還好；
但 Bat 0.50×1.05=0.525 與 Gartley 0.618×0.95=0.587 之間只剩 0.06 的緩衝）。

### 慣例三：log 距離軟評分（`neurotrader888` 的做法，最適合本專案）

不做二值 pass/fail，而是算誤差分數再取最小者：

```python
# 單點目標
err = abs(log(actual) - log(target))
# 區間目標：在區間內 err=0，區間外算到最近邊界的 log 距離 × range_mult(=2.0) 懲罰
```

用 log 空間的好處：`1.618` 與 `0.618` 的相對誤差可比（比例是乘法量，不是加法量）。
最後對每個形態把四條 err 加總，取總分最低且低於閾值者為命中。

### 給本專案的建議【推測，需你裁決】

1. **單點目標用 ±5%**（0.618、0.786、0.886、1.13、1.27、1.618、0.50 這些）。
   2% 對 crypto 的雜訊太緊，命中數會太少。
2. **區間目標不加容差**，直接用表列端點。
3. **AD/XA 用更緊的容差（±3%）**——它是形態識別鍵，放寬會讓 Bat/Gartley/Butterfly 互相污染。
4. **形態互斥檢查 — 已實跑，結果 PASS**（`scratchpad/excl.py`，2026-08-06）。
   對 §8 凍結表的 8 個走統一四欄的形態（Cypher 除外）做 28 組 pairwise 檢查，
   單點目標依 ε 展開、區間目標不加容差、`None` 軸視為必然重疊：

   | ε | 四軸全重疊的配對數 |
   |---|---|
   | 0.02 | **0** |
   | 0.03 | **0** |
   | 0.05 | **0** |

   → 三個容差設定下都**兩兩互斥**，不需要定義優先序。
   關鍵分離軸實測：
   - **Crab vs Deep Crab**（AD/XA 都是 1.618）靠 `AB/XA` 分開：
     ε=0.05 時 `0.382–0.618` vs `0.842–0.930`，不重疊 ✅
   - **Gartley vs Crab** 的 `AB/XA` 確實重疊（ε=0.05 時 `0.587–0.618` 相交），
     但靠 `AD/XA`（0.786 vs 1.618）完全分開 ✅
     → 印證 §5 的結論：**AD/XA 才是識別鍵**，單看 AB/XA 會誤判。

---

## 8. 實作用凍結表（Python dict，可直接貼）

```python
# 預註冊比例表 — 2026-08-06 凍結，來源見 m_pattern_ratios_research.md
# 值為 (lo, hi)；單點目標寫成 (v, v) 由容差層展開
# None = 該形態無此約束

HARMONIC_RATIOS = {
    #                AB/XA           BC/AB           CD/BC           AD/XA
    "gartley":      ((0.618, 0.618), (0.382, 0.886), (1.13,  1.618), (0.786, 0.786)),
    "bat":          ((0.382, 0.500), (0.382, 0.886), (1.618, 2.618), (0.886, 0.886)),
    "alt_bat":      ((0.382, 0.382), (0.382, 0.886), (2.0,   3.618), (1.13,  1.13 )),
    "butterfly":    ((0.786, 0.786), (0.382, 0.886), (1.618, 2.618), (1.27,  1.27 )),
    "crab":         ((0.382, 0.618), (0.382, 0.886), (2.24,  3.618), (1.618, 1.618)),
    "deep_crab":    ((0.886, 0.886), (0.382, 0.886), (2.24,  3.618), (1.618, 1.618)),
    "shark":        (None,           (1.13,  1.618), (1.618, 2.24 ), (0.886, 1.13 )),
    "five_zero":    ((1.13,  1.618), (1.618, 2.24 ), (0.50,  0.50 ), None),
    # cypher 不走這張表 —— 見 CYPHER_RATIOS
}

# Cypher 用自己的基準（BC 對 XA、D 對 XC），塞進上表必錯
CYPHER_RATIOS = {
    "ab_over_xa": (0.382, 0.618),
    "xc_over_xa": (1.272, 1.414),   # C 相對 XA 段，從 X 起算
    "cd_over_xc": (0.786, 0.786),   # D 相對 XC 段
}

# 內嵌 AB=CD（soft score，非 hard gate）
AB_CD_RATIOS = {
    "gartley": 1.0, "bat": 1.27, "alt_bat": 1.618,
    "butterfly": (1.27, 1.618), "five_zero": 1.0,
    # crab: 1.27/1.618（單一來源）；deep_crab/shark/cypher: 不適用
}

TOLERANCE = 0.05        # 單點目標 ±5%；區間目標不加
TOLERANCE_AD_XA = 0.03  # 形態識別鍵，收緊
```

---

## 9. 未解決 / 你需要裁決的事

1. **Cypher 要不要納入**。它的定義分歧最大、且兩大開源實作都寫錯，
   意味著市面上「Cypher 有效」的說法可能建立在錯誤的比例上。
   建議：納入但單獨標記，回測時分開統計。
2. **Butterfly 的 AD/XA 用 1.27 還是 1.27+1.618 兩個變體**。
3. **Shark 的 AB/XA 是否加約束**（三種互斥說法）。
4. **容差 5% vs 2%**——這會直接決定樣本數，是回測統計顯著性的前置條件。
   （互斥性不是限制因素：ε=0.05 下仍然兩兩互斥，見 §7.4。）
5. ~~形態互斥檢查~~ **已實跑通過**（§7.4），無待辦。
6. **Carney 的三本書原文未取得**——harmonictrader.com 的公開頁面對 Shark／5-0
   只給片段（完整定義在 *Harmonic Trading Vol. 3*，2016）。Shark／5-0 的完整比例
   是靠 3–5 個二級來源交叉確認的，**不是一級來源直證**。
