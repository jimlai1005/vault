# Strategy Direction Decision — 2026-07-03

**Context:** momentum (sub-project C) came back NO-GO. Owner directive: keep
finding directions until the wallet grows fast with controlled MDD; Claude
decides, owner observes.

## Evidence gathered (all real data, scripts in `scripts/`)

### 1. Momentum failure diagnosis (`diagnose_momentum.py`)

| Side | PnL on $10k |
|---|---:|
| Long trades | **+$1,710** |
| Short trades | **−$3,155** |
| Fees | −$980 |

Shorts are the entire loss. SOL shorts lost $1,585 *even though SOL fell 48%*
(bear-market rallies squeeze), and the model kept trying to short HYPE during
its +416% run. Consistent with known crypto behavior: daily-bar trend shorts
get destroyed by violent counter-rallies. Lesson taken: **directional
strategies on daily bars are fragile here** — pivot to structural,
non-directional income. (Not flipping to long-only and re-testing the same
sample — that's the selection bias our own NO-GO discipline exists to stop.)

### 2. Funding-carry scan (`research_funding_carry.py`, 12mo hourly, 25 coins)

- Persistent positive funding exists: LINK (+11.5%/yr, 96% of hours positive),
  HYPE (+12.1%, 92%), AAVE (+10.7%, 92%), UNI (+10.5%, 90%), PENDLE (+10.6%, 90%).
- Naive top-3 trailing-funding rotation: **−0.3%/yr after fees** (turnover
  eats it). The carry is real but slow (~8–10%/yr unlevered) — a future
  low-vol ballast, not a rapid-growth engine. Parked, documented, not built.

### 3. Gridbot live validation

- Our instance: **+1.6% in ~2 days** ($1,000 → $1,016.01), no halts.
- The mechanic's originator (target wallet): ~$585k realized over ~10 months
  across ~25 coins (HYPE +$432k, xyz:CL +$70k, ZEC +$66k, BTC +$44k, …).

## Decision

**Deploy the idle momentum wallet ($1,000, currently LIVE_TRADING=false and
never traded) as a second gridbot instance on a non-overlapping,
backtest-selected coin set.** Scaling the only doubly-validated engine
(our live run + the target's long track record) across more markets is the
highest-evidence path to faster growth at the same 20%-MDD risk policy —
better than betting on another unvalidated hypothesis.

Momentum module stays dormant (code kept; verdict stands). Funding carry
stays on the shelf as a documented future option.

See `docs/superpowers/specs/2026-07-03-gridbot-second-instance-design.md`.
