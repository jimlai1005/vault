# Audit: stablepairs G0 NO-GO（sub-project I，2026-07-11 判定）對抗審計

**Date:** 2026-07-12
**Auditor:** fresh-context adversarial audit agent（無委派，全程本人執行；無 Agent 工具呼叫）
**Scope:** `stablepairs/reports/stablepairs-g0-verdict.md`、`stablepairs/g0_hl_stables.py`、
`stablepairs/g0_cross_pairs.py`、`stablepairs/reports/g0_usdc_perp_recheck.md`、
`stablepairs/CLAUDE.md` §9、`stablepairs/reports/{fee_ground_truth,hl_spot_stable_universe}.md`。
**Verdict under audit:** stablepairs G0 — NO-GO（穩定幣對均值回歸，最佳單對 USDe/USDC 2.55×
< 3× 門檻；合成跨對最佳 0.45×；perp 覆核 4 情境全 FAIL）。已有 opus 第二意見與多次驗數。
**紅線遵守：** 全程唯讀，未修改 `stablepairs/` 下任何既有檔案；未讀取/印出任何 `.env*`；重現
腳本與新抓的 HL 1h/1m candle 資料、L2 book 快照均落在 `/private/tmp/claude-501/.../scratchpad/
stablepairs_audit/`；資料來源全部是 Hyperliquid 公開 `/info` REST endpoint（唯讀，無需認證）。

---

## 結論先行

原始判定文字與代碼邏輯基本一致，208 天窗（`fetch_1h_history`）與 3× 門檻算術可獨立重現
（見下方 F1 之外的所有數字複算）。**找到一個可重現、可量化、方向為「冤殺」的實作 bug**
（F1）：`g0_hl_stables.py::compute_z_scores` 的 rolling window 在 trim 之後才計算，導致
每個對子分析窗口最前面 720 根（~30 天）的 z-score 是用嚴重欠填的 rolling std 算出來的，
產生虛假的低振幅事件，稀釋了小樣本 cell 的中位數。修正後，**USDe/USDC 的 z_peg 定義、
entry_z=2.0 這一格從 FAIL（1.59×）翻成 PASS（3.11×）**——但樣本極小（n=4-5 個「真」事件 /
208 天）且是 27 個測試組合中唯一翻案的一格，帶著明顯的多重比較疑慮，我把它標記為
`verdict_changing: maybe` 而非 `yes`，理由詳見 F1。除此之外，六維度通掃找到 5 個
【假設】/【資料完整度】級的觀察，全部方向中性或反而加固 NO-GO；沒有找到會讓 headline
「USDe 2.55×」cell 本身翻案的問題。3× 安全係數本身是品味項，不重複爭論。

---

## Findings

### F1 — `compute_z_scores` 的 rolling window 在 trim 之後才計算，前 720 根欠填視窗製造虛假事件（可重現 bug；USDe z_peg@2.0 一格翻案，但 n 太小、屬多重比較邊緣案例）

- **位置**：`stablepairs/g0_hl_stables.py:126-134`
  ```python
  df = df[df.index >= LOOKBACK_BARS]  # Need lookback window
  df = df.reset_index(drop=True)
  rolling_mean = df["c"].rolling(LOOKBACK_BARS, min_periods=1).mean()
  rolling_std = df["c"].rolling(LOOKBACK_BARS, min_periods=1).std()
  ```
  意圖（docstring："z_roll: allow slow drift via 720h rolling mean"，LOOKBACK_BARS=720=30 天）
  是每個 bar 都用「前 30 天」算 z-score。但程式先把前 720 根 **切掉**、`reset_index`，
  才對切剩的序列做 `rolling(720, min_periods=1)`——切剩序列自己的第 0 列此時只有 1 個樣本
  可用（不是原始序列的前 720 根），要再等切剩序列自己的第 720 列（＝原始序列第 1440 根）
  滾動視窗才真正填滿。即每個對子分析樣本裡，**前 720 列（16.8%）的 z-score 是用嚴重欠填、
  雜訊極大的 std 算出來的**，不是文件宣稱的 30 天視窗。
- **機制證明**（同一份真實 HL 資料，USDe/@150）：
  ```
  行 51（原始序列，事件之一）: std_shipped=0.000090 vs std_fixed(完整720窗)=0.000600
  → shipped 的 std 只有正確值的 15%，z 被放大約 6.7 倍，讓一個真實只有 z≈0.3 的價格波動
    被誤判成 z≥2.0 事件觸發。行 720 之後兩者完全收斂（ratio=1.000）。
  ```
- **對 G0 結論的量化影響**（同一份 fresh 抓取的 208 天 1h 資料，`entry_z=2.0`，USDe z_peg
  定義——這是原始報告也計算但沒有選為 headline 的 cell）：
  - **SHIPPED（現有程式邏輯）**：9 個事件（其中 5 個落在前 720 根欠填視窗內，entry 時間全部
    集中在 2026-01-16~01-20 五天內，振幅只有 2.0-4.6bps）→ median=4.60bps，ratio=**1.59×**（FAIL）。
  - **FIXED（roll 720 天再 trim，`min_periods=LOOKBACK_BARS`）**：只剩 5 個事件，全部來自
    完整 720 小時視窗（entry 分散在 2026-01-23、03-19、04-07、04-20、05-21），振幅
    8.11/8.81/9.01/9.91/12.62 bps → median=9.01bps，ratio=**3.11×（PASS，越過 3× 門檻）**。
  - USDT0/USDH 同一比較下都仍遠低於門檻（USDT0 z_peg@2.0：1.32×→1.51×；USDH 全部 <1×），
    合成跨對（`g0_cross_pairs.py` 有相同 min_periods=1 寫法但沒有 trim，欠填問題更早開始，
    但因為門檻缺口本來就有 6× 以上差距，修正前後都遠低於 3×，最高只到 1.48×）不受影響。
- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/stablepairs_audit/repro_window_bug.py
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/stablepairs_audit/prove_mechanism.py
  ```
  （原始 1h 資料快取在同目錄 `dfs_1h.pkl`，由 `fetch_1h.py` 對 HL `/info` candleSnapshot
  重新抓取，208.3-208.5 天、5001-5004 根，與原報告的 208.3-208.5 天/5001-5004 根一致，
  確認資料面可重現。）
- **為什麼標 `maybe` 不標 `yes`**：(a) 修正後的「真」事件只有 **n=4-5**，208 天裡不到一個月
  一次，bootstrap 95% CI 落在 [8.11, 12.62]（見 repro 腳本輸出），雖然 94.5% 的重抽樣中位數
  仍 ≥ 門檻，但 n 本身太薄，不足以撐起一個部署決策；(b) 這是 **27 個測試組合**
  （3 對 × 2 個 z 定義 × 3 個 entry_z，加 3 個合成跨對 × 3 個 entry_z）裡唯一翻案的一格，
  且是先前完全沒被 headline 選中的 z_peg 定義——修正一個 bug 後在 27 選 1 裡挑出剛好過門檻
  的那格，本身就是原判定文件自己已經提醒過的「entry_z 選最佳值＝一種 selection」同一類疑慮，
  只是這次連累到「該用哪個 z 定義」也變成事後選擇維度。sub-project J 計畫的翻案判準 3(a)
  字面上「【bug】且修正後數字過原 gate」已符合，但我判斷這個多重比較疑慮和小樣本問題
  重到需要 owner/opus 裁決是否要求案例 (b) 等級的樣本外確認，而非直接判定翻案。
- **direction**：冤殺（bug 使 USDe/z_peg/entry_z=2.0 這一格被誤判為 FAIL）。
- **verdict_changing**：**maybe**——單一 cell 翻案，n 太小＋27 選 1 的多重比較，需 owner/opus
  裁決是否比照案例(b)要求新窗樣本外確認；聚合判定（3 個單對 + 3 個合成跨對的 27 格中，
  其餘 26 格）不受影響，NO-GO 的整體證據權重仍然壓倒性。

---

### F2 — headline cell（z_roll, USDe, entry_z=2.0, n=16）本身的中位數也有不可忽略的小樣本抽樣不確定性（統計維度，原報告未做此檢查）

- **位置**：`stablepairs/reports/stablepairs-g0-verdict.md:28`（USDe/USDC 2.55× 這格，
  對應 `g0_hl_stables.md` 的 z_roll entry_z=2.0，n=16）。
- **問題**：原報告只給點估計中位數（7.4bps），沒有對這個只有 16 個事件的樣本做任何信賴區間
  估計。用同一份資料對這格做 5000 次 bootstrap：
  ```
  USDe entry_z=2.0 (z_roll) n=16: median=6.85bps 95%CI=[5.60,9.92] 3xRT_threshold=8.70
  P(bootstrap median >= threshold) = 7.9%
  ```
  （中位數 6.85 而非報告的 7.4 是因為我的資料多抓了 2026-07-11→07-12 一天，事件池略有
  差異，屬預期的資料新鮮度差異，不是本項發現的重點。）
- **判斷**：92.1% 的重抽樣仍然支持 FAIL，這不是推翻 FAIL 的證據，但確實有約 8% 的機率單純
  因為 n=16 的抽樣雜訊而讓真實母體中位數落在門檻之上。原報告的「這是門檻方向的 selection，
  只會讓 FAIL 更可信」論證處理的是「entry_z 挑最佳值」這個選擇偏誤，跟「同一個已選定 cell
  內部的樣本量夠不夠」是兩個不同問題，後者沒有被討論過。
- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/stablepairs_audit/bootstrap.py
  ```
  （同腳本對 USDT0/USDH 全部 cell 做了同樣的 bootstrap，其餘全部 0% 超過門檻的機率，
  只有 USDe 這格有非零值，反映它本來就是最接近門檻的案例。）
- **direction**：中性偏冤殺（點估計仍是 FAIL，只是原報告沒揭露這個 cell 的統計不確定性有多大）。
- **verdict_changing**：no（92% 的重抽樣質量仍支持 FAIL，且 8% 本身不足以構成翻案證據，
  只是建議這個具體數字被引用時應該帶上「小樣本」但書）。

---

### F3 — RT 成本模型漏算 USDe 的原生質押收益機會成本（假設級，方向：過寬，加固 NO-GO）

- **位置**：`stablepairs/g0_hl_stables.py:34-37`（`TAKER_RT_BPS_ONLY_FEES` 只含手續費+價差，
  沒有機會成本項）；USDe 是 Ethena 的合成美元，市場上可質押成 sUSDe 賺取 funding-driven
  收益（歷史區間約 4-35% APY，2026-04 附近 7 日移動平均約 9.4%——來源：Ethena 官方
  transparency dashboard 相關報導，見下方 Sources）。
- **問題**：策略在等待均值回歸期間持有現貨 USDe（不是 sUSDe），等於放棄了這段時間的質押
  收益（若替代用途是把資金放在其他穩定幣借貸市場賺取 ~4% 的話，機會成本是兩者的差值
  ~5%；若完全沒有替代收益，機會成本是 sUSDe 全額 ~9%）。用報告本身的 median hold 時數
  換算：
  ```
  hold=14h  （z_peg entry=1.0）：9% APY → 1.44bps；5% 差值 → 0.80bps
  hold=81h  （z_peg entry=1.5/2.0）：9% APY → 8.32bps；5% 差值 → 4.62bps
  hold=108.5h（z_roll entry=2.0，headline cell）：9% APY → 11.15bps；5% 差值 → 6.19bps
  ```
  這個量級跟 RT 本身（2.9bps）同數量級，headline cell 的持有時間下甚至超過 RT 本身。
- **判斷**：這是一個真實存在、方向明確、但原報告完全沒提及的額外成本項——它只會讓策略的
  淨經濟性更差，不會讓 FAIL 翻案（本來就已經 FAIL，多算一項成本只會讓缺口更大）。這與
  F1/F2 的「冤殺」方向相反，屬於原判定「過寬」（低估真實成本）的一面，兩者互相牽制，不用
  互相抵銷，都應該原樣呈現。
- **Sources**：[Ethena USDe and sUSDe 2026: Delta-Neutral Yield](https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield)、
  [Ethena Fees, APY & Interest Rates Explained (2026)](https://earnpark.com/en/posts/ethena-fees-apy-interest-rates-explained-2026/)
  （7 日/30 日移動平均 APY，非本次唯讀 API 直接查證，屬公開網頁二手引用，數字本身有
  時效性，僅供量級參考）。
- **direction**：過寬（漏算的是成本，不是收益；使 NO-GO 更站得住腳）。
- **verdict_changing**：no（只會強化 FAIL，不會推翻）。

---

### F4 — 預先註冊 gate 的「24h 量 ≥ config 下限」條款從未被具體實作或一致套用（spec 與實作漂移，中性）

- **位置**：`stablepairs/CLAUDE.md:110`（"標的 24h 量 ≥ config 下限"）vs
  `stablepairs/g0_hl_stables.py`（全檔搜尋 `volume`/`Vlm`/`min_quote` 無結果——**沒有任何
  程式碼檢查或套用量能下限**）vs `stablepairs/config.py:24`
  （`min_quote_volume_usd: float = 2_000_000.0`，唯一存在的具體下限數字，但這個 config 是
  給 `discovery.py`/`data.py` 的 ccxt-based 舊管線用的，不是給 HL 專用的 G0 腳本用）。
- **問題**：`stablepairs-g0-verdict.md:29` 只對 USDH（$146k 日量）標註「量能亦不足」，
  但 headline 案例 USDe 的日量 **$572k 同樣遠低於 repo 裡唯一存在的 $2M 下限**（僅 28.6%），
  卻從未被標註為量能不足——兩者的判斷標準不一致，而且這個唯一存在的數字本身很可能不是
  設計給這條 HL 分支用的（原本是為 ccxt 交易所折現流動性門檻設計）。換句話說，gate 文字
  裡寫的「量能下限」條款在 HL 分支從未被具體定義過，USDH 被標記純粹是敘事判斷，不是規則
  執行。
- **判斷**：不影響最終結論（USDe 就算量能過關依然在振幅上 FAIL），但如果日後有人真的要
  幫 HL 分支定義一個量能下限（例如假設策略要求 ≥$500k 或 ≥$1M 日量以確保執行深度），
  USDe 是否連「有沒有資格進入 G0 振幅比較」都需要重新界定——目前的「2.55×，最接近」敘事
  本身是否該先過一道從未被寫死的流動性關卡，是懸而未決的。
- **direction**：中性（不改變本案結論，但暴露 gate 條款沒有被完整實作，屬於文件/程式碼
  一致性缺口）。
- **verdict_changing**：no。

---

### F5 — 同一天內，另一份報告聲稱 HL 現貨穩定對 L2Book 回傳 null，但 G0 腳本同一天用同一支 API 成功取得真實價差（資料完整度，中性，已現場複驗）

- **位置**：`stablepairs/reports/hl_spot_stable_universe.md:13,30`（"Hyperliquid spot market
  does not expose individual bid/ask orders via L2Book API (requests return null)"，
  2026-07-11）vs `stablepairs/g0_hl_stables.py:93-113`（`sample_l2_spreads()` 呼叫
  `l2_spread_bps()`，同一天跑出 USDT0=2.5bps／USDe=0.1bps／USDH=0.5bps，這三個數字直接
  進了 `stablepairs-g0-verdict.md` 的 RT 成本計算）。
- **現場複驗**（2026-07-12，唯讀公開 API）：
  ```
  @166 l2Book: 20/20 levels，spread=2.80bps
  @150 l2Book: 20/16 levels，spread=2.00bps
  @230 l2Book: 20/19 levels，spread=1.50bps
  ```
  L2Book 現在（也大概率當時）對這三個 coin index 運作正常，回傳真實掛單簿。
  `hl_spot_stable_universe.md` 的「null」結論很可能是用錯了 coin 識別碼格式（例如傳
  `"USDT0/USDC"` 字串而非 `"@166"` 索引）導致的呼叫錯誤，而非平台真的沒有掛單簿。
- **判斷**：不影響 G0 verdict 本身（g0_hl_stables.py 用的是正確、成功的呼叫路徑），純粹是
  同一 sub-project 內兩份報告互相矛盾、其中一份包含一個未被更正的錯誤結論，日後若有人
  讀到 `hl_spot_stable_universe.md` 可能被誤導以為 HL 現貨完全沒有掛單簿數據。
- **direction**：中性。**verdict_changing**：no。

---

## 已檢查、未發現問題（或檢查後反而加固 NO-GO）的項目

### C1 — 振幅量測用「單次收斂淨位移」是否系統性低估策略可捕捉的「總行程」（DCA/加碼假說）——**檢查後不成立**

用同一份 720h z_roll 事件重新計算「entry→exit 之間逐 bar 絕對變動總和」（total path length）
對比「entry→exit 淨位移」（net amplitude，即現有量測方式）：

```
USDe entry_z=1.0: median_net=4.10bps  median_path=44.67bps  ratio(path/net)=12.18×
USDe entry_z=1.5: median_net=5.91bps  median_path=96.35bps  ratio(path/net)=10.03×
USDe entry_z=2.0: median_net=6.85bps  median_path=100.99bps ratio(path/net)=10.85×
USDT0/USDH 的 ratio 落在 1.0×-5.4× 之間
```

單看這個比值，「總行程」的確比淨位移大 3-12 倍，乍看支持「加碼/分批進出能多榨出邊際」的
直覺。但用縮短 rolling window（更頻繁進出、理論上更貼近捕捉這些內部來回）直接測試這個
假說是否可執行：

```
USDe z_roll entry_z=1.0:
  lookback=168h: n=108 median=3.10bps ratio_to_RT=1.07×
  lookback=360h: n=51  median=3.10bps ratio_to_RT=1.07×
  lookback=720h: n=36  median=4.10bps ratio_to_RT=1.42×（現有 gate 用的窗）
  lookback=1440h: n=38 median=3.81bps ratio_to_RT=1.31×
```

視窗切得越短、事件越密集，單筆淨位移對成本的比值反而**變差**，不是變好——因為每一次額外
的來回都要重新付一次固定的 RT 成本，總行程裡「藏著」的波動大多是無法在不增加交易次數
（因而不增加費用侵蝕）的前提下擷取的。**這個假說已用資料檢查並被推翻**：更密集的擷取
嘗試讓比值更差，不是更好；也連帶說明 720h 這個 gate 使用的窗口在測試過的 4 個窗口
（168/360/720/1440h）裡其實是次佳到最佳之間，不是被挑成一個特別不利的選擇（見 C2）。

- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/stablepairs_audit/analyze.py
  ```

### C2 — 720h（30 天）rolling window 選擇是否恰好選到對 FAIL 有利的窗口——**檢查後不成立，反而是接近最佳的選擇**

同一支腳本測試 168h/360h/720h/1440h 四個窗口對 USDe 的影響（見 C1 輸出）：720h 與 1440h
給出的 ratio（1.42-2.36×、1.31-2.40×）明顯優於 168h/360h（1.07-1.35×、1.07-1.71×）。
**如果窗口選擇有偏誤，偏誤方向是「現有窗口對 FAIL 判定反而比較保守（比較容易 PASS）」，
不是相反**——這跟原報告需要擔心的「選到不利窗口冤枉策略」方向正好相反,是加固而非削弱
NO-GO 的證據。

### C3 — 1h 收盤取樣的 intrabar aliasing——量化原報告已定性承認但未量化的但書，數值不足以翻案

用即時抓取的 HL 1m 資料（@166、@150，各約 83 小時、4976-4997 根 1m bar，`pull_1m_history`）
量化 1h 收盤取樣漏掉多少真實波動：

```
USDT0: 1m 總變動量/1h 總變動量 = 7.37×；每小時真實高低範圍 / 該小時收盤淨位移 中位數 = 2.25×
USDe:  1m 總變動量/1h 總變動量 = 4.66×；每小時真實高低範圍 / 該小時收盤淨位移 中位數 = 1.00×
```

單小時尺度的「真實高低範圍 vs 收盤淨位移」比值落在 1.0-2.25×，量級上跟原報告第 5 節
「1h 收盤系統性低估 intrabar 振幅」的定性判斷一致，但幅度不足以把 USDe headline cell
從 2.55× 拉到 3×（即使樂觀地全部乘以 2.25×上限，也還要考慮原報告已指出的逆選擇問題——
intrabar 極值同時要能在進場和出場都精準成交，不可能對每筆交易都成立）。3.5 天的樣本量
也遠小於 208 天的全窗口，此數字只作為量級參考，不是全窗口重新量測。

- **重現指令**：
  ```
  .venv/bin/python /private/tmp/claude-501/-Users-jim-projects-vault/536e13db-d32d-4c1f-8070-3a7e2ee09b40/scratchpad/stablepairs_audit/analyze_1m.py
  ```

### C4 — 現貨 L2 價差的代表性——單次 15 秒/5 樣本點估計是否穩健

在複驗 F5 時發現：2026-07-11 報告用的價差（USDT0 2.5bps／USDe 0.1bps／USDH 0.5bps，
5 個樣本、3 秒間隔取中位數）與 2026-07-12 現場重新取樣（USDT0 2.8→4.1bps／USDe 2.0bps／
USDH 1.5bps，10 個樣本、2 秒間隔）差異達 4-20 倍；同一次 10-sample/20-秒 window 內完全
沒有變化（HL 現貨對的頂層掛單是緩慢移動的階梯函數，不是逐秒跳動的連續價格），代表這類
點估計在單一時刻很「穩定」，但跨天/跨時段可以整層跳動一個數量級，用單次 15 秒窗口代表
208 天的平均價差方法論上偏薄弱。**但做零價差下限檢查**（假設價差=0，只算 2.8bps 純手續費
RT）：USDT0 最佳 ratio=5.7/2.8=2.04×、USDe 最佳=7.4/2.8=2.64×、USDH 最佳=2.7/2.8=0.96×——
**三個單對即使在價差=0 的最有利假設下也全部低於 3× 門檻**，代表 FAIL 對價差量測誤差
是穩健的，這項方法論弱點不影響結論方向。

---

## 總評

六維度通掃（判定鏈重建／資料／機制／成本／統計／spec 漂移）+ 五個未被問過的角度全部執行完畢。
1 個可重現【bug】（F1，`compute_z_scores` 視窗欠填）在 27 個測試組合中翻案了 1 格
（USDe/z_peg/entry_z=2.0，1.59×→3.11×），但因樣本量（n=4-5）與多重比較疑慮，標記
`verdict_changing: maybe`，建議交給 owner/opus 裁決是否比照【假設】級案例要求新窗樣本外
確認，而非直接視為翻案。其餘 4 個發現（F2 headline cell 的小樣本不確定性、F3 USDe 質押
機會成本漏算、F4 量能下限條款未實作、F5 兩份報告的 L2Book 矛盾）方向中性或加固 NO-GO。
四個主動檢查的「未被問過的假說」（DCA 總行程、窗口選擇偏誤、1h aliasing 量級、價差點估計
穩健性）全部檢查後不支持翻案，其中 DCA 假說與窗口選擇兩項甚至被資料本身反證。

**建議 owner 確認清單**：(1) F1 是否要求修正 `compute_z_scores` 並對全部 27 格重新計算
（機械修正，成本低）；(2) 修正後若 USDe/z_peg/2.0 仍過門檻，是否比照【假設】級要求新資料
窗口做樣本外確認才算「翻案」，還是接受 27 選 1 的統計解釋、維持 NO-GO；(3) 3× 安全係數
本身（品味項，不在此次審計裁決範圍）。
