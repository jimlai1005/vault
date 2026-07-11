# Scalping Phase 0-1 Verdict（sub-project H）：**NO-GO**

日期：2026-07-11｜judgment: 主對話綜合＋opus 第二意見（見 §7）
Spec：`docs/superpowers/specs/2026-07-11-scalp-strategy-design.md`｜Plan：`docs/superpowers/plans/2026-07-11-scalp-phase01-plan.md`

## 0. 一句話結論

在 1 分鐘 K 線資訊層級上，六個最流動的 Hyperliquid 幣、兩年 proxy 歷史、三個訊號家族
＋一輪預先註冊的成本結構假說，**沒有任何一條路的觸發後條件期望移動能覆蓋現實成本**；
依預先註冊的規則（round 2 滅 → 收檔），專案 NO-GO，phase 2（跨幣 pairs）不啟動。

## 1. 判定總表

| Gate / 家族 | 結果 | 關鍵數字（pooled walk-forward OOS） |
|---|---|---|
| G0 宇宙掃描 | **PASS** | 6 幣入選（BTC/ETH/SOL/HYPE/ZEC/LIT），波動/成本比 3.05-6.84 |
| F1 突發動能延續 | **FAIL** | n=10,858、PF 0.56、毛 edge（扣滑價未扣費）**−4.79bps**、MDD 249% |
| F2 過度延伸回歸（taker） | **FAIL** | n=1,894、PF 0.754、−8.12bps/筆、t=−4.16、stop 出場 55.4% |
| F3 時段效應 | **無熱點** | 最強穩定格 ~0.3bps/hr（BTC 21:00 Thu），低於成本門檻兩個數量級 |
| F2b maker 版（round 2） | **FAIL** | NoFilter n=1,910、PF 0.749、−7.99bps、t=−4.25；WithFilter PF 0.758、t=−3.33 |
| **G1 → 專案** | **NO-GO** | 六條門檻（PF≥1.3、n≥300、正月≥60%、MDD≤15%、t≥2.0、成本×1.5 PF≥1.15）除 n 外全滅 |

月度切片（自 trades csv 重建，精度有限但方向穩固）：F1 0/6、F2 2/6、F2b 2/6 正月，全部遠低於 60%。

## 2. 成本結構（實測，G0 產出）

taker 4.5bps/side（帳戶實際費率待 owner 提供地址覆核；全 repo 歷史統一假設）＋每幣實測滑價
（240 輪 l2Book 取樣：BTC 0.58 / ETH 0.78 / SOL 0.56 / HYPE 1.07 / ZEC 2.20 / LIT 4.19 bps）：
單幣 taker 來回 ≈ 10.1-17.4bps。每筆需要的毛 edge 門檻 ~15-26bps（含 1.5× 安全係數）。

## 3. 三種死法的經濟學解讀（`reports/scalp-edge-decomposition.md`）

1. **F1（順勢）：訊號本身無 edge。** 3σ 突發＋量能後的 5-30 分鐘，平均毛移動是 **−4.79bps**
   （逆突發方向）——1m 級突發後是弱回歸而非延續，降成本救不了負毛利，此路死透。
2. **F2（回歸）：方向對，幅度不夠。** 毛 edge **+0.88bps**，不到 taker 成本的 1/10。
   獲利全集中 target 出場組（毛 +65bps），但 55% 的觸發以 stop 收場——延伸傾向繼續發散，
   與 pair-trading 1h NO-GO（spread 發散、60% 硬停損）同構。
3. **F2b（maker 進場，round 2）：省的費被逆選擇一比一吃掉。** 費用從 ~11-15bps 壓到
   3-10bps，PF 卻只從 0.754 → 0.749——限價單恰好在「砸穿掛價」的最爛延續案例成交、
   錯過立即反彈的好案例（stop 率 55.4%→60.8% 佐證）。波動過濾小幅改善（PF 0.758）但
   離 G1 十萬八千里。敏感度（成本×1.5）下全部進一步惡化（0.690/0.695）。

合併結論：**1m K 線所能看見的資訊，在這個市場不含可以覆蓋成本的短線 edge**。
若 scalping edge 存在，它在更細的層（tick/orderbook/清算 feed），需要 WS 實時基建與
歷史 L2 資料——超出本子專案基建與資料可及範圍。

## 4. 資料與方法極限（誠實條款）

- **價格是 Binance perp proxy**（HL 原生 1m 僅保留 ~3.5 天，實測 2026-07-11）。
  HL/Binance 1m 波幅保真比 0.70-0.90 → proxy **高估** HL 可捕捉幅度 10-30%，
  實盤只會比回測更差；此偏差方向強化 NO-GO。
- HL 每小時 funding 邊界效應無法在 proxy 上檢定（原計畫移至 forward-test；專案收檔後不再執行）。
- maker 成交模擬為悲觀近似（fill at limit、同 bar 不給 target）；但 taker 版（無此假設）同樣失敗，結論不依賴此假設。
- 資料窗 2024-07 → 2026-07（覆蓋牛尾＋熊初；LIT 199d、HYPE 407d 較短）。
  無任何 regime 切片出現值得標註的條件性亮點。
- 帳戶實際費率未覆核（用 base tier 4.5bps 假設）；即使 VIP 費率減半，F2 毛 edge +0.88bps
  仍蓋不過剩餘成本，結論不變。
- （第二意見補充）OOS 交易在清算瀑布中高度自相關，t-stat 量級被高估——因本案 t 全為負，
  此偏差不影響結論方向；正月統計分母僅 6 個有交易月，無法區分 regime-conditional 失效
  與全面失效，但兩者都到不了 60% 門檻。

## 5. 多重檢定聲明

F1 18 configs、F2 9 configs、F2b 2 變體 × 9 configs，全部**預先註冊、零事後擴充**；
config 選擇只發生在 walk-forward train 窗，本檔所有數字皆為 OOS 串接。
探索性切片（24 個 coin×side 中 ZEC-long PF 1.39、HYPE-short PF 1.14）**未作為任何決策依據**
——24 個事後切片挑出 2 個 PF>1 與雜訊預期相符。Round 2（F2b）是唯一由 round 1 結果
知情的假說，於執行前預先註冊（commit `cdd0c55`）並依註冊規則收檔。
（第二意見批評，採納：F2b 本質是 F2 同訊號的**執行變體**而非獨立新假說——round 2 的
假說預算花在了非獨立的測試上。此點不改變結論，但列為本研究的方法學弱點之一。）

## 6. 對原始構想的逐點回答

1. 「熊市暴漲暴跌之間有很多機會」→ 機會存在（P90 五分鐘波幅 31-119bps）但 **1m 資訊抓不住**：
   順勢是反向指標、回歸吃不過成本。
2. 「事件交易、開收盤」→ 檢定過 US 開收盤/UTC00/週末/整點邊界：無穩定熱點 ≥ 成本門檻。
3. 「手續費滑價要算清楚，不是每個都能做」→ 完全正確且是決定性因素：成本 10-17bps vs
   毛 edge −4.8 ~ +0.9bps。
4. phase 2「beta/correlation pairs mean reversion」→ 依 gate 不啟動；且單幣回歸已示範
   發散主導的失敗模式，跨幣版每筆成本加倍（~22-30bps），先驗更差。

## 7. 第二意見（opus，獨立判定）

獨立 opus agent 只拿數字表與 gate 定義（未見本檔結論），判定：F1/F2/F3/F2b 逐家族
NO-GO、專案 NO-GO，**與主判定完全收斂**，並標註「證據驅動、非品味判定，信心高」。
其獨立補充採納入本檔：
- F2b 是全案最有診斷力的一筆——它證明問題是「無 edge」而非「成本太高」，把降成本
  這條退路也堵死了。
- ZEC-long 切片為教科書級 data snooping（24 個無校正事後切片之一、n<300、未預先註冊），
  不值得單獨追；本檔僅存此一句備查。
- Round 3 沒有站得住腳的假說；遵守預先註冊的 stop 本身就是正確做法。

## 8. 殘餘資產與後路

- **可重用基建**（已 commit）：`scripts/scalp_lib.py`（HL＋Binance 雙源資料層、分頁、保真對照）、
  `scripts/scalp_backtest_lib.py`（9 條誠信測試：no-lookahead/成本/停損優先/跳空/maker 合約）、
  宇宙掃描器。未來任何分鐘級研究直接取用。
- **知識入檔**：HL candleSnapshot 每 interval 只留 ~5000 根（已寫入專案 CLAUDE.md）；
  HL/Binance 保真比與其樂觀偏差方向；maker 逆選擇實證。
- **若要重開 scalping**：需要新資訊源（實時 L2/trades 錄製、清算 feed）＋ WS 基建，
  不是新參數。在現有資訊集上繼續挖是資料窺探。
- 唯一值得記住的市場結構觀察：HYPE 的波動/成本比（6.18-6.31）全場最佳；
  若未來做**非 scalping** 的波動類策略，HYPE 優先。

## 9. 產物清單

腳本：`scalp_lib.py`、`scalp_fee_check.py`、`scalp_universe_scan.py`、`scalp_pull_history.py`、
`scalp_backtest_lib.py`（＋`tests/test_scalp_backtest.py` 9 tests）、`research_scalp_f1_burst.py`、
`research_scalp_f2_fade.py`、`research_scalp_f2b_maker.py`、`research_scalp_f3_session.py`。
報告：`scalp-universe-scan.md`、`scalp-f1-burst-results.md`、`scalp-f2-fade-results.md`、
`scalp-f2b-maker-results.md`、`scalp-f3-session-stats.md`、`scalp-edge-decomposition.md`、本檔。
關鍵 commits：`9f8f577`（spec/plan）→ `6904435`（proxy 修訂）→ `cdd0c55`（round 2 預先註冊）
→ `dbb8768`（F2b 結果）。所有報告數字經 fresh-context agent 自 trades csv 重算驗證。
