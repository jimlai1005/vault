# Edge Decomposition Analysis: F1 vs F2 Scalp Strategies

**Analysis date:** 2026-07-11

---

## Task 1: F1 Verification Against Report

F1 report claims n=10,858, PF=0.560. Verified against `f1_trades.csv`:

| Metric | Reported | Calculated | Difference |
|--------|----------|------------|-----------|
| Pooled n | 10,858 | 10,858 | ✓ Match |
| Pooled PF (wins/\|losses\|) | 0.560 | 0.560 | ✓ Match (0.06% variance) |
| Avg net_bps | -13.79 | -13.79 | ✓ Match |

**By-coin spot check (ZEC, BTC):**

| Coin | n | PF | Avg (bps) |
|------|---|---|----|
| ZEC | 3,039 | 0.561 | -18.19 |
| BTC | 1,921 | 0.463 | -10.25 |

**Conclusion:** F1 report numbers verified; no discrepancies detected.

---

## Task 2: Gross/Net Edge Decomposition

**Definition:** 
- `m` (gross move PnL) = `net_bps + 9.0` (reverses the taker fee to show pre-cost edge)
- Interpretation zones:
  - `mean(m) ≤ 0`: No signal edge even gross; cost reduction (maker mode, lower frequency) cannot save strategy
  - `0 < mean(m) < 9`: Weak gross edge but loses to taker fee; only viable via maker rebate or structural cost cut
  - `mean(m) ≥ 9`: Strong gross edge ≥ taker cost; if net PF < 1, issue is execution or slippage not covered by entry/exit px

### F1 (Burst Continuation)

**Pooled (all 6 coins):**

| Metric | Value |
|--------|-------|
| n | 10,858 |
| mean(m) | -4.787 bps |
| median(m) | -19.079 bps |
| mean(net_bps) | -13.787 bps |
| PF_m (on gross move) | 0.805 |

**Interpretation:** Signal has **NO edge** even at gross level (mean(m) < 0). Cost reduction is futile; root cause is signal itself.

**By-coin breakdown:**

| Coin | n | mean(m) | median(m) | mean(net_bps) | PF_m | Signal quality |
|------|---|--------|-----------|---------------|------|--------|
| BTC | 1,921 | -1.25 | -9.86 | -10.25 | 0.897 | Weak negative |
| ETH | 2,406 | -2.48 | -17.28 | -11.48 | 0.874 | Weak negative |
| HYPE | 1,115 | -5.30 | -23.50 | -14.30 | 0.789 | Weak negative |
| LIT | 623 | -17.83 | -40.06 | -26.83 | 0.535 | **Strongly negative** |
| SOL | 1,754 | +0.76 | -20.14 | -8.24 | 1.034 | Only coin with positive gross edge |
| ZEC | 3,039 | -9.19 | -27.29 | -18.19 | 0.736 | Weak negative |

**Key finding:** LIT is the worst performer (mean(m)=-17.83 bps, no positive gross edge). SOL is the sole coin with slight positive gross edge (+0.76 bps) but still underwater net (-8.24 bps).

---

### F2 (Overextension Reversion)

**Pooled (all coins):**

| Metric | Value |
|--------|-------|
| n | 1,894 |
| mean(m) | +0.876 bps |
| median(m) | -17.459 bps |
| mean(net_bps) | -8.124 bps |
| PF_m (on gross move) | 1.031 |

**Interpretation:** Signal has **weak positive gross edge** (+0.876 bps) but **below taker fee cost (9 bps)**. Strategy is theoretically viable only via maker rebate or frequency reduction to 1-2 trades/day to lower per-trade cost.

**By-coin breakdown:**

| Coin | n | mean(m) | median(m) | mean(net_bps) | PF_m | Signal quality |
|------|---|--------|-----------|---------------|------|---------|
| BTC | 342 | -2.72 | -14.37 | -11.72 | 0.828 | Negative |
| ETH | 408 | -0.30 | -20.91 | -9.30 | 0.987 | Marginally negative |
| HYPE | 231 | +1.22 | -12.55 | -7.78 | 1.041 | Weak positive |
| LIT | 83 | -0.04 | -38.96 | -9.04 | 0.999 | Flat |
| SOL | 416 | -2.50 | -20.92 | -11.50 | 0.917 | Negative |
| **ZEC** | **414** | **+8.38** | **+5.34** | **-0.62** | **1.227** | **Strong positive edge** |

**Key finding:** ZEC short side is the standout performer (mean(m)=+8.38 bps, PF_m=1.227). Other coins and sides show minimal or negative gross edge.

---

## Task 3: F1 MDD Recalculation

Original report shows **MDD: 14965.6%** in the G1 Gate Checklist — this is clearly erroneous (mixes bps scale with percent, or calculation error).

**Recalculation from f1_trades.csv:**

- Capital base: $6,000 (6 coins × $1,000 max concurrent per coin)
- Equity curve: `cumsum(net_bps / 1e4 * 1000)` sorted by exit timestamp
- Max equity reached: -$1.03 (indicating overall cumulative loss)
- **Max drawdown: $14,968.62**
- **MDD%: (14968.62 / 6000) × 100 = 249.48%**

**Gate status:** MDD ≤ 15% requirement: **FAIL** (249.48% >> 15%)

---

## Task 4: Exploratory Slicing (n ≥ 100 per coin-side group)

### F1 By Coin × Side (n ≥ 100)

| Coin | Side | n | mean(net_bps) | mean(m) | PF | Profitable? |
|------|------|---|-------|--------|-----|--------|
| ZEC | Long | 1,597 | -14.04 | -5.04 | 0.652 | ✗ |
| ZEC | Short | 1,442 | -22.78 | -13.78 | 0.464 | ✗ |
| ETH | Long | 1,236 | -10.82 | -1.82 | 0.566 | ✗ |
| ETH | Short | 1,170 | -12.18 | -3.18 | 0.569 | ✗ |
| BTC | Long | 967 | -9.43 | -0.43 | 0.492 | ✗ |
| BTC | Short | 954 | -11.08 | -2.08 | 0.436 | ✗ |
| SOL | Short | 884 | -9.27 | -0.27 | 0.693 | ✗ |
| SOL | Long | 870 | -7.20 | +1.80 | 0.736 | ✗ |
| HYPE | Short | 608 | -13.93 | -4.93 | 0.572 | ✗ |
| HYPE | Long | 507 | -14.74 | -5.74 | 0.521 | ✗ |
| LIT | Short | 319 | -26.32 | -17.32 | 0.420 | ✗ |
| LIT | Long | 304 | -27.37 | -18.37 | 0.398 | ✗ |

**Finding:** **No coin-side group with PF > 1.0.** All combinations are unprofitable.

### F2 By Coin × Side (n ≥ 100)

| Coin | Side | n | mean(net_bps) | mean(m) | PF | Profitable? |
|------|------|---|-------|---------|------|--------|
| SOL | Long | 240 | -6.46 | +2.54 | 0.821 | ✗ |
| ZEC | Short | 213 | -14.22 | -5.22 | 0.697 | ✗ |
| ETH | Long | 212 | -7.07 | +1.93 | 0.754 | ✗ |
| **ZEC** | **Long** | **201** | **+13.80** | **+22.80** | **1.386** | **✓ YES** |
| ETH | Short | 196 | -11.70 | -2.70 | 0.594 | ✗ |
| SOL | Short | 176 | -18.38 | -9.38 | 0.473 | ✗ |
| BTC | Short | 171 | -15.46 | -6.46 | 0.295 | ✗ |
| BTC | Long | 171 | -7.97 | +1.03 | 0.629 | ✗ |
| **HYPE** | **Short** | **116** | **+3.69** | **+12.69** | **1.136** | **✓ YES** |
| HYPE | Long | 115 | -19.35 | -10.35 | 0.531 | ✗ |

**Findings:**
- **ZEC long (n=201):** PF=1.386, mean(net_bps)=+13.80 bps, mean(m)=+22.80 bps — **strong profitable edge**, 110 target exits
- **HYPE short (n=116):** PF=1.136, mean(net_bps)=+3.69 bps, mean(m)=+12.69 bps — **marginally profitable**, 62 target exits
- All other groups: unprofitable

**F2 Target Exit Breakdown:**

Among F2's 1,894 total trades:
- 816 trades exited at target (mean(m)=+65.08 bps, mean(net_bps)=+56.08 bps)
- Remaining 1,078 trades exited at stop/time (net negative on average)

→ F2's edge is **entirely driven by successful target hits**, particularly in ZEC long and HYPE short. Stop losses are overly frequent or poorly calibrated.

---

## Synthesis

| Aspect | F1 (Burst) | F2 (Reversion) |
|--------|----------|-------|
| **Gross edge (mean m)** | -4.79 bps | +0.88 bps |
| **Feasibility** | Structural failure (no edge) | Weak edge, needs cost reduction |
| **Best coin** | SOL (+0.76 m) | ZEC long (+22.80 m, PF=1.39) |
| **Worst coin** | LIT (-17.83 m) | BTC short (-6.46 m, PF=0.30) |
| **Winning slices (PF>1)** | None | ZEC long, HYPE short |
| **Root issue** | Signal picks wrong direction consistently | Reversion overshoots on both sides; targets work, stops don't |

**Verdict:** F1 is fundamentally broken at the signal level. F2 has a weak but real edge in specific coin-side combinations (ZEC long, HYPE short) but is drowned by too-frequent stops in other combos. Both fail pooled gates, but F2's failure is structural cost (too many stops) vs. F1's failure being fundamental signal weakness.
