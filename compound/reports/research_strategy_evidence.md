# 外部實證：Crypto Trend-Following 與 Grid Trading 的分 Regime 表現

日期：2026-07-05｜方法：網路文獻調查（學術 > 機構 > 從業者）｜用途：對照內部回測（CTA short-only ＋ gridbot 的四年週期配置決策）

## 結論先行

1. **Crypto trend-following（日線 TSMOM／均線）長期正期望，證據充分**——但收益集中在 long 腿與趨勢明確段；2024–2025 的震盪年對趨勢基金是實錘的懲罰年，且有跨市場的 alpha 衰減證據。
2. **Short 腿（子問題 2，核心）：外部證據傾向「short 是危機保險，不是收益引擎」。** 傳統 CTA 實證顯示 short-only 子策略對整體績效是負貢獻（equity 類資產最差）；crypto 學術研究顯示 momentum 利潤集中在 winner（long）腿，short 腿貢獻較小且成本後常不顯著；crypto 特有的負 funding（熊市時 short 付費）與暴力熊市反彈進一步壓縮實盤期望。**「熊市做空 BTC 是正期望」在 2018、2022 這種整年單邊熊成立，但無條件常開的 short 腿長期不是。** 這支持給 short-only CTA 設窄的、regime-gated 的配置窗，而非常駐配置。
3. **Grid：數學上純網格在無費率隨機漫步下期望為零，含費率為負，單邊趨勢（尤其下跌）中期望為負且損失與跌幅成正比**——這是 2025 年 arXiv 論文的解析結果，與從業者共識（橫盤 10–30% 年化、趨勢段優勢消失）一致。網格的正期望完全來自「震盪 regime ＋ regime 判斷正確」，不是策略本身。
4. **危機 alpha 可部分遷移到 crypto**：TSMOM「微笑」（最壞與最好環境都賺）在傳統資產有 60 年證據；crypto 內部證據（日內 TSMOM 在下跌期表現最好、趨勢策略避開大回撤）方向一致。但危機 alpha 依賴「趨勢有時間建立」——慢熊（2022）捕捉得到，快崩（2020/3、2025/10 清算瀑布）與震盪熊（2025）反而挨打。
5. **四年週期擇時配置：沒有嚴謹的學術框架可對照。** 全部是從業者論述，且 2025–2026 的主流機構觀點（Fidelity、Schwab、Amberdata、Pantera）一致認為週期結構已被 ETF／機構資金與全球流動性改變。n≈3 個完整週期在統計上不可檢定——內部回測的 n=2~3 限制，外部證據不能替你補上，只能告訴你「別人也補不上」。

---

## 子問題 1：Crypto trend-following 的實證與衰減

**有數據支撐：**

- **Rozario et al. (2020), "A Decade of Evidence of Trend Following Investing in Cryptocurrencies"（arXiv:2009.12155）**：十年 crypto 資料上，各種均線規格（約 SMA 10/40 日表現穩定）一致獲利，報告 255% walkforward 年化（早期高波動年代、含槓桿，數字不可外推）；同時指出**近年表現已有輕微下滑**。crypto 市場特性類似 20 世紀商品市場，適合趨勢策略。https://arxiv.org/abs/2009.12155
- **Han, Kang & Ryu (2024), SSRN 4675565**：TSMOM 證據強、cross-sectional momentum 證據弱；**momentum 效應集中在 winners（long 側）**；在「現實假設」（交易成本、日內價格波動導致的清算）下，許多統計顯著的組合實際利潤不顯著。https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565
- **Huang, Sangiorgi & Urquhart (2024), SSRN 4825389**：volume-weighted TSMOM 年化 Sharpe 2.17（學術組合、疑似成本前，取方向不取數字）。https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389
- **Grayscale（機構研究）**：50 日均線 long/flat 策略 2012–2023/07 Sharpe 1.9 vs buy-and-hold 1.3，波動更低（僅取自摘要，原文被擋無法全文驗證）。https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals
- **Dobrynskaya, "Cryptocurrency Momentum and Reversal"**：短週期（≤2 週）momentum 顯著，2–4 週轉不顯著，**更長週期出現強反轉**——日線以上做太慢的 lookback 有結構性風險。https://conference.hse.ru/files/download_file_ex?hash=FAE0AB2DC7A67656E89A0B1CB27D8C7D&id=3B5EE9A5-0B18-458A-9458-B4ED0F6C6664

**衰減（alpha decay）證據：**

- 2025 年是趨勢基金的懲罰年：「Choppy crypto markets punished trend-following funds in 2025, with violent swings erasing months of positioning」（Bloomberg, 2026-02）。2025 全年由宏觀、政策 whipsaw 與 10 月 $20B+ 清算瀑布主導，非趨勢市。https://www.bloomberg.com/news/articles/2026-02-27/crypto-trend-following-trade-finds-relief-after-sharp-selloff ；https://www.coindesk.com/markets/2026/01/23/altcoins-have-been-in-a-bear-market-since-late-2024-pantera-says
- 跨市場的量化 alpha 衰減：中位數量化基金年化 alpha 3.6%→1.0%，因子半衰期 ~60 個月（2005–2010 vintage）→ ~18 個月（2020–2024 vintage）（arXiv:2605.23905，非 crypto 專屬，方向性參考）。https://arxiv.org/pdf/2605.23905

**小結**：長樣本正期望成立；但「日線趨勢在 BTC 上躺賺」的年代證據指向已結束——2023 後的證據是「趨勢明確的年份賺（2023、2024 上半）、震盪年挨打（2025）」，regime 依賴度上升。

## 子問題 2：Short 腿的特殊問題（核心）

**傳統 CTA 的直接證據（非 crypto，但機制可遷移）：**

- **QuantPedia／Quantica 的 CTA ETF momentum 分解**：short-only 子策略對整體 CTA 績效**不提供正貢獻**（累計異常報酬 -0.62%、Sharpe -0.09）。分資產類別：**short equity 最差（年化 -4.94%、波動 16.64%、MDD -72.66%）**；short bonds+FX +0.74%；short commodities +0.53%。short equity 有危機對沖價值，「but it is done at costs that are too high」——移除 equity short 腿後整體 Sharpe 從 0.37 升到 0.78。https://quantpedia.com/exploration-of-cta-momentum-strategies-using-etfs/
- BTC 的報酬結構（高正偏、暴力反彈、50–80% 回撤後 V 轉）比債券商品更像「equity 的極端版」——上述 equity short 腿的結論是對 short-only BTC CTA 最不利的一條外部證據。
- 補充：短週期趨勢在傳統市場 2009 後已失效的微結構研究（arXiv:2607.01550），提醒 lookback 選擇的時代依賴。https://arxiv.org/html/2607.01550

**Crypto 內部的證據：**

- **Momentum 利潤集中在 long 腿**：Han et al.（前引）明確說 momentum 集中在 winners。Dobrynskaya 的 7/7 週策略 19% 週報酬中 12% 來自 long winners、7% 來自 short losers——short 腿成本前為正但較小，**且這是 cross-sectional 做空 altcoin losers，與「時序做空 BTC」是不同的交易，實盤中借券／永續做空 alt 的成本與可行性使其大幅縮水**。
- **Funding 成本的不對稱**：熊市中 funding 轉負＝**short 付費給 long**。2022 FTX 底部 funding 連續負約 50 天；深度負 funding 在歷史上（2020/3、2021 年中、2022/11、2024/8）**每次都對應局部底部與隨後的軋空反彈**——short 訊號最強的時刻，正是持倉成本最高、軋空風險最大的時刻。https://phemex.com/blogs/bitcoin-funding-rates-negative-46-days-ftx-bottom ；https://www.coindesk.com/markets/2026/04/16/bitcoin-funding-rates-hit-most-negative-since-2023-history-suggests-bottom-is-in
- 量級參考（從業者）：$50k 名目、funding +0.015%/8h 時 short 月成本約 $675（~1.35%/月）；負 funding 時同量級反向。成本不致命，但在錯的時點疊加軋空是右尾傷害的來源。https://blog.bitunix.com/en/funding-rates-perpetual-futures/

**對「熊市做空 BTC 是否正期望」的直接回答：**

- **有條件成立**：在成型的長熊（2018、2022——每次持續 12 個月上下、跌幅 75%+）中，日線趨勢 short 有大段可捕捉的單邊趨勢，這是趨勢策略數學上最有利的形態。危機 alpha 文獻（見子問題 4）支持這點。
- **無條件不成立**：長樣本下 short 腿平均貢獻小或為負（上述兩路證據），且 crypto 熊市中 30–40% 的反彈屢見不鮮（2021 年 $20k→$69k 一路軋空的教訓見 https://blog.bitunix.com/en/shorting-crypto-guide/ ，從業者觀點）。CTA 行業的長期收益主流結論是由 long 腿與非 equity 資產貢獻，short equity-like 腿是買保險。
- **證據缺口（誠實標註）**：我沒有找到「BTC 日線趨勢 long/short vs long/flat 的成本後學術分解」這篇決定性的論文——上述判斷是由（a）傳統 CTA 的 short 腿分解、（b）crypto momentum 的 winner 集中性、（c）funding／軋空機制三路間接證據合成的。內部回測若顯示 short-only 在熊 regime 內 Sharpe 顯著為正，與外部證據**不矛盾**——外部證據反對的是「常開」，不是「regime-gated 的窄窗配置」。

## 子問題 3：Grid 的數學與分 regime 實證

**有數據支撐：**

- **Chen, Chen & Jang (2025), "Dynamic Grid Trading Strategy"（arXiv:2506.11921）**——目前最接近「網格分 regime 數學」的文獻：
  - 對稱隨機漫步＋無手續費下，**純網格期望值恰為 0**；加手續費為負。
  - **價格線性移動（單邊趨勢）時期望為負**；下跌中網格持續加倉，**損失與跌幅成正比**——這就是單邊下跌的尾部風險：虧損 ≈ 全程趨勢跌幅 × 累積庫存，不是有界的。
  - 正期望的來源是「套利次數超過門檻」＝震盪足夠多；理論上需要「無限資金＋無限時間」才能在任意路徑下保證正報酬（實務上即：資金上限就是爆倉線）。
  - 他們的修正（DGT：破格後重掛新格＋利潤再投入）在 BTC/ETH 2021/01–2024/07 一分鐘資料上做到 60–70% 年化 IRR、回撤顯著低於 buy-and-hold——但這已經是「網格＋隱含趨勢跟隨」的混合體，不是純網格。https://arxiv.org/abs/2506.11921
- **Volatility harvesting 理論（arXiv:1508.05241）**：再平衡溢酬存在的前提是特定市場動態（震盪/均值回歸）持續——與網格同構。https://arxiv.org/pdf/1508.05241

**從業者觀點（有部分數據）：**

- 橫盤期簡單網格約 10–30% 年化；一旦進入持續趨勢段優勢消失。2022 年 -73.3%、長達 435 天的回撤是網格的滅頂 regime。「grid with regime detection」與「without」的差距是核心，散戶回測普遍只挑橫盤段展示。https://neutralis.finance/insights/market-making-beat-market-research ；https://darkbot.io/blog/trading-bot-backtest-results-a-crypto-traders-guide

**小結**：外部證據與「網格收益＝波動收割 − 趨勢損耗」的內部直覺完全一致，且給出解析形式。**網格的配置問題 100% 是 regime 判斷問題**；在四年週期框架裡，網格的自然位置是「高波動但無單邊趨勢」的段（週期中段震盪、熊市底部築底段），最危險的位置是牛轉熊的單邊下跌段。

## 子問題 4：危機 alpha 的可遷移性

- **Man Group（傳統資產，1960– 長樣本）**：TSMOM 在最壞的 equity 與 bond 環境表現最好（「smile」兩端翹起），1–4 個月 lookback 最有效，多月報酬正偏。危機保護不限於 equity 崩盤。https://www.man.com/insights/trend-following-equity-and-bond-crisis-alpha
- **Crypto 內部方向一致的證據**：Rozario et al. 發現 crypto 趨勢策略對傳統 equity 提供「strong bear market diversification」；Reading 大學的 BTC 日內 TSMOM 研究發現**日內動量在 BTC 下跌期表現最好、能避開大回撤**。https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf
- **遷移的限制條件**：危機 alpha 需要「危機以趨勢形式展開」。慢熊（2022，全年單邊）→ 趨勢 short 捕捉得到；**快崩（2020/3、2025/10 清算瀑布，數日內完成）→ 日線趨勢來不及翻空或翻空在底部**；震盪熊（2025 全年 whipsaw）→ 兩面挨打（Bloomberg 前引）。QuantPedia 對 BTC 的定性——「extreme trend persistence and violent mean reversion」——說明 crypto 的危機同時含有對趨勢最有利與最不利的兩種成分。https://quantpedia.com/silicon-vs-satoshi-tactical-asset-rotation-between-nasdaq-100-and-bitcoin/
- **對 CTA short-only 配置的含義**：危機 alpha 文獻支持在「已確認的下跌趨勢 regime」持有 short 趨勢敞口；不支持把它當作快崩保險（那是 long vol/期權的工作，不是日線趨勢的）。

## 子問題 5：四年週期擇時配置的既有框架

- **結論：沒有可對照的嚴謹研究。** 找到的全部是從業者／機構論述：
  - Fidelity、Schwab：承認歷史上約四年的頂底節奏，但「translating that into an allocation framework has been difficult and highly uncertain」，且明言樣本太少、時距不精確，警告勿當策略使用。https://www.fidelity.com/learning-center/trading-investing/four-year-bitcoin-and-crypto-cycles ；https://www.schwab.com/learn/story/will-bitcoin-halving-cycle-persist
  - Amberdata《2026 Outlook: The End of the Four-Year Cycle》、Pantera、Caleb & Brown（2025–2026）：主流從業者觀點已轉向「週期變形而非消失——halving 仍相關但全球流動性與 ETF/機構資金主導振幅與時點」。https://blog.amberdata.io/2026-outlook-the-end-of-the-four-year-cycle-clone ；https://panteracapital.com/blockchain-letter/navigating-crypto-in-2026/
  - 學術端最接近的是 MSGARCH 分析 halving 前後的波動 regime（MDPI Mathematics, 2023），但那是波動結構描述，不是配置框架。https://www.mdpi.com/2227-7390/11/3/698
- **含義**：內部回測 n=2~3 週期的限制，外部沒有人能補——任何以週期相位觸發的配置規則，其統計信心本質上是「敘事＋2~3 個樣本」，應以 regime 指標（趨勢/波動狀態）為主、週期相位最多當先驗，不當觸發器。

---

## 最強反面證據（對上述結論的挑戰）

1. 對「short 腿負貢獻」：Dobrynskaya 顯示 crypto 短週期 momentum 的 short-loser 腿成本前顯著為正（7%/週策略貢獻）；2018 與 2022 兩次長熊是 short 趨勢教科書級的獲利段。若配置窗只開在「已確認熊 regime」，外部證據不反對。
2. 對「網格趨勢段必虧」：Chen et al. 的 DGT 在含 2022 熊市的區間仍打敗 buy-and-hold——但那靠的是破格重掛（實質上引入趨勢跟隨成分）＋一分鐘級高頻震盪收割，與日線級靜態網格不可比。
3. 對「趨勢長期有效」：2025 是有紀錄以來對 crypto 趨勢基金最差的年份之一，且量化 alpha 半衰期普遍縮短——「長樣本 Sharpe」可能系統性高估未來。

## 證據品質標註

- 學術含成本後分析：Han et al.（SSRN 4675565）、Chen et al.（arXiv 2506.11921）——權重最高。
- 學術但成本前／樣本偏早期：Rozario et al.、Huang et al.、Dobrynskaya。
- 機構研究：Man Group（傳統資產長樣本，可信）、Grayscale（未能全文驗證，取自摘要）、QuantPedia 轉述的 Quantica 研究。
- 從業者觀點（無嚴謹方法）：funding 成本量級、網格橫盤年化 10–30%、四年週期論述——只取方向不取數字。
- 本報告未能取得全文的來源：Grayscale 報告、AUT/SSRN 的 Han et al. 全文（403），相關結論來自搜尋摘要，已降權處理。
