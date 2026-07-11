# Scalping 策略設計（sub-project H）

日期：2026-07-11｜狀態：規劃完成，待執行 phase 0
目標鏈：研究 → 回測 → forward/paper → lightsail 實盤（與 carry/gridbot/momentum/cta 同一部署模式）

## 1. 背景與目標

市場現況為熊市（cycle clock H+26.5 個月，P4 階段，見 `compound/reports/cycle_allocation_verdict.md`），
特徵是暴漲暴跌頻繁、清算瀑布常見。本子專案在 Hyperliquid perp 上開發**分鐘級 scalping**：
捕捉短時間窗內可重複的條件性價格行為（突發動能、過度延伸回歸、時段/事件效應），
每筆持倉數分鐘到一小時，賺取扣除手續費與滑價後的小額但高頻的 edge。

**資金約束**：跨產品配置 verdict 規定投機腿 ≤ 1% 總資金。本策略初期部署規模比照
CTA forward-test（~$500-1,500）。scalping 容量需求低，與此約束相容。

**明確非目標**：
- 不做次秒級 HFT／不做雙邊掛單造市（現有基建全 REST 輪詢、無 websocket，延遲不支援）。
- 不做選擇權、不做跨交易所套利。
- 時間尺度下限 = 1 分鐘 K 線；訊號一律在收盤 bar 上計算。

## 2. 既有證據與硬約束（規劃輸入）

| 事實 | 來源 | 對設計的約束 |
|---|---|---|
| 全 repo 統一回測費率 0.045%/side taker | `scripts/research_pair_trading.py:52` 等 | 成本模型基準；phase 0 拉實際帳戶費率驗證 |
| pair trading 1h cointegration NO-GO：median Sharpe -1.63、60% 出場是硬停損、spread 發散不回歸 | `reports/pair-trading-verdict.md:39-46` | phase 2 不得重用 cointegration 機制；雙腿成本 ~0.18% 是硬門檻 |
| momentum 日線 NO-GO（Sharpe 0.28、MDD -65%） | `reports/momentum-backtest-verdict.md` | 日線級方向性動能不過費用；本專案賭的是「分鐘級條件性行為」是不同母體 |
| CTA 教訓：edge 是 regime 依賴的；多重檢定要有紀律（t-stat/Bonferroni 門檻） | `reports/cta-phase2b-verdict.md`、`reports/cta-overnight-synthesis-2026-07-06.md` | 參數網格預先註冊、只看 walk-forward OOS、regime 標註誠實 |
| 引擎基建：ResilientExchange + io/source.py 邊界、notify/telegram、dotenv 隔離 config、`setup-<engine>.sh`/`hl-<engine>.service` | `src/hlvault/io/source.py:20-32` 等 | phase 3 直接複用；所有外呼走既有邊界 |
| candleSnapshot 單次 ~5000 根；1m K 線 5000 根 ≈ 3.47 天 | 專案 CLAUDE.md | 長歷史要分頁抓；歷史深度 phase 0 實測 |
| Coinalyze free：~335 天歷史、40 req/min、時間戳為秒 | 專案 CLAUDE.md | 清算/OI 資料可用於 F1 觸發標註（僅大幣） |
| gridbot 幣別掃描：17 幣只有 HYPE Sharpe>0.5 | pandora `raw/gridbot2-coin-selection.md` | HYPE 波動×流動性組合值得優先納入候選 |

## 3. 成本模型（預先註冊，回測前鎖定）

- taker fee：0.045%/side（基準）；maker fee 假設 0.015%/side——**兩者都要在 phase 0 用
  `userFees` info endpoint 對實際錢包驗證**，以實測值覆寫。
- 滑價：每幣實測。phase 0 對候選幣取樣 `l2Book`（每 30s、連續 ≥2 小時），
  記 median spread 與 $1k notional 的 impact；回測滑價 = max(spread/2, impact) + 0.5bp 緩衝。
- 回測一律假設 **taker 進、taker 出**（最悲觀）。maker 進場的改善留到 forward 階段驗證，
  回測不得引用 maker 費率美化結果。

| 型態 | 來回成本估計 | 每筆最低毛 edge 門檻（成本×1.5） |
|---|---|---|
| 單幣 taker-taker | 9bps + 2×slip ≈ 11-15bps | ~17-23bps |
| 配對雙腿 taker | 18bps + 4×slip ≈ 22-30bps | ~33-45bps |

任何訊號家族若觸發後的條件期望移動 < 上表門檻，直接淘汰，不進參數優化。

## 4. 訊號家族（假說與證偽條件）

### F1 突發動能延續（burst continuation）
- 假說：熊市清算瀑布自我強化——1m 報酬 z-score 與成交量 z 同時極端時，
  後續 5-30 分鐘沿突發方向有正漂移（清算連鎖、停損踩踏）。
- 觸發：|z_ret| ≥ Z 且 vol_z ≥ V（網格見 plan），順向進場，時間停損＋ATR 停損。
- 證偽：pooled OOS 淨 PF < 1.15 或觸發後條件期望移動 < 成本門檻。

### F2 過度延伸回歸（overshoot fade）
- 假說：W 分鐘內累積移動超過 K 個 σ√W 且出現量能高潮（climax）＋長影線時，
  價格向均值部分回歸（清算掃完、流動性真空回填）。
- 觸發：逆向進場，目標 = 延伸段的 38.2% 回撤，停損 = 極值外 0.5×ATR，時間停損 60 bar。
- 證偽：同 F1。F1/F2 是近似對偶——若兩者同時「都賺」或「都虧」在同一參數區，
  代表在擬合雜訊，一併淘汰。

### F3 時段／事件效應（session & event）
- 假說：crypto 雖 24/7，但流動性與波動集中在特定窗口：US 股市開/收盤、UTC 00:00 日結、
  Hyperliquid 每小時 funding 邊界、週末薄流動性、排程宏觀事件（CPI/FOMC）。
- 方法：先做純統計（UTC hour × 星期的條件報酬/波動/量能熱圖 + funding 邊界 ±5m 漂移），
  只有統計顯示的前 2 個熱點才允許形成交易規則進 OOS 測試——避免規則先行的資料窺探。
- 證偽：熱點在 walk-forward 的後半段消失，或規則化後不過成本。

### F4（phase 2）跨幣短期錯位（lead-lag / beta-hedged dislocation）
- 假說：分鐘尺度上，BTC/ETH 大幅移動後，相關 alt 的跟隨有延遲；或高相關幣對的
  分鐘級價差出現暫時性錯位後快速收斂。**與 1h cointegration NO-GO 的區別**：
  (a) 機制是「事件驅動的暫時錯位」不是「長期均衡回歸」；(b) 持倉分鐘級，
  不承擔 cointegration 漂移風險；(c) 有 time-stop，不等 z 收斂。
- 兩個變體：F4a 單腿 lead-lag（只交易落後腿，成本減半）；F4b beta 對沖雙腿。
  F4a 優先——雙腿成本 22-30bps 是重負擔。
- 前置條件：phase 1 的回測基建通過驗收後才開工；有自己的 gate（G2）。
- 誠實條款：既有 NO-GO 的失敗模式（spread 發散）在分鐘級同樣可能發生，
  回測必須報告 MAE（最大不利偏移）分布與 time-stop 觸發占比。

## 5. 幣別選擇方法論（phase 0 資料決定，不憑感覺）

1. 拉全宇宙 `metaAndAssetCtxs`：dayNtlVlm、funding、openInterest、impactPxs。
2. 初篩：24h 名目成交 ≥ $20M；有 ≥180 天的 1m 歷史。
3. 對初篩通過者取樣 l2Book spread（§3）。
4. 評分 = median(1m 高低幅) / (round-trip 成本)，取前 6-8 名為 shortlist。
- 暫定候選（待資料否決/確認）：BTC、ETH、SOL、HYPE、DOGE、XRP ＋掃描新增。

## 6. 回測誠信規範（每支研究腳本強制遵守）

1. 訊號只用已收盤 bar；成交在下一根 bar 開盤價 ± 滑價。無任何同 bar 前視。
2. 參數網格在 plan 中預先註冊；擴網格要在 verdict 中明寫「事後擴充」並降權其結果。
3. Walk-forward：train 60d → test 30d、步進 30d；config 在 train 選、只報 OOS 串接結果。
4. 敏感度：費率與滑價 ×1.5 重跑，結果一併呈報。
5. 每筆固定 $1,000 名目、單幣單倉、不加碼；統計含：淨 PF、每筆淨 bps、勝率、
   交易數、月度切片勝負、equity MDD、OOS 淨報酬 t-stat。
6. Regime 標註：資料窗涵蓋的市場階段（P3/P4）要寫進 verdict；
   若 edge 只在熊市段成立，結論寫「regime-conditional GO」，不寫無條件 GO。

## 7. GO/NO-GO gates（預先註冊）

- **G0（phase 0 → 1）**：shortlist ≥ 4 幣同時滿足：spread ≤ 5bps、
  P90(連續 5 根 1m bar 高低幅) ≥ 3× 來回成本、1m 歷史 ≥ 180 天。
  不足 4 幣 → 縮到大幣重評；0 幣 → 專案 NO-GO（成本結構不支撐）。
- **G1（phase 1 → 2/3，逐家族判定）**：pooled OOS 淨 PF ≥ 1.3 且交易數 ≥ 300
  且 ≥60% 月度切片為正 且 equity MDD ≤ 15% 且成本×1.5 下 PF ≥ 1.15
  且 OOS t-stat ≥ 2.0。任一家族過 → 進 phase 3（引擎）；全滅 → 允許一輪新假說，
  再滅 → 專案 NO-GO，寫 verdict 收檔。
- **G2（phase 2 pairs）**：F4 在雙倍成本下 OOS 淨 PF ≥ 1.3，且相對已過關的
  單幣家族有增益（Sharpe 更高，或與其報酬相關性 < 0.3 提供分散）。
- **G3（上實盤）**：paper/forward ≥ 2-4 週、實測滑價 ≤ 模型×1.2、無引擎事故；
  **上實盤動真錢屬紅線，執行前必問使用者**（部署規模依 §1 資金約束）。

## 8. 工程原則映射（phase 3 引擎適用）

1. 同源比較：新錢包的 equity basis 先盤點價值桶（perp 自由保證金/部位/掛單），與網頁對帳。
2. 失敗分類：下單走 cloid（client order id）冪等；transient 重試、semantic 上報。
3. 大聲失敗：平倉失敗 → notify 告警 + 下一輪對帳，絕不吞。
4. 測試不碰真實世界：mock 全部外呼；防真 .env。
5. 單一 resilience 邊界：全部外呼走 `io/` 與 ResilientExchange，禁止裸呼。
- Scalping 特有：每日虧損上限熔斷、連虧 N 筆暫停、資料過期（stale bar）守門、
  下單頻率上限（防 API 濫發）。

## 9. 執行分工模式

- 主對話 = 決定者與派工者，不下場寫碼；機械性任務派 haiku subagent
  （設計已在本 spec 與 plan 嚼碎成機械步驟），失敗依 delegation.md §5 升級。
- 每個 task 完成後由 fresh-context agent 驗收（驗證不自驗）。
- Phase 順序：0（資料/宇宙）→ 1（單幣回測）→ gate → 2（跨幣，條件啟動）→ 3（引擎/部署）。
