# Carry Engine Go-Live — 2026-07-03

**Position entered 15:52 local:** long 8.9038 HYPE spot ($599.57) + short
$599.99 HYPE perp @ 1.91x. Delta -$0.42 (0.07% of target — inside the 2%
band). Entry cost ~$1.12 (fees + IoC slippage, one-time). Trailing 7d
funding APR at entry: **+10.4%**.

**Wallet:** ex-momentum wallet, $1,000 split $685 spot / $315 perp margin
(manual transfer by owner — agent keys cannot usdClassTransfer; the engine
was redesigned transfer-free the same day, commit 3332bf3).

**Gates passed before LIVE_TRADING=true:** 147/147 tests incl. the
liquidation-defense simulation (2x pump, paired unwind, perp equity never
below 3.4x maintenance); two consecutive sane dry-run cycles against the
real wallet; status readout verified.

**Running:** local `hl-carry` process, 5-min cycles, logs to `logs/carry.log`,
Telegram alerts wired (go-live message delivered). Circuit breaker 20% MDD.

**Portfolio now:**
| engine | wallet | position | expectation |
|---|---|---|---|
| gridbot (inst 1) | 0xfB9C...9760 | HYPE/BTC/ETH grid, $1,016 | fast leg, ~+0.8%/day observed (2d) |
| carry | 0xbAC6...3662 | delta-neutral HYPE, $999 | steady leg, ~7-10%/yr, hedges gridbot's long bias |

Next checkpoints: 24h carry health (delta/funding/no false halts),
2026-07-15 gridbot 14-day per-coin PnL review.
