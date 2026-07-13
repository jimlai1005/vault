# Sub-project L Stage 2 執行計畫（嚼碎版）

協議（判準唯一來源）：`docs/superpowers/specs/2026-07-14-cta-l-stage2-protocol.md`。
上位 spec：`2026-07-13-cta-staged-sizing-design.md`（§8 修正案 1 的 MDD 公式適用全程）。

**紅線（每個 task 適用）**：不讀不印 `.env*`；不跑任何會下單/轉帳的腳本；不修改
`src/hlvault/`（live 引擎凍結）、`scripts/cta_proxy_lib.py`、
`scripts/research_cta_positioning_phase2b.py`；不修改 Stage 1 產出腳本的既有函式行為
（只准加預設值向後相容的參數）；`data/cache/cta_l2/` 為 Stage 2 唯一輸出目錄。

**派工建議**：T1 需要 web 查證（general-purpose＋網路）；T2-T3 sonnet；T4/T6/T8 的
verifier 必須 fresh-context 且禁讀實作；T9 主對話整合＋opus 二審。每 task 驗收逐條
要證據。**判定順序 A1→A2→A3 嚴格串行**——前一個 ablation 的 verdict 段定稿前，
不得開後一個的正式 run（baseline 定義依賴前果）。

## T1 事件日曆資料（A1 前置，PIT）

- 整理 FOMC 決議聲明＋US CPI 發布時刻（2020-09-14→2026-06-30）成
  `data/events/us_macro_calendar.csv`（協議 §4 欄位），逐筆 ET→UTC 含 DST。
  來源：federalreserve.gov 會議日曆、bls.gov CPI 發布排程（歷年 schedule 頁）。
- 驗收：(1) 筆數合理（FOMC ~8 次/年、CPI ~12 次/年，共約 120±15 筆）；
  (2) 獨立 spot-check agent 抽 ≥3 筆（含 ≥1 筆 DST 切換月）對官方頁面核時刻；
  (3) csv 先 commit，記 hash。

## T2 引擎擴充 `scripts/cta_l_stage2.py`

- 在 Stage 1 引擎上加：entry veto hook（`veto_fn(coin, entry_ts)->bool`）、事件窗
  存續期縮放（協議 §4 的縮放/恢復/成本規則）、乘數組合 `m_total`（協議 §3）。
- ledger schema 照協議 §4 寫死：`notional`=進場鎖定值、`resize_events` JSON 欄、
  `fees` 含全部 resize 成本、`pnl`=逐段 mark-to-market − fees。
- 驗收（協議 §8）：(1) 無 veto、無事件、m_f≡1.0 時與 B1 路徑逐位相等
  （assert_frame_equal exact）；(2) Stage 1 兩支 selftest 全過；(3) 含 resize 路徑
  過新恆等 guard（`Σ日報酬×基底 == Σtrade.pnl`，1e-6）；(4) A1 縮放成本手算
  spot-check（對 `resize_events`＋`fees`）＋2-bar 合成情境 mtm 歸屬數值錨
  （協議 §8.2）；(5) A2 同源 assert（協議 §5 可執行版）；
  (6) 全部寫成可重跑 selftest 腳本。

## T3 A1 正式 runs → `data/cache/cta_l2/`

- Runs（variant = B1＋A1 主配置；baseline = B1，其主窗/cost15/端點 csv 直接沿用
  Stage 1 `data/cache/cta_l/`）：`a1`、`a1_cost15`、`a1_ep30/60/90`＋敏感度
  `a1_sens_noresize`、`a1_sens_w48`（只跑主窗）。manifest 記參數與事件 csv hash。
- 驗收：檔案齊全、行數=窗日數、trades 欄位含 m_total 與縮放記錄、b1 錨定
  spot-check（沿用檔案的 MAR/MDD 對協議 §1 錨）。

## T4 A1 gates＋盲測驗證

- gate 腳本 `scripts/cta_l_stage2_gates.py`：啟動先重現協議 §1 六個數值錨，
  再算 G-A·1…4（N=11）。輸出 `data/cache/cta_l2/a1_gates.md`。
- 盲測 verifier（fresh-context，只拿協議 §2/§7＋csv）獨立重算，逐格 1e-6。
  不一致 → 停下找唯一根因（Stage 1 前例），禁取平均。
- 判定：全過 → baseline 更新為 B1+A1（產 `b2` 全套 csv：主窗/cost15/端點）；
  不過 → A1 收檔，baseline 維持 B1。

## T5-T6 A2（同 T3-T4 型，N=14）

- variant = 存活 baseline＋A2；敏感度 `a2_sens_p95`、`a2_sens_p99`。
- 若 T4 併入了 A1：baseline csv 用 `b2` 全套；否則沿用 B1。

## T7-T8 A3（同型，N=17）

- variant = 存活 baseline＋A3；敏感度僅 `a3_sens_sma100`、`a3_sens_sma300`
  （協議 §6：乘數 0.75 敏感度**取消不跑**，維持每 ablation 恰 3 試驗）。

## T9 Stage 2 總 verdict

- `reports/cta-l-stage2-verdict.md`：三個 ablation 的 gate 全表、存活 baseline 定義、
  m_total 分佈、與 B1 全窗對比、協議 §9 誠實條款重述、Stage 1 繼承揭露。
- opus 二審只看數字表；不一致呈 owner。commit：
  `docs(cta): L stage-2 verdict — {存活因子摘要} (sub-project L)`。

## 重試上限與凍結

同一 task 最多兩輪；gate 腳本 bug 修正不算重試但要全表重算＋diff 說明（上位 spec §2:63-66）。
主配置與門檻已凍結（協議 §10）；執行期發現的例外裁決記入協議修正案並帶日期戳。
