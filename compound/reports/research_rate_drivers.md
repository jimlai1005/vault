# 研究：USD 放貸利率為何逐週期衰減，2028 還能期待 20%+ 嗎

日期：2026-07-05。研究方法：網路來源（研究機構、交易所數據、從業者討論）＋我們自己算的 Bitfinex 2 天期日線數據。
每個結論附來源；無來源的推測標「推測」。

---

## 結論先行

1. **衰減主因是結構性的，大部分不可逆。** 三股力量疊加：(a) 可放貸的美元供給爆發——USDT 從 2017 年初約 5,100 萬美元漲到 2026 年約 1,870 億、全體 stablecoin 超過 3,000 億；(b) 套利資本制度化——Ethena（USDe 峰值 140 億美元）、CME ETF basis trade（對沖基金淨空單）把「收利差」變成工業化產品，任何 >10% 的利差幾週內就被資本灌平；(c) 槓桿需求遷移——散戶槓桿早已從 Bitfinex 式 margin 搬到 perp（Bitfinex 活躍 margin funding 2025 年僅 2 億美元量級，perp 市場未平倉量是它的百倍以上）。
2. **「常年 20%+」不會回來，「尖峰 20-40%」仍會出現但以天/週計。** 2024-25 牛市已示範：CME basis 2024/2 曾達 25% 年化、2024/11 超過 20%，perp funding 短暫衝上 100% 年化——但每次幾週內就被套利資本壓回 10% 以下。這是新常態：尖峰照舊，持續期崩塌。
3. **2028 週期的合理預期（推測，基於上述結構）**：牛市月份 Bitfinex USD 放貸均值 8-15% 年化，狂熱期出現數天到數週的 20-40% 尖峰；全年 ≥20% 的天數大概率是「數天到低雙位數」，不是 2017 的 217 天，也難回 2020 的 58 天。把「放貸 20%+」當常設策略腿的期望值應下修為「放貸 10-15%＋機會性抓尖峰」。
4. **高利率若真要回來，領先指標**：(a) perp funding 年化持續 >30% 超過兩週而不回落（代表套利資本容量被打滿）；(b) Ethena 類 carry 產品在負 funding 期大規模贖回後、牛市重啟時尚未回補（2025/10 USDe 供給 -40% 就是這種空窗）；(c) 監管事件切斷美元入金管道（2017 高利率的一半劇本是 Bitfinex 被銀行斷線造成的平台內美元稀缺）；(d) stablecoin 總供給增速轉負。

---

## 子問題 1：高利率的機制——歷史高利率時段各是什麼在驅動

Bitfinex margin funding 利率由平台內借貸供需決定：借 USD 開多的需求 vs 平台上願意放貸的 USD 存量（[Bitfinex Help Center](https://support.bitfinex.com/hc/en-us/articles/214441185-What-is-Margin-Funding)）。三個歷史高利率時段的驅動各不相同：

**2017 全年（USD 年均 30.86%，區間 5.83%–123.66%，12/21 見頂）**
（來源：[Marcopolobot, Cryptocurrency Lending Markets Review 2017](https://medium.com/@Marcopolobot/cryptocurrency-lending-markets-review-2017-outlook-2018-8435bcd94efc)）
兩個驅動疊加：
- **散戶槓桿多頭湧入**：新用戶大量借 USD 做多 BTC 與 altcoin，12 月狂熱期需求空前。
- **平台內美元人為稀缺**：2017/3/31 Wells Fargo 切斷 Bitfinex 的美元匯路，法幣出入金癱瘓（[CoinDesk](https://www.coindesk.com/markets/2017/04/11/bitfinex-sues-wells-fargo-over-bank-transfer-freeze)、[Bitcoin Magazine 時間線](https://bitcoinmagazine.com/business/warning-signs-timeline-tether-and-bitfinex-events)）。新美元進不來，放貸供給無法擴張，利率只能往上撮合。當時全市場的「美元池」極小——USDT 流通量 2017/3 才 5,100 萬美元。
- 換句話說：**2017 的 217 天 ≥20% 有一半是供給側故障造成的，不是純牛市現象**。

**2020/11–2021/01 與 2021 Q1（利率一度 >20% 年化）**
（來源：[earn-usd.com](https://earn-usd.com/bitfinex-lending-rates-history/)、[ALTINVEST](https://medium.com/@altinvestbot/bitfinex-lending-beginners-guide-understanding-crypto-lending-opportunities-through-interest-rate-ac72162a949b)）
驅動是**全市場的槓桿多頭溢價**：perp funding 連續數月維持高檔，Q1 2021 長時間超過 0.1%/8h（>100% 年化）（[Zipmex funding 分析](https://zipmex.com/blog/how-to-analyze-funding-rates-in-crypto/)、[CryptoSlate 2021 vs 2024](https://cryptoslate.com/insights/bitcoin-funding-rates-showcase-market-sentiment-shifts-from-2021-to-2024/)）。同期 GBTC 溢價套利、交易所間價差套利都要借美元，需求外溢到每一個美元借貸市場。當時 stablecoin 池（USDT 約 200 億）仍遠小於需求脈衝，且 Ethena 式的工業化 carry 資本還不存在——套利要人手動做，供給反應慢，利率高原能撐數月。

**共同機制**：高利率 = 槓桿多頭需求脈衝 ×（美元供給小或反應慢）。後面兩節說明這兩個乘數在 2024-25 都垮了。

## 子問題 2：供給面——美元變得又多又快（量化證據）

- **Stablecoin 供給**：USDT 2017/3 約 0.51 億 → 2017/5 約 1.08 億 → 2021 年底約 780 億 → 2026 年約 1,867 億；全體 stablecoin 市值 2025/4 約 2,292 億 → 2026 年中約 3,075 億（[Bitcoin Magazine](https://bitcoinmagazine.com/business/warning-signs-timeline-tether-and-bitfinex-events)、[CoinLaw Tether 統計](https://coinlaw.io/tether-statistics/)、[stablecoinbeat](https://stablecoinbeat.com/charts/market-cap/)）。**放貸供給池比 2017 大了三個數量級以上，比 2021 初大了一個數量級。**
- **供給增加直接壓利率的量化例子**：USDC 供給 +28.4% 的期間其 DeFi 放貸利率降至 3.3%（約 -6%）；USDT 供給只 +4.3% 但利率 -20.2%（借款需求走弱）（[CoinLaw 借貸統計](https://coinlaw.io/crypto-lending-and-borrowing-statistics/)）。
- **機構放貸資金回流**：加密借貸市場規模 Q4 2024 達 365 億美元，較 2023 Q3 低點 +157%（[Galaxy 報告，Cryptopolitan 轉述](https://www.cryptopolitan.com/crypto-lending-market-declines-43/)）。
- **利率環境的反證強化結構論**：2017/2021 的無風險利率接近 0-1%，2024-25 的 T-bill 有 4-5%。名目上高無風險利率「應該」抬高加密放貸利率，實際卻反而更低——說明壓低利率的不是宏觀，是加密內部的供給與套利結構（本段推理為我們的分析；Fed 利率為公開事實）。
- 自動放貸 bot 普及的直接量化證據：未找到獨立數據。間接證據是 earn-usd 等追蹤站顯示 Bitfinex 放貸已高度自動化、利率日內快速回歸（[earn-usd.com](https://earn-usd.com/bitfinex-lending-rates-history/)）。標註：**此點證據薄弱**。

## 子問題 3：需求面遷移——槓桿搬去 perp（量化證據）

- **Bitfinex 邊緣化**：2013-2017 是全球交易量前列，之後份額持續流失，現定位為專業戶／大額 USDT 交易平台（[CoinLaw Bitfinex 統計](https://coinlaw.io/bitfinex-statistics/)、[cryptoexchangesreview](https://cryptoexchangesreview.com/reviews/bitfinex/)）。2025 年全平台活躍 margin funding 總量僅 **2 億美元量級**（同上 CoinLaw）。
- **對照 perp 市場的體量**：光 CME 一家（只是 perp+期貨市場的一角）BTC 期貨未平倉 2024/11 就達 4.5 萬口（每口 5 BTC，約 200 億美元名目）（[CF Benchmarks](https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity)）。幣安/Bybit/Hyperliquid 的 perp 未平倉合計數百億美元。**想加槓桿的散戶如今付的是 funding rate，不是 Bitfinex 放貸人的利息**——Bitfinex 利率失去了 2017 年那個「全市場唯一槓桿計價器」的地位。
- **水準對照（2024-25 牛市）**：perp funding 大多數時間在 0.01%/8h 附近（約 11% 年化）且常態性貼近零、偶爾轉負（[The Block funding 數據](https://www.theblock.co/data/crypto-markets/futures/btc-funding-rates)、[CryptoSlate](https://cryptoslate.com/insights/bitcoin-funding-rates-showcase-market-sentiment-shifts-from-2021-to-2024/)）；尖峰時刻（2024/2-3、2024/11-12）短暫衝到 60-100% 年化（[CoinDesk 2024/2/27](https://coindesk.com/markets/2024/02/27/bitcoin-funding-rates-jump-to-100-sparking-opportunity-for-savvy-traders/amp)）。Bitfinex USD 放貸利率與 perp funding 現在高度連動（同一批套利者在兩邊搬平），我們自己的數據顯示 2024-26 合計只有 2 天 ≥20%——與 perp 的「均值低、尖峰短」形態一致。

## 子問題 4：跨市場套利把利差灌平（利率市場的「工業化」）

這是 2021→2024 之間最大的結構變化，量化證據最硬：

- **Ethena/USDe**：把「做空 perp 收 funding」打包成合成美元，供給 2025 年峰值超過 **140 億美元**（[Forbes](https://www.forbes.com/sites/digital-assets/2026/06/15/ethenas-usde-pays-yield-legally-and-the-genius-act-has-no-answer-for-it/)、[Coin Metrics](https://coinmetrics.substack.com/p/state-of-the-network-issue-335)）。等於一支永遠在線、百億級的 carry 部隊：funding 一高就自動擴倉收割。sUSDe 收益率 2023-25 週期均值約 11%、區間 -6% 到 +75%；2024/8 一次 funding 反轉讓 APY 從 19% 壓到 4% 只花 11 天（[eco.com](https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield)、[CoinLaw stablecoin yields](https://coinlaw.io/stablecoin-yields/)）——利差的半衰期已經以「天」計。
- **CME ETF basis trade**：現貨 ETF 給了機構合規的現貨腿，對沖基金在 CME 淨空 15,399 口 vs 淨多 3,003 口（做多 IBIT＋做空期貨收 basis）（[CME OpenMarkets](https://www.cmegroup.com/openmarkets/equity-index/2025/Spot-ETFs-Give-Rise-to-Crypto-Basis-Trading.html)、[OFR hedge fund monitor](https://www.financialresearch.gov/hedge-fund-monitor/categories/size/chart-94/)）。basis 2024/2 達 25%、2024/11 超過 20%，到 2025/5 已被壓到 10% 以下、2025 年底剩 4-6%（[CF Benchmarks](https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity)）。
- **含義**：Bitfinex 放貸、perp funding、CME basis、DeFi 借貸如今是同一個利率市場的四個窗口，被 Ethena＋對沖基金＋跨所套利 bot（hl-carry 屬於同一物種的小型版）連通。任何單一窗口的利率想長期高於其他窗口＋套利成本，都會被搬平。**2017 式的「Bitfinex 獨立高利率」在市場結構上已不存在。**

## 子問題 6（先於 5）：2024-25 牛市裡放 USD 收息哪裡最高

| 市場 | 2024-25 大致水準（年化） | 來源 |
|---|---|---|
| Ethena sUSDe（perp carry 打包） | 均值約 11%，2024 初曾 19-30%+，尖峰 75%；會轉負 | [eco.com](https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield)、[CoinLaw](https://coinlaw.io/stablecoin-yields/) |
| 自營 funding rate 套利（跨所） | 2024 約 14.4%、2025 約 19.3%（單一來源，數字偏樂觀，謹慎採用） | [Gate Learn](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166) |
| CME basis trade（機構版） | 尖峰 20-25%，常態 5-10%，2025 底 4-6% | [CF Benchmarks](https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity) |
| Bitfinex USD margin funding | 我們的數據：2024-26 僅 2 天 ≥20%；2026 年中 30 日均值約 12-14%（top-50% 放貸人口徑） | 自算＋[earn-usd.com](https://earn-usd.com/bitfinex-lending-rates-history/) |
| DeFi 放貸（Aave USDC） | 約 3-6%，尖峰期 8-12% | [Spark 比較](https://www.spark.money/tools/stablecoin-yield-comparison)、[Aavescan](https://aavescan.com/) |
| CeFi（Ledn、Nexo 等） | 8.5%（Ledn）至宣稱 16%（Nexo 促銷檔位，含平台風險） | [Ledn](https://www.ledn.io/post/best-stablecoin-interest-rates) |
| T-bill（基準） | 4-5% | 公開事實 |

結論：2024-25 週期收息最高的不是被動放貸，是**主動 carry（自營 funding arb / sUSDe）**，約 11-19%；Bitfinex 被動放貸落在 8-14% 區間，只比 T-bill 高一截。各市場利差已收斂到「套利成本＋風險溢價」之內，印證子問題 4。

## 子問題 5：前瞻——什麼情境下 20%+ 會回來？2028 怎麼估

**支持「回不來」的結構論（主論點）**：供給三個數量級的擴張不會逆轉；Ethena/對沖基金的 carry 容量只增不減（Janus Henderson 等傳統資管 2026 年還在接入 USDe，[Forbes](https://www.forbes.com/sites/digital-assets/2026/06/15/ethenas-usde-pays-yield-legally-and-the-genius-act-has-no-answer-for-it/)）；槓桿需求不會搬回交易所 margin。三者都是單向門。

**反面證據（支持 2028 仍可能出現高利率時段）——依驗收條件主動列出**：

1. **尖峰從未消失，只是變短**：2024/2 perp funding 曾衝 100% 年化（[CoinDesk](https://coindesk.com/markets/2024/02/27/bitcoin-funding-rates-jump-to-100-sparking-opportunity-for-savvy-traders/amp)）；CME basis 兩度破 20%。需求脈衝的振幅還在，被壓掉的是持續時間。若 2028 出現 2021 Q1 等級、持續數月的散戶狂熱，套利容量（百億級）仍可能被數千億級的槓桿需求短暫打穿——2021 Q1 就是在 USDT 已有 200 億的情況下把 funding 撐在 100%+ 數月的。
2. **carry 資本是順週期的、會踩踏**：2025/10 去槓桿讓 USDe 供給縮水 40%（[DL News](https://www.dlnews.com/articles/defi/ethena-usde-supply-plummets-as-traders-cool-on-risky-crypto-bets/)）；2024/8 funding 反轉 11 天內 APY 19%→4%。負 funding 期會把套利資本洗出場，若牛市在資本回補前重啟，會有一段利率真空期——這是 2028 抓尖峰最可能的窗口。
3. **監管黑天鵝**：GENIUS Act 禁止付息 stablecoin（[Forbes](https://www.forbes.com/sites/digital-assets/2026/06/15/ethenas-usde-pays-yield-legally-and-the-genius-act-has-no-answer-for-it/)）；若未來監管進一步打擊 Ethena 式合成美元或切斷主要出入金管道（2017 劇本重演），供給側故障可以人為製造稀缺。機率低但非零。
4. （推測）若 Fed 到 2028 已降回低利率，T-bill 資金外溢找收益的力量減弱，加密內部利率的「地板」下移，但「天花板」在狂熱期仍由需求決定——低宏觀利率反而是 2020-21 高 crypto 利率的背景。

**2028 合理預期（推測，綜合以上）**：
- 基線：牛市期 Bitfinex USD 放貸均值 **8-15% 年化**（≈ perp funding 常態＋小溢價）。
- 尖峰：狂熱段落有 **數天到數週的 20-40%**，個別日可能更高；全年 ≥20% 天數估 **5-30 天**（介於 2021 的 23 天與 2024-25 的 2 天之間，偏向前者的條件是散戶狂熱重現）。
- 不應再把「放貸 20%+ 常年可得」寫進配置假設；應寫成「基線 10-15%＋事件驅動尖峰」，且尖峰期與 perp funding 尖峰同步，用 funding 監控即可捕捉。

**領先指標清單（監控用）**：
1. perp funding 年化 >30% 且持續 >2 週不回落（套利容量打滿的信號）。
2. USDe/sUSDe 供給在負 funding 期大幅縮水後，牛市重啟（carry 真空窗口）。
3. stablecoin 總供給增速轉負或主要發行商遭監管行動。
4. Bitfinex 平台自身事件（銀行通道、USDT 脫錨恐慌會推高平台內 USD 需求——2018/10 USDT 危機時 USD 放貸利率也曾尖峰，屬同一機制）。

---

## 資料極限標註

- 我們自己的「≥20% 天數」用 2 天期日線 close 口徑，會低估盤中尖峰與短期限（FRR 浮動）口徑的收益；跨週期趨勢判斷不受影響。
- Gate Learn 的 funding arb 收益數字是單一來源且有行銷動機，僅作量級參考。
- 「放貸 bot 普及壓利率」缺獨立量化證據，列為薄弱環節。
- CoinLaw / eco.com 屬聚合站，關鍵數字（USDe 峰值、basis 峰值）已與 Coin Metrics、CF Benchmarks、CME 等一手來源交叉核對，一致。
