# Bitfinex USD Margin Funding：策略研究報告

日期：2026-07-05。目的：為放貸策略引擎（目標淨年化 ≥12%）提供有證據的策略基礎，
區分「有公開證據/程式碼支持」與「社群傳說」。

**證據等級標記**：
- 【官方】Bitfinex 官方文件/API/blog
- 【程式碼】開源 bot 的實際策略原始碼
- 【一手數據】本研究直接從 Bitfinex 公開 API 拉取 2019-08~2026-07 數據自行計算（方法見 §8）
- 【三方】第三方服務文件/教學（可信度中等，注意行銷偏差）
- 【推測】無直接來源，標明推理依據

---

## 0. 核心結論（TL;DR）

1. **近三年（2024–2026H1）無腦滾 2 天期市價單的淨報酬只有 5–6%**（一手數據，含 15% 抽成、日複利）。
   FRR/auto-renew 級的被動策略在現行市場達不到 12%。2020 年同樣的無腦策略是 12.1%——報酬主要由市場 regime 決定。
2. 要往 12% 靠，有三個有證據的增益來源，全部要吃：
   **(a) 期限溢價**：30 天期成交利率中位數比 2 天期高 +2.2pp APR（平均 +4.1pp，79% 的日子 30d>2d）【一手數據】；
   **(b) 尖峰捕捉**：利率尖峰貢獻大——每年約 15–19 次尖峰事件，暴跌日的當日最高利率平均衝到 153% APR（無條件平均 32%）【一手數據】；
   **(c) 零閒置＋複利**：每 3–5 分鐘檢查、重掛、把已收利息滾入本金（所有開源 bot 的共同設計）【程式碼】。
3. 尖峰的形狀決定戰術：**暴跌日尖峰最高但隔天就衰減一半以上**（153%→46%）——只有「事先掛好的高利率長天期單」吃得到（守株待兔有數據支持）；
   **暴漲期的高利率持續數天**（63→48→56→63% APR）——這種用「追價重掛」吃得到。兩種機制都要有。
4. 「BTC 下跌時放貸利率上升（有人借錢抄底）」這個假設：**對單日暴跌事件成立、對利率水位不成立**。
   暴跌日當天尖峰最大，但衰減極快；而利率「水位」與前 7 日 BTC 報酬呈弱**正**相關（+0.105），
   高利率 regime 整體上伴隨多頭槓桿需求，不是下跌。詳見 §7。
5. 對 ≥12% 的初步判斷：**條件性可行**。牛市/高波動年（2019、2020、2023）被動策略已達或接近 12%，加上 (a)(b)(c) 可明顯超過；
   但在 2024–2026 這種低利率 regime，即使吃滿三個增益來源，12% 也緊繃——引擎必須是 regime-aware 的，並誠實回測 2024–2026 區間。

---

## 1. FRR 機制與「FRR vs 固定利率」（子問題 1）

### FRR 是什麼、怎麼更新
- 【官方】FRR（Flash Return Rate）= 「以金額加權的近期 funding 成交均價，經平滑處理避免突然尖峰，**每小時更新一次**」
  （官方 blog：blog.bitfinex.com/education/how-to-earn-with-margin-lending-on-bitfinex）。
  官方 support 文章（213919009，經 Cloudflare 阻擋、以搜尋摘要取得）的說法是「所有活躍固定利率 funding 以金額加權的平均」。
  兩個官方來源的公式描述不完全一致（成交 vs 活躍放貸）；引擎不應依賴精確公式，直接讀 API 發布的 FRR 值即可
  （`GET /v2/funding/stats/fUSD/hist` 每小時一筆，欄位為 FRR/365）。
- 【官方】掛 FRR 單成交時，**利率鎖定在成交當下的 FRR，貸款期間不再浮動**（blog 與 support 文章一致）。
  要讓利率隨 FRR 浮動，必須用 **FRRDELTAVAR**（API offer type：`LIMIT` / `FRRDELTAFIX` / `FRRDELTAVAR`；
  docs.bitfinex.com/reference/rest-auth-submit-funding-offer）。
  ⚠️ 歧義警告：API 文件寫「FRRDELTAVAR 掛 0 偏移 = 零偏移浮動單」，UI 的「FRR」選項到底對應 FRRDELTAFIX(0) 還是 FRRDELTAVAR(0)
  文件沒有明說——上線前用最小金額（150 USD）實測一筆確認。
- 【一手數據】當前（2026-07 初）FRR ≈ 0.0373%/日 ≈ 13.6% APR；書上供給 ~5.99B USD、被使用 ~5.92B（利用率 ~98.8%）。

### FRR vs 固定利率的取捨
| 面向 | FRR 單 | 固定利率單 |
|---|---|---|
| 省事 | 完全被動【官方】 | 要管理 |
| 尖峰 | 平滑化+每小時更新 → **吃不到短尖峰**【三方：AltInvest 2025-04】 | 事先掛高利率單才吃得到 |
| 成交速度 | 排隊；低活躍期可能等 | 貼著 book 掛可以很快成交【三方：kkinvesting 2026-03】 |
| 報酬 | ≈ 市場平均；社群實測 auto-renew 6–8%（2024–25）【三方：earn-usd】 | bot 使用者宣稱 8–20%【三方，注意自賣自誇】 |

**結論**：FRR 是 benchmark 不是策略。引擎用 FRR 當定價錨（所有 bot 都這樣做），但下單以固定利率單為主。

---

## 2. 利率尖峰特性（子問題 2）——一手數據

資料：fUSD 2 天期日 K（2019-08-31 ~ 2026-07-04，n=2500 天），方法見 §8。利率一律換算 APR%（日利率×365）。

### 年度分布（成交價）
| 年 | 收盤中位 APR | 收盤平均 | 日最高 p95 | 日最高 max | 收盤≥12% 天數 | 收盤≥20% 天數 |
|---|---|---|---|---|---|---|
| 2019 | 10.60 | 11.36 | 21.2 | 2555 | 40 | 4 |
| 2020 | 11.67 | 13.49 | 36.5 | 2555 | 176 | 58 |
| 2021 | 5.12 | 7.75 | **272.7** | 2555 | 63 | 23 |
| 2022 | 4.78 | 6.87 | 36.5 | 2555 | 35 | 17 |
| 2023 | 7.20 | 8.21 | 32.4 | 1253 | 41 | 15 |
| 2024 | 4.85 | 5.90 | 23.7 | 256 | 20 | 1 |
| 2025 | 5.70 | 6.71 | 32.9 | 277 | 38 | 1 |
| 2026H1 | 5.01 | 5.44 | 18.3 | 20.2 | 10 | 0 |

多個年份日最高恰好打到 2555% APR（= 7%/日）→【推測】平台日利率上限 0.07（API 驗證上限），引擎的利率參數驗證可用此界。

### 尖峰頻率與持續時間
- 定義「尖峰日」= 日最高 ≥ max(2×前 30 日收盤中位, 20% APR)：**105 次事件 / 6.8 年 ≈ 15–19 次/年**（每年都有，不挑牛熊）；
  **中位持續 2 天**、平均 6 天（被牛市長事件拉高，最長 69 天）。
- 「收盤 ≥12% APR」的 regime：183 段，**中位長度 1 天**、平均 2.3 天、最長 30 天，佔全部天數 17%。
- 「收盤 ≥20% APR」：60 段，中位 1 天，佔 5% 天數；條件平均利率 21–30% APR。
- **報酬集中度**：一年中利率最高的 10% 天數貢獻全年利率合計的 17–32%。尖峰不可放棄。

### 什麼觸發尖峰（事件研究，n=2499 天）
以「BTC 單日漲跌幅」分組，看事件日 +0..+3 的日最高利率平均（無條件平均 32.4% APR）：

| 事件 | n | day0 | day+1 | day+2 | day+3 |
|---|---|---|---|---|---|
| BTC 日跌 ≤ −5% | 107 | **153.3%** | 46.0 | 39.8 | 40.1 |
| BTC 日漲 ≥ +5% | 127 | 63.6 | 48.1 | 55.6 | 62.6 |
| BTC 日跌 ≤ −8% | 27 | 118.0 | 16.5 | 15.4 | 108.1 |
| BTC 日漲 ≥ +8% | 46 | 80.6 | 28.8 | 47.6 | 77.1 |

解讀：
- **暴跌日的當日尖峰最猛**（爆倉潮＋抄底槓桿），但**隔天迅速衰減**——想吃到它，掛單必須「事先」在高利率位掛好（守株待兔）。
  等看到暴跌再掛，通常只吃到殘值。
- **暴漲日的尖峰較低但持續**——多頭槓桿需求讓利率高原化數天，這段用動態追價（每小時重掛貼 book）就吃得到。
- 觸發因子的社群說法（槓桿多空比、CME 期貨溢價、Fear&Greed 高檔＝利率活躍）【三方：AltInvest 2025-05】方向與數據一致，但只有敘事沒有量化檢驗。

### 守株待兔掛單的證據
- 【程式碼】MikaLendingBot `hideCoins`（預設 True）：市場利率低於你的 `mindailyrate` 時不掛單，把錢藏著，
  「以便利率尖峰衝過你的 mindailyrate 時接到」——這就是守株待兔的實作（poloniexlendingbot.readthedocs.io configuration）。
- 【程式碼】Mika `xdaythreshold`（預設 0.2%/日 = 73% APR）：成交利率超過門檻時自動改掛 `xdays`（預設 60 天）長天期——
  尖峰時鎖長天期是既有 bot 的標準設計。
- 【一手數據佐證】尖峰中位只持續 1–2 天 → 尖峰價成交的單若只有 2 天期，鎖不住高利率；長天期才把 1 天的尖峰變成 30–120 天的高息。

---

## 3. Ladder（階梯掛單）的常見設計（子問題 3）——全部有程式碼

五個開源 bot 的階梯設計對照：

| Bot（語言/年代） | 階層數 | 定價基準 | 間距邏輯 | 重掛週期 |
|---|---|---|---|---|
| eAndrius/BitfinexLendingBot「MarginBot」(Go) | `SpreadLend`（例 5） | **book 深度**（走 ask 側累積量） | 從 `GapBottom` 到 `GapTop` 的深度均分，每層取該深度的 book 利率，floor=`MinDailyLendRate` | 每輪全撤重掛 |
| 同上「CascadeBot」 | 單價起掛 | **FRR + 增量**（`StartDailyLendRateFRRInc`） | 不階梯、用時間衰減：每 `ReductionIntervalMinutes` 降 `ReduceDailyLendRate`，可加 `ExponentialDecayMult`，floor=`MinDailyLendRate` | 依衰減間隔 |
| BitBotFactory/MikaLendingBot (Python) | `spreadlend` 預設 3（1–20） | **book 深度百分位**：`gapbottom` 預設 10、`gaptop` 預設 200（% 相對自己總資金，或 raw 金額） | gapbottom→gaptop 均分；`frrasmin` 可把 FRR 當最低利率 | 定時輪詢 |
| instabot42/funding-bot (JS) | `orderCount` 例 10 | **FRR 倍數**：`frrMultipleLow` 0.5×FRR ~ `frrMultipleHigh` 5×FRR，含絕對 floor | `easing`（linear/easein/easeout）非等距布點＋`randomAmountsPercent` 隨機化金額 | 每 60 分全撤重掛＋回收到期資金 |
| huaying/bitfinex-lending-bot (JS) | 金字塔 | 絕對利率區間 `LOW_BOUND_RATE` 0.0001~`UP_BOUND_RATE` 0.001/日 | **金額指數遞增**（`AMOUNT_GROW_EXP` 1.4）：利率越高掛越多 | 每 3 分鐘檢查 |
| MarcelSuleiman/SelfDriveFinancialResources (Python, 2024 後, 自稱 Lending Pro 替代品) | cascade 等分 N 層 | FRR 或 **WALL**（掃 book 找大額流動性牆，掛牆前一檔） | 連續檔位遞減（例 0.00045/43/41） | 每 5 分鐘檢查；**掛超過 4 小時未成交就撤** |

共同模式（可視為業界共識）【程式碼】：
1. 定價錨 = FRR 或 book 深度，不是拍腦袋的絕對利率；絕對利率只當 floor/ceiling。
2. 3–10 層，低層貼市價求成交、高層守尖峰；金額分配從均分到「高利率端加碼」（金字塔）都有。
3. 全撤重掛是主流（簡單、保證與市場同步），週期 3–60 分鐘。
4. 有 floor（`MinDailyLendRate`）防止在垃圾利率成交。

---

## 4. 期限選擇邏輯（子問題 4）

- 【官方】期限值域 2–120 天；官方 blog 建議常態用短天期（2–7 天）保持重定價彈性。
- 【程式碼】門檻式「利率高就鎖長」是標準設計：
  - MarginBot：`ThirtyDayDailyThreshold`——book 利率 ≥ 門檻 → 掛 30 天，否則 2 天；另有 `HighHoldAmount/HighHoldDailyRate` 保留一筆固定掛超高利率、永遠 30 天（純守株待兔倉）。
  - Mika：`xdaythreshold` 預設 0.2%/日（73% APR）→ 掛 60 天（範圍 2–60）。
  - instabot42：雙門檻插值——利率 < `lendingPeriodLow` 掛 2 天；> `lendingPeriodHigh` 掛 30 天；之間線性插值。
  - SelfDrive：`MIN_FOR_30D` 單一門檻切 2/30 天。
  - huaying：`PERIOD_MAP` 按權重混合（30d:30%、20d:25%、10d:20%、5d:15%、3d:12%）。
- 【一手數據】**期限溢價存在**：30 天期 vs 2 天期成交收盤的逐日配對差，中位數 +2.22pp APR、平均 +4.14pp，
  79% 的日子 30d>2d（各自的收盤中位數：p2 6.53%、p30 10.59%；n=2497 對齊日）。⚠️ 注意 p30 K 線成交稀疏、可能有 staleness/選擇偏差（借長天期的人通常更急）。
- 【推測，方向由數據支持】合理設計：常態資金主力掛 30 天上下吃期限溢價（數據顯示溢價為正且穩定），
  保留一部分 2 天期滾動保持彈性；利率打到高門檻（例如 ≥20–30% APR）時把成交單鎖到 60–120 天。
  120 天鎖定的機會成本：若後續出現更大尖峰吃不到——回測時要模擬。

---

## 5. 現行參數查證（子問題 5，2025–2026 資料）

| 參數 | 值 | 來源 |
|---|---|---|
| 放貸利息抽成 | **15%**（賺到的利息的 15%） | 【官方】blog + support 213919589/360024039494（搜尋摘要）；kkinvesting 2026-05 更新版同 |
| Hidden offer 抽成 | **18%** | 同上（多來源一致） |
| 最低掛單 | **150 USD** 等值 | 【官方】blog；kkinvesting；earn-usd 皆同 |
| 期限 | **2–120 天** | 【官方】API 文件 rest-auth-submit-funding-offer |
| Offer 類型 | `LIMIT`、`FRRDELTAFIX`（FRR+偏移，成交時定格）、`FRRDELTAVAR`（隨 FRR 浮動） | 【官方】API 文件 |
| 利率表示 | 日利率、小數（1% = 0.01/日） | 【官方】API 文件 |
| 利息結算 | 每日約 01:30 UTC 入帳；到期還本 | 【官方】blog；earn-usd |
| 利率上限 | 0.07/日（=2555% APR） | 【推測】多年 K 線最高價恰好 2555% APR |
| 下單 API 限速 | 90 req/min | 【官方】API 文件 |
| LEO 折扣 | LEO 持有者放貸費率有減免（幅度未查證） | 【三方：earn-usd】——實作前用帳戶實測 |
| Lending Pro | **已於 2024-08-28 停用**（官方自動放貸工具退場，自建 bot 的理由） | 【三方引官方公告：CoinCarp bitfinex-1054】 |

FRR 單抽成與固定利率單相同（15%）；沒有任何來源顯示 FRR 單費率不同。Hidden offer 的 +3pp 費率買到的只是「不顯示在 book 上」，
開源 bot 無一使用 hidden——【推測】對放貸方是負期望值功能，不用。

---

## 6. 已知 bot 失敗模式（子問題 6）

有直接證據的：
1. **資金閒置**：未成交的掛單賺 0。earn-usd Q&A 明列此風險；每個 bot 都有對策——instabot42 每 60 分全撤重掛、
  SelfDrive 4 小時未成交強制撤、huaying 每 3 分檢查。引擎的核心 KPI 之一就是 utilization。
2. **掛太高永不成交**：Mika 文件明說 `mindailyrate` 設太高＝錢永遠躺著；hideCoins 是刻意版本（賭尖峰），要有意識地配額。
3. **在垃圾利率成交**：book 前排常有 dust——Mika `gapbottom`（預設跳過 book 前 10%）就是為了「skip past dust at the bottom of the lending book」【程式碼文件原文】。
4. **FRR 平滑滯後**：尖峰時 FRR 跟不上（AltInvest 2025-04）；純 FRR 錨定的階梯在尖峰日會整體掛太低——尖峰偵測要用即時 book/成交，不能只看 FRR。
5. **複利斷鏈**：利息每天入帳但不會自動加入掛單，剩餘 <150 USD 的零頭也掛不出去——不重掛就沒有複利。官方 auto-renew 只續本金設定。
6. **2 天期吃到尖峰卻鎖不住**：尖峰中位持續 1–2 天（§2），尖峰價成交的 2 天單到期時利率已回落——沒有「尖峰→長天期」聯動的 bot 把最肥的肉做小了。
7. **全撤重掛的排隊成本**：【推測】同利率檔位是時間優先，頻繁全撤重掛會不斷排到隊尾；在深供給檔位（如 FRR 檔）尤其傷。
  對策（推測）：只重掛「偏離目標價超過閾值」的單，貼市單保留排隊位置。

社群傳說（無證據）：
- 「bot 一定比 FRR 賺很多」——bot 服務商自己的宣稱（8–20%），無獨立驗證；對照組數據（auto-renew 6–8%）也來自同一生態的 earn-usd。
- 「AI 優化利率」（Coinlend 首頁）——無任何方法學或數據披露，行銷語言。

---

## 7. 利率可預測性的證據（子問題 7）

### 一手數據（2019-08~2026-07 日線，n≈2500）
- corr(利率日變動, BTC 同日報酬) = **+0.063**（幾乎零，方向為正）
- corr(利率日變動, |BTC 同日報酬|) = 0.001
- corr(利率水位, 前 7 日已實現波動) = +0.053
- corr(利率水位, 前 7 日 BTC 報酬) = **+0.105**（弱正——漲一週後利率略高）

**線性可預測性趨近於零；訊號全在尾部事件**（§2 事件研究）。這對引擎的含義：不要做「利率預測模型」，
做「事件反應＋事先佈局」——平時吃 base+期限溢價，把高利率掛單當作免費的尖峰選擇權常駐在 book 上。

### 檢驗使用者假設：「BTC 下跌 → 放貸利率上升（借錢抄底）」
- **支持**：暴跌日（≤−5%，n=107）當日利率尖峰平均 153% APR，是無條件平均（32%）的 4.7 倍、也比暴漲日（64%）高——
  下跌確實觸發最猛的瞬時借貸需求（爆倉重建倉＋抄底槓桿混合，數據無法區分兩者）。
- **反對**：(a) 尖峰隔天就衰減到 46%，不是持續狀態；(b) 利率「水位」與 BTC 前 7 日報酬呈**正**相關，
  高利率年份（2019 median 10.6%、2020 11.7%）是多頭槓桿活躍期，2022 熊市 median 只有 4.78%——
  **熊市整體是低利率環境**；(c) 三方敘事一致指向「牛市槓桿需求」為主驅動（kkinvesting：「When Bitcoin runs hard, demand for leverage spikes, and lending rates follow」；AltInvest 2025-05：2021 牛市 >20% 年化、2022 熊市只有「brief spikes」）。
- **裁決**：假設對「事件」成立、對「水位」錯誤。正確版本：**任何方向的劇烈波動都造成 1–3 天的利率尖峰（下跌更猛更短），
  而持續的高利率 regime 屬於牛市**。
- 旁證（相鄰市場）：BitMEX perp funding 與 BTC 價格有 Granger 因果、GARCH 可建模（arXiv:1912.03270）；
  crypto carry 研究（CMU CarryTrade.v1.0）把 funding 需求連到槓桿需求。皆非 Bitfinex margin funding 的直接研究——
  **找不到針對 Bitfinex USD funding 利率可預測性的正式學術研究**（查過 arXiv/RePEc/ResearchGate 關鍵詞組合）。

---

## 8. 一手數據方法與回測資料源（給今晚的引擎）

本報告一手數據的取得（全部公開、無需 API key）：
```
GET https://api-pub.bitfinex.com/v2/candles/trade:1D:fUSD:p2/hist?limit=2500   # 2天期日K [MTS,O,C,H,L,V]，利率=日利率
GET https://api-pub.bitfinex.com/v2/candles/trade:1D:fUSD:p30/hist?limit=2500  # 30天期日K
GET https://api-pub.bitfinex.com/v2/candles/trade:1D:tBTCUSD/hist?limit=2500   # BTC 日K
GET https://api-pub.bitfinex.com/v2/funding/stats/fUSD/hist?limit=250          # 每小時：FRR/365、平均期限、供給量、使用量、<0.75% 掛單量（250筆/頁，start/end 翻頁）
```
- 更高解析度：同 candles 端點支援 1m/5m/1h；聚合 key `trade:1D:fUSD:a30:p2:p30`（合併 2–30 天期）。
- 完整歷史 funding book/stats：官方 bitfinexcom/bitfinex-terminal（GitHub，Dazaar 分散式 DB，免費），examples/funding-stats.js。
- 已知限制：K 線的 high 可能是極小量的成交（尖峰可捕捉量未知——回測要對「尖峰可成交量」做保守假設）；
  candles 只反映成交，不含掛單簿深度；p30 成交稀疏。要做成交模擬得用 bitfinex-terminal 的 book 資料。

計算定義（可重現）：年化 APR% = 日利率×365×100；「無腦滾動」= 每日以 p2 收盤利率計息複利、×0.85 費後、幾何年化；
尖峰事件 = 日最高 ≥ max(2×前30日收盤中位, 20% APR) 的連續日；事件研究以 BTC 日 K open→close 報酬分組。

---

## 9. 策略設計建議（證據 → 設計的映射）

依證據強度排序的引擎組件：
1. **零閒置循環**（證據最強、所有 bot 共識）：3–5 分鐘輪詢；到期/入帳資金立即重掛；未成交 1–4 小時撤單重定價；複利入本金。
2. **雙錨定價**：base 錨 = max(FRR, book 深度加權價)；floor = 動態最低利率（參考 Mika `frrasmin`）。不用絕對利率當錨。
3. **階梯**：3–7 層。低層（~60–70% 資金）貼市價/FRR 附近求成交吃 base＋30 天期限溢價；
   高層（~20–30% 資金）掛 2–5× 當前利率、**長天期（30–120 天）**守尖峰（對應 MarginBot HighHold＋Mika hideCoins 的組合，且由 §2 尖峰衰減數據支持）。
4. **期限規則**：利率門檻式（全部 bot 的共識設計）——常態 2 天（低利率時保彈性）或 30 天（利率尚可時吃溢價）；
   成交利率 ≥ 高門檻時鎖 60–120 天。門檻值今晚用 2019–2026 數據回測定，不要抄 bot 預設（Mika 預設 0.2%/日在 2024–26 regime 幾乎永不觸發）。
5. **regime 偵測（弱訊號，保守用）**：利率水位與多頭動能弱正相關——牛市態（BTC 7d 上漲＋利用率高）可整體上移階梯；
   別做日級預測模型（線性相關 ≈ 0）。
6. **不做**：hidden offer（+3pp 費率無放貸方收益）；純 FRR 掛單（尖峰吃不到）；把全部資金鎖 120 天（失去尖峰選擇權）。

## 10. 「有證據 vs 傳說」總表

| 做法 | 判定 |
|---|---|
| FRR 當定價錨、固定利率單執行 | ✅ 程式碼共識 |
| 階梯 3–10 層、book 深度/FRR 倍數間距 | ✅ 程式碼共識 |
| 利率門檻→鎖長天期 | ✅ 程式碼共識＋一手數據（期限溢價、尖峰衰減） |
| 守株待兔高利率長天期單 | ✅ 程式碼（hideCoins/HighHold）＋一手數據（暴跌日尖峰隔日即衰減） |
| 頻繁重掛防閒置＋複利 | ✅ 程式碼共識 |
| 「下跌=利率漲」 | ⚠️ 只對 1–3 天事件成立；水位反而與上漲弱正相關 |
| 「bot 穩定 8–20%」 | ⚠️ 服務商自述，無獨立驗證；被動基準近年僅 5–6% |
| 「AI 優化利率」（Coinlend 等） | ❌ 無披露、無證據 |
| Hidden offer | ❌ 對放貸方負期望（多付 3pp 費率） |
| 利率預測模型（日級方向） | ❌ 線性相關趨近 0；無學術支持 |

---

## 來源清單

**官方**
- Bitfinex blog（費率/FRR/期限/建議）：https://blog.bitfinex.com/education/how-to-earn-with-margin-lending-on-bitfinex
- Submit Funding Offer API（類型/期限/利率格式/限速）：https://docs.bitfinex.com/reference/rest-auth-submit-funding-offer
- Funding Stats API（FRR 歷史）：https://docs.bitfinex.com/reference/rest-public-funding-stats
- 歷史數據：https://github.com/bitfinexcom/bitfinex-terminal
- Support 文章（Cloudflare 擋直抓，內容經搜尋摘要，關鍵數字已與 blog/三方交叉驗證）：213919589（費率）、360024039494（利息計算）、213919009（FRR）、115003284729（FRR Delta）
- Lending Pro 停用公告（轉載）：https://www.coincarp.com/exchange/announcement/bitfinex-1054/

**開源 bot（策略程式碼）**
- https://github.com/eAndrius/BitfinexLendingBot（marginbot.go、cascadebot.go）
- https://github.com/BitBotFactory/MikaLendingBot ＋ https://poloniexlendingbot.readthedocs.io/en/latest/configuration.html
- https://github.com/instabot42/funding-bot
- https://github.com/huaying/bitfinex-lending-bot（server/custom-config.example.js）
- https://github.com/MarcelSuleiman/SelfDriveFinancialResources
- https://github.com/cryptic-core/bf-lending-bot（README 資訊少）

**三方/社群**
- kkinvesting 教學（2026-05 更新；費率/APY 區間/策略）：https://kkinvesting.io/en/posts/bitfinex-lending-tutorial/
- earn-usd Q&A（2025-09）：https://earn-usd.com/articles/bitfinex-qa ；利率頁：https://earn-usd.com/bitfinex-lending-rates-history/
- AltInvest：FRR 深析（2025-04）https://medium.com/@altinvestbot/is-bitfinex-frr-lending-the-best-choice-a-deep-dive-into-automated-lending-bots-ad42d0c5b3f1 ；利率趨勢（2025-05）https://medium.com/@altinvestbot/bitfinex-lending-beginners-guide-understanding-crypto-lending-opportunities-through-interest-rate-ac72162a949b
- Cryptolend 策略taxonomy（歷史參考，2015-16 宣稱 USD 19%）：https://cryptolend.net/resources/strategies-introduction.html

**學術（相鄰市場，非直接）**
- BitMEX Funding Rate 與 BTC 相關性（GARCH/Granger）：https://arxiv.org/abs/1912.03270
- The Crypto Carry Trade（CMU）：https://www.andrew.cmu.edu/user/azj/files/CarryTrade.v1.0.pdf

**一手數據**：Bitfinex 公開 API（§8 端點），2019-08-31~2026-07-04，分析於本報告 §2/§4/§7；原始 JSON 在 session scratchpad（暫存），端點與計算定義已載明可重現。
