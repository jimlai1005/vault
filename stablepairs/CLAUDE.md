# CLAUDE.md — Stablecoin Pairs Regime Calibration

> Build note / handoff. Claude Code auto-loads this file. 讀完你就知道我們做到哪、為什麼這樣設計、下一步要幹嘛。Work surgically, keep module boundaries, don't over-engineer.

## 0. TL;DR — where we are
Offline calibration layer for a **regime-hardened stablecoin pairs strategy**. Python
calibrates a 2-state Markov-switching OU on the spread and emits thresholds; a separate
Pine strategy (`Stay Cool C — Regime-Hardened`) executes live.
- ✅ Package scaffolded, `tests/test_synthetic.py` passes offline (no network).
- ✅ HMM recovers 2 regimes; `run.py` emits suggested Pine inputs.
- ⏳ NOT yet run on live exchange data — **that is your first job**.

## 1. Why this exists (theory recap)
**Pairs trading** — trade the spread of two cointegrated legs, long cheap / short rich,
bet on convergence. `spread s = log P1 - beta * log P2`.

**Mean reversion (OU / Vasicek)** — `ds = kappa*(theta - s)*dt + sigma*dW`.
`kappa` = reversion speed, half-life = `ln2/kappa`. Naive rule = fixed z-score bands;
assumes the relationship is stationary forever.

**Regime switching (the fix)** — reality: the spread flips between a REVERT state
(stationary, high kappa) and a DIVERGE state (cointegration broken, random-walk /
momentum drift). A hidden 2-state Markov chain governs which OU params are active:
`ds = kappa(a_t)*(theta(a_t) - s)*dt + sigma(a_t)*dW`, state `a_t` unobserved → filter it.
Pair trades blow up when they keep betting reversion in the DIVERGE state. The original
`Stay Cool C` did exactly this: a fake limit-order "stop" that never fills, and zero
regime awareness.

**Two modes** — REVERT = bet it comes back; DIVERGE = it trends / doesn't (momentum in
spread space). Which is active is a regime question, *detected not assumed*.

## 2. Architecture — estimation / execution split
- **Python (this repo)** = heavy offline estimation. Fits MS-AR(1) (Hamilton filter via
  `statsmodels`), extracts per-regime kappa / half-life / sigma + transition matrix, and
  derives calibrated thresholds (`kappaMin`, `maxHold`, ...).
- **Pine (separate file)** = live execution. Can't run a Hamilton filter, so it
  approximates the hidden state with OBSERVABLES: rolling AR(1) kappa, return-correlation
  breakdown, spread-vol ratio, plus a hard **depeg circuit breaker**.
- Loop: `run.py` → prints `kappaMin` etc. → paste into the Pine strategy inputs.

## 3. File map
| file | role |
|---|---|
| `config.py` | all tunables (exchange, stablecoin universe, tf, fees, thresholds) |
| `data.py` | ccxt OHLCV fetch + parquet cache — needs internet |
| `discovery.py` | find LIVE stablecoin pairs, rank by Engle-Granger cointegration |
| `spread.py` | frozen-beta OLS spread, z-score, AR(1) half-life |
| `regime_hmm.py` | 2-state MS-AR(1) → per-regime OU params + `suggest_pine_inputs()` |
| `backtest.py` | honest backtest: regime gate, real stop, fees, depeg breaker, time stop |
| `run.py` | orchestrator: discover → calibrate → backtest → print Pine inputs |
| `tests/test_synthetic.py` | offline end-to-end validation (no network) |

## 4. How to run (M1 Pro, native arm64, pure-python wheels)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python tests/test_synthetic.py     # validate offline FIRST
python run.py                      # live: discover → calibrate → backtest → inputs
```

## 5. Validated (synthetic)
MS-AR recovered the two regimes cleanly:
```
regime [REVERT ] phi=0.929  kappa=0.071  half-life=9.5 bars   sigma≈1x
regime [DIVERGE] phi=0.991  kappa=0.009  half-life=73  bars   sigma≈2.7x
→ suggested Pine inputs: kappaMin=0.04, maxHold=28, entryZ=1.0, stopZ=3.0
```

## 6. Next steps (in order)
1. Run `tests/test_synthetic.py` — confirm it still passes in this env.
2. **Set `config.fee_bps` to the real taker fee FIRST**, then `python run.py`.
   - Expect discovery to DROP XUSD (it was Binance.US only, a different exchange) and pick
     something like FDUSD/USDT, USDC/USDT, DAI/USDT.
3. Read the backtest: is return **positive net of fees**? bp-scale edge means fees usually
   decide. If it's negative, the pair has no edge — **say so, don't torture the params**.
4. Paste emitted `kappaMin` / `maxHold` into the Pine strategy inputs.
5. Walk-forward OOS + Deflated Sharpe before any capital (Go-No-Go discipline).

## 7. Gotchas / constraints
- MS-AR needs a genuinely stationary spread. If two "stablecoins" aren't cointegrated, the
  fit falls back to a rolling AR(1) proxy and the pair is weak — **that's signal, not a bug**.
- Don't hardcode a pair. `discovery.py` exists precisely because Binance delists thin
  stablecoin pairs regularly. Swap venue (binance/okx/bybit/hyperliquid) in `config.exchange`.
- Data source reality: XUSD = Binance.US (`Binanceus:`), US-only, not the same as
  binance.com. Use ccxt against the global venue.
- Evaluate NET of fees + slippage, always.

## 8. Definition of done (this phase)
A live backtest on a discovered pair, net of real fees, regime ON vs OFF compared, and a
set of Pine inputs written back — ending in an honest **GO / NO-GO** verdict.

---

## 9. Vault 收編註記（sub-project I，2026-07-11）

本目錄是 vault 的自包含子專案（前例：`compound/`）。原始碼源自 owner 的
pair-trading Pine（`pine_original_stay_cool_c.txt`）＋regime-switch 討論版。
Desktop 原檔未動；本目錄為工作副本。研究紀律沿用 vault：預先註冊 gate、
walk-forward、fresh-context 驗證、verdict 落 `stablepairs/reports/`。

**與既有 verdict 的關係**：vault 的 pair-trading NO-GO（1h、crypto 對）死因是
cointegration 樣本外發散；穩定幣對的 mean 是結構性錨（雙腿掛鉤 $1），機制上
排除「mean 被帶偏」，殘餘尾部風險 = depeg（regime 閘門＋斷路器的職責）。
sub-project H（scalping NO-GO）的成本教訓直接適用：bp 級 edge，費率決定生死。

### 預先註冊 Gates（2026-07-11 寫定，先於任何實盤數據）

- **G0 成本可行性（blocking）**：真實費率查證後，`median(|z 從 entry 到 exit 的
  spread 移動| in bps) ≥ 3 × 來回成本`；標的 24h 量 ≥ config 下限。過不了 → 換
  venue/pair 或 NO-GO，不准調小 entry_z 硬湊。
- **G1 回測（train_frac=0.6 凍結，只看後 40% OOS）**：OOS 淨報酬 > 0 且
  年化 Sharpe ≥ 1.5 且 MDD ≤ 5% 且 trades ≥ 30 且 regime ON 的 (報酬, MDD) 不劣於
  OFF 且 費率 ×1.5 仍淨正。六條全過才有 GO。
- **G2（GO 之後）**：paper/前向 ≥ 2 週再談真錢；斷路器與 regime 閘門的實時行為
  要先在 paper 驗證。depeg 尾部（如 USDC 2023-03）不在 120d 回測窗內——GO 也只是
  conditional GO，倉位上限由 owner 裁定。

### 看實盤數據前必修的誠實缺陷（2026-07-11 code review）

1. `backtest.py` 同 bar 收盤成交：訊號在 bar i 收盤算出、`entry_px = px[i]` 也是
   同一收盤價——改為**下根 bar 開盤成交**（半步前視，我們的紀律不允許）。
2. `discovery.py` 用 coint p-value 排序：兩個真穩定幣的 log 價都平穩，EG 檢定
   近乎退化、p 值普遍極小——排序意義有限。保留但補充**成本導向指標**：
   spread z-band 振幅（bps）／來回成本 比值（G0 的量化基礎）。
3. `config.qty_pct=30` 存在但 `backtest.py` 實際用 100% equity——擇一，不許帳面
   與實作不一致（工程原則 #1 同源比較的精神）。
4. 費率 7.5bps/side 是佔位——真實費率（含 venue 促銷、maker/taker 差）先查證
   後寫入，並在 verdict 標註查證日期與來源。
