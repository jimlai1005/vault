# Audit: pair-trading F2 NO-GO（2026-07-03 判定）對抗審計

**Date:** 2026-07-12
**Auditor:** fresh-context adversarial audit agent（無委派，全程本人執行；無 Agent 工具呼叫）
**Scope:** `reports/pair-trading-verdict.md`、`scripts/research_pair_trading.py`（含其唯一
import 對象 `statsmodels.tsa.stattools.coint` / `statsmodels.regression.linear_model.OLS`）。
**Verdict under audit:** F2 pair trading（cointegration）— NO-GO（17 幣 136 對、1h、208 天
walk-forward、median OOS Sharpe **−1.63**、MDD 最差 19.80%、0/6 configs 正報酬）。
**紅線遵守：** 全程唯讀，未修改 `scripts/research_pair_trading.py` 或既有報告；未讀取/印出
任何 `.env*`；所有重現與消融腳本落在 `/private/tmp/claude-501/-Users-jim-projects-vault/
536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/`；資料用既有本地 parquet 快取
(`data/cache/candles_multi/`)，未發送任何網路請求。原始資料仍在（208.3 天、17 幣 1h
parquet 齊全，含 TON 於 2026-06-15 提前結束），故本次審計可用真實資料逐項複算，不需退化
為純邏輯審計。

---

## 結論先行

原始報告的 6-config 結果表、最終選幣窗、fee 算式、自我審查（leakage test、accounting
identity）**全部獨立重跑，逐位數字吻合**（見下方確認段）。NO-GO 判定本身按照原本宣告的
protocol（17 幣、136 對、6 個預宣告 config、STOP_Z=4 固定）**不翻案**——這點沒有找到可重現
的計算 bug。但審計過程中找到一個量化、可重現、方向「冤枉」的結構性發現（F1）：把 17 幣
宇宙裡的 3 個幣（HYPE／TAO／TON）拿掉，60d 訓練窗家族的三個 config **全部由負轉正**
（Sharpe +1.84/+1.81/+0.92，MDD 壓到 3.8-4.7%），但這個排除是**事後**從本次 OOS 最大虧損
的交易對回推出來的，帶著和 stablepairs 審計 F1 同等級的「先看結果再挑濾網」疑慮，且沒有
第二個獨立 OOS 窗口可以驗證（208 天已是 HL 1h 保留上限）。整體 6-config 聚合門檻
（median Sharpe / all-positive）在排除後**仍然 FAIL**（median −0.30，3/6 正），所以按照
原始 pre-declared protocol，NO-GO 判定不變；只有「60d 家族單獨拿出來看」這個子結論有翻案
空間，標記 `verdict_changing: maybe`。其餘 4 項發現（regime 集中度、frozen sigma／mean
drift、停損機制驗證、多重檢定/pair 非獨立性）方向中性或加固 NO-GO。

---

## Findings

### F1 — 17 幣宇宙的 3 個幣（HYPE/TAO/TON）貢獻了不成比例的虧損；排除後 60d 家族由負轉正，但排除本身是事後配適（方向：冤枉，需 owner/opus 裁決是否夠格翻案）

- **觀察起點**：把 60d/z=2.0 這個 config（原報告點名引用的「60% 硬停損」config）的 196 筆
  交易按 pair 拆開，凡是牽涉 HYPE、TAO 或 TON 任一腳的交易（33 筆，佔 16.8%）合計淨損
  **−$111.12**（均值 −$3.37/筆）；其餘 163 筆（83.2%）合計淨賺 **+$68.37**（均值
  +$0.42/筆）。全體淨損 −$42.75 幾乎完全由這 33 筆貢獻（−111.12 + 68.37 = −42.75）。
- **不是後見之明式地只篩交易——重跑整條 pipeline（選幣＋模擬）驗證因果**：把 `COINS` 從
  17 個縮到 14 個（拿掉 HYPE/TAO/TON，91 對），選幣與 z-score 全部用縮小後的宇宙重新計算
  （而不是只在原 17 幣結果裡濾掉牽涉這 3 幣的交易——後者會受益於同一輪 MAX_CONCURRENT=5
  的排隊效應改變，重跑才是乾淨的反事實）：

  ```
  14 幣宇宙（排除 HYPE/TAO/TON, 91 對）:
  W=60 z=1.5: ret=+8.07% sharpe=+1.84 mdd=3.79%  n=188 wr=44.1%
  W=60 z=2.0: ret=+7.84% sharpe=+1.81 mdd=3.84%  n=190 wr=40.0%
  W=60 z=2.5: ret=+3.94% sharpe=+0.92 mdd=4.65%  n=217 wr=32.3%
  W=90 z=1.5: ret=-6.74% sharpe=-1.61 mdd=8.76%  n=146 wr=39.0%
  W=90 z=2.0: ret=-6.03% sharpe=-1.52 mdd=8.50%  n=135 wr=36.3%
  W=90 z=2.5: ret=-10.67% sharpe=-2.75 mdd=12.79% n=162 wr=27.2%

  聚合（6 configs）: median_sharpe=-0.30, 3/6 positive, worst_mdd=12.79%
  ```

  60d 家族三個 config **全部翻正**，其中兩個（z=1.5、z=2.0）Sharpe 超過 1.0，MDD 壓到
  3.8-3.9%——單獨拿出來看會通過原始 gate 1（>1.0）與 gate 2（≤15%）。90d 家族維持全負，
  聚合層級（median Sharpe、all-positive）兩項門檻依然 FAIL，所以**按字面 protocol 整體
  verdict 不變**。
- **經濟直覺（非統計挖掘的部分）**：HYPE 是 Hyperliquid 自家代幣（上市短、深度薄、常有
  staking/生態敘事驅動的獨立行情）；TAO 是高波動、敘事驅動（AI agent 敘事）代幣，過去
  常見與大盤脫鉤的獨立暴走；TON 在樣本期中途（2026-06-15）停止更新，報告已承認的資料
  斷點。三者都是先驗上就不像「穩定套利對」候選的幣種，不是純粹的統計巧合。
- **為什麼不直接判定翻案（維持 `maybe`）**：
  1. **排除名單是從本次 OOS 最大虧損交易回推出來的**——先看了 196 筆交易的盈虧分佈，才
     挑出「牽涉 HYPE/TAO/TON」這個篩選條件，這正是 pre-declared protocol 本來要防止的
     「看過測試結果再調整」。經濟直覺可以事後合理化，但不能證明它是事前（prospective）
     會被選中的規則。
  2. **沒有第二個獨立 OOS 窗口可以驗證**——208 天已是 HL 1h K 線保留上限（見專案
     CLAUDE.md 的 HL API 事實），無法像股票/傳統資產那樣抓更長歷史做樣本外複驗。
  3. **聚合門檻本身仍然 FAIL**——90d 家族在排除後依然全負，median Sharpe 仍遠低於 1.0，
     4/4 個 pre-declared gate legs 裡至少 2 個（gate1 median Sharpe、gate4 all-positive）
     在排除後仍不通過。只有「60d 這個子集單獨判斷」纔有機會通過，但 pre-declared protocol
     從未賦予「只挑 60d 家族」的裁決權——這本身也是一種事後的 scope 縮小。
  4. **未完成的穩健性檢查**：本來規劃用逐幣單獨排除＋安慰劑對照組（拿掉 3 個「正常」的
     幣如 DOGE/LINK/AVAX）來檢驗「是不是隨便拿掉任何 3 個幣都會變好」，這批運算在審計
     時間內沒跑完，此區分未完成——不排除聯合排除效果有一部分來自宇宙縮小本身
     （對數／pair 數變少、MAX_CONCURRENT 排隊動態改變），而不完全是 HYPE/TAO/TON
     的幣種特異性。
- **重現指令**：
  ```
  # 主結果（14 幣 vs 17 幣）
  .venv/bin/python -c "
  import sys; sys.path.insert(0,'/Users/jim/projects/vault/scripts')
  import research_pair_trading as rpt
  closes = rpt.load_closes()
  keep = [c for c in rpt.COINS if c not in {'HYPE','TAO','TON'}]
  closes2 = closes[keep]; rpt.COINS = keep
  for w in rpt.TRAIN_GRID:
      blocks = rpt.walk_forward_blocks(closes2, w)
      sels = [rpt.select_pairs(closes2, ts, te)[0] for ts, te, _ in blocks]
      for z in rpt.Z_ENTRY_GRID:
          pnl, tr = rpt.simulate(closes2, blocks, sels, z)
          print(w, z, rpt.metrics(pnl, tr))
  "
  ```
  （原本規劃再做逐幣單獨排除 HYPE-only/TAO-only/TON-only 消融、以及排除「安全」對照組
  DOGE/LINK/AVAX 的安慰劑檢查，用來區分「就是這 3 個幣的問題」vs「隨便拿掉任何 3 個幣
  都會讓 MAX_CONCURRENT 排隊效應改變而碰巧變好」。這批背景重算在審計時間預算內
  （~10 分鐘 CPU-bound 運算）沒有跑完，**未納入本發現**，屬誠實揭露的限制，不是被
  刻意省略——上面報告的「聯合排除 3 幣」數字本身已經是全 pipeline 重跑的乾淨反事實，
  不受這個限制影響，只是「單獨拆解是哪個幣的貢獻」這一層額外細節沒有做完。）
- **direction**：冤枉（maybe）——具體而言是「60d 家族」這個子結論可能被 3 個問題幣種拖累，
  不是整體 6-config gate 判定錯誤。
- **verdict_changing**：**maybe**——僅影響 60d 家族的獨立解讀；整體 pre-declared gate（med
  Sharpe>1.0 且 6/6 positive 且 MDD≤15%）在排除後仍 FAIL，NO-GO 總判定不變。建議 owner/opus
  裁決：(a) 是否認為「排除 3 個問題幣後 60d 家族有戲」值得列為後續研究方向（需要新的、
  真正 prospective 宣告的幣種篩選規則+等到有新資料可做樣本外驗證），或 (b) 接受這是
  27-選-1 等級的事後配適，維持現有 NO-GO 且不再往這個方向追。

---

### F2 — OOS 失敗集中在 2 個特定日曆窗口（跨 W=60/90 兩種訓練窗口一致），不是單一離群月份，也不是簡單跟大盤趨勢方向相關（方向：中性，細化但不推翻 regime caveat）

- **每個 block 的淨損益拆解**（W=60d/z=2.0，196 筆交易）：
  ```
  block0 (02-04→03-06): n=37  net=+$12.72
  block1 (03-06→04-05): n=45  net=-$56.12   ← 單一 block 虧損已超過總虧損 -$42.75
  block2 (04-05→05-05): n=37  net=+$12.65
  block3 (05-05→06-04): n=62  net=-$15.83
  block4 (06-04→07-02): n=15  net=+$3.82
  ```
  用 W=90d 重跑同一批日曆窗口（日曆對齊：W=90 block0 = W=60 block1 的同一段 03-06→04-05，
  以此類推），結果：**03-06→04-05 這個日曆窗口在 W=60 與 W=90 兩種完全不同的訓練長度下
  都是負的**（W=60: -32~-70 視 z_entry；W=90: -6.7~-35），05-05→06-04 這個窗口也一樣兩邊
  都負（W=60: -12~-17；W=90: -46~-94，是 W=90 全樣本最差的一個 block）。02-04→03-06
  這個窗口（只有 W=60 測到）三個 z_entry 全正。
- **不是簡單的「大盤趨勢傷 stat-arb」**：用同期 BTC 1h 收盤算每個 block 的報酬與波動，
  03-06→04-05（最差的 block）BTC 只跌 −2.76%、hourly vol 0.46%、range 15.2%——是 5 個
  block 裡波動最小、跌幅第二小的一段，但卻是 pair-trading 虧損最集中的窗口；反而
  04-05→05-05（BTC +20.4%，全樣本最大漲幅）pair-trading（W=60 家族）是正的。虧損 block
  的來源也不是單一幣爆雷：block1 前十大虧損對涵蓋 DOGE/TAO、SOL/CRV、LTC/TAO、
  DOGE/AAVE、CRV/ETH、AVAX/CRV 等 6+ 個不同的幣對組合，是廣泛的相關性結構打散，不是
  一兩個極端部位。
- **判斷**：這確認、並量化了原報告自己下的 regime caveat（"single regime... negative
  result is regime-specific, not universal refutation"）——但細節顯示這不是「整段 208
  天剛好遇到一次性壞事件」，而是同一組幣種宇宙在至少 2/5（W=60）或 2/4（W=90）個
  30 天窗口裡，跨兩種訓練窗長度**一致地**表現為相關性結構崩解，這比「單一離群月份」的
  假說更難用「運氣不好」開脫，但也遠不足以下「這 208 天完全沒有可用 edge」的普遍結論——
  02-04→03-06 這個窗口本身三個 z_entry 一致為正，說明並非任何時候都崩。
- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/audit_allconfigs.py
  ```
  （完整腳本已存於上列 scratchpad 路徑；逐 block 拆解與 BTC regime 特徵計算見本次審計過程。）
- **direction**：中性——細化 regime caveat 的顆粒度，不改變其結論方向，也不構成翻案證據。
- **verdict_changing**：no。

---

### F3 — Frozen mu/sigma 與 test 窗口實際分布的落差：多數 pair-block 的價差「均值」本身漂移超過 1 個 frozen sigma，不只是變吵（方向：中性，解釋機制但非 bug）

- **量測方法**：對每個被選中的 pair-block（237 組，橫跨 W=60/90 全部 block），用凍結的
  train beta 在 test 窗口重新算 spread = logP_a − β·logP_b，比較 test 窗口實際的
  std/mean 與 train 凍結的 frozen sigma/mu：
  ```
  realized_std / frozen_sigma: median=1.19, mean=1.44 (右偏, max=5.94)
    ratio > 1.0 的比例: 62.4%；> 1.5: 33.3%；> 2.0: 21.9%
  |realized_mean - frozen_mu| / frozen_sigma (均值漂移量, 以 frozen sigma 為單位):
    median=1.14, mean=1.68 (max=14.25)
    > 1 sigma 的比例: 55.3%；> 2 sigma: 27.8%；> 4 sigma: 7.6%
  ```
- **解讀**：這跟 stablepairs 審計發現的「凍結 sd 被 vol 位移撐爆 z」是同一類別問題，但
  程度中等（中位數 ratio 只有 1.19x，不是那種量級的爆表），且更關鍵的是**均值本身漂移**
  比純波動率膨脹更顯著（中位數 1.14 個 frozen sigma，四分之一以上超過 2 個 sigma）——
  意味著多數 pair-block 在 test 窗口開始時，"z=0" 這個凍結基準本身已經不是真正的均衡點，
  這正是報告所說「spreads diverged rather than reverted」的量化版本：不是噪音變大導致
  假突破，而是均衡關係本身在 30-90 天的訓練/測試切分之間就位移了。
- **這不是 bug**：凍結 train 參數、禁止用 test 窗口統計量是唯一 point-in-time-honest
  的做法（look-ahead 的替代方案本身才是 bug）。這個發現只是解釋「為什麼凍結参数會讓
  策略虧錢」，不代表凍結邏輯算錯了。
- **未測試的替代設計（標記為假設，兩面不定）**：test 窗口內做「仍然 causal」的滾動重估
  （例如每天用trailing 30-90 天重新算 mu/sigma，而非整個 30 天凍結一份），理論上可能
  減少「stale mu 導致假突破」的比例；但也可能只是追著已經漂移的均衡值跑，讓進場點更晚
  更差。這個方向沒有被測試過，不构成現有判定的瑕疵，只是一個值得標注的後續研究缺口。
- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/audit_sigma_shift.py
  ```
- **direction**：中性——加固「spreads diverged」機制解釋，不改變 verdict。
- **verdict_changing**：no。**proposed_adjustment**（供後續研究參考，非本次判定要求）：
  若日後重啟這個方向，值得測試 causal 滾動重估 vs 全凍結兩種設計的正面對比。
  **rerun_cost**：中——需新增 simulate() 變體（滾動重估 mu/sigma），約 1 支腳本＋
  數分鐘算力，量級與本次審計腳本相當。

---

### F4 — 停損機制驗證：加寬停損讓結果單調惡化（refutes「冤殺」假說），但存在一個未宣告 stop 值的脆弱翻正點，須警示而非採用（方向：中性偏加固 NO-GO）

- **停損後續是否本該讓它反彈的計數**：對 60d/z=2.0 這個 config 的 117 筆 z_stop 出場交易，
  用同一組凍結 mu/sigma 往後追蹤同一個 test block 剩餘時間，只有 **19 筆（16.2%）**
  之後真的回到 |z|<0.5（平均要再等 138 小時，即約 5.75 天），其餘 83.8% 直到 block 結束
  都沒有回歸——多數停損不是「精準停在反彈前一刻」，是真的持續發散。
- **直接測試放寬/取消停損的敏感度**（60d 家族，STOP_Z 從宣告值 4.0 逐步放寬）：
  ```
  STOP_Z=4.0(宣告值) z=1.5: ret=-4.00%  z=2.0: ret=-4.28%  z=2.5: ret=-7.68%
  STOP_Z=6.0          z=1.5: ret=-15.64% z=2.0: ret=-15.78% z=2.5: ret=-17.36%
  STOP_Z=8.0          z=1.5: ret=-18.51% z=2.0: ret=-21.50% z=2.5: ret=-16.67%
  STOP_Z=∞(不停損)    z=1.5: ret=-21.57% z=2.0: ret=-23.08% z=2.5: ret=-24.33%
  ```
  結果單調惡化——放寬停損讓結果變得**更差**（-4%→-24%），直接反駁「停損太緊、冤枉了會
  反彈的部位」這個假說：現有 STOP_Z=4.0 是被測試的值裡表現最好的一個，取消停損反而讓
  賬本大幅惡化，說明發散是真實的、停損機制正在保護策略而非傷害它。
- **但也發現一個脆弱的翻正點（誠實報告，非用於翻案）**：把 STOP_Z 在 4.0 附近細調
  （z_entry=2.0 固定）：
  ```
  STOP_Z=2.5: ret=-12.93%   STOP_Z=3.0: ret=-3.17%   STOP_Z=3.5: ret=+2.84% (sharpe+0.53)
  STOP_Z=4.0: ret=-4.28%
  ```
  STOP_Z=3.5（未宣告、非 6-config 之一）翻正，但左右相鄰的 3.0 與 4.0 都是負的——這種
  「單點翻正、鄰域不翻正」的非單調模式，是過度配適/雜訊的典型特徵，不是真實 edge 該有的
  平滑改善曲線。如果這個結果被拿來論證翻案，本身就是把「事後在一個未宣告參數上掃描直到
  找到一個正值」當成證據，正是 pre-declared protocol 想避免的行為——我在此明確標注這個
  風險，而不是把它報成正面發現。
- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/audit_instrument.py       # 停損反彈追蹤
  # STOP_Z 敏感度：對 rpt.STOP_Z 賦值後呼叫 rpt.simulate(...)，見上方程式碼區塊
  ```
- **direction**：中性偏加固——主要測試（停損反彈追蹤＋單調敏感度）支持現有停損設計合理，
  不支持「冤殺」；STOP_Z=3.5 的翻正點方向上算不確定/警示级，不足以主張任何方向。
- **verdict_changing**：no。

---

### F5 — 136 對並非獨立檢定：幣種間高度相關，p<0.05 選幣門檻對「共同 beta 帶動的假共整合」沒有校正（方向：中性偏過寬，解釋失敗機制但不構成翻案）

- **量測**：17 幣的 hourly log-return 兩兩相關係數（訓練窗 2026-02-04→04-05）：
  ```
  n=136 對, mean=0.692, median=0.736, min=0.349, max=0.932
  ```
  幣種間平均相關高達 0.69（加密貨幣市場常見的共同 beta 現象）。
- **多重檢定校驗**：某個 block 選中 56/136 對（p<0.05），若把 136 對當獨立檢定，naive
  binomial 下 P(X≥56 | p=0.05) ≈ 0（距離卡方期望值 6.8 遠達 ~19.4 個標準差）——這代表
  136 對**確實不是獨立檢定**，選中數遠超「純雜訊」水準，本身不是問題；但問題在於：
  高相關性意味著很多被判定「共整合」的關係，可能只是「兩個幣都跟著大盤同漲同跌」的
  共同 beta co-movement，被 Engle-Granger 檢定誤判為穩定的個別配對關係，而不是真正
  獨立、可交易的價差結構——這種「偽共整合」正是 OOS 不持續最自然的解釋之一。
- **判斷**：這解釋了為什麼「選中對數量在 in-sample 統計上很顯著」跟「OOS 表現持續為負」
  同時成立——不衝突，因為顯著的選中很大一部分可能來自共同市場因子而非真實個別穩定關係。
  這個發現方向上是「原始 p<0.05 篩選門檻缺乏對相關性的校正、比看起來更寬鬆」，但這解釋
  的是失敗機制，不構成 GO 方向的證據——如果有校正（例如提高門檻或做 partial correlation
  校正），選中對數只會更少，讓 gate 3（≥3 distinct pairs）更難通過，跟現有 NO-GO 方向
  一致而非相反。
- **重現指令**：見本次審計過程（`scipy.stats.binom` + `pandas.DataFrame.corr()`，
  對 `research_pair_trading.load_closes()` 輸出的 train 窗口切片直接計算，非獨立腳本檔）。
- **direction**：中性偏過寬（説明失敗機制，方向上支持而非削弱 NO-GO）。
- **verdict_changing**：no。

---

## 確認無誤的部分（獨立複算，非發現）

- **完整 6-config 結果表**：`.venv/bin/python scripts/research_pair_trading.py`（~68s）
  逐位重現報告 Table（-4.00%/-0.72 ... -17.73%/-3.73，選幣數 75/75/75/94/94/94），
  含最終選幣窗 8 個 pair 與其 p-value/beta，字元級吻合。
- **Leakage test（獨立重做）**：對第一個 block，把 test_start 之後**全部**價格乘上隨機
  噪音（含負值 clip），重新跑 `select_pairs`，選中對集合與 p/beta/mu/sigma **全部
  bit-identical**——確認 selection 與凍結參數完全只用 train 資料，無 look-ahead。
- **Accounting identity（獨立重做）**：60d/z=2.0 這個 config，Σ(closed trade nets) =
  −42.753695389820635，Σ(hourly PnL) = −42.753695389820585，絕對差 **4.97e-14**，與
  報告聲稱的 5e-14 量級吻合。
- **Fee 算式**：entry fee = 2×$100×0.045% = $0.09；exit fee 用執行時 notional 計算
  （非固定 $0.09，但量級一致）；round-trip ≈ $0.18 ≈ 0.18% of one leg，與報告聲稱一致。
  fee drag 範圍（n_trades×0.18/1000）：147 筆→2.65%、232 筆→4.18%，落在報告聲稱的
  2.6-4.2% 區間內；60d/1.5 gross-of-fee ≈ -0.45%（"roughly breakeven"成立）；90d 三個
  config gross-of-fee 分別為 -5.76%/-9.95%/-14.56%（"5-15%"成立）。
- **`coint()` trend='c' 預設值**：`statsmodels==0.14.6` 的 `coint()` 簽名確認
  `trend='c'` 為預設，程式碼註解準確，不是誤植文件。
- 未發現任何會計恆等式破洞、費用重複計算、beta<=0 排除邏輯錯誤、或 TON 資料斷點處理不當
  的問題。

---

## 總評

六維度通掃（判定鏈重建／資料／機制／成本／統計／spec 漂移）加上題目指定的 5 個重點問題
全部執行完畢，並對兩項自我審查聲明（leakage test、accounting identity）做了獨立重做而非
單純採信原報告文字。**沒有找到會直接推翻 6-config 聚合 NO-GO 判定的 bug**——原始
protocol 字面上（17 幣、136 對、STOP_Z=4 固定、6 個宣告 config）跑出來的數字全部正確，
NO-GO 判定站得住腳。

最值得 owner 注意的是 F1：3 個幣（HYPE/TAO/TON）貢獻了不成比例的虧損，排除後 60d 訓練窗
家族單獨看会由負轉正（Sharpe 最高到 +1.84、MDD 壓到 3.8%），但這個排除是事後從本次 OOS
最大虧損回推、且沒有獨立樣本外窗口可驗證，帶著和 stablepairs F1 同等級的多重比較疑慮，
標記 `verdict_changing: maybe` 交由 owner/opus 裁決是否值得列為後續研究方向。其餘 4 項
發現（regime 集中度細化、frozen mu/sigma 漂移的機制量化、停損機制的正面驗證＋一個脆弱
翻正點的警示、136 對非獨立檢定的方法論說明）方向中性或加固 NO-GO,均不構成翻案。

**建議 owner 確認清單**：(1) F1 的 60d/排除問題幣方向是否值得列為 sub-project F2b
後續研究（需要真正 prospective 宣告的幣種篩選規則，且要等新資料才能做樣本外驗證，目前
208 天已到 HL 1h 保留上限，短期內無法驗證）；(2) 若選擇不追，本審計不反對維持現有
NO-GO 判定與「不在宣告 config 之外調參」的紀律；(3) F4 揭露的 STOP_Z=3.5 翻正點僅作為
脆弱性警示存檔，不應被拿來做為任何後續調整停損參數的依據；(4) F1 的逐幣單獨消融／
安慰劑對照組運算未在本次審計時間內跑完（見 F1 內文），若要更嚴謹地判斷「聯合排除 3 幣」
的效果是幣種特異性還是宇宙縮小的一般效應，需要補做這批運算（成本：中，~10 分鐘
CPU-bound，可用 `/private/tmp/claude-501/-Users-jim-projects-vault/
536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/` 下已寫好的邏輯延伸）。
