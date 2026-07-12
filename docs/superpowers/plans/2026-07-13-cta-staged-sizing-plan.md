# Sub-project K 執行計畫（Stage 1；嚼碎版）

Spec（先讀，判準以它為準）：`docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md`。
本計畫只涵蓋 Stage 1；Stage 2/3 在 Stage 1 全過後，先 commit 協議細化再另開計畫。

**紅線（每個 task 都適用）**：不讀不印任何 `.env*`；不跑任何會下單/轉帳的腳本；
`scripts/cta_proxy_pull_data.py` 只打公開行情 API，允許。不得修改 `src/hlvault/cta/` 之下
任何檔案（live 引擎凍結）。不得修改 `scripts/cta_proxy_lib.py` 既有函式的行為（只准新增）。

**派工建議**：T1-T5 各派一個 sonnet subagent（T4 機械、可 haiku）；T6 驗證者必須是
fresh-context（不給實作推理）；T7 由主對話整合＋opus 二審。每個 task 的驗收條件
必須逐條有證據（輸出貼尾段），否則不算完成。

---

## T1 資料就緒檢查

- 動作：檢查 `data/cache/cta_proxy/` 覆蓋 2020-09-14 → 2026-06-30（5 幣、4h、klines
  ＋funding＋quote-volume）。右端不足就跑 `scripts/cta_proxy_pull_data.py` 補到 2026-06-30。
- 驗收：一張表列出每幣每資料型的 bar 數、首末 UTC 時間戳；全部覆蓋窗兩端。

## T2 建 `scripts/cta_k_stage1.py`（sizing hook 骨架）

- 架構事實（先知道再動手）：`cta_proxy_lib.run_cell`（`cta_proxy_lib.py:191`）呼叫的
  `simulate` 是 import 自 `scripts/research_cta_positioning_phase2b.py`（別名 `p2b`），
  且 `simulate` 收不到 coin（coin 是 run_cell 事後才貼上）。所以 hook 掛不進原函式。
- 動作：把 `p2b.simulate` 與 `cta_proxy_lib.run_cell` **複製**到 cta_k_stage1.py 改名
  `simulate_k`/`run_cell_k`，加兩個參數：(a) 進場 notional 乘數 `m_fn(coin, entry_ts)
  -> float`（預設恆 1.0）；(b) `slippage_per_side`（預設 0.0001＝1bp；設 0 可關）。
  fee 與 slippage 都必須按實際 notional（含 m）計。config 用 phase-2b 釘死的
  `4h-p10-fuel24`。不修改 cta_proxy_lib.py 與 p2b 原檔。
- 驗收（對應 spec §3 guards 0/2/3）：
  1. **引擎錨定**：`m_fn≡1.0` 且 `slippage=0` 之下，與原始 `cta_proxy_lib.run_cell`
     路徑的逐日報酬完全相等（`pandas.testing.assert_frame_equal(check_exact=True)`，貼輸出）。
  2. **trade ledger 恆等**：`m_fn≡1.0`（slippage 1bp）與任意 m 之下，(coin, entry_ts,
     exit_ts) 集合相等（集合差為空，貼輸出）。
  3. **線性縮放**：`m_fn≡0.5` 之下，逐日報酬 == 0.5 × B0 逐日報酬（`np.allclose`
     rtol=1e-12、atol=0，貼輸出）——抓漏乘 fee/slippage 的靜默灌水。
  4. **成本手算 spot check**：任取一筆 trade，手算 fee＋slippage（0.055%/side × 實際
     notional × 2 side）與引擎記帳一致（貼對照）。

## T3 σ 序列與乘數

- 動作：每幣 4h log return 的 EWMA 波動（span=180 bars）、年化 ×√2190、closed-bar、
  shift-by-one；`m_i,t = clip(60%/σ_i,t, 0.25, 1.0)`；warmup 前 180 bars m=1.0；
  m 於進場時鎖定。
- 驗收：
  1. 抽 3 個 (coin, ts) 手算對照 EWMA 值，`abs diff < 1e-9`（貼對照表）。
  2. 無前視 spot check：把 t 之後所有 bar 設 NaN，重算 t 時的 σ 與 m 不變（貼輸出）。
  3. 全期 m 的分佈摘要（min/median/max、m=1.0 佔比）——供 verdict 引用，非 gate。

## T4 跑全部 config（14 個 run，全部模擬都在此產生，T5 只讀不跑）

- 動作：輸出到 `data/cache/cta_k/`（每 run 一對 `{config}.csv` 逐日報酬＋
  `{config}_trades.csv`）。標準成本 = 0.055%/side（fee＋slippage）；主窗硬編
  2020-09-14 → 2026-06-30。清單：
  1. `b0` — m≡1.0
  2. `v1` — 主配置（σ_target 60%、span 180、clip 0.25）
  3. `sens_st40`、4. `sens_st80` — σ_target 40%/80%（span 180）
  5. `sens_sp90`、6. `sens_sp360` — span 90/360（σ_target 60%）
  7. `b0_cost15`、8. `v1_cost15` — 成本 ×1.5（0.0825%/side），供 G-K4
  9.–14. `b0_ep30/60/90`、`v1_ep30/60/90` — 右端點 −30/−60/−90d，**截斷窗重跑**
  （窗末強制平倉規則與主窗一致），供 G-K5
- 驗收：14×2 檔案齊全（列 ls 輸出）；逐日報酬 csv 行數 = 對應窗日數 ±1（列實際行數）；
  trades csv 非空且欄位齊備（coin, entry_ts, exit_ts, notional, pnl, fees）。

## T5 gate 腳本 `scripts/cta_k_stage1_gates.py`

- 動作：**只從** `data/cache/cta_k/` 的 csv 讀數（不產生任何新模擬），計算 spec §3 的
  G-K1…G-K5 全表：MAR（定義照 spec §2：非複利算術年化 ÷ |MDD|，每折 MDD 下限 0.5%）、
  6 折 MAR、paired stationary block bootstrap（**聯合重抽 (r_V, r_B) 對齊 block**，
  block 20d、B=10,000、`numpy.random.default_rng(42)`）的 ΔSharpe 90% CI、
  成本 ×1.5 組（讀 `*_cost15`）、端點方向表（讀 `*_ep*`）。附錄輸出 paired ΔMAR CI
  （標註「只呈報，MDD 碎裂 caveat 見 spec §2」）與 m 分佈摘要。輸出 markdown gate 表。
- 驗收：
  1. **自比測試**：以 B0 對 B0 跑一次，ΔSharpe CI 含 0、G-K1 比值 = 1.0（貼輸出）。
  2. gate 表每格都有數字與 PASS/FAIL，無空格。
  3. bootstrap 重跑兩次結果完全相同（同 seed，貼兩次 CI）。

## T6 獨立驗證（fresh-context，不給實作推理）

- 派工內容：只給 (a) `data/cache/cta_k/` csv 路徑、(b) spec §2-§3 的 gate 定義原文。
  要求獨立寫最小重算腳本、產出自己的 gate 表。
- 驗收：驗證者 gate 表與 T5 逐格一致（數字容差 1e-6；bootstrap CI 因同 seed 應完全一致）。
  不一致 → 停下找原因，禁止「取平均」或挑一邊。

## T7 Verdict 與二審

- 動作：主對話整合 T5/T6 寫 `reports/cta-k-stage1-verdict.md`（含敏感度與端點全表、
  spec §6 誠實條款重述、m 分佈摘要）；派 opus 只看數字表做獨立判定；一致才寫結論，
  不一致呈 owner。之後 commit（`docs(cta): K stage-1 verdict — …`）。
- 判定語義照 spec §3：全過 → B1 確立、開 Stage 2（先寫 Stage 2 計畫再動工）；
  任一不過 → 全案收檔，verdict 記錄，不再有變體。

---

## 重試上限（照全域規則）

同一 task 最多兩輪重試；gate 腳本 bug 修正不算重試但要全表重算並註明。
禁止任何形式的配置改選——主配置在 spec 已釘死。
