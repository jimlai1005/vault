# Trend-Filtered Grid — NO-GO (2026-07-03)

**Hypothesis** (declared before running, derived from two independent
observations — momentum's longs were profitable while shorts lost, and the
plain grid only made money on the uptrending coin): run the grid per coin
only while price > its N-day SMA (point-in-time), flatten and stand aside
below it.

**Pre-declared pass gate:** filtered aggregate PnL positive on BOTH bar
configs (1h/208d and 4h/730d) AND ≥60% of the 14 candidate coins
non-negative AND aggregate MDD ≤ 20% of $1,000 AND sign robust across
filter lengths {90,120,150}d.

## Result: fails every leg of the gate

| config | unfiltered | f90 | f120 | f150 | non-neg (f120) | MDD (f120) |
|---|---:|---:|---:|---:|---:|---:|
| 1h / 208d | −$1,645 | −$514 | −$425 | −$290 | 7% | 65% |
| 4h / 730d | −$3,149 | −$1,043 | −$1,087 | −$1,249 | 14% | 266% |

The filter cuts the bleed substantially but never flips the candidates
positive; under the strictest filter many coins simply never qualify
(PnL = 0 → the filter's real message is "don't grid these alts at all").
HYPE stays strongly positive under every variant (+$134…+$560 on a $333
budget) and BTC is mildly positive on the long window — i.e. the grid's
edge remains coin/regime-specific, not a universal harvest.

**Verdict: NO-GO.** Per the pre-declared plan, no parameter tuning follows;
the fallback hypothesis (delta-neutral funding carry) proceeds instead —
see `docs/superpowers/specs/2026-07-03-funding-carry-design.md`.

Script: `scripts/research_trend_filtered_grid.py` (cached candles under
`data/cache/candles_multi/`).
