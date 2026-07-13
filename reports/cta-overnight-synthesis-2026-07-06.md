# CTA 過夜研究綜合報告（2026-07-06）

**性質：研究綜合，非 GO/NO-GO 輸入。** 未改任何 live 引擎、未部署、未下單。所有數字來自唯讀回測。
資金判定仍綁定 `reports/cta-phase2b-verdict.md`（真 crowd，NO-GO / owner-override forward-test）。

決策者：主對話（Fable 5）；執行：haiku/sonnet subagents，逐層驗收。四層＋一次 bug 稽核。

---

## Bottom line（先讀這段）

1. **crowd filter＝真 alpha，跨週期穩健，絕不可放寬/移除。** 三源印證（真 crowd 11 個月 + TV 6 年 + funding proxy 5.7 年）。proxy 上短長兩側 **7/7 年**開 crowd 都降 MDD。關掉 crowd：PF 崩、MDD 爆 3-7 倍（proxy 全期甚至 −148%）。信心：高。

2. **槓桿：不要加，可能還要縮。** 抓到一個 8× 的 MDD 計算 bug（`eq.max()` 誤用為 running peak），修正後 11 個月真 crowd 短側 MDD 在 1x 約 **−4%**——但這是**良性窗口的地板，不是天花板**。三角驗證真實全周期 MDD：TV 6 年單幣 ~20%、proxy 5.7 年組合 **−32%**。**現行 1x sizing 在一個 2022 式年份就可能吃 ~30% 回撤、觸發 20% 熔斷。要守住 20%，該往 ~0.6x 縮，不是往上加。** 信心：高。

3. **短邊（生產側）是「regime 依賴的空頭/盤整策略」，不是高 Sharpe 引擎。** proxy 全期 Sharpe 僅 0.35，但它在 2022/2025/2026 勝出、在多頭年虧——它的價值是**負 beta 對沖 / 分散**，不是穩定報酬來源。這解釋了為何 short-only 帳戶會有多年空窗（見 memory）。

4. **加多邊 / 多空都開：proxy 不支持（風險調整後）。** 多空都開全期 Sharpe 0.30 ≈ 只做空 0.35，並未改善；只做多 Sharpe 0.62 看似最好，但那幾乎確定是 2020-2024 大多頭的 beta（long/crowd-OFF 賺 $1008 vs ON $207，錢在「順勢做多」不在 crowd）。**建議維持 short-only，別追多側的週期數字。** 信心：中（判斷題，proxy 受限）。

5. **進出場：沒找到穩健改善。** 短邊的趨勢過濾本身已是 de facto 的 risk-off 過濾（172 筆有 90% 落在 risk-off），無須再加 regime gate；多邊低波動 gate 不穩健（跨門檻擺盪、正值幾乎全來自 XRP 一顆）。**別做逐 regime 微調——在 11 個月上那是過擬合。**

6. **真正的瓶頸是資料，不是參數。** 11 個月真 crowd＝只有一個 regime。所有關鍵問題（多側是不是 alpha、全周期 MDD、regime 配置）都被資料長度卡死。proxy 是目前最好的跨週期替身，但 funding≠真實持倉。**真正的解鎖是更長的真 crowd 歷史**（付費 Coinalyze，或讓 live 引擎自己累積）。

---

## 你原本問的四題，用整晚證據回答

**① 槓桿調整** → 不加、考慮縮。理由見 Bottom line #2。11 個月的低 MDD 是海市蜃樓；真實錨是全周期 ~20-32%。

**② 進出場調整** → 維持現狀。短邊已自對齊 risk-off；多邊 gate 不穩健。任何逐 regime 客製在此資料量下＝過擬合。crowd 保持開啟是唯一「不可退讓」的設定。

**③ MDD 調整** → 20% 熔斷保留，但要認清短邊全周期真實 MDD 已逼近它。實務上該用**降低 sizing**（~0.6x）把平常的 MDD 壓遠離 20%，而不是靠熔斷在最低點救你。附帶：稽核發現 `scripts/research_cta_layer2a_analysis.py:78,232` 的 `eq.max()` bug（今晚 haiku 建的分析腳本，非 live），已用正確算法（phase-2b 的 `eq.cummax()`）取代，該檔留給你決定要修或刪。

**④ Overfitting 確認** → 整晚就是一場反過擬合演練。存活的結論：crowd＝alpha（三源）、短邊＝regime 依賴的對沖。被打掉的：低波動多邊 gate（XRP 帶動）、只做多最佳（bull beta）、11 個月低 MDD（良性窗口）。核心教訓：**這個策略的 edge 是邊際且 regime 依賴的，11 個月資料無法解析關鍵問題——別在薄資料上硬擠設定。**

---

## 逐層數字（可追溯）

- **L1 regime 分解**（真 crowd 11 個月）：短 172 筆/+$183.67，90% 在 risk-off（趨勢過濾＝regime 過濾）；多 149 筆/−$70.21，只在低波動桶正。sum-back 對帳完美。
- **L2a**：多邊低波動 gate 跨 25/33/40 分位在 −$3.47~+$4.75 擺盪、逐幣看正值幾乎全 XRP → 不穩健。（此腳本的槓桿表有 MDD bug，見下。）
- **MDD 稽核**：`eq.max()` vs `eq.cummax()` 造成 8× 高估；phase-2b 引擎算法正確。權威短側 leverage-vs-MDD（11 個月、bar 級 MTM、running peak）：1x −3.98%、2x −7.49%、3x −10.62%、4x −13.43%（$ 金額對名目線性）。
- **L2b**（funding proxy 5.7 年，5 幣，HYPE 排除）：重疊區驗證 PASS（方向對、量級弱）。逐年勝方翻轉：多贏 2020/21/23/24，空贏 2022/25/26。crowd 降 MDD 7/7 年。全期短側 MDD **−32.2%**。已做 point-in-time shuffle 測試確認無未來函數。
- **L3**（proxy 全期三配置）：短 0.35/−32.2%/$120、多 0.62/−11.4%/$207、多空都開 0.30/−22.5%/$327。都開勝空 2/7 年、勝多 0/7 年。

---

## 需要「你醒著拍板」的（我沒動）

1. **是否把 sizing 降到 ~0.6x** 以在全周期尺度守住 20% MDD（碰真錢，我不決定）。
2. **short-only 的定位**：你要的是「空頭對沖 sleeve」（那 short-only 正確）還是「多頭報酬」（那你其實在買 beta，有更便宜的來源）？這決定 add-long 的答案。
3. **是否投資更長的真 crowd 資料**（付費 Coinalyze）來真正解掉「多側是不是 alpha」與全周期 MDD——這是唯一能把上面幾個「中信心」升級成「高信心」的路。

## 邊界與極限（誠實條款）

- 全程唯讀研究，無 live 變更、無部署、無下單、無 secret 外洩。新增未追蹤檔：`scripts/cta_proxy_*`、`scripts/research_cta_layer2a_analysis.py`、`reports/cta_proxy_layer2b_verdict.md`、`data/cache/cta_proxy/`（皆 Binance 公開資料），你可自行 review/commit 或丟棄。
- 跨週期結論**全部基於 proxy**（funding≠持倉、volume≠OI）。Sharpe 全在 0.3-0.6，本就邊際。
- phase-2b 的 t-stat NO-GO 天花板不變——今晚沒有任何結果讓策略跨過統計顯著線。
