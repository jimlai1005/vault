> **Sub-project M 背景研究**｜產出日期：2026-08-06｜作者：Claude subagent（Opus 5）
> 本報告為 sub-project M（諧波形態策略）的證據基礎，非最終 verdict。
> 研究方法與來源見內文；所有結論以內文標註的來源為準，未標來源者為推論。

# Harmonic patterns (Gartley/Bat/Butterfly/Crab/Shark/Cypher)：實證證據盤點

研究日期 2026-08-06。所有結論附來源；未經本次查證的以【推測】或【未查證】標記。

---

## 結論先行

1. **沒有任何一份大樣本、同行評審的研究測過 harmonic patterns 本身**——不是「測過而結果為負」，
   是**根本沒人做過**。整個 XABCD 家族在學術文獻裡的全部足跡是兩篇波蘭文期刊論文，其中一篇
   我實際下載讀完，樣本是**手挑的 5 筆交易**。
2. **但形態的核心成分——Fibonacci 比例——被嚴格測過而且結果是明確的負**：160 檔股票、
   51 年日線，價格在 Fib 位反彈的機率與在**隨機非-Fib 位**反彈的機率統計上無法區分
   （49.08% / 51.89% / 49.84%，即擲硬幣）；用 Fib 位做交易規則的報酬與用隨機位做的無顯著差異。
   同一篇論文還直接量化了問題 b：**放寬容差會單調提高「命中率」但完全不改善交易績效**——
   這正是所有「勝率 80%」宣稱的製造機制。
3. 因此建議：**不要做「更好的 harmonic 腳本」，Fib 比例那一層應該整個丟掉**。形態邏輯裡真正
   有文獻支撐的是「掃單後反轉」與「短期反轉」這兩個**微結構**成分（見問題 e），它們有
   機制解釋、有大樣本證據，而且**不需要 Fibonacci**。

---

## a. 有沒有大樣本（>1000 實例）研究測過 harmonic patterns？

### 直接答案：沒有。文獻裡的全部足跡如下。

| 研究 | 樣本 | 性質 |
|---|---|---|
| Bednarz (2013), *Folia Oeconomica Stetinensia* 13(1):7-21，BAT 形態 | 未揭露樣本數，abstract 只給「206.43% / 27 天」單一數字 | 概念示範，非統計檢定 |
| Bednarz (2014), *Roczniki Ekonomii i Zarządzania* 6(42) nr 1，Butterfly 形態 | **n = 5 筆手挑交易**（3 勝 2 敗，總報酬 492.31%） | 教學案例 |

- Bednarz (2013) abstract：<https://ideas.repec.org/a/vrs/foeste/v13y2013i1p7-21n2.html>
- Bednarz (2014) 全文 PDF（波蘭文，我已下載並抽文字驗證）：
  <https://ojs.tnkul.pl/index.php/reiz/article/download/10193/10122/>
  — 論文第 5 節「PODSUMOWANIE PRZEPROWADZONYCH INWESTYCJI」的 Tabela 5 逐筆列出
  五筆交易：I +93.08%、II −10%、III +313.08%、IV +106.15%、V −10%，RAZEM ≈ 492.31%。
  無樣本外測試、無統計檢定、無交易成本、標的為單一波蘭指數期貨。

**這是全世界「harmonic patterns 有效」最強的同行評審證據。n=5，手挑。**

### 相鄰但不等同的學術證據（測的是「圖形形態」而非 harmonic）

- **Lo, Mamaysky & Wang (2000)**, *Journal of Finance* 55(4):1705-1765。美股 1962-1996，
  kernel regression 自動偵測 H&S、雙底等。結論：部分形態確有 incremental information。
  **但作者自己就寫**：「patterns that are optimal for detecting statistical anomalies need not be
  optimal for indicating trading profits」。<https://www.nber.org/papers/w7613>
- **Savin, Weller & Zvingelis (2007)**, *J. Financial Econometrics* 5(2):243-265。S&P500 +
  Russell 2000，1990-1999，H&S。風險調整後超額報酬 5-7%/年，**但「little or no support
  for the profitability of a stand-alone trading strategy」**。
  <https://academic.oup.com/jfec/article-abstract/5/2/243/785044>
- **Dawson & Steeley (2003)**, *J. Business Finance & Accounting* 30(1-2):263-293。英股複製
  Lo et al.，結論同樣是「形態有資訊、但不轉化為交易利潤」。

**共同模式：形態能帶來統計上的資訊增量，但那點資訊不足以支付交易成本。** 這對 crypto
更嚴苛，因為 HL taker 費率遠高於美股。

### 「勝率 68% / 80-90%」的宣稱來源
- 「*Journal of Technical Analysis* 發現 harmonic 在 forex 68%、股票 62%、crypto 58%」——
  **查不到原始論文**。這串數字只出現在賣指標的 vendor blog（LuxAlgo 等）互相抄襲，
  沒有卷期、沒有作者、沒有 DOI。
- 「FxGroundworks 系統性分析近 3000 個形態，成功率 >80%，部分 >90%」——
  同樣**查無原始出處**，只在行銷頁互引。
- 連 harmonic 指標商自己都承認這些數字是假的：algotrading-investment.com 指出這類數字來自
  **repainting 指標「只顯示成功的形態、不顯示失敗的形態」**，且「When you see success rate
  like this, you must question yourself what is the Reward/Risk ratio... Otherwise, these numbers
  are meaningless」。<https://algotrading-investment.com/2019/03/15/harmonic-pattern-success-rate-and-testing-results-explained/>
- Trendoscope 的 Auto Harmonic Pattern Backtester（TradingView 上最主流的 harmonic 回測工具）
  **不發表任何彙總勝率**，且自己標註「NOT A STRATEGY AND SHOULD NOT BE FOLLOWED BLINDLY」。

---

## b. 偵測自由度（Fib 容差、pivot depth）如何改變結果？有人量化過嗎？

### 有，而且是本次研究最重要的一份文獻。

**Tsinaslanidis, Guijarro & Voukelatos (2022)**, "Automatic identification and evaluation of
Fibonacci retracements: Empirical evidence from three equity markets",
*Expert Systems with Applications* 187:115893。
開放全文：<https://riunet.upv.es/bitstream/handle/10251/195083/TsinaslanidisGuijarroVoukelatos%20-%20Automatic%20identification%20and%20evaluation%20of%20Fibonacci%20retracemen....pdf>
（我已下載全文並逐段驗證下列數字。）

**樣本**：DJIA 30 檔 + DAX 30 檔 + NASDAQ 100 檔 = 160 檔藍籌股，日線，
**1968 年 1 月 – 2019 年 3 月（超過 50 年）**，資料來源 Bloomberg。

**方法**：把「容差」形式化為 ζ（在每個 Fib 位上下建構寬度 ±ζ 的 zone），
測 ζ ∈ {0%, 2%, 4%, 6%}；用 bootstrap（樣本 500–10,000、重複 500 次）比較
「打到 Fib zone 後反彈」vs「打到隨機非-Fib zone 後反彈」的 log-odds。

**結果（逐字自論文）**：
- ζ = 0（精確 Fib 位）時，反彈機率：**DOW 49.08%、DAX 51.89%、NASDAQ 49.84%**——擲硬幣。
- 「we cannot reject the null hypothesis of equal probabilities at the 5% significance level...
  the probability of prices bouncing on Fibonacci levels is **statistically indistinguishable**
  from the probability of bouncing on non-Fibonacci levels.」
- **容差敏感度（直接回答問題 b）**：ζ 從 0→2%→4%→6%，反彈機率的 slope「consistently positive,
  statistically significant, and **monotonically increasing across the zone width**」。
  但同一篇：「**trading performance remains poor irrespective of the width selected**」。
- **更糟的轉折**：ζ = 6% 時，統計上顯著地變成「價格在**非-Fib** zone 反彈的機率比 Fib zone **更高**」。
- 交易規則：「an investor who trades according to hits on Fibonacci zones would have earned
  **statistically the same mean return** as another investor who simply trades based on hits on
  **random non-Fibonacci zones**」。
- 作者對機制的詮釋：「analysts are naturally more likely to identify what they perceive to be
  profitable trading opportunities as they consider wider Fibonacci zones that reflect higher
  subjectivity/inaccuracy, **but at no significant improvement in their subsequent trading performance**」。

**這對本專案的直接意涵**：`Fib 容差` 這個參數是一個**純粹的自欺旋鈕**——調大它，
偵測到的形態數與「命中率」都會漂亮地上升，回測報表會變好看，而期望值不動。
如果我們做 harmonic 回測，這個參數的敏感度分析會是報告裡最重要的一張表，
而根據這篇論文，我們幾乎可以預先知道它會長什麼樣。

### pivot depth 這一側：沒有直接量化文獻，但有形式化框架
- ZigZag/pivot 偵測的參數（depth、deviation、backstep）沒有找到學術級敏感度研究。
  能找到的只有 vendor 文件（「depth 太低會過早認定 pivot，太高會濾掉有意義的趨勢」）。
- 正確的形式化工具是 **Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest
  Overfitting"**（<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>）與
  **Bailey & López de Prado, "The Deflated Sharpe Ratio"**, *J. Portfolio Management* 40(5):94-107
  （<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>）：只要記錄嘗試過的
  參數組合數 N，就能把 Sharpe 折減回真實水準。Bailey et al. 證明**在真實 Sharpe = 0 的
  模擬路徑上，試幾組參數就能輕鬆做出 Sharpe > 1 的回測**。
- **harmonic 偵測的自由度粗算**：pivot depth/deviation（2）× 每個形態 3-5 個比例約束 ×
  每個約束的容差（1）× 形態種類（6+）× 進場規則 × 停損位 × 目標位（通常 3 個 Fib 目標）
  ≈ 輕易上百組合。**這正是 Deflated Sharpe / PBO 存在的理由。**
- **repaint 是額外的、非參數的問題**：ZigZag 天生 repaint（確認 pivot 需要未來 K 棒）。
  TradingView 社群的處理是「confirm only when D pivot forms」。**任何不做這件事的回測
  數字一律不可採信**——這是「用了就賺」宣稱最大的單一來源。

---

## c. 「用了就賺」的說法來自什麼偏誤？

按殺傷力排序：

1. **Repaint / 事後選圖（最大宗）**。ZigZag 需要未來 K 棒確認 pivot，指標在圖上「回頭畫」
   出完美形態；失敗的形態則從不顯示。algotrading-investment 明說這類指標
   「do not show the failed patterns in chart」。
2. **勝率與風報比脫鉤**。harmonic 的傳統目標是 D 點後 AD 段的 0.382 回撤——一個**很近的目標**，
   自然高命中率；停損放在 X 點外——一個**很遠的停損**。勝率 80% 搭配 R:R = 1:5 的期望值是負的。
   所有引用勝率而不引用 R:R 的宣稱都是無意義的（同上引文）。
3. **容差旋鈕（見 b）**。放寬 ζ 單調拉高命中率、不動期望值。Tsinaslanidis et al. 已實測。
4. **多重檢定不做校正**。以下是一個活生生的學術例子：
   **Miller, Yang, Sun & Zhang (2019)**, "Identification of technical analysis patterns with
   smoothing splines for bitcoin prices", *Journal of Applied Statistics*,
   DOI 10.1080/02664763.2019.1580251（我已下載全文驗證下列細節）：
   - 資料：GDAX BTC，**2018-02-05 至 2018-03-06，僅一個月**，43,199 根 1 分鐘 K。
   - 檢定：12 種形態 × 10 種持有期 = **120 個檢定，零多重檢定校正**（α=0.05 下期望 6 個假陽性）。
   - 宣稱的「very high excess returns」：H&S 1 分鐘平均報酬 **0.0001451 = 1.45 bps**；
     IHS 4 分鐘 **0.0003726 = 3.73 bps**。
   - **全文零交易成本會計**。crypto taker 來回成本約 10-20 bps，**edge 比成本小一個數量級**。
   - 期間 BTC 上漲 30.54%（單一 regime）；雙頂形態在 43,199 分鐘內產生 13,683 筆「交易」
     （平均每 3 分鐘一筆，視窗高度重疊），而其 bootstrap 假設 iid 抽樣，**未處理重疊**。
   - 形態偵測跑在 35 分鐘視窗的平滑樣條擬合值上（「the presence of patterns is investigated on
     smoothing splines model fits, not on the price data itself」）——雙邊平滑的端點極值
     判定在實時是拿不到的。【推測：這構成 look-ahead，但論文未揭露足夠細節可確證。】
   - 作者自己的結論仍是「Our results are promising」。**一份通過同行評審的論文可以長這樣。**
5. **樣本外崩潰 / 資料窺探**。Sullivan, Timmermann & White (1999), *J. Finance* 54(5):1647-1691：
   White's Reality Check 校正後，Brock et al. 樣本內最佳規則仍優越，但**在其後 10 年樣本外
   不再優越**；S&P500 期貨上校正資料窺探後**無任何規則勝出**。
   <https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00163>
6. **交易成本**。Bajgrowicz & Scaillet (2012), *J. Financial Economics* 106(3):473-491：
   DJIA 1897-2011，用 FDR。「even in-sample, the performance is **completely offset** by the
   introduction of **low** transaction costs」，且持續性檢定顯示投資人**事前永遠選不出**
   未來最佳規則。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1095202>
7. **survey 級的總評**。Park & Irwin (2007), *J. Economic Surveys* 21(4):786-826：95 份現代研究，
   56 正、20 負、19 混合——**但作者接著指出大多數研究本身有 data snooping、事後挑規則、
   風險與交易成本估計不當的問題**。正面多數本身就是發表偏誤的產物。

---

## d. 加密貨幣（永續、24/7、高波動）上有沒有專門證據？

**harmonic patterns 在 crypto 上：零學術證據。** 我用多組關鍵字搜 arXiv q-fin、SSRN、
ScienceDirect、MDPI、Springer、Semantic Scholar，找不到任何一份針對 crypto 的 harmonic/XABCD
實證研究。這是「沒人研究過」，不是「研究過而結果為負」。

相鄰的 crypto 技術分析證據（都不是 harmonic）：

| 研究 | 樣本 | 結論 |
|---|---|---|
| Miller et al. (2019), *J. Applied Statistics* | BTC 1 分鐘，1 個月 | 見上，方法論不可用 |
| Svogun & Bazán-Palomino (2022), *JIFMIM* 79:101601，"Technical analysis in cryptocurrency markets: Do transaction costs and bubbles matter?" | 69 條 MA/breakout 規則，2016-2021，日線與 1 分鐘，5 種幣 | TA **可能**勝過 buy-and-hold；但成本與泡沫的影響**逐幣不同**（對 XRP/LTC 成本降低勝率，對 BTC/ETH 反而提高）——逐幣不一致本身就是雜訊的特徵。69 條規則，未見 Reality Check。 |
| Gurrib, Nourani & Bhaskaran (2022), *Financial Innovation*，Fibonacci 回撤 | 10 檔能源股 + 4 種能源幣，**543 個日線觀測值**（2017-11 至 2020-01） | 宣稱 Fib 策略優於 buy-and-hold，但 Sharpe 一律很低，且「Fibonacci 工具捕捉股票優於加密貨幣」。**在 crypto 崩盤期，任何會空手的策略都能贏 buy-and-hold**——這個比較基準有結構性偏誤。<https://pmc.ncbi.nlm.nih.gov/articles/PMC8752186/> |
| Han, Kang & Ryu (SSRN 4675565)，crypto momentum | 全市場 | 「when appropriately assessed, accounting for transaction costs and daily price fluctuations, many momentum portfolios are liquidated and many with statistically significant returns earn **insignificant** profits」<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565> |

**crypto 的結構讓情況更壞，不是更好**：24/7 無收盤價、無 session 邊界（Fib 常用的
swing 高低點定義因此更任意）；波動更高使「±5% 容差」在 BTC 上比在股票上更容易被隨機命中；
永續的資金費率是額外的持有成本，harmonic 的持有期通常數天到數週。

---

## e. 反過來問：形態邏輯裡哪些成分有獨立實證支持？【本節是可執行的替代清單】

**判準**：以下每一項都要有 (i) 大樣本實證 或 (ii) 明確的微結構機制，且**不依賴 Fibonacci 比例**。
標註為「機制級」的最強——它們解釋了為什麼 S/R 反轉這件事本身是真的，而 Fib 位不是。

### E1. 掃單反轉（swing failure / liquidity sweep）— 機制級，最強的替代品 ★★★
- **Osler (2003)**, "Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive
  Success of Technical Analysis", *Journal of Finance* 58(5)。用一家大型外匯做市銀行的**真實委託單簿**
  資料，證明：**take-profit 單強烈聚集在整數關卡**（→ 解釋「趨勢在可預測的 S/R 位反轉」）；
  **stop-loss 單強烈聚集在整數關卡的『稍外側』**（→ 解釋「價格穿過 S/R 後異常加速」）。
  <https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588>
- **Osler, "Stop-Loss Orders and Price Cascades in Currency Markets"**, NY Fed Staff Report 150。
  「exchange rates trend rapidly, on average, when they hit clusters of stop-loss orders」。
  <https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf>
- **這是整份研究裡唯一一個「S/R 反轉」的真實機制**。關鍵翻譯：反轉的原因不是幾何比例，
  是**掛單分布**。harmonic 的 D 點之所以偶爾管用，是因為它常好落在一個 swing 極值外側，
  也就是停損堆積處——但那是**巧合命中了 E1，不是 Fib 在起作用**。
- **crypto 可實作性極高，而且比外匯更好**：外匯的委託單簿是私有的（Osler 拿的是一家銀行的
  內部資料）；**永續合約的清算資料是公開的**。可用的代理變數：liquidation 事件流、
  open interest 驟降、資金費率極值、L2 簿深度真空。
- crypto 側佐證：`arXiv:2607.27070`（七次 BTC 永續清算級聯，2022-2025，分鐘級價格 +
  5 分鐘槓桿/委託流資料）與 `arXiv:2608.03616` 都在實證清算級聯的微結構通路。
  另有文獻記載「3.51% of long positions and 1.89% of short positions face forced liquidation
  on a daily basis」——**這是每天都在發生的高頻現象，不是罕見事件**。
- **具體訊號形狀**：`前 N 根的 swing 高/低被刺破 → X 分鐘內收回該水位之內 → 同時伴隨
  清算量尖峰 / OI 驟降 → 反向進場，停損放在刺破極值外`。這是「SFP」的量化版，
  每一個成分都對應到 Osler 的機制。

### E2. 短期反轉 — 大樣本級，但**有一個對本專案致命的但書** ★★☆
- **Zaremba, Bilgin et al. (2021)**, "Up or down? Short-term reversal, momentum, and liquidity
  effects in cryptocurrency markets", *International Review of Financial Analysis*。
  **>3,600 種幣的日線**。低前日報酬的幣顯著跑贏高前日報酬的幣。
  <https://www.sciencedirect.com/science/article/pii/S1057521921002349>
- **但書（必須劃重點）**：「The daily reversals result from the **illiquidity** of the vast majority
  of traded cryptocurrencies... the handful of **largest and most tradeable coins exhibit daily
  momentum rather than a reversal**.」
  → **Hyperliquid 上能交易的正是「最大、最好交易」的那一小撮幣。**
  這條 edge 在本專案的可交易宇宙裡**方向是相反的**。這是我找到最重要的反面證據之一，
  若要用短期反轉，必須自己在 HL 的實際幣種上重測，不能引用這篇的正面結論。
- **Wen, Bouri, Xu & Zhao (2022)**, "Intraday return predictability in the cryptocurrency markets:
  Momentum, reversal, or both", *North American J. Economics and Finance* 62。BTC 高頻資料
  2013-03-03 至 2020-05-31，**日內動能與日內反轉同時存在**，且形態隨大跳動、FOMC、
  流動性、COVID 而改變。<https://www.sciencedirect.com/science/article/abs/pii/S1062940822000833>
  → 意涵：**反轉是有條件的（conditional），不是無條件的**。條件變數（跳動、流動性）
  才是真正該建模的東西。
- **反面證據**：Caporale & Plastun (2019), *Journal of Economic Studies*，「Price overreactions in
  the cryptocurrency market」：基於過度反應後反向操作的策略**不獲利**；順勢版本獲利但
  **與隨機結果無統計差異** → 「the overreactions detected in the cryptocurrency market do not
  give rise to exploitable profit opportunities (possibly because of transaction costs)」。
  同組作者 2020 年在 *JIFMIM* 65 的後續研究則得到較正面結論。**同一組作者、同一主題、
  結論不一致——這條 edge 的信心應該低。**

### E3. 訂單流失衡（order flow imbalance）— 機制級、可實作 ★★★
- **Cont, Kukanov & Stoikov (2014)**, "The Price Impact of Order Book Events",
  *Journal of Financial Econometrics*。50 檔 NYSE 股票、TAQ 資料。短區間內價格變動
  **主要由最佳買賣價的委託流失衡驅動**，且關係**近似線性**，斜率與市場深度成反比；
  結果對季節性穩健、跨時間尺度與跨個股穩定。
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1712822> / <https://arxiv.org/pdf/1011.6402>
- **為什麼列在這裡**：這是「支撐壓力位聚集效應」唯一有堅實實證的版本——不是幾何位置，
  是**掛單量在價位上的分布**。HL 有 L2 簿與逐筆成交，這是可以直接量測的。
- 專案 CLAUDE.md 已記載 1m K 線 scalping 的 NO-GO 判定「重開需新資訊源（L2/WS）」——
  **E3 正好就是那個新資訊源**。

### E4. 整數關卡聚集 — 效應存在，但「可交易性」未獲證實 ★☆☆
- **Urquhart (2017)**, "Price clustering in Bitcoin", *Economics Letters*：BTC 日收盤價顯著聚集
  在整數，>10% 的價格以 00 結尾。<https://www.sciencedirect.com/science/article/abs/pii/S0165176517303233>
- 後續：*Finance Research Letters* (2022) "Evidence for round number effects in cryptocurrencies
  prices"；*Financial Innovation* (2021) 日內聚集；1 分鐘級整數聚集約 2.84%–5.29%。
- **關鍵反面證據**：搜尋摘要指出這些研究「there is **no significant pattern of returns after the
  round number**」——聚集是真的，但**穿越整數後的報酬沒有可預測性**。
  【此句為二手搜尋摘要，未由原文逐字驗證；若要採用 E4 必須先讀原文確認。】
- 判斷：整數關卡適合當**條件變數**（標記「這裡可能有掛單堆積」），不適合當**訊號本身**。
  與 E1 組合使用（整數關卡外側的掃單）比單獨使用強得多。

### E5. 波動壓縮→擴張 — 支持「波動可預測」，**不支持「方向可預測」** ★★☆（但用途受限）
- 沒有找到 NR7/squeeze 的同行評審研究。找到的全部是 vendor blog（例：「550 個壓縮形態、
  63% 在隨後一週跑贏 S&P」——樣本一個半月，無校正，不可採信）。
- **真正有支撐的是底層事實**：波動有長記憶、可預測（HAR-RV 類模型）。
  【Corsi (2009), *J. Financial Econometrics* 7(2):174-196 — 此引用來自訓練資料，**本次未查證**。】
- vendor 文獻自己也承認：「Low volatility does **not** predict direction; instead, it reflects
  temporary equilibrium between buyers and sellers.」
- **正確用途**：**不是進場訊號，是 sizing / 停損寬度的輸入**。這與本專案 memory 裡
  「B1 變身／超一」的 vol-target sizing 層是同一件事——**已經在用了**，不需要重新發明。

### E6.（附帶）harmonic 唯一可能有意義的殘餘成分
把 harmonic 拆開後，剩下**不含 Fib** 的部分是：「一段趨勢 → 一次回撤 → 一次反向延伸
超過前極值 → 收回」。剝掉比例約束，這就是 **E1（掃單反轉）** 的幾何描述。
**Butterfly / Crab（D 點在 X 點之外）本質上就是 SFP；Gartley / Bat（D 點在 X 之內）不是。**
【推測，但可檢驗】：若要證偽整個家族，最有資訊量的單一實驗是——
**測「D 點超出 X 點」的子集 vs 「D 點在 X 點之內」的子集**。
如果前者顯著較好，那 edge 來自 E1 而不是 Fib；如果兩者一樣，Fib 與掃單都不成立。
這個實驗把「六種形態 × 多個比例」壓縮成**一個二元對照**，自由度極低，難以過擬合。

---

## 最強的反面證據（兩個方向各自）

### 對「harmonic 有用」最強的反證
**Tsinaslanidis, Guijarro & Voukelatos (2022)**：160 檔股票、51 年、bootstrap 500 次。
價格在 Fib 位反彈機率 ≈ 50%，與隨機位**統計上無法區分**；ζ=6% 時**隨機位還顯著更好**；
Fib 交易規則報酬與隨機位交易規則報酬無顯著差異。
harmonic patterns 的每一個約束都是 Fib 比例的複合——**如果單一 Fib 位沒有資訊，
把 3-5 個沒有資訊的約束疊起來不會產生資訊，只會產生更少的樣本與更多的自由度。**

### 對「harmonic 沒用」最強的反證（誠實列出）
1. **Osler (2003) 的機制是真的**。趨勢確實會在可預測的價位反轉，而且有委託單簿的直接證據。
   harmonic 交易者宣稱的現象（「PRZ 是高機率反轉區」）**在現象層次不是幻覺**——
   錯的是歸因（歸給 Fibonacci 而不是掛單分布）。所以「harmonic 完全沒用」也是過強的說法：
   它是一個**對真實現象的錯誤模型**，偶爾會蒙對。
2. **Lo, Mamaysky & Wang (2000) 與 Savin, Weller & Zvingelis (2007)** 都在大樣本上找到
   圖形形態的統計資訊增量（後者 5-7%/年風險調整超額報酬）。形態辨識這件事本身
   不是零資訊。**但兩篇都明說不轉化為 stand-alone 交易利潤。**
3. **沒人測過 ≠ 測過是負的**。嚴格說，harmonic patterns 的直接證據是**空集合**。
   我上面的推論是「其核心成分（Fib）被證偽 + 其複合結構放大自由度」，這是**推論不是實測**。
   若要下 NO-GO verdict，誠實的說法是「基於成分證偽的高信心先驗」，不是「已被實測否定」。
4. **Svogun & Bazán-Palomino (2022)** 在 crypto 上確實找到 TA 勝過 buy-and-hold 的證據。
   雖然逐幣不一致、雖然是 MA/breakout 而非 harmonic，但這是 crypto TA 有效的最好同行評審證據。

---

## 對本專案的具體建議

1. **不要做「更好的 harmonic 腳本」**。要贏過那支 TradingView 腳本很容易（它多半 repaint），
   但贏過它不代表有 edge——**基準本身是負期望值的**。
2. **如果一定要對 harmonic 下判定**，做最小自由度的證偽實驗（E6）：
   固定 pivot 偵測、只測「D 超出 X」vs「D 在 X 內」的二元對照，加 ζ 敏感度掃描
   （0/2/4/6%，預期會複現 Tsinaslanidis 的模式：命中率單調上升、期望值不動）。
   這是一到兩天的工作，產出是一份可信的 NO-GO，而不是一個要維護的策略。
3. **真正該投入的是 E1 + E3**：掃單反轉（用永續清算流 / OI 驟降作為 Osler 停損聚集的代理）
   ＋ 訂單流失衡（HL L2/WS）。這兩者有機制、有大樣本文獻、有 crypto 特有的**公開資料優勢**
   （外匯做不到的事，永續能做），而且正好對應專案 CLAUDE.md 裡 1m scalping NO-GO 註記的
   「重開需新資訊源（L2/WS）」。
4. **E2（短期反轉）在 HL 的可交易宇宙上方向可能是反的**（Zaremba et al.：最大最流動的幣
   呈現日內動能而非反轉）。若要用，必須在 HL 自己的幣種上重測，不可引用文獻的正面結論。
5. **回測紀律**：預註冊 ζ 與 pivot depth 的網格、記錄嘗試次數 N、報告 Deflated Sharpe；
   端點 ±數日敏感度（專案既有慣例）；成本以 HL 實際 taker 費率計，並計入永續資金費率。
