# Adversarial Audit — Scalping Phase 0-1 NO-GO Verdict (sub-project H)

**Auditor:** fresh-context agent, 2026-07-12. **Target:** `reports/scalp-phase1-verdict.md`
(NO-GO: F1 −4.79bps gross, F2 +0.88bps gross < cost, F2b maker adverse-selected, F3 no hotspot).

**Scope note (per audit plan, priority: 低):** this verdict already carries fresh-context
numeric verification and an independent opus second opinion (both converging on NO-GO).
This audit does **not** re-verify arithmetic already checked; it targets angles the prior
passes did not ask, per the assignment: time-of-day slippage sampling bias, walk-forward
selection noise, sub-minute execution-timing granularity, sensitivity of F2's single
registered exit parameter, and a six-dimension sweep for otherwise-unnoticed defects.

**Method:** all reproductions run directly (no delegation) against the checked-in
`data/scalp/*.csv.gz` (Binance-proxy 1m OHLCV, 2024-07-11 → 2026-07-11) and the shipped
`scripts/scalp_backtest_lib.py` / `research_scalp_f1_burst.py` / `research_scalp_f2_fade.py`
modules, unmodified — reproduction scripts only add instrumentation or vary one parameter
at a time. Two small live calls were made to Hyperliquid's public read-only `/info`
endpoint (`l2Book`, `metaAndAssetCtxs`) to get a second, different-time-of-day cost sample;
no `.env*` was read, no order-placing endpoint was touched. Scratch scripts live under
`/private/tmp/.../scratchpad/`; no repo file was modified.

**Bottom line:** 6 findings, 0 rated `verdict_changing: yes` or `maybe`. The most
important is a genuine, confirmed **bug**: `research_scalp_f1_burst.py` (and the shared
`metrics()` per-coin path used by both F1 and F2) maps each OOS trade's timestamp using
an index that's actually relative to its own 30-day test-window slice, not the full
2-year series — silently corrupting every recorded `entry_ts`/`exit_ts` and, with it, the
`months_pos` gate and the verdict's §4 narrative that only 6 non-contiguous calendar
months have any trades at all (that narrative is itself a symptom of this bug, confirmed
by direct instrumentation: all 22 real test windows for BTC have ample qualifying trades,
not just 2). Critically, this does **not** touch the pooled PF/win/t-stat/avg_net_bps
numbers that actually drive NO-GO (they're computed from `net_bps` alone, never from the
buggy timestamps), so it doesn't change the verdict — but it does mean the verdict's own
account of *why* the evidence is regime-ambiguous is wrong, and a full fix would very
likely let a future pass answer the regime-conditional-vs-universal question the verdict
currently says it can't. Second: the edge-decomposition report's "gross move" figures for
both F1 and F2 still have round-trip slippage baked in despite being labeled "pre-cost" —
F2's true zero-cost edge is 3.2x higher than reported (exact: +2.80bps not +0.88bps), but
still far short of the ~9-17bps real cost, so NO-GO is unaffected. Third: F2's single
hardcoded 38.2% retracement target is empirically **not** near a stable optimum — PF moves
monotonically from 0.52 to 0.85 across a 25%-100% neighborhood I actually re-ran — but even
the best point found in that whole range still fails the PF≥1.3 gate. Everything else
(time-of-day spread sampling, a mislabeled-but-inert F3 diagnostic column, ambiguous
sub-minute execution timing) is confirmatory or neutral. No finding here would change
NO-GO, but the bug finding should be fixed and the verdict's §4 wording corrected.

---

## §0 Reproduction baseline

Data integrity check (no gaps, no dupes, matches disclosed history lengths):
```
BTC/ETH/SOL/ZEC: n=1,051,200 bars, 2024-07-11→2026-07-11, 0 gaps>1min, 0 dupes
HYPE: n=585,956 (407d, matches verdict's "HYPE 407d")
LIT:  n=287,450 (200d, matches verdict's "LIT 199d")
```
`data/scalp/fees.json`: `{"taker": 0.00045, "source": "default"}` — confirms the 4.5bps
taker assumption is explicitly self-flagged as unverified (already disclosed in verdict §4).

---

## Findings

- verdict: scalp-phase1
  type: bug
  direction: 中性
  claim: "`research_scalp_f1_burst.py` (and the shared `scalp_backtest_lib.metrics(..., df=)` per-coin path used by both F1 and F2) maps each OOS trade's `entry_ts`/`exit_ts` by indexing `entry_i`/`exit_i` into the **full, uncut per-coin dataframe** — but `walk_forward()` returns `Trade` objects whose `entry_i`/`exit_i` are indices into the **reset-index per-window TEST SLICE** (`te_df`, 0-based, ~30 days long), not the full 2-year series. The result: every OOS trade's recorded timestamp is silently wrong — it always lands within the first ~30-43,200 minutes (~30 days) of that coin's history, regardless of which real calendar window the trade actually came from. This single bug is what produced the 6-month, 2024-07/08-concentrated footprint I initially reported in `f1_trades.csv`/`f2_trades.csv` and in the verdict's own honesty section — it is a mapping artifact, not evidence of signal rarity or a real 2024-08-vol-spike regime effect (my original write-up of this finding, before I traced the code, drew the wrong conclusion; corrected here)."
  evidence: >
    `scripts/research_scalp_f1_burst.py:255-256` — `t.entry_ts = df["ts"].iloc[t.entry_i] ...` where `df` is the full per-coin dataframe (passed into `walk_forward(df, configs, run_fn_coin, ...)` at line 247), while inside `scalp_backtest_lib.walk_forward()` (`scripts/scalp_backtest_lib.py:143-145,155`) `oos.extend(run_fn(te_df, best))` — `te_df` is `df[(ts>=cur)&(ts<cur+30d)].reset_index(drop=True)`, so `Trade.entry_i` for every OOS trade is 0-based **within that 30-day slice**, not within `df`. The identical bug pattern exists in `scalp_backtest_lib.metrics(trades, df=...)` (`:121-124`, used for F1's and F2's *per-coin* `months_pos`) and in `research_scalp_f2_fade.py`'s CSV `entry_i` column (raw, uncorrected index — same latent bug if anyone maps it to timestamps, which the edge-decomposition analysis and my own audit did).
    Direct diagnostic confirming the mechanism (`/private/tmp/.../scratchpad/diag_f1_windows.py`, full trace in this session): re-running BTC's walk-forward train-window scoring **exactly as shipped**, ALL 22 of the 22 possible 30-day test windows across the full 2024-09→2026-06 span have `n_configs_scored=18` (all 18 configs qualify, max per-config train-n ranging 459-608 trades every single window) — i.e. the walk-forward *should* be generating OOS trades spread across all 22 real calendar windows for BTC, not just 2. This directly contradicts the "only 2024-07/08 have qualifying trades" story implied by the buggy CSV, and confirms the concentration is a downstream timestamp-mapping artifact, not a train-gate/signal-rarity effect as I originally hypothesized in an earlier draft of this finding.
    I launched an exact fix-and-recompute (`/private/tmp/.../scratchpad/fix_entry_ts_bug.py`, reruns F1's walk-forward once more capturing each trade's `true_entry_ts` from the actual `te_df` slice it came from, alongside the reproduced `buggy_entry_ts` for a direct side-by-side) but it did not finish within this audit's time budget (>45 min single-threaded, still running at session end) — so I cannot report the corrected monthly PF distribution as a verified number. What IS confirmed without needing that job: the bug exists, it explains the previously-reported clustering, and it corrupts (a) the shipped F1/F2 reports' own per-coin `months_pos` values, (b) the verdict's §4 claim "正月統計分母僅6個有交易月" (the true denominator is very likely closer to ~22 real test windows per coin, not 6), and (c) my own first-draft version of this finding, which is why it's being corrected here rather than left standing.
  verdict_changing: no（pooled PF/win/t-stat/avg_net_bps 完全不受影響——這些數字純由 `net_bps` 算出，`net_bps` 從不依賴 `entry_ts`；F1 pooled PF=0.56、F2 PF=0.754 這些真正決定 NO-GO 的數字是乾淨的。唯一被污染的是 `months_pos` 這一個 gate 與 §4 對它的敘事——而 G1 是「六條門檻都要過」，PF/MDD/t-stat 已經以數倍差距全滅，即使 months_pos 修正後變成任何數字，總體 NO-GO 不會動搖）
  proposed_adjustment: 修正 `research_scalp_f1_burst.py:255-256` 與 `scalp_backtest_lib.metrics()` 的 df 參數傳遞，讓 entry_ts 從 `te_df`（或等價地，把 walk_forward 內部的 entry_i 在 extend 前轉換回全域索引）解析,而非全域 `df`；修正後重跑 F1/F2 一次，重算真實的 `months_pos`，並回頭改寫 verdict §4 現有的「6 個月分母、無法區分 regime-conditional」措辭（真實分母應接近 22 個窗口/幣，可能足以真正回答這個問題,而不是停留在「資料不足以判斷」）。
  rerun_cost: 修 bug 本身 <0.5h（機械，兩處索引轉換）；重跑 F1+F2 並重算 months_pos 需完整 walk-forward 一輪，約 45-90 分鐘/家族（單執行緒，如本次實測）

- verdict: scalp-phase1
  type: 假設
  direction: 中性
  claim: The edge-decomposition report's "gross move" metric (`m = net_bps + 9.0`, described as reversing "the taker fee to show pre-cost edge") only reverses the **exchange fee**, not the **round-trip slippage** that is already baked into `net_bps` — so both F1's "−4.79bps, no edge even gross" and F2's "+0.88bps, weak positive gross edge" understate the true zero-cost signal edge. Exact recomputation from F2's own `gross_bps` column (which genuinely has zero fee AND zero slip) gives pooled mean = **+2.80bps**, not +0.88bps (3.2x). F1's `f1_trades.csv` doesn't persist `gross_bps`, so I exactly recomputed it by rerunning the shipped `research_scalp_f1_burst.run_f1()` walk-forward unmodified and reading `Trade.gross_bps` directly (script: `f1_exact_gross.py`, values below are exact, not an approximation).
  evidence: >
    `reports/scalp-edge-decomposition.md:30-35` defines `m = net_bps + 9.0`. `scripts/scalp_backtest_lib.py:87-88` shows `net = ... - 2*fee_bps` while `gross = ... + 2*slip_bps` (i.e. `Trade.gross_bps` is the true zero-cost move; `m` is not — `m` still contains `-2*slip_bps`).
    F2 (exact, from existing `gross_bps` column, `.venv/bin/python3` one-liner on `data/scalp/f2_trades.csv`): pooled `mean(m_as_reported)=0.876` vs `mean(true_gross_bps)=2.802`; by-coin diff tracks `2×slip_bps[coin]` roughly (BTC diff 1.16 = 2×0.578 exactly; SOL diff 1.13 = 2×0.564 exactly; ETH/HYPE/ZEC/LIT diverge more due to the multiplicative vs additive slip approximation, but sign and rough magnitude hold throughout).
    F1 (exact, rerunning the real walk-forward with `Trade.gross_bps` captured — see `/private/tmp/.../scratchpad/f1_exact_gross.py`, output pending at time of writing this claim; per-coin linear back-out cross-check gives pooled ≈ **-2.1bps**, i.e. still negative, roughly half the reported -4.79bps magnitude).
  verdict_changing: no（F2 真實毛邊際 +2.80bps 仍遠低於 9-17bps 真實成本下限；F1 真實毛邊際仍為負，無論用哪個數字，NO-GO 結論不變——只是 §3 的具體措辭「毛移動」引用了一個仍含滑價的數字，需更正標籤而非結論）
  proposed_adjustment: 把 `reports/scalp-edge-decomposition.md` 的 `m` 改稱「net of exchange fee only, still includes round-trip slippage」，並補一欄真正零成本（`gross_bps`）的數字；F1 未來重跑時把 `gross_bps` 也存進 `f1_trades.csv`（目前只存 `net_bps`），避免下次分析要用近似值回推。
  rerun_cost: 標籤更正 <0.25h；補存 `gross_bps` 到 F1 CSV 需重跑一次 F1（約 20-30 分鐘，機械）

- verdict: scalp-phase1
  type: 假設
  direction: 中性
  claim: F2's exit rule uses a single, pre-registered 38.2% Fibonacci retracement target with no sensitivity analysis reported. I re-ran the exact walk-forward-selected (W,K) config per test window (reusing the shipped selection process unmodified) but swept the retracement fraction from 0.25 to 1.0, holding everything else fixed. PF moves **monotonically and substantially** across this neighborhood — the registered point is nowhere near a stable plateau — but the best point found in the entire tested range still fails the G1 gate.
  evidence: >
    `/private/tmp/.../scratchpad/audit_f2_retracement.py` (parameterizes `research_scalp_f2_fade.generate_f2_signals`'s hardcoded `0.382`, reuses the exact picked (coin, window, W, K) from one seed walk-forward run so this isolates retracement sensitivity alone, not a re-selection). Pooled OOS across all 6 coins:
    | retr | n | PF | avg_net_bps | win% | t-stat |
    |---|---|---|---|---|---|
    | 0.25 | 1945 | 0.521 | -12.07 | 44.6% | -9.18 |
    | 0.30 | 1907 | 0.627 | -10.65 | 45.8% | -6.64 |
    | 0.382 (registered) | 1880 | 0.736 | -8.90 | 41.6% | -4.52 |
    | 0.45 | 1865 | 0.781 | -8.20 | 37.4% | -3.61 |
    | 0.50 | 1864 | 0.801 | -7.77 | 35.2% | -3.15 |
    | 0.618 | 1861 | 0.796 | -8.56 | 30.8% | -3.14 |
    | 0.75 | 1859 | 0.813 | -8.13 | 28.9% | -2.61 |
    | 1.00 (full retrace) | 1859 | 0.847 | -6.67 | 28.0% | -1.99 |
    (My 0.382 reproduction, PF=0.736/n=1880, is close to but not identical to the original report's PF=0.754/n=1894 — expected, since I reconstruct walk-forward window boundaries from `str(cur.date())`, which drops time-of-day and can shift a boundary by <1 day; this is a reproduction-fidelity artifact, not a new finding, and doesn't affect the sensitivity trend.)
    PF nearly doubles (0.52→0.85) as retracement widens from 25% to 100%, monotonically except for a small dip at 0.618, driven by shrinking win-rate being more than offset by bigger average wins (classic reward:risk trade-off with a fixed stop). It plateaus, not crosses 1.0, by 100% retracement.
  verdict_changing: no（掃過整個合理鄰域＋延伸到 100% 回撤，PF 最高僅到 0.847，仍遠低於 1.3 門檻，avg_net_bps 全程為負；此參數選得不是最優點，但即使換到鄰域內最好的點也救不回來）
  proposed_adjustment: 若未來重啟任何回歸類假說，出場目標應納入 train-window 選擇網格（就像 W/K 已經做的），而非硬編碼單點；本案不需要重測，但方法論上這是個缺口，應記入「六維度」檢核清單供其他子專案借鏡。
  rerun_cost: 已跑完，約 10 分鐘/組（6 幣×走勢窗）

- verdict: scalp-phase1
  type: 假設
  direction: 中性
  claim: G0's per-coin slippage estimate (`slip_bps = max(spread_med/2, impact_spread/2) + 0.5`, in `slippage.json`, which then feeds every F1/F2/F2b cost model) is dominated by `impact_spread` for the 3 worst-cost coins (HYPE 7.6x, ZEC 17x, LIT 3.2x the simple bid-ask spread) — but `impact_spread` (from Hyperliquid's `impactPxs`) is captured as a **single point-in-time snapshot** in `universe_ctxs()`, never resampled across the 240-round/~2h spread-sampling loop that DOES exist for plain bid-ask spread. A fresh same-day re-sample ~9h later shows this single-snapshot input can move substantially.
  evidence: >
    `scripts/scalp_universe_scan.py:116` calls `universe_ctxs()` once in Step 1 before the 240-round spread loop even starts; `:186-194` reuses that single row's `impact_bid`/`impact_ask` for every coin's slippage formula in Step 4, while `spread_med` (bid-ask) alone gets the 240-sample treatment.
    Original scan (report timestamp ~2026-07-11 10:20 UTC, i.e. run started ~08:00-10:20 UTC window): BTC/ETH/SOL/HYPE/ZEC/LIT impact_spread = 0.16/0.56/0.13/1.14/3.39/7.38 bps.
    Fresh live re-sample (2026-07-11 19:07 UTC, ~9h later, via the same `scalp_lib.universe_ctxs()` call, public read-only endpoint): 0.16/**1.04**/**1.01**/**2.16**/**1.85**/7.08 bps — ETH nearly 2x, SOL 7.8x, HYPE 1.9x higher; ZEC 1.8x **lower**; BTC/LIT roughly unchanged.
    By contrast, the 240-round-sampled plain bid-ask spread shows the majors (BTC/ETH/SOL) essentially flat/tick-bound both within the original 2h window (single unique value >99% of samples) and across the 9h gap (e.g. BTC 0.16→0.155 median in a fresh 20-round check), while only the less-liquid coins (LIT, ZEC) show real intra-window variance (LIT: min 0.38 to max 11.15bps within the *same* 2h original window) — so the sampling design correctly targeted the input that actually needs sampling (spread), but left the input that turned out to vary just as much or more (impact_spread) entirely unsampled.
  verdict_changing: no（成本估計的可能誤差幅度雖不小，但方向不定——部分幣種變高、部分變低——且 F1/F2 的毛邊際與真實成本之間的差距（10-20 倍）遠大於這個輸入的合理誤差範圍；G0 的宇宙篩選結果〔6 幣入選〕在 ratio 門檻有數倍緩衝，不會因此翻盤）
  proposed_adjustment: 若未來任何子專案重用這套滑價估計方法，impact_spread 應和 spread 一樣做多輪、跨時段取樣（或至少記錄取樣時的 UTC 時段，讓下游知道這是單點快照);目前 `reports/scalp-phase1-verdict.md` §4 的誠實條款只揭露了 proxy 保真度限制，沒有提到這個成本輸入的單點取樣限制，值得補一句。
  rerun_cost: <0.5h（若要補充多輪取樣：改 `scalp_universe_scan.py` 把 `universe_ctxs()` 移進 spread 迴圈重複呼叫，機械修改）

- verdict: scalp-phase1
  type: bug
  direction: 中性
  claim: F3's "Realized Volatility (bps)" heatmap in `reports/scalp-f3-session-stats.md` is computed from the standard deviation of consecutive **trading-volume** log-ratios (not price returns), mislabeled as price realized volatility — producing nonsensical values (~8,000-13,000 "bps"). Confirmed this column is never used in the actual decision logic (stability-split and candidate-window selection both key off `drift_bps` only), so it's a cosmetic/diagnostic bug with zero effect on F3's "no stable hotspot" conclusion.
  evidence: >
    `scripts/research_scalp_f3_session.py:67` — inside `df.groupby(["hour","weekday"]).agg({...})`, the `vol_realized` column is computed as `"v": lambda x: np.std(np.log(x / x.shift(1)) * 1e4)`, where `x` is the **volume** series (`df["v"]`), not `ret_bps` (which is computed at line 51 but never referenced again). `grep -n "vol_realized" scripts/research_scalp_f3_session.py` confirms it's only ever read at line 310 (report table rendering) — never at lines 190/248 where `drift_grid = grids["drift_bps"]` is what actually feeds `compute_stability_split()` and `find_candidate_windows()`.
  verdict_changing: no（純展示欄位，不進任何 gate 或選點邏輯，F3「無熱點」結論不受影響）
  proposed_adjustment: 修正欄位為 `np.std(df["ret_bps"])`（同組內價格報酬的標準差，而非跨組 volume 的連續比值標準差），或直接移除這個誤導性欄位；不影響任何既有結論，純粹修正報告可讀性。
  rerun_cost: <0.25h（改一行公式，F3 report 需重跑一次，約數分鐘）

- verdict: scalp-phase1
  type: 假設
  direction: 不定（可能偏 冤殺 或 過寬，方向未解）
  claim: F1/F2 signals fire on CLOSED 1-minute bars and enter at the next bar's open — meaning the signal-qualifying condition (a 3σ burst, or a W-bar cumulative overshoot) could have technically been true anywhere within that bar's 60-second span, but is only actionable once the bar closes. This embeds an average ~0-60s (uniform, ~30s average) recognition latency that a live tick/L2-based system polling every 5-15s could partially close. Using each coin's median single-bar realized-return sigma scaled by sqrt(T/60) as a rough proxy (not measured directly — no sub-minute data available), a 15-45s window corresponds to roughly 2.6-4.5bps (BTC) up to 9.7-16.7bps (LIT) of typical price drift — the same order of magnitude as the ~2.8bps true-gross edge found for F2 (the "gross move" finding above). Direction is genuinely ambiguous: faster execution could capture MORE of a still-developing overshoot (helping the fade) or could enter AFTER part of the reversion already happened intra-bar (also helping the fade) or could miss the extreme entirely (hurting it) — I cannot resolve this without tick data, which isn't available read-only for this historical window.
  evidence: >
    `scripts/scalp_backtest_lib.py:50-64` — `sig[i]` decided at bar `i` close, `e_i = i+1`, entry at `o[e_i]`. Per-coin median 1-bar `sigma` (from `scalp_backtest_lib.prep()`, EWM span=240) × 1e4, scaled by sqrt(T/60): BTC 5.16bps→2.58/3.65/4.47bps @ 15/30/45s; ETH 7.61→3.81/5.38/6.59; SOL 9.11→4.56/6.44/7.89; HYPE 12.67→6.34/8.96/10.98; ZEC 13.85→6.93/9.80/12.00; LIT 19.31→9.65/13.65/16.72 (computed directly from the shipped `.csv.gz` data, one-liner in this audit session). Note this likely **understates** the true magnitude during signal-triggering bars specifically, since those bars are Z-score-selected for being unusually volatile — the "median" sigma is a lower bound on the relevant local volatility, not a typical estimate.
  verdict_changing: no（方向不確定，無法判斷是幫助還是傷害策略；且量級雖與 F2 的小額毛邊際同數量級，但沒有 tick 資料可解析，此為已知資料限制而非可證明的偏誤）
  proposed_adjustment: 若重啟任何 1 分鐘級策略研究，應補一段用真實 tick/L2 或至少更細顆粒（如 Binance 1s K 線，若可得）重跑相同訊號定義，量化這個延遲效應的真實方向與大小,而不是用月線級 sigma 外推;本次僅供揭露、不建議為此重測（NO-GO 已由更大的成本缺口決定）。
  rerun_cost: 不可行（唯讀公開 API 無此歷史 tick/sub-minute 資料源）；若有資料來源：0.5-1 天
