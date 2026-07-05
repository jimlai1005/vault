# Bitfinex fUSD (USD margin funding) historical data

Fetched 2026-07-04/05 UTC by `../scripts/fetch_history.py` (stdlib-only, Python 3.9).
Re-run with `/usr/bin/python3 scripts/fetch_history.py [--only candles|snapshots|stats]`
from the repo root. Every file is written atomically (`.tmp` + `os.replace`), so a
re-run or interrupted run never corrupts existing files.

All timestamps are **UTC**, `timestamp_ms` = millisecond epoch, `date_iso` = UTC ISO 8601.
API base: `https://api-pub.bitfinex.com/v2/`. All endpoints are public (no auth).

## Rate units — read this before backtesting

**Candle OHLC, book RATE, ticker FRR/BID/ASK/LAST_PRICE are simple per-day interest
rates in decimal form.** Example: `0.00037` = 0.037%/day. Bitfinex UI annualizes as
simple APR = `rate x 365` (0.00037 -> ~13.5% APR). Daily-compounded APY would be
`(1+rate)^365 - 1`.

**Exception — `funding_stats.csv` raw `frr` column is 1/365th of the daily rate.**
The official docs (https://docs.bitfinex.com/reference/rest-public-funding-stats)
define it verbatim as:

> "1/365th of Flash Return Rate (To get the daily rate, use: rate x 365. To get the
> daily rate as percentage use: rate x 365 x 100. To get APR as percentage use
> rate x 100 x 365 x 365.)"

To remove this trap, the CSV also carries a derived **`frr_daily` = `frr` x 365**
(same unit as every other file: per-day decimal rate).

Evidence the units are right (cross-checked at fetch time, 2026-07-04T16:02Z):

| source | raw value | as per-day rate | as APR |
|---|---|---|---|
| ticker `FRR` | 0.00037200548 | 0.00037200548 | 13.58% |
| funding stats latest `frr` | 1.02e-06 | x365 = 0.0003723 | 13.59% |
| 1D p2 latest candle close | 0.00013851 | 0.00013851 | 5.06% (spot dip vs 1h-avg FRR) |

Ticker FRR (an average of fixed-rate funding over the last hour) and stats FRR x 365
agree to 4 significant digits — two independent endpoints, one unit story. Candle
close is the same unit (it is the last traded rate; it sits below the hourly-average
FRR at fetch time, which is normal intraday dispersion, not a unit mismatch).

## Files

### candles_1D_p2.csv — daily candles, 2-day-period funding trades
- Key `trade:1D:fUSD:p2` (funding candles require a period suffix; p2 = only trades
  with a 2-day period, the most liquid fUSD tenor).
- Columns: `timestamp_ms, date_iso, open, close, high, low, volume`. OHLC = per-day
  rate (see above); `volume` = USD amount traded in the interval.
- Coverage: **2016-07-31 .. 2026-07-04, 3617 rows** (API has no fUSD candles before
  2016-07-31). Spec required 2021-01-01→now; fetched from 2016 because it cost zero
  extra requests and adds two more regimes to the backtest.
- Gaps: exactly one — **2016-08-02 -> 2016-08-12 (9 missing days)** = the August 2016
  Bitfinex hack downtime. **Zero missing days from 2016-08-12 through 2026-07-04.**
- Note: the last row is the current, still-forming day.

### candles_1D_p30.csv — daily candles, 30-day-period funding trades
- Key `trade:1D:fUSD:p30`. Same columns/units.
- Coverage: **2016-07-31 .. 2026-07-04, 3614 rows**.
- Gaps: the same 2016 hack gap, plus three single missing days with no p30 trades:
  2022-10-27, 2025-02-16, 2026-03-25.

### candles_1h_p2.csv — hourly candles, 2-day-period funding trades
- Key `trade:1h:fUSD:p2`. Same columns/units.
- Coverage: **2021-01-01T00:00Z .. 2026-07-04T15:00Z, 48,234 rows** (spec minimum was
  18 months; full 2021→now fetched). Hours with zero p2 trades have no row
  (48,234 of ~48,400 hours ≈ 99.7% present; treat missing hours as "no trades",
  carry-forward the last rate if a strategy needs a continuous series).

### ticker_snapshot.json — current funding ticker (fUSD)
- Endpoint `/ticker/fUSD`, fetched 2026-07-04T16:02Z. `raw` = 17-element array,
  `named` maps fields per docs: FRR, BID, BID_PERIOD, BID_SIZE, ASK, ASK_PERIOD,
  ASK_SIZE, DAILY_CHANGE, DAILY_CHANGE_PERC, LAST_PRICE, VOLUME, HIGH, LOW,
  2 placeholders, FRR_AMOUNT_AVAILABLE, FIRST_TRADE.
- BID_PERIOD/ASK_PERIOD are in days. FRR_AMOUNT_AVAILABLE = USD available at FRR.

### book_snapshot.json — current funding order book (fUSD, P0, len=100)
- Endpoint `/book/fUSD/P0?len=100`, fetched 2026-07-04T16:02Z. 200 entries of
  `[RATE, PERIOD_DAYS, COUNT, AMOUNT]`.
- Sign convention (funding books): **AMOUNT > 0 = ask (lend offer), AMOUNT < 0 = bid
  (borrow demand)**. RATE is per-day decimal.

### funding_stats.csv — hourly funding statistics, full available history
- Endpoint `/funding/stats/fUSD/hist`, paginated backwards 250 rows/request until
  empty (endpoint ignores `sort=1`; verified empirically).
- Columns: `timestamp_ms, date_iso, frr, frr_daily, avg_period, funding_amount,
  funding_amount_used, funding_below_threshold`.
  - `frr` raw = 1/365th of daily rate (see unit section); `frr_daily` = frr x 365
    (derived at fetch time, per-day decimal).
  - `avg_period` = average period (days) of funding provided.
  - `funding_amount` = total funding provided; `funding_amount_used` = portion used
    in positions (both USD).
  - `funding_below_threshold` = sum of open funding offers with rates < 0.75% APR
    (docs verbatim: "Sum of open funding offers < 0.75%").
- Records are ~hourly (spacing ~3,600,000 ms, with small drift).
- Coverage: (filled after fetch completes)

## Data quality notes

- Daily-candle continuity was checked with a >3-missing-days threshold; the only
  such segment in either daily file is the 2016 hack gap listed above.
- Funding candles only aggregate *executed trades at that exact period* (p2, p30).
  The aggregate key syntax `trade:1D:fUSD:a30:p2:p30` (periods 2..30 combined,
  AGGR must be 10 or 30) exists but was not needed: p2 alone is near-continuous.
- The last candle row of each file is a partial (still-forming) interval.
- funding_stats history depth is whatever the API serves; see Coverage above.
