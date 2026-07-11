# Stablepairs（sub-project I）G0 Verdict：**NO-GO**

日期：2026-07-11｜judgment: 主對話＋opus 第二意見（獨立、只給數字，結論收斂）
Spec/gates：`stablepairs/CLAUDE.md` §9（2026-07-11 預先註冊，先於任何實盤數據）

## 0. 一句話結論

穩定幣 peg 均值回歸死在 **G0 成本可行性（blocking gate）**：可捕捉振幅（個位數 bps）
蓋不過任何可及 venue 的來回成本；唯一便宜的 venue（HL 穩定對 1.4bps/side）上，
最佳案例 USDe/USDC 只有 **2.55×**（門檻 3×），合成跨對最佳僅 **0.45×**。
規則內的出路（換 pair、換 venue、量測解析度質疑）已全部窮盡。未進入 G1 回測。

## 1. 費率地面真相（2026-07-11 查證，`reports/fee_ground_truth.md`）

| Venue | 穩定對 taker/side | 對本案判定 |
|---|---|---|
| Binance（一般戶） | 10bps（USDC 對促銷 7.1bps） | 死刑：RT ≥14bps vs 帶寬 <10bps |
| OKX / Bybit | 15bps / 10bps（ccxt 中繼資料） | 死刑同上 |
| **Hyperliquid 現貨穩定對** | **1.4bps（基礎費率 20%，永久）** | 唯一可行成本結構 → 全部火力測它 |

## 2. G0 實測（HL 原生 1h × 208 天，`reports/g0_hl_stables.md`、`g0_cross_pairs.md`）

單對（RT = 2×1.4 + 實測 spread；判準 median 振幅 ≥ 3×RT）：

| 對 | 日量 | spread | RT | 3×RT | 最佳 median 振幅 | 倍數 | 判定 |
|---|---|---|---|---|---|---|---|
| USDT0/USDC | $2.9M | 2.5bps | 5.3 | 15.9 | 5.7bps | 1.08× | FAIL |
| USDe/USDC | $572k | 0.1bps | 2.9 | 8.7 | 7.4bps | **2.55×** | FAIL |
| USDH/USDC | $146k | 0.5bps | 3.3 | 9.9 | 2.7bps | 0.82× | FAIL（量能亦不足） |

合成跨對（雙腿成本）：166-150 最佳 7.4 vs 需 24.6；166-230 5.8 vs 25.8；
150-230 8.3 vs 18.6——全部 FAIL，最佳僅門檻的 45%。

註：「最佳」cells 全部來自 entry_z=2.0（事件數僅 ~16/對）——本身已是往門檻方向的
selection；照預先註冊規則，這只能讓 FAIL 更可信，不能反向放寬。

## 3. Binance 管線診斷（120d 5m，佔位費率——具方法論價值的失敗）

- 全費率死亡算術：596 筆 × 17bps ≈ e^(−1.01)−1 = **−63.7%**，與實測 −63.2% 吻合
  ——毛價格損益 ≈ 0，虧損全部是手續費。churn（entry_z=1 的 5m 進出）× 費率 = 死。
- **OLS β 在兩個 $1 錨定幣之間是退化的**：discovery 選出的「最佳 cointegrated 對」
  FDUSD/USD1 擬合出 β=−0.58（負對沖比，經濟上無意義）。修法（若未來重開）：
  穩定對 β≡1 是結構先驗；HL 的 USDC 計價對更直接——價格本身就是 peg 偏離。
- 83% 出場是 z 停損：train 凍結的 sd 在 OOS 被 vol 位移撐爆 z——凍結參數修了
  「mean 被帶偏」，但 **sd 也會被帶偏**；MS 模型的 per-regime σ 本是對症藥（未及使用）。

## 4. 對原始構想的回答

「換到穩定幣，mean 就不會被帶偏」——**對，而且實測確認 mean 錨住了**。但代價是
一個對稱的束縛：**錨住 mean 的同一個力量也壓扁了振幅**。crypto 對死於發散
（spread 逃逸、mean 不存在），穩定對死於束縛（mean 完美、振幅 < 成本）。
兩次失敗夾出這類策略的生存條件：**mean 要錨定、振幅要夠肥、費率要夠薄**——
可及的 venue/universe 裡沒有同時滿足三者的角落。regime 閘門設計本身沒有被檢驗
（G0 在它之前擋下）；它的邏輯（depeg 段不接刀）依然是對的，只是輪不到上場。

## 5. 誠實條款與殘餘不確定

- 208 天窗**無重大 depeg 事件**：振幅統計是平靜期的地板；但「等大事件」不是策略，
  是 event-risk taking，屬另一類研究。
- 1h 收盤量測系統性低估 intrabar 可捕捉振幅（opus 確認方向）——但誠實修正
  遠小於高低幅（intrabar 極值成交＝樂觀上限＋逆選擇），不足以翻轉 G0。
- **maker 基準下 USDe 約 4×**——但 maker 成交品質無法誠實回測（H 專案 F2b 實證
  逆選擇 1:1 吃掉費用節省；靜止買單在賣壓中成交對 mean-reversion 是結構性逆風）。
  opus 判定：不作為 GO 路徑。owner 若想收微結構數據，可自行裁量一個 time-boxed
  探針（預註冊 kill：實測淨成交振幅 < 3×maker RT 即殺），與本 verdict 解耦。
- **費率是分母**：若未來任一 venue 給出 ≤0.5bps/side（VIP、返佣、新 venue），
  G0 重跑只需一小時（腳本在 `stablepairs/g0_hl_stables.py`）。

## 6. 第二意見（opus，獨立判定）

G0 乾淨 FAIL（並指出最佳 cells 本身是 selection）；maker+paper 不是 GO 路徑
（「無法量測的 gate 不能當 gate」）；1h 低估不翻案；建議收檔前補跨對掃尾——已補，
全 FAIL。與主判定完全收斂。

## 7. 資產與產物

- 可重用：誠實化回測器（`backtest.py` 一步延遲成交版）、MS-AR 校準管線
  （`regime_hmm.py`，合成資料驗證過能正確分離 REVERT/DIVERGE）、G0 振幅/成本
  分析腳本、HL 穩定對 universe 與費率地面真相報告。
- 報告：`fee_ground_truth.md`、`hl_spot_stable_universe.md`、`g0_hl_stables.md`、
  `g0_cross_pairs.md`、本檔。
- Owner 的 Pine 原始碼（`pine_original_stay_cool_c.txt`）與 Desktop 原檔未動。
