# Coinalyze Data Pull Report

**Date:** 2026-07-04T02:35:28.104945
**Requested range:** 2025-08-01T00:00:00 to 2026-07-04T02:34:03.490110
**Interval:** 4 hours

> Note: original Phase 2b plan assumed 2 years of history (from 2024-07-01). Empirically this API key's plan only serves ~335 days of 4h OI/long-short-ratio history — requests before ~2025-08-03 return an empty list (verified against both BTC and HYPE). `DATE_START` was pulled forward to 2025-08-01; actual earliest/latest coverage per dataset is in the summary table below.

## Symbols Used

- BTC: `BTCUSDT_PERP.A`
- DOGE: `DOGEUSDT_PERP.A`
- ETH: `ETHUSDT_PERP.A`
- HYPE: `HYPEUSDT_PERP.A`
- SOL: `SOLUSDT_PERP.A`
- XRP: `XRPUSDT_PERP.A`

## Data Summary

| Coin | OI Dataset | OI Rows | OI Earliest | OI Latest | LSR Dataset | LSR Rows | LSR Earliest | LSR Latest |
|------|-----------|---------|------------|----------|-------------|---------|-------------|------------|
| BTC | oi_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 | lsr_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 |
| ETH | oi_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 | lsr_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 |
| SOL | oi_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 | lsr_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 |
| HYPE | oi_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 | lsr_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 |
| DOGE | oi_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 | lsr_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 |
| XRP | oi_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 | lsr_4h | 2,007 | 2025-08-04T00:00:00 | 2026-07-04T00:00:00 |

## Schema Details

### Open Interest History (OI)

Observed fields: `t` (unix **seconds**, not ms), `o` (open), `h` (high), `l` (low), `c` (close), OI value in base-asset units

**BTC OI Schema:**
```
  t: int64
  o: float64
  h: float64
  l: float64
  c: float64
```

**ETH OI Schema:**
```
  t: int64
  o: float64
  h: float64
  l: float64
  c: float64
```

**SOL OI Schema:**
```
  t: int64
  o: float64
  h: float64
  l: float64
  c: float64
```

**HYPE OI Schema:**
```
  t: int64
  o: float64
  h: float64
  l: float64
  c: float64
```

**DOGE OI Schema:**
```
  t: int64
  o: int64
  h: int64
  l: int64
  c: int64
```

**XRP OI Schema:**
```
  t: int64
  o: float64
  h: float64
  l: float64
  c: float64
```

### Long/Short Ratio History (LSR)

Observed fields: `t` (unix **seconds**, not ms), `r` (long/short ratio), `l` (long %), `s` (short %)

**BTC LSR Schema:**
```
  t: int64
  r: float64
  l: float64
  s: float64
```

**ETH LSR Schema:**
```
  t: int64
  r: float64
  l: float64
  s: float64
```

**SOL LSR Schema:**
```
  t: int64
  r: float64
  l: float64
  s: float64
```

**HYPE LSR Schema:**
```
  t: int64
  r: float64
  l: float64
  s: float64
```

**DOGE LSR Schema:**
```
  t: int64
  r: float64
  l: float64
  s: float64
```

**XRP LSR Schema:**
```
  t: int64
  r: float64
  l: float64
  s: float64
```

## Output Files

- `data/cache/coinalyze/BTC_oi_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/BTC_lsr_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/ETH_oi_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/ETH_lsr_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/SOL_oi_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/SOL_lsr_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/HYPE_oi_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/HYPE_lsr_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/DOGE_oi_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/DOGE_lsr_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/XRP_oi_4h.parquet` (2,007 rows)
- `data/cache/coinalyze/XRP_lsr_4h.parquet` (2,007 rows)
