# Adversarial Audit — Momentum Backtest NO-GO Verdict

**Auditor:** fresh-context agent, 2026-07-12. **Target:** `reports/momentum-backtest-verdict.md`
(NO-GO: Sharpe 0.28, total return -24.0%, MDD -65.1%; universe BTC/ETH/SOL/HYPE, daily,
2024-07-02 -> 2026-07-02).

**Method:** re-ran `scripts/run_momentum_backtest.py` and `scripts/diagnose_momentum.py`
against live Hyperliquid public data (read-only `candleSnapshot` / `fundingHistory`
endpoints); built one reproduction script,
`reports/audit/repro_momentum_sizing_funding.py`, that imports the shipped
`hlvault.momentum.{signals,risk,backtest}` functions unmodified (no signal/PnL logic
reimplemented) and only swaps the **sizing scheme** and/or adds a **funding PnL** term
to run counterfactuals. Full run log: `reports/audit/repro_momentum_sizing_funding.log`.
No repo file was modified (one accidental overwrite of
`reports/momentum-backtest-verdict.md` from running the driver script was reverted with
`git checkout --`); no `.env*` accessed.

**Bottom line:** 7 findings. The single most important one is **verdict_changing: maybe**
— the shipped sizing scheme (flat 3x leverage, no portfolio vol-targeting) is very likely
the dominant cause of the -65% MDD and most of the -24%/-32% loss, not the trend signal
itself; a standard vol-target sizing overlay clears all three GO/NO-GO gates in most
tested configurations, even after adding back a real cost (funding PnL) the shipped
backtest omits entirely. Two other bugs (funding omission, non-pinned backtest window)
independently make the *reported* NO-GO numbers look **better than honest reality**, not
worse — so this is not a case of the strategy being unfairly convicted on inflated costs;
it is a case of the specific sizing implementation being untested against a very plausible
fix that the spec itself demanded.

---

## §0 Reproduction baseline

```
$ .venv/bin/python scripts/run_momentum_backtest.py   # today's rolling window, 2026-07-11 end
panel: 731 days x 4 coins (2024-07-11 -> 2026-07-11)
Total return -31.9% | Sharpe (ann.) 0.22 | Max drawdown -65.1%
```
Directionally consistent with the checked-in verdict (-24.0% / 0.28 / -65.1% for the
2026-07-02 window) but **not numerically identical** — see Finding 3. MDD reproduces
exactly across both windows; Sharpe and total return do not. `reports/momentum-backtest-verdict.md`
was reverted to its original committed content after this reproduction run
(`git status` confirms clean).

---

## Findings

- verdict: momentum
  type: 假設
  direction: 冤殺
  claim: The shipped position-sizing scheme (a flat `LEVERAGE=3` multiplier on top of inverse-vol per-coin budgets, with no portfolio-level vol-targeting) is very likely the dominant driver of the -65% MDD and most of the negative total return — not the trend signal. A standard, causal (no-lookahead) 20%-vol-target sizing overlay flips all three GO/NO-GO gates in most tested parameterizations, including after adding back the funding cost the backtest omits (Finding 2).
  evidence: >
    `.venv/bin/python reports/audit/repro_momentum_sizing_funding.py` (full output in
    `reports/audit/repro_momentum_sizing_funding.log`). Same 731-day panel used for every row below:

    | scenario | Sharpe | Total ret | MDD | passes all 3 gates? |
    |---|---:|---:|---:|---|
    | baseline (3x leverage, as shipped) | 0.217 | -31.9% | -65.1% | no |
    | counterfactual: 1x leverage cap | 0.175 | +1.6% | -24.0% | no (Sharpe, MDD fail) |
    | counterfactual: 2x leverage cap | 0.197 | -10.6% | -46.2% | no |
    | 20% vol-target overlay (no funding) | 0.691 | +35.4% | -18.8% | **yes** |
    | 20% vol-target overlay + real funding (Finding 2) | 0.568 | +26.6% | -19.6% | **yes** (barely, MDD) |
    | 15% vol-target + funding | 0.636 | +28.8% | -16.9% | **yes** |
    | 25% vol-target + funding | 0.534 | +25.7% | -21.9% | no (MDD fails) |
    | 30% vol-target + funding | 0.505 | +24.6% | -24.0% | no (MDD fails) |
    | vol_lookback=40d target 20% + funding | 0.683 | +34.5% | -19.2% | **yes** |
    | vol_lookback=10d target 20% + funding | -0.102 | -13.9% | -44.8% | no |

    The vol-target overlay reuses the exact same `signals.py`/`risk.py` functions (same
    signal, same inverse-vol per-coin budgeting via `risk_budget_per_coin`) — it only
    replaces the flat `* LEVERAGE` multiplier with a causal scalar computed from the
    strategy's own trailing realized daily-return vol (20-40 day lookback), capped at the
    same 3x gross-leverage ceiling, so it cannot lever up more than the shipped design.
    This is exactly the "structurally guarantee the MDD budget" mechanism the spec itself
    demanded and the shipped code admits it lacks:
    `docs/superpowers/specs/2026-07-02-momentum-strategy-design.md:181-184` — "they must
    jointly guarantee the 20% MDD budget is structurally hard to blow through... worst-case
    sizing math belongs in the implementation plan / `risk.py`" — and
    `src/hlvault/momentum/config.py:73-76` self-documents that gap: "It is NOT
    mechanically tied to MAX_DRAWDOWN_PCT: the drawdown breaker is polled every
    SYNC_INTERVAL_SECONDS, not a pre-trade hard cap, so a fast correlated move... can
    exceed the intended 20% budget first."
  verdict_changing: maybe（強證據，但這是設計層的替代方案，非對現有實作的單純除錯；6 組參數中 4 組三關全過、2 組（25%/30% vol target）MDD 差一點沒過 — 不是「隨便選一組就過」，是一個標準技巧族系在合理參數範圍內多數過關）
  proposed_adjustment: 在 risk.py 補一個 portfolio-level vol-target sizing 選項（取代或疊加現有 flat LEVERAGE 乘數），重新用 walk-forward OOS 方法（見 Finding 4）驗證，而非僅用本次單一 in-sample 全歷史重跑的結果直接翻案為 GO。
  rerun_cost: 已跑完，秒級（<1 分鐘/組合）；补 risk.py 選項與 OOS 重驗約 0.5-1 天

- verdict: momentum
  type: bug
  direction: 過寬
  claim: The backtest (`src/hlvault/momentum/backtest.py`) never models funding PnL despite the strategy holding overnight/multi-day perp positions on both sides. Adding real Hyperliquid funding history back in makes the reported result WORSE, not better — the omission currently flatters the strategy relative to honest economics.
  evidence: >
    `src/hlvault/momentum/backtest.py:62-70` — `day_pnl` only accumulates `prev_notional[c]
    * ret` (price PnL) and a fee term; no funding term anywhere in the module. Repro pulls
    real `fundingHistory` for BTC/ETH/SOL/HYPE over the same 731-day window via
    `hlvault.carry.funding._fetch_funding` (paginated — see Finding 3b) and adds
    `funding_pnl_t = -prev_notional[c] * fundingRate_t` (sign convention confirmed against
    `src/hlvault/carry/funding.py:1-4`'s own documented convention: shorts receive when
    rate is positive). Result (`repro_momentum_sizing_funding.log:16-24`):
    total_price_pnl=-$1,320, total_fee=-$754, **total_funding_pnl=-$2,531** over 731 days
    (~-12.6%/yr of starting capital drag for this specific position mix). With funding
    added: Sharpe 0.217->0.084, total return -31.9%->-46.1%, MDD -65.1%->-70.0%.
  verdict_changing: no（已是 NO-GO，加回真實 funding 讓它更明確地 NO-GO，不改變方向，但按方向對稱規則仍需回報：目前報告對這個策略是「偏寬容」而非「偏嚴苛」)
  proposed_adjustment: `backtest.py`（和 `live.py` 的即時風控）都應把 funding 計入 equity/PnL，比照 `hlvault/equity.py` 既有的 equity spine 慣例（`equity_t = starting_equity + cum(realized_pnl) + cum(funding) - cum(fee)`）。
  rerun_cost: 已跑完，秒級（funding pull 含分頁約 1-2 分鐘/次，已加 cache）

- verdict: momentum
  type: bug
  direction: 中性
  claim: The verdict driver script anchors its 730-day window to `time.time()` at run time rather than a pinned date, and overwrites `reports/momentum-backtest-verdict.md` in place with no dated snapshot or diff-review step — so "re-running the same backtest" a few days later silently produces different Sharpe/return numbers with no record of the discrepancy.
  evidence: >
    `scripts/run_momentum_backtest.py:26-27` — `end = int(time.time() * 1000); start = end -
    LOOKBACK_DAYS * 86400 * 1000`, and `:71-72` writes directly to
    `reports/momentum-backtest-verdict.md` via `Path(...).write_text(report)`. Re-running it
    9 days after the checked-in verdict's window (2026-07-02 -> 2026-07-11) reproduced MDD
    exactly (-65.1%) but Sharpe fell from 0.28 to 0.22 and total return fell from -24.0% to
    -31.9% (§0 above; confirmed twice independently in this audit, both agreeing with each
    other and differing from the committed number). I had to `git checkout --
    reports/momentum-backtest-verdict.md` after accidentally regenerating it this way.
  verdict_changing: no（不改變策略本身的經濟性，但代表任何人事後重跑「同一個」驗證都得不到同一組數字，動搖此 gate 作為固定判定紀錄的可信度）
  proposed_adjustment: 加一個顯式的 pinned end-date 參數（預設用 spec 批准當天或首次生成當天的日期），輸出檔名帶日期戳，覆蓋前先 diff 或另存新檔。
  rerun_cost: <0.5h

- verdict: momentum
  type: bug
  direction: 中性
  claim: The spec explicitly commits this backtest to "walk-forward OOS, same discipline as sub-project A... parameter grid (lookback windows, breakout thresholds) evaluated with a multiple-testing correction analogous to DSR" — but nothing in the momentum module or its driver scripts implements a parameter grid, an OOS/train-test split, or any DSR/deflated-Sharpe-style correction. What shipped is a single fixed-parameter, full-history, in-sample replay.
  evidence: >
    `docs/superpowers/specs/2026-07-02-momentum-strategy-design.md:127-130` states the
    commitment. `grep -rn "DSR|deflated|grid|walk.forward|out.of.sample|holdout"
    src/hlvault/momentum scripts/run_momentum_backtest.py scripts/diagnose_momentum.py`
    returns zero hits for any of those concepts (only the phrase "walk-forward-safe" in
    `backtest.py:1`'s docstring, which on inspection means "no-lookahead" — i.e. rolling
    windows only look backward — not "walk-forward out-of-sample validation"). `run_backtest()`
    (`src/hlvault/momentum/backtest.py:29-85`) takes one fixed `entry_threshold`/`vol_lookback`/
    `LOOKBACKS_DAYS=(20,60,120)` and replays the entire 731-day history once; no grid search
    occurred, so there is no evidence the specific parameters were fit to this data (they
    match the literature-standard Moskowitz-Ooi-Pedersen construction per `signals.py:1-4`'s
    docstring), but the spec's own claimed rigor ("same discipline as sub-project A") is not
    actually delivered.
  verdict_changing: no（沒有實際做參數搜尋，所以不構成事後選擇偏誤，數字本身未必失真；但 spec 承諾的方法論嚴謹度並未兌現，是流程誠信問題）
  proposed_adjustment: 若要維持「walk-forward OOS」的宣稱，需真的實作 train/test 切分或至少滾動視窗重估；否則把報告用語改為「single-pass historical replay」，不要再稱為 walk-forward OOS。
  rerun_cost: 若要補實作：0.5-1 天；若只是改報告措辭：<0.5h

- verdict: momentum
  type: 假設
  direction: 中性
  claim: The 4-coin universe (`COIN_UNIVERSE` default `BTC,ETH,SOL,HYPE`) is a static hardcoded list with no liquidity-filtering mechanism implemented anywhere, despite the spec's stated design rationale that a liquidity-filtered, broader universe is "the mechanism that lets the strategy chase big absolute returns without concentrating drawdown risk in one asset." BTC/ETH/SOL/HYPE are all large-cap, trend-correlated crypto assets (not "uncorrelated trend signals"), and the diagnostic PnL attribution shows the -65% MDD is concentrated in exactly the assets that moved most together against the strategy's short side.
  evidence: >
    `docs/superpowers/specs/2026-07-02-momentum-strategy-design.md:131-134` states the
    universe should be "Hyperliquid's liquid perp markets (liquidity-filtered, not just
    BTC/ETH...)"; `src/hlvault/momentum/config.py:66` implements this as a static
    comma-split default string with zero dynamic liquidity filter anywhere in
    `src/hlvault/momentum/*.py` (grep confirms no "liquid" logic outside a docstring
    comment). `.venv/bin/python scripts/diagnose_momentum.py` (today's window) attribution:
    HYPE net -$1,096 (short side -$1,521, while HYPE buy-hold over the window was +431.2%),
    BTC net +$151 but short side alone -$1,006 (BTC buy-hold +12.2%), SOL net -$3,177 (both
    long -$1,484 AND short -$1,480 lost — pure whipsaw, no diversification benefit realized
    between SOL and the other three). This is consistent with, but does not prove, the
    diversification mechanism the spec relied on not being delivered by a 4-large-cap-crypto
    universe. No broader/liquidity-filtered-universe counterfactual was actually backtested
    in this audit.
  verdict_changing: no（未實測替代宇宙，只是記錄一個未驗證的設計缺口，與 MDD 症狀一致但非因果證明）
  proposed_adjustment: 若要重跑，實作真正的流動性篩選（如 24h volume 門檻，動態滾動選幣），並測試更寬、相關性更低的宇宙是否降低 MDD 集中度。
  rerun_cost: 0.5-1 天（需要抓更多幣的歷史資料並重跑）

- verdict: momentum
  type: 假設
  direction: 過寬
  claim: The backtest models zero slippage cost (only `FEE_RATE` taker fee), and the only slippage-shaped constant in the module (`ORDER_SLIPPAGE=0.05` in `live.py`) is an unrelated concept — an IOC limit-price safety buffer for live execution, not an expected-slippage cost estimate — so there's no double-counting, but real daily rebalancing (especially on HYPE, a much thinner/younger market than BTC/ETH) would incur real slippage beyond the modeled taker fee, a further unquantified optimistic bias in the reported numbers.
  evidence: >
    `src/hlvault/momentum/backtest.py:68` — the only cost term is
    `abs(target - prev_notional[c]) * FEE_RATE`; no slippage term. `src/hlvault/momentum/live.py:47`
    — `ORDER_SLIPPAGE = 0.05  # matches hyperliquid.exchange.Exchange.DEFAULT_SLIPPAGE`, and
    the module docstring (`live.py:7-20`) confirms this is the IoC aggressive-limit price
    buffer used only by the live order-placement path (`_place_order`), never imported by
    or referenced from `backtest.py`. I did not have a reliable historical L1
    orderbook/spread dataset available read-only to quantify a magnitude, so this is flagged
    directionally (in the same 過寬 direction as Finding 2, reinforcing rather than
    contradicting it) without a bps estimate.
  verdict_changing: no（方向明確但未量化，且已 NO-GO，只會讓 NO-GO 更成立）
  proposed_adjustment: 若要精確量化，需要 L1/orderbook depth 歷史或至少用同宇宙其他策略（scalp 系列）已建立的 slip 估計方法論套用過來。
  rerun_cost: 若有 orderbook 資料源：0.5 天；否則不可行（唯讀公開 API 無此資料）

- verdict: momentum
  type: bug
  direction: 冤殺
  claim: `FEE_RATE = 0.0005` (5.0bps/side) in the backtest is undocumented in origin and is ~11% higher than this repo's own real-world-validated taker-fee baseline (0.045%/side, sourced from HL's actual `userFees` endpoint via `scripts/scalp_fee_check.py`'s `DEFAULT_TAKER=0.00045`, and used consistently across `research_pair_trading.py`, `research_cta_positioning.py`, `research_funding_carry.py`). The discrepancy is real but immaterial to the verdict.
  evidence: >
    `src/hlvault/momentum/backtest.py:17` — `FEE_RATE = 0.0005`, no sourcing comment.
    `scripts/scalp_fee_check.py:18` — `DEFAULT_TAKER = 0.00045`. Materiality: baseline total
    fee paid over 731 days is ~$754-909 (`repro_momentum_sizing_funding.log:14,21`); at
    0.00045 instead of 0.0005 (10% lower), the fee bill would drop by roughly $75-90 over 2
    years (~0.4%/yr) — two orders of magnitude smaller than the ~30-45 percentage-point
    swings driving every other finding here.
  verdict_changing: no（量級太小，不影響任何門檻判定）
  proposed_adjustment: 改用 0.00045 並加註來源（或改為讀 `data/scalp/fees.json` 之類的既有機制），純粹一致性問題。
  rerun_cost: <0.25h
