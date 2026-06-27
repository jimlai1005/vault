# Sub-project A — Hyperliquid Trader Selection Research Pipeline

**Date:** 2026-06-27
**Status:** Design approved (decision delegated to Claude as project decider)
**Repo:** `hl-vault` (new; reuses `hl-copytrader` SDK plumbing in sub-project B)

## 執行摘要 (Executive Summary)

目標:從 Hyperliquid 鏈上資料,產出一份**可重現、嚴格 point-in-time、以風險調整後 alpha(非 beta)+ 持續性為準**的 top-N trader 排名與**共變異感知權重向量**,並用 walk-forward **out-of-sample backtest** 給出 **go/no-go** 結論。

這是整個 vault 的關鍵實驗:若「過去贏家」在 OOS 沒有顯著正報酬,thesis 證偽,**不進入子專案 B(執行引擎)**。本 spec 只涵蓋 A。A 沒有任何真實資金或下單副作用 —— 純讀公開鏈上資料 + 計算。

## Goals / Non-Goals

**Goals**
- Reconstruct a true daily equity curve for each candidate address from on-chain fills + funding + mark-to-market.
- Rank traders by **risk-adjusted, persistence-validated, alpha-not-beta** criteria — never raw PnL.
- Produce a covariance-aware weight vector over the selected set (HRP primary; risk-parity / fractional-Kelly as comparators), using a Ledoit-Wolf-shrunk covariance.
- Run a walk-forward OOS backtest that is the **go/no-go gate** and reports a realistic expected OOS Sharpe/return for the live vault.
- Be fully reproducible from cached raw data with a single CLI command.

**Non-Goals (this sub-project)**
- No live trading, no order placement, no real funds, no on-chain vault creation (that is sub-project B).
- No real-time/streaming pipeline — batch/scheduled is sufficient for selection.
- No UI beyond a static report artifact (HTML/markdown + plots).

## Architecture Overview

Pipeline of independently-testable stages, each a focused package with a clear interface. Data flows one direction; every stage reads cached inputs and writes cached outputs (parquet), so any stage can be re-run in isolation.

```
leaderboard ─▶ [1 universe] ─▶ [2 ingest] ─▶ [3 equity] ─▶ [4 metrics] ─▶ [5 factors] ─▶ [6 select] ─▶ [7 weights]
                                                                                                           │
                                                              [8 backtest: walk-forward re-runs 3→7 as-of T]
                                                                                                           ▼
                                                                                                   [9 report + verdict]
```

### Resilience boundary (CLAUDE.md principle #5)
All external calls (HL info API, S3 archive, price source) go through **one** `io/source.py` boundary that demands classification at the call site: read vs write (all reads here), transient-retryable (backoff on 5xx/timeouts/connection-reset) vs semantic (bad address/4xx → surface, no retry). No scattered try/except. Tests inject a fake source; **no test touches the network** (autouse fixture mutes the real client — CLAUDE.md principle #4).

## Components

### 1. `universe/` — candidate ingestion
- Pull the Hyperliquid leaderboard (info API) → top ~300 addresses as the candidate universe. Persist `universe.parquet` with the as-of date (the leaderboard itself is point-in-time; for the OOS backtest the universe must be reconstructed as-of T from archived snapshots, not today's leaderboard — see §Point-in-time).
- Interface: `get_universe(as_of: date) -> list[Address]`.

### 2. `ingest/` — raw data acquisition + cache
- **Primary historical source:** `s3://hl-mainnet-node-data/node_fills_by_block` (requester-pays) — full-history, all-address fills. Fallback: Hydromancer Reservoir free S3 archive (incl. daily account snapshots).
- **Recent window:** official `userFillsByTime` (rolling, ≤10k fills) for freshness.
- **Funding:** ledger updates per address. **Prices:** OHLCV (1h/1d) per coin for mark-to-market.
- Pluggable `FillSource` / `PriceSource` interfaces so API-first works now and S3 archive adds depth without changing downstream stages.
- Cache everything to parquet keyed by `(address, source, time-range)`; idempotent — re-runs hit cache.

### 3. `equity/` — equity curve reconstruction
- Per address, build a daily return series:
  `equity_t = starting_equity + Σ realized_pnl(≤t) + Σ funding(≤t) + unrealized_mtm(position_t, price_t)`
  where `position_t` is the running net position from cumulative fills and `price_t` from OHLCV. (If Hydromancer daily account snapshots are available, use them directly as ground truth and reconcile.)
- Output `returns.parquet`: address × date → daily return.
- **Sample-length gate:** drop any address with < configurable threshold (default 9 months; range 6–12) of active history. This gate runs here so all downstream stages see only sufficiently-sampled traders.

### 4. `metrics/` — risk-adjusted + persistence
- Sharpe, Sortino, max drawdown, Calmar, win-rate and **win-rate stability** (variance of rolling win rate), active-days, turnover.
- **Deflated Sharpe Ratio (DSR):** correct for selection over ~300 candidates (multiple-testing). A trader must clear DSR, not raw Sharpe — this is what stops the backtest from fooling itself.
- Output `metrics.parquet`.

### 5. `factors/` — alpha vs beta decomposition
- For each survivor, OLS (Newey-West HAC SEs) of trader returns on BTC & ETH returns: `r_i = α + β_btc·r_btc + β_eth·r_eth + ε`.
- Keep the residual series and α with significance. **Drop pure-beta traders** (α not significantly > 0, or α≈0 with high R²). Ranking score is built on risk-adjusted **α / residual**, not total return.
- Output `factors.parquet` (α, βs, t-stats, residual series).

### 6. `select/` — top-N selection
- Combine risk-adjusted-α score + persistence (DSR, win-rate stability, sample length) into a single rank. Pick top-N (default 30).
- Output `selection.parquet`.

### 7. `weights/` — covariance-aware weighting
- Σ from survivors' return (or residual) series → **Ledoit-Wolf shrinkage**.
- **HRP** (hierarchical risk parity) as primary weight method — auto-penalizes correlated clusters. Provide **risk-parity** and **fractional-Kelly (on shrunk Σ)** as comparators in the report.
- Output `weights.parquet` (method × address → weight).

### 8. `backtest/` — walk-forward OOS (the go/no-go)
- Walk-forward: for each rebalance time T in a grid, run stages 3→7 **using only data with timestamp ≤ T** (strict, enforced by an as-of clock — see §Point-in-time), producing a selected set + weights. Hold over (T, T+h], record the selected portfolio's realized OOS return. Roll T forward; concatenate OOS segments.
- Compare OOS performance of: **HRP-selected**, **equal-weight-selected**, and benchmarks (**BTC buy-hold**, leaderboard-average). Significance test (t-stat / bootstrap) on OOS mean return > 0 and > benchmark.
- **Verdict logic:** GO iff selected-portfolio OOS mean return is significantly > 0 **and** > BTC, with acceptable OOS drawdown; else NO-GO. Report the realized OOS Sharpe as the honest live expectation.

### 9. `report/` — artifact + verdict
- Markdown/HTML report: ranked table, α/β table, weights per method, OOS equity curves, the verdict and the numbers behind it. Written to `reports/`.

## Point-in-time correctness (the OOS lifeline)
- A single **as-of clock** is threaded through stages 3→7 during backtest. Any data read with timestamp > as-of is invisible — enforced structurally at the `ingest` cache layer (an as-of filter), not by remembering to slice in each stage.
- Universe at T is reconstructed from archived leaderboard/activity as-of T, **not** today's leaderboard (today's leaderboard already embeds survivorship — the #1 way this backtest could lie to itself).
- A dedicated test feeds future data and asserts selection output is byte-identical to running without it.

## Data model
- Addresses: 42-char hex, validated at the boundary (semantic error if malformed → no retry).
- All intermediate artifacts are parquet under `data/cache/` (raw) and `data/derived/` (per-stage outputs), keyed by as-of where relevant.
- Config via pydantic settings + `.env` (thresholds: universe size, sample-length months, N, rebalance horizon, DSR cutoff, Kelly fraction).

## Testing strategy (TDD)
- **Synthetic ground-truth tests:** generate a trader with known α/β → assert §5 recovers them within CI; generate a correlated return block → assert §7 HRP down-weights the cluster vs equal-weight; generate a known equity path from synthetic fills → assert §3 reconstructs it.
- **No-lookahead test:** §Point-in-time test above.
- **No-network guarantee:** autouse fixture mutes the real `io/source` client; a present real `.env` must not cause real S3/API calls (CLAUDE.md #4).
- **Compared-values test:** equity reconstruction asserts current vs peak equity come from the same series/units (CLAUDE.md #1 — drawdown must not mix sources).

## Tech stack
- Python 3.11+ (hl-copytrader is 3.9; new repo targets 3.11 for typing). pandas, numpy, scipy, scikit-learn (LedoitWolf), statsmodels (OLS+HAC), pyarrow, boto3 (requester-pays S3), pydantic, matplotlib, pytest. Package + CLI (`hl-vault select`, `hl-vault backtest`, `hl-vault report`).

## Open risks (tracked, not blocking)
- S3 archive volume/cost (requester-pays) for 300 addresses × deep history — mitigate by caching aggressively and starting the universe smaller if needed.
- If deep history is thin for many addresses, the sample-length gate shrinks N — report honestly rather than lowering the bar.
- DSR/selection-bias correction may kill most candidates — that is a feature (it means the naive thesis was weak), surfaced in the verdict.

## Deliverable / definition of done (A)
A single command reproduces: ranked selection + weights + an OOS report ending in an explicit **GO** or **NO-GO** verdict with the supporting OOS statistics. Sub-project B is gated on GO.
