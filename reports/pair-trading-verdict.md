# F2 — Pair-Trading (Cointegration) Research Verdict

**Date:** 2026-07-03 · **Script:** `scripts/research_pair_trading.py` · **Verdict: NO-GO**

## Method

Walk-forward Engle-Granger pair trading on Hyperliquid 1h perp closes, 17 coins / 136 pairs, 2025-12-06 → 2026-07-02 (~208d, the max HL keeps at 1h). For each 30d test block, pairs are selected **on the trailing train window only** (W ∈ {60d, 90d}): `statsmodels.coint` on log prices with p < 0.05, hedge ratio β by OLS, spread = logP_a − β·logP_b, z-scored with **frozen train mean/std** — no test-window statistic is used anywhere. In the test block: enter at |z| > z_entry (long cheap / short rich, $100 per leg, equal notional), exit |z| < 0.5, hard stop |z| > 4 or 7 days; max 5 concurrent pairs on a $1,000 book; fees 0.045% taker per leg per side (≈0.18% of one leg's notional per round trip); funding approximated as zero-mean. Sharpe is computed on the hourly account PnL series and annualized via √(24·365).

## Results (6 pre-declared configs, all OOS)

| W (train) | z_entry | OOS return | Sharpe (ann.) | MaxDD | trades | win rate | distinct pairs selected | distinct pairs traded |
|---|---|---|---|---|---|---|---|---|
| 60d | 1.5 | -4.00% | -0.72 | 9.05% | 197 | 43.7% | 75 | 52 |
| 60d | 2.0 | -4.28% | -0.76 | 9.62% | 196 | 39.8% | 75 | 52 |
| 60d | 2.5 | -7.68% | -1.40 | 11.14% | 232 | 31.9% | 75 | 55 |
| 90d | 1.5 | -8.50% | -1.86 | 12.15% | 152 | 39.5% | 94 | 56 |
| 90d | 2.0 | -12.60% | -2.59 | 14.87% | 147 | 38.8% | 94 | 59 |
| 90d | 2.5 | -17.73% | -3.73 | 19.80% | 176 | 29.5% | 94 | 61 |

Walk-forward blocks: 5 for W=60d (OOS 2026-02-04 → 07-02, last block 28d), 4 for W=90d (OOS 2026-03-06 → 07-02). Per-block selection counts were wildly unstable (W=60d: 3, 25, 56, 20, 3 pairs), i.e. "cointegration" here is largely regime-local.

## Final selection window (test 2026-06-04 → 2026-07-02)

| W | Pair | EG p-value | β (OLS, train) |
|---|---|---|---|
| 60d | SOL/AVAX | 0.0012 | 1.158 |
| 60d | BNB/PENDLE | 0.0338 | 0.109 |
| 60d | BNB/TON | 0.0395 | 0.117 |
| 90d | BNB/PENDLE | 0.0248 | 0.111 |
| 90d | AVAX/UNI | 0.0267 | 0.369 |
| 90d | BNB/SUI | 0.0434 | 0.247 |
| 90d | LINK/SUI | 0.0476 | 0.524 |
| 90d | SUI/CRV | 0.0491 | 1.110 |

## Pre-declared gate (ALL must hold for GO)

| Leg | Requirement | Actual | Result |
|---|---|---|---|
| 1 | Walk-forward OOS Sharpe > 1.0 at the median config | median Sharpe = **−1.63** | **FAIL** |
| 2 | Aggregate MDD ≤ 15% (worst of 6 configs) | **19.80%** (90d/2.5); median config ≈ 11–12% | **FAIL** |
| 3 | ≥ 3 distinct pairs qualify in the final selection window | 3 (W=60d), 5 (W=90d) | PASS |
| 4 | Return sign positive across all 6 configs | **0/6 positive** | **FAIL** |

## **VERDICT: NO-GO**

Three of four gate legs fail; per the pre-declared protocol no parameter tuning beyond the 6 configs was attempted. The failure is not a fee artifact alone: round-trip fees ≈ $0.18/trade cost ~2.6–4.2% of the book per config, so the best config (60d/1.5) is roughly breakeven **gross** of fees, and the 90d configs lose 5–15% even before fees. Train-window cointegration simply did not persist out-of-sample in this period — at the 60d/2.0 config, 60% of exits (117/196) were the |z| > 4 hard stop and only 18% (35/196) the |z| < 0.5 reversion target; spreads diverged rather than reverted. Losses deepen with wider entry thresholds and longer train windows, the opposite of what a real mean-reversion edge would show.

## Caveats (honest limitations — none would flip the verdict favorably)

- **Single regime:** ~208 days (Dec 2025 – Jul 2026) is all HL keeps at 1h; only 5 (W=60d) / 4 (W=90d) walk-forward blocks. The negative result is regime-specific evidence, not a universal refutation — but it is the only regime we could trade next.
- **Funding ignored** (assumed zero-mean). Both-legs perp positions pay/receive funding; net effect on a dollar-neutral book is plausibly small but not modeled.
- **Fill assumption:** IoC fills at the hourly close that produced the signal, no slippage. Real fills would be worse, making these results an upper bound.
- **TON history ends 2026-06-15** (data stops mid-period); open TON trades are force-closed at its last bar, and coverage checks drop TON pairs from later train windows.
- Positions are force-closed at each 30d block boundary (train stats expire) — adds some fee drag but also caps stale-parameter risk.
- Implementation details declared in the script header: entries require z_entry < |z| ≤ 4; β ≤ 0 pairs excluded (7 pair-blocks at W=60d, 11 at W=90d); >5 signals prioritized by lowest train p-value.

## Self-review evidence

- **Leakage test:** scrambling *all* price data at/after `test_start` with random noise leaves pair selection and every frozen parameter (p, β, μ, σ) bit-identical — selection/β/z-stats provably use train data only.
- **Accounting identity:** Σ(closed-trade nets) == Σ(hourly PnL) to 5e-14 (all positions force-closed, nothing dangling).
- **Fee math:** entry fee $0.0900 (2 legs × $100 × 0.045%), exit on executed notional ≈ $0.09 → ≈ $0.18 ≈ 0.18% of one leg per round trip, as specified.

*Full run log reproducible via `.venv/bin/python scripts/research_pair_trading.py` (~52s).*
