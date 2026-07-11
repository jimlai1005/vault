# Adversarial Audit — CTA Positioning Phase-2b NO-GO Verdict

**Auditor:** fresh-context agent, 2026-07-12. **Target:** `reports/cta-phase2b-verdict.md` (NO-GO, dated 2026-07-04).
**Method:** independently re-executed `scripts/research_cta_positioning_phase2b.py` end-to-end (bit-exact
match to the published table, see Repro §0), then built small read-only reproduction scripts
(`reports/audit/repro_effective_n.py`, `reports/audit/repro_funding_addback.py`) that import the
verdict script's own functions (no reimplementation of signal/simulation logic) to test the four
assigned questions quantitatively. No existing file was modified; no `.env*` accessed; all data
reads were from already-cached local parquet (`data/cache/cta/`, `data/cache/coinalyze/`,
`data/cache/funding/`).

**Bottom line:** 5 findings, all type 假設 or bug-but-immaterial, **none verdict-changing at `yes`**.
The two strongest candidates for flipping gate 2 (effective-N correction, funding add-back) are both
real and reproducible, but (a) the more defensible effective-N method still fails the corrected bar,
and (b) funding's effect is two orders of magnitude too small to matter. NO-GO stands.

---

## §0 Reproduction baseline

```
$ .venv/bin/python scripts/research_cta_positioning_phase2b.py
...
median config Sharpe = 1.27  (nearest config: 1d-p20-fuel24-short, sharpe 1.27)
best config = 4h-p10-fuel24-short  sharpe 2.34  tstat 2.14 (gate 2.9)
...
VERDICT: NO-GO   (0.7s)
```
Exact match to `reports/cta-phase2b-verdict.md` lines 156-224. Confirms the published run is
reproducible from the checked-in data cache with no hidden state.

---

## Findings

- verdict: cta-phase2b
  type: 假設
  direction: 過寬（原始門檻本身，方法論上）
  claim: Gate 2's t>2.9 threshold assumes 24 INDEPENDENT trials; the 24 configs are heavily correlated (same 6 coins, overlapping TF/pctile/fuel/side combos), so a proper effective-N correction should raise the bar less than full Bonferroni does — but which correction method you use changes whether the best config passes.
  evidence: >
    `reports/audit/repro_effective_n.py` reconstructs all 24 configs' daily $PnL via
    `research_cta_positioning_phase2b.py`'s own `load_klines/load_coinalyze/bar_frame/raw_indicators/shifted_signals/simulate`
    (no logic duplicated), builds their 24x24 correlation matrix over the stats window (304 days).
    `.venv/bin/python reports/audit/repro_effective_n.py` output:
    mean off-diagonal corr = 0.406; eigenvalues sum to 24.0 (sanity check), largest eigenvalue = 12.6/24
    (one dominant common factor). Li & Ji (2005) eigenvalue effective-N = **7.31**; cruder
    average-pairwise-correlation approximation M_eff = **2.32**. Corrected one-sided-5% thresholds:
    Li&Ji → t>2.48 (best cfg t=2.136 → **still FAILS**); avg-corr → t>2.03 (best cfg t=2.136 → **PASSES**).
    Declared 2.9 reproduces almost exactly from z=norm.ppf(1-0.05/24)=2.865 / t.ppf(...,df=303)=2.887 —
    the gate's own math is internally correct for M=24, the open question is only whether M=24 is the
    right N.
  verdict_changing: maybe（方法依賴：用文獻標準的 Li&Ji eigenvalue 法仍 FAIL；只有較粗略的平均相關近似法才 PASS——不建議只憑後者翻案）
  proposed_adjustment: 若未來重跑，改用 Li&Ji 或等效的 eigenvalue-based effective-N 取代原始 24-trial 假設，作為門檻校準的既定方法，而非事後挑對自己有利的修正法。
  rerun_cost: <0.5h（腳本已可跑，秒級）

- verdict: cta-phase2b
  type: 假設
  direction: 中性（抵銷上一條的寬鬆，強化 FAIL，但同樣是方法論調整，非確定性 bug）
  claim: The best config's reported t=2.14 itself may be inflated because daily PnL is NOT i.i.d. — the 4h/p10/fuel24/short config (172 trades, up to 14-day holds) shows meaningful positive lag-1 autocorrelation, which a standard Newey-West HAC correction reduces.
  evidence: >
    Lag-1 autocorrelation of best-config daily PnL = 0.193 (median config: -0.011, negligible —
    the issue is specific to the 4h/best config, not the family generally). Newey-West HAC
    (statsmodels `OLS(...).fit(cov_type='HAC', cov_kwds={'maxlags':5})`, Bartlett kernel,
    Newey-West rule-of-thumb lag count for n=304) t-stat = **1.909** vs the reported i.i.d. t=2.136.
    A cruder AR(1) effective-N approximation (n_eff = n(1-ρ)/(1+ρ)) gives an even lower t=1.756.
    Combined with the prior finding: even the LOOSEST multiplicity correction (avg-corr method,
    threshold t>2.03) is now failed by the HAC-adjusted t (1.909 < 2.03) — closing the one path
    that looked like it could flip gate 2.
  verdict_changing: no（本身不翻案；其作用是把前一條「效N修正可能翻案」的唯一路徑也堵死，讓 FAIL 更穩固）
  proposed_adjustment: 未來版本的 tstat 計算應對重疊持倉的日報酬序列使用 HAC/Newey-West 標準誤，而非樸素 iid 假設——尤其是短週期（4h）configs，長週期（1d）configs 本身自相關可忽略。
  rerun_cost: <0.5h（同一組腳本延伸，秒級）

- verdict: cta-phase2b
  type: 假設
  direction: 中性
  claim: The pre-declared gate requires the BEST config to survive multiplicity correction (spec: `docs/superpowers/specs/2026-07-03-cta-positioning-design.md:32-35`), but it's ambiguous whether "best" is actually what would be deployed — the median config (gate 1's target) or a non-cherry-picked ensemble might be the more honest deployment candidate, and neither clears even an UNCORRECTED single-test significance bar.
  evidence: >
    Selection-penalty-free (uncorrected, one-sided 5%, z=1.645) checks from
    `reports/audit/repro_effective_n.py`: median config (`1d-p20-fuel24-short`) tstat = 1.166 →
    **FAILS** even with zero multiplicity correction. Equal-weight ensemble of ALL 24 pre-declared
    configs: tstat = 1.355 → **FAILS**. Equal-weight ensemble of the 8 pre-declared short-only
    configs (side is a first-class pre-declared switch per spec line 30, not a tuned parameter):
    tstat = 1.747 → PASSES the uncorrected bar, but still FAILS both the original t>2.9 bar and the
    Li&Ji-corrected t>2.48 bar from finding 1.
  verdict_changing: no（每一種「實際會部署的東西是什麼」的合理讀法都 FAIL 顯著性下限，除了 short-ensemble 對 uncorrected bar，但那條在兩種 Bonferroni 修正法下都仍 FAIL——NO-GO 對這個歧義穩健）
  proposed_adjustment: 未來 spec 應明確定義「若通過 gate，實際部署的是 best config、median config、還是宣告的 ensemble」——目前 gate 2 只檢查 best，但若部署目標其實是別的候選，statistical target 應對齊。
  rerun_cost: 已含在同一次 repro 執行中，0h 額外成本

- verdict: cta-phase2b
  type: bug
  direction: 冤枉（方向正確但量級可忽略）
  claim: Phase 2b PnL excludes HL funding accrual (documented caveat, `reports/cta-phase2b-verdict.md:22`); this strategy's short entries specifically fire when retail is crowded LONG, a condition historically correlated with positive funding (paid to shorts) — so the omission should bias AGAINST the short side, but the magnitude is negligible.
  evidence: >
    `reports/audit/repro_funding_addback.py` re-simulates median/best/8-short-ensemble configs with
    a funding accrual term added (identical mechanics to Phase 2a's own `research_cta_positioning.py`
    simulate(), using the real `data/cache/funding/{COIN}.parquet` HL series for the SAME phase-2b
    window). Funding IS structurally positive for shorts over this window: 65-92% of hours per coin
    had positive funding rate (mean rate +0.5 to +1.4 bps/hr across coins). But dollar impact is tiny:
    best config pnl $183.67→$185.00 (+$1.33), tstat 2.136→2.152 (+0.016); median config pnl
    $106.44→$108.45 (+$2.01), tstat 1.155→1.176 (+0.022); 8-short ensemble tstat 1.747→1.767 (+0.020).
    Quantitatively confirms the verdict's own caveat text ("a few dollars either way") rather than
    contradicting it.
  verdict_changing: no（Δtstat ~0.02，遠不足以跨越任一門檻，無論原始 2.9 或任何修正後門檻）
  proposed_adjustment: 若未來 Coinalyze 方案取得對應 HL funding 序列，補回累加是正確方向的小改善，但不應被當作解鎖 gate 2 的手段——量級對不上。
  rerun_cost: <0.5h（腳本已可跑，數秒；資料已在 cache）

- verdict: cta-phase2b
  type: 假設
  direction: 過寬（措辭層面，非 gate 結果）
  claim: The verdict's prose ("real data confirms the strategy family has a genuine, coin-broad, risk-contained edge") reads more confident than the fuller cross-cycle picture supports — but this couldn't have been known at the time (the multi-year proxy evidence postdates phase-2b by 2 days), and the actual NO-GO decision is unaffected either way.
  evidence: >
    File dates: `reports/cta-phase2b-verdict.md:1` = 2026-07-04 (git-committed same day);
    `reports/cta_proxy_layer2b_verdict.md:3` = 2026-07-06; `reports/cta-overnight-synthesis-2026-07-06.md`
    same date — both untracked/2 days later, chronologically impossible to have informed phase-2b.
    Substantively (`reports/cta_proxy_layer2b_verdict.md:100-116`, 5.7yr Binance-funding-proxy,
    year-by-year Sharpe): short/crowd-ON wins only in 2022/2025/2026 (bear/choppy); LONG wins
    2020/2021/2023/2024 (bull/recovery), with short badly negative in 2020/2021 (Sharpe -1.07,
    -1.98). I.e. the "short-only, long is dead weight" pattern phase-2b measured so cleanly
    (Sharpe 2.34 short, -1.61 long) is regime-specific to 2025-26, not a persistent cross-cycle
    property — consistent with, and slightly stronger than, phase-2b's own caveat #5 ("one regime").
    No statistically defensible method exists to POOL the 334d real-crowd t-stat with the 5.7yr
    funding-proxy t-stat into one corrected significance number (different signal sources = not
    repeated measurements of the same effect); the current document separation (binding verdict vs
    "not a GO/NO-GO input" research layer, per `reports/cta_proxy_layer2b_verdict.md:3`) is the
    statistically correct handling, not a process gap.
  verdict_changing: no（時序上不可能影響、且實質證據若真的可用也是強化而非削弱 NO-GO；只有措辭稍嫌樂觀，操作結論不受影響）
  proposed_adjustment: 未來若這個 strategy family 被重新提起，report 應直接引用 layer2b 的 regime-flip 表，避免「genuine edge」這類跨週期語感的措辭在只有單一 regime 樣本時被過度引用。
  rerun_cost: 0h（純讀取既有報告，無需重跑）

---

## Checked, no finding

- **Gate 3 (MDD) calc**: `daily_stats()` line 261 uses `eq.cummax()` (not the `eq.max()` bug found
  elsewhere in `research_cta_layer2a_analysis.py` per `reports/cta-overnight-synthesis-2026-07-06.md:32`)
  — phase-2b's own MDD calc is correct.
- **Gate 5 (split-half) robustness**: re-ran the same-sign check at 5 alternative split dates
  (2025-12-01 through 2026-03-01) for both median and best config — same sign holds at every split
  tested; not fragile / not date-cherry-picked (the actual split_at is a deterministic function of
  data coverage, not of realized PnL).
- **PIT/look-ahead discipline**: verdict's own synthetic-shuffle test (§ Data verification #4) is
  sound; did not find a reason to doubt it, and did not attempt to re-derive it independently given
  time budget (would require rebuilding the shuffle harness — flagged as unchecked, not "passed by me").
- **Fee assumption (0.045%/side)**: cross-checked against the sibling audit
  `reports/audit/J-cross-costs-scan.md` (produced in this same audit batch) — 0.045% is used
  consistently across Phase 2a/2b/pair-trading, and is the HL base-tier taker fee; the only lower
  observed rate (1.4bps) is specific to stable-pair fee tier, not applicable to BTC/ETH/SOL/HYPE/DOGE/XRP
  majors. No CTA-specific discrepancy found.
- **Correlation-matrix sanity**: eigenvalues of the 24x24 correlation matrix sum to exactly 24.0
  (trace check); same-side/same-TF pairs correlate 0.82-0.89 (economically sensible — differ only
  in one knob), opposite-side pairs correlate ~0.00 (long/short signals are near-disjoint by
  construction) — the correlation structure behind finding 1 is not a computation artifact.

## Process observation (品味, not a finding)

The two statistical corrections that matter most here (effective-N reduction from cross-config
correlation, and t-stat inflation from within-series autocorrelation) point in **opposite**
directions and are of comparable size in this dataset — they roughly cancel, leaving the FAIL
conclusion intact more by coincidence of magnitude than by the original gate having been calibrated
for either effect. A future phase with a different correlation/autocorrelation profile (e.g. a
config matrix with less redundancy, or longer average holding periods) could see this cancellation
NOT hold. This is a design observation for whoever revisits this gate, not a defect in phase-2b's
own arithmetic.

## Files

- `reports/audit/repro_effective_n.py` — Q1 (effective-N / Li&Ji) + Q2 (selection-penalty
  applicability) reproduction, read-only.
- `reports/audit/repro_funding_addback.py` — Q4 (funding accrual add-back) reproduction, read-only.
- This file: `reports/audit/J-cta2b-findings.md`.
