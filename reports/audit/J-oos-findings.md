# Adversarial Audit — Trader-Selection / Copy-Trading OOS NO-GO Verdict

**Auditor:** fresh-context agent, 2026-07-12. **Target:** `reports/oos-verdict.md` (NO-GO, dated
2026-06-27), design spec `docs/superpowers/specs/2026-06-27-trader-selection-pipeline-design.md`,
implementation `src/hlvault/{factors,select,pipeline,backtest,reconstruct,universe,prescreen,report}.py`,
drivers `scripts/run_backtest.py` / `scripts/run_neutral.py` / `scripts/pull_archive.py`.

**Method:** independently re-ran the production pipeline's own functions (no reimplementation) against
the already-cached local data (`data/cache/fills/`, `data/cache/account_values.json`,
`data/cache/prices.parquet`, `data/cache/candidates.json`) to bit-reproduce every row of the published
robustness table, then built three read-only reproduction scripts to test the assigned questions
quantitatively:

- `reports/audit/repro_oos_gate_bug.py` — sample-length gate integrity + sensitivity re-run
- `reports/audit/repro_oos_beta_narrative.py` — in-sample vs ex-post beta of the selected portfolio
- `reports/audit/repro_oos_alpha_power.py` — Monte-Carlo power of the α-tstat≥2 criterion

All three exactly reproduce the published numbers as a baseline before diverging. No existing file
modified; no `.env*` touched; all reads from already-cached local parquet/json.

**Bottom line:** 5 findings. The headline finding (#1) is the important one: **one single trader was
let through the "6-month"/"3-month" track-record gate with only 46–76 real trading days**, due to a
zero-fill artifact in equity reconstruction, and injected wild +45%/−55% swings into the walk-forward
test. Removing that one address flips **every one of the three reported OOS configurations** from
strongly negative (−22% to −25.5%, |t|≈1.0–1.2) to **near-zero and statistically insignificant**
(+1.6% to +3.8% long-only, −0.9% market-neutral, |t|<1 in all three). This does **not** flip NO-GO to
GO — the corrected numbers are nowhere near the report's own `t>2.0` GO bar — but it invalidates the
report's headline framing ("no configuration tested shows positive... return", "structurally NO-GO
across every construction and threshold"). The honest, corrected conclusion is **inconclusive /
underpowered**, not **decisively negative** — which is actually closer to the report's own buried
caveat ("Underpowered, not definitively falsified") than to its bolded verdict language. Recommend
**NO-GO stands** (insufficient evidence to deploy capital either way) but the verdict document's
causal narrative (peer sections 22–31 in `reports/oos-verdict.md`) needs correction before anyone
reads it as "these traders are proven to have no edge."

---

## Findings

- verdict: oos-trader-selection
  type: bug
  direction: 冤殺（報告用「每個設定都穩健 NO-GO」的措辭，實際上這個穩健性幾乎全部來自單一資料完整性錯誤）
  claim: 「sample-length gate」(spec 要求「drop any address with < threshold of **active** history」)沒有量測選手真實交易年資，而是量測「archive 本身存在多久」——因為 `daily_pnl_panel()` 用 `pivot_table(..., fill_value=0.0)`，把選手真正開始交易之前的每一天都填成精確的 0.0 報酬，和「真的在交易但那天剛好打平」無法區分。`returns_panel()` 對每個使用者回傳的 series 因此被 reindex 到整個 archive 區間(336天)，`(r.index.max()-r.index.min()).days` 對每個人都約等於「T 減 archive 起點」，跟這個地址真正開始交易的日期完全無關。
  evidence: >
    `src/hlvault/reconstruct.py:28-30`（`fill_value=0.0` pivot）+ `src/hlvault/pipeline.py:54`（`(r.index.max()-r.index.min()).days < min_days` 用的就是這個被填零的 index）。
    重現：`.venv/bin/python reports/audit/repro_oos_gate_bug.py` §1：
    地址 `0x36076e4bfad9624d7feba562326fdfa2063ede23` 第一筆真實成交在 2026-02-06；在 T=2026-03-24（6mo gate,
    要求真實 tenure ≥180 天）該地址被 `select_at()` 判定通過，但真實 tenure 只有 47 天——回歸用的 241 天樣本裡
    有 194 天（80%）是交易開始前的假 0 報酬 padding。§2：此地址在 T=2026-03-24 權重 0.20（該期自身報酬 +45.4%，
    有它 port=+6.9% vs 拿掉後 port=-1.8%），在 T=2026-04-23 權重 0.50（自身報酬 -54.6%，有它 port=-30.5%
    vs 拿掉後 port=+0.7%）——單一地址的兩次極端擺盪。§3：三個已發布設定的敏感度重跑——
    6mo long-only 公佈 -23.8%/Sharpe-1.42/t=-1.10 → 拿掉此地址後 **+1.6%/Sharpe+0.57/t=+0.44**；
    3mo long-only 公佈 -22.2%/t=-1.00 → 拿掉後 **+3.8%/t=+0.91**；
    6mo market-neutral 公佈 -25.5%/t=-1.18 → 拿掉後 **-0.9%/t=-0.20**（本質上是雜訊）。
    3mo gate 下同一地址在 T=2026-03-24（46天）與 T=2026-04-23（76天）都違反 90 天門檻。
  verdict_changing: maybe（不會把 NO-GO 翻成 GO——修正後 t 值仍遠低於 2.0 的 GO 門檻，證據仍不足以部署資金；
    但會把「決定性、每個設定都穩健為負」的敘述改成「證據不足、接近零，雜訊主導」——這改變的是報告該給讀者的
    信心程度與「等 6-12 個月再跑」這條路是否值得走的判斷，值得算 verdict-relevant。）
  proposed_adjustment: 修正 `returns_panel`/`daily_pnl_panel`，讓每個地址的 pnl 系列只從其「第一筆真實成交日」開始
    （在 pivot 前先各自截斷，或改用 NaN 而非 0.0 標記「該地址尚未存在」再由下游明確處理），使 `min_days` gate
    真正反映交易年資；修正後重跑完整 robustness sweep（六個設定），重新出具 verdict。
  rerun_cost: ~2-3 小時（改 reconstruct.py 的 gate 邏輯 + 加對應 unit test + 重跑六個設定 + 重寫 report）。

- verdict: oos-trader-selection
  type: bug
  direction: 過寬（對受測選手池有利的存活者偏誤，但沒有讓已經是 NO-GO 的結論翻盤，反而讓它更站得住腳）
  claim: spec 的「Point-in-time correctness」明文要求「Universe at T is reconstructed from archived
    leaderboard/activity as-of T, not today's leaderboard (today's leaderboard already embeds
    survivorship — the #1 way this backtest could lie to itself)」，且 `universe.py` 檔案開頭註解也重申
    「the backtest reconstructs the as-of universe to avoid survivorship bias」。但實作沒有照做：
    `scripts/pull_archive.py` 只在整個研究期間結束時(~2026-06-27，跟 archive 終點同一天)對 leaderboard 做
    **一次性** `prescreen()`（要求 all-time ROI > 0），凍結成 `data/cache/candidates.json`（300 個地址），
    這個**固定死的**候選集被套用到整個 walk-forward 的每一個 rebalance date，包括回溯到 2025-08 的早期日期——
    完全沒有「as-of T 重建 universe」這一步。既有的 no-lookahead 測試（`tests/test_backtest_nolookahead.py`）
    只驗證了「`select()` 看不到 panel 裡未來的報酬列」，沒有驗證 universe 成員本身是否用了未來資訊——這個缺口
    沒有測試涵蓋。
  evidence: >
    `docs/superpowers/specs/2026-06-27-trader-selection-pipeline-design.md:89-92`（spec 原文）；
    `src/hlvault/universe.py:1-3`（程式碼自己的註解與實際行為矛盾）；
    `scripts/pull_archive.py:45-54`（`load_candidates()`：candidates.json 存在就直接複用，不存在才從
    `/tmp/hl_lb2.json`（單一次 leaderboard pull）+`prescreen()`凍結一次）；
    `src/hlvault/prescreen.py:43`（`roi <= min_alltime_roi` 過濾，min_alltime_roi 預設 0.0，即要求
    all-time ROI 為正）；`tests/test_backtest_nolookahead.py`（讀取全文確認只測 date-slice，未測 universe
    membership）。
  verdict_changing: no（此偏誤對受測選手有利——只留下「撐到研究結束那天」都還有正報酬的地址——如果修正成真正
    as-of-T 重建，會讓一些「早期表現好、後來爆倉/退出」的地址也被納入某些早期 rebalance，真實結果大機率更負，
    不會把 NO-GO 翻成 GO。）
  proposed_adjustment: 若要重跑，universe 建構要按 spec 改成用「archived leaderboard snapshot as-of T」
    而非單一 frozen 列表；至少幫 no-lookahead test 加一個 case 專門測「universe membership 不能因為 T 之後
    才發生的事而改變」。
  rerun_cost: universe 重建需要對每個歷史 T 都有一份 as-of leaderboard snapshot（若當初沒存下來，需要重新從
    HL API/S3 找歷史 leaderboard 快照，成本可能到天級；若只是加測試守住這個缺口，1 小時內。

- verdict: oos-trader-selection
  type: bug
  direction: 中性（不改變 NO-GO 決策本身，但這條因果敘述本身是錯的，會誤導「等更好的 regime」這條路徑的判斷）
  claim: 報告第 3 點結論「These traders are net-long crypto beta, not market-neutral alpha... They
    tracked the BTC bear market down with no downside protection」不被同一套 pipeline 自己算出來的數字支持。
    用 `pipeline.portfolio_betas()`（跟 `run_neutral.py` 拿去做避險用的同一函式）在每個 rebalance 對「實際被選中」
    的子投組算 in-sample beta，結果 beta_btc 只在 -0.01 ~ +0.08 之間（幾乎為零）；用被選中投組「實現的」OOS
    報酬序列直接對實現的 BTC/ETH 報酬做事後回歸，beta_btc=+0.13（t=+1.04，不顯著），r²=0.0072，
    corr(port,BTC)=0.066——投組報酬跟大盤幾乎沒有統計上的關聯。投組 -23.8% 跟 BTC -28.5% 同期都是負的，
    是「同一段時間市場剛好也在跌」的巧合，不是「這些選手是隱藏的多頭 beta」的因果關係。
  evidence: >
    重現：`.venv/bin/python reports/audit/repro_oos_beta_narrative.py` §1（五次 rebalance 的
    portfolio beta_btc：-0.009, +0.017, +0.012, +0.042, +0.083——全部趨近零）；§2（事後回歸：
    `realized beta_btc=+0.131 (t=+1.04) beta_eth=-0.071 (t=-0.93) r_squared=0.0072`，
    `realized alpha annualized=-40.4% (t=-0.83)`）。對照 `reports/oos-verdict.md:30-31`。
  verdict_changing: no（不管是不是 beta 造成的，實現報酬本身就是負的，NO-GO 不變；但如果真的是 beta 造成，
    「等到不同 regime」會是有效的解方——而數字顯示不是 beta，是接近零相關、統計上不顯著的負向殘差，
    這代表「等一個更好的市場 regime」未必有幫助，真正該做的是等更長真實年資的資料，這點跟 finding #1
    的結論方向一致。）
  proposed_adjustment: 修正報告第 3 點的敘述，改成「實現報酬與大盤 beta 幾乎無關（r²=0.007），負報酬是
    idiosyncratic 的，其中很大一部分可歸因於 finding #1 的 gate bug」，而不是「這些人是多頭 beta 玩家」。
  rerun_cost: 純文字修正，<0.5 小時；若要更嚴謹地把「拿掉 finding #1 那個地址之後」的 ex-post beta 也一併
    重算，再加 0.5 小時。

- verdict: oos-trader-selection
  type: 假設
  direction: 中性偏冤殺（量化了報告自己已經承認的 caveat，沒有推翻它，但顯示這個 caveat 的份量被低估了）
  claim: 用真實 BTC/ETH 報酬區塊 + 已知注入的 daily alpha 做 Monte Carlo，重新算 `factors.alpha_beta()`
    這個 α t-stat≥2 判準在「6-9 個月 gate 實際可得的樣本數（n=180-270 天）」＋「99 個選手池實際觀測到的
    殘差波動率分布（p25=0.6%、中位數=3.7%、p75=5.5% 日報酬標準差）」下的檢定力：對「中位數波動率」的選手，
    就算真實年化 alpha 高達 100%（幾乎不可能發生的水準），檢定力也只有 33-44%；對一個已經非常優秀的 20%
    年化 alpha，檢定力只有 4-6%——跟「完全沒有 alpha」時的偽陽性率(~3%)幾乎沒有差別。只有低波動率(p25)
    的選手，檢定力才算合理（20% alpha 有 45-60% 檢定力，30% alpha 有 77-92%）。
  evidence: >
    重現：`.venv/bin/python reports/audit/repro_oos_alpha_power.py`（節錄，n_days=270）：
    resid_std=median(3.7%) 時，ann_alpha=20% → power=6.0%；ann_alpha=100% → power=44.0%；
    resid_std=p25(0.6%) 時，ann_alpha=20% → power=59.8%；ann_alpha=30% → power=91.5%。
    真實選手池的殘差波動率分布來自對 99 位可重建選手跑 `factors.alpha_beta()` 的 describe()：
    resid_std median=0.0370, p25=0.0059, p75=0.0548（見 repro 過程；未落檔為單獨 parquet，
    可用 `hlvault.reconstruct.returns_panel` + `hlvault.factors.alpha_beta` 對
    `data/cache/fills` 重新算出相同分布）。
  verdict_changing: no（報告本身已經誠實承認「Underpowered, not definitively falsified」，這條 finding
    不是新矛盾，是把這句話量化成具體數字——但量化後顯示，對母體裡波動率中等以上的多數選手，這個判準幾乎
    等於丟硬幣，這代表報告第 2 點「the persistent, copyable universe is tiny...only 1-4 with significant
    alpha」的措辭把「檢定力不足」誤讀成「選手池本身很小」，兩者需要區分。）
  proposed_adjustment: 報告應該把這個 power 數字放進正文而非隱藏在 caveat 裡，並且說明「1-4 人過檢定」
    主要是短年資+高波動率選手的檢定力問題，不是「99 人裡只有 1-4 人有 edge」的母體事實陳述。
  rerun_cost: 已完成（本次審計的 repro 腳本可直接複用）；若要放進正式報告，<1 小時整理成表格。

- verdict: oos-trader-selection
  type: 假設
  direction: 過寬（對回測有利，實盤成本只會更差，但因為已經是深度負值，不影響方向）
  claim: 整條 equity 重建管線只扣了「原始選手自己的手續費」(`closedPnl - fee`)，沒有為「跟單者」自己執行
    鏡像交易所需要的滑價/延遲/自己的手續費建模——spec 的 non-goals 也沒有明確排除或涵蓋這塊。真實跟單機器人
    在 leader 下單之後才能反應，鏡像成交價與 leader 實際成交價會有落差，這是額外、單向的成本，只會讓已經
    是負的 OOS 報酬更負。
  evidence: >
    `src/hlvault/reconstruct.py:27`（`f["pnl"] = f["closedPnl"] - f["fee"]`，fee 是原始選手的手續費，
    不是跟單者的）；`reports/oos-verdict.md:48`（"Realized-PnL returns (what a mirror captures)"——
    報告自己承認這是「假設鏡像能完全複製」，但沒有量化鏡像本身的額外成本）。
  verdict_changing: no（已經是 -22% 到 -25%，額外成本只會讓 NO-GO 更確定，不會翻案；即使把 finding #1
    的 bug 修正後結果轉為 +1.6%~+3.8%，這種等級的跟單滑價/延遲成本，對一個月頻率、只有 1-4 個標的的組合，
    很可能就足以把這個小幅正報酬打平或轉負——值得在報告裡明說「就算統計上不顯著為負，扣掉跟單成本後大概率
    也不會是正的」，而不是留白。）
  proposed_adjustment: 若要往子專案 B（執行引擎）推進，需要單獨對「鏡像跟單」的滑價/延遲做實測或保守假設
    （例如以歷史成交簿深度估算跟隨 1-4 個地址的市場衝擊成本），而不是直接沿用選手自己的 realized PnL。
  rerun_cost: 需要新的滑價估計模型，非既有 pipeline 產物；抓量級估計 2-4 小時，精確模型是另一個子專案量級。

---

## 品味（僅列出，不列為錯誤）

- **Rebalance/hold 週期無執行延遲**：`walk_forward()` 的 `future` 直接從 `(T, T+H]` 開始，選股當下立刻
  100% 進場，沒有模擬「決定跟單到實際掛上倉位」之間的任何延遲。這是研究階段常見的簡化假設，不算錯——
  真正的問題是 finding #5（成本）而不是時滯本身；審計簡報問題 2（選擇→跟單的時滯）在程式碼層面沒有發現
  look-ahead 或延遲設計錯誤，`walk_forward()`/`test_backtest_nolookahead.py` 對「T 之前的資料才能拿來選股、
  T 之後的報酬才算 OOS」這件事驗證是正確的。
- **`min_alpha_tstat=2.0` 與 `dsr_pvalue=0.05` 門檻本身**：屬於方法論選擇，這次沒有發現這兩個數字本身
  有邏輯錯誤，只是它們的「檢定力代價」在 finding #4 被量化出來——門檻要不要因此調整是品味/風險胃納問題，
  不在本次 bug 範圍內。

---

## 檔案

- `reports/audit/J-oos-findings.md`（本檔）
- `reports/audit/repro_oos_gate_bug.py`（sample-length gate bug + 三個設定的敏感度重跑）
- `reports/audit/repro_oos_beta_narrative.py`（in-sample vs ex-post beta 檢查）
- `reports/audit/repro_oos_alpha_power.py`（Monte Carlo 檢定力模擬）
