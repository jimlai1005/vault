#!/usr/bin/env python3
"""Fetch Bitfinex fUSD (USD margin funding) history -> CSV/JSON under data/.

Datasets (all fUSD, public endpoints, no auth):
  candles_1D_p2.csv    daily funding candles, key trade:1D:fUSD:p2   (2016 -> now)
  candles_1D_p30.csv   daily funding candles, key trade:1D:fUSD:p30  (2016 -> now)
  candles_1h_p2.csv    hourly funding candles, key trade:1h:fUSD:p2  (2021-01-01 -> now)
  ticker_snapshot.json current funding ticker
  book_snapshot.json   current funding book (P0, len=100)
  funding_stats.csv    funding stats, full available history (hourly records)

Key syntax verified against https://docs.bitfinex.com/reference/rest-public-candles:
  funding candles need a period ("trade:1D:fUSD:p2") or an aggregated period
  ("trade:1D:fUSD:a30:p2:p30" = trades of periods 2..30 days aggregated, AGGR in [10, 30]).

RATE UNITS (verified 2026-07-05, see data/README.md for full evidence):
  - candle OHLC / book RATE / ticker FRR-BID-ASK-LAST: simple PER-DAY rate, decimal.
    APR shown by Bitfinex UI = rate * 365.
  - funding stats FRR: "1/365th of Flash Return Rate (To get the daily rate, use:
    rate x 365 ...)" per https://docs.bitfinex.com/reference/rest-public-funding-stats.
    The CSV keeps the raw value in `frr` and adds a derived `frr_daily` = frr * 365.

Constraints honored:
  - stdlib only (Python 3.9): urllib.request / json / csv.
  - >= 2.5 s between requests; exponential backoff on 429/5xx/network starting at
    15 s, doubling, max 5 retries. Semantic errors (bad params) fail immediately
    and loudly - retrying them cannot help.
  - candles: limit=10000 max, ascending pagination via sort=1 + start cursor,
    loops until an empty page (never trusts len(batch) < limit as end-of-data).
  - funding stats: limit=250 max; endpoint ignores sort=1 (verified empirically),
    so it pages backwards in time via the `end` cursor until an empty page.
  - re-runnable: every file is written to <name>.tmp then os.replace()'d, so an
    interrupted run never leaves a torn/partial file at the final path.

Usage:
  /usr/bin/python3 scripts/fetch_history.py                 # everything
  /usr/bin/python3 scripts/fetch_history.py --only candles  # candles|snapshots|stats
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://api-pub.bitfinex.com/v2"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, "..", "data"))

SYMBOL = "fUSD"
START_DAILY_MS = 1451606400000  # 2016-01-01T00:00:00Z (API's first fUSD candle is 2016-07-31)
START_1H_MS = 1609459200000     # 2021-01-01T00:00:00Z (spec: at least last 18 months)
CANDLE_LIMIT = 10000            # documented max (rest-public-candles)
STATS_LIMIT = 250               # documented max (rest-public-funding-stats)
MIN_INTERVAL = 2.5              # seconds between any two requests
BACKOFF_START = 15.0            # seconds; doubles per retry
MAX_RETRIES = 5
DAY_MS = 86_400_000
GAP_THRESHOLD_DAYS = 3          # report daily-candle gaps wider than this

CANDLE_HEADER = ["timestamp_ms", "date_iso", "open", "close", "high", "low", "volume"]

# Funding ticker fields per https://docs.bitfinex.com/reference/rest-public-ticker
TICKER_FIELDS = [
    "FRR", "BID", "BID_PERIOD", "BID_SIZE", "ASK", "ASK_PERIOD", "ASK_SIZE",
    "DAILY_CHANGE", "DAILY_CHANGE_PERC", "LAST_PRICE", "VOLUME", "HIGH", "LOW",
    "_PLACEHOLDER_13", "_PLACEHOLDER_14", "FRR_AMOUNT_AVAILABLE", "FIRST_TRADE",
]

# Funding stats fields per https://docs.bitfinex.com/reference/rest-public-funding-stats
# [0]=MTS [3]=FRR [4]=AVG_PERIOD [7]=FUNDING_AMOUNT [8]=FUNDING_AMOUNT_USED
# [11]=FUNDING_BELOW_THRESHOLD ("Sum of open funding offers < 0.75%"), rest placeholders.
STATS_ROW_LEN = 12

_last_request_at = 0.0


def log(msg):
    print("[%s] %s" % (datetime.now(timezone.utc).strftime("%H:%M:%SZ"), msg), flush=True)


def iso(ms):
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SemanticAPIError(RuntimeError):
    """Bad key/params/symbol: the request itself is wrong; retrying cannot help."""


def api_get(path, params=None):
    """Single resilience boundary - every outbound request goes through here.

    All calls are read-only public GETs (idempotent), so transient failures
    (HTTP 429, 5xx, ratelimit error array 11010, network/JSON hiccups) are
    retried with exponential backoff. Semantic failures (other 4xx, explicit
    non-ratelimit API error arrays) raise SemanticAPIError immediately.
    """
    global _last_request_at
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    backoff = BACKOFF_START
    for attempt in range(MAX_RETRIES + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()
        err = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "compound-fetch-history/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except OSError:
                body = b""
            arr = None
            try:
                arr = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                pass
            is_api_ratelimit = (isinstance(arr, list) and len(arr) >= 2
                                and arr[0] == "error" and arr[1] == 11010)
            if e.code == 429 or is_api_ratelimit:
                err = "rate limited: HTTP %d %r" % (e.code, body[:120])
            elif e.code >= 500:
                if isinstance(arr, list) and arr and arr[0] == "error":
                    # 5xx carrying an explicit non-ratelimit API error is semantic
                    # (Bitfinex answers bad params/symbols with 500 + error array).
                    raise SemanticAPIError("%s -> HTTP %d %s" % (url, e.code, arr)) from e
                err = "HTTP %d %r" % (e.code, body[:120])
            else:
                raise SemanticAPIError("%s -> HTTP %d %r" % (url, e.code, body[:200])) from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = repr(e)
        else:
            if isinstance(payload, list) and payload and payload[0] == "error":
                if len(payload) >= 2 and payload[1] == 11010:
                    err = "rate limited: %s" % (payload,)
                else:
                    raise SemanticAPIError("%s -> %s" % (url, payload))
            else:
                return payload
        if attempt == MAX_RETRIES:
            raise RuntimeError("giving up on %s after %d retries; last error: %s"
                               % (url, MAX_RETRIES, err))
        log("  transient failure: %s; retry %d/%d in %.0fs" % (err, attempt + 1, MAX_RETRIES, backoff))
        time.sleep(backoff)
        backoff *= 2


def atomic_write(path, write_fn):
    """Write via tmp + os.replace so reruns/crashes never corrupt existing files."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        write_fn(f)
    os.replace(tmp, path)


def write_csv(path, header, rows):
    def _w(f):
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    atomic_write(path, _w)
    log("wrote %s (%d data rows)" % (path, len(rows)))


# ---------------------------------------------------------------- candles

def probe_candles(key):
    """Small request first: verify the key returns non-empty, well-formed candles."""
    batch = api_get("/candles/%s/hist" % key, {"limit": 3})
    ok = (isinstance(batch, list) and batch
          and all(isinstance(r, list) and len(r) == 6
                  and all(isinstance(x, (int, float)) for x in r) for r in batch))
    if not ok:
        raise RuntimeError("probe for %s returned unexpected payload: %.200s" % (key, batch))
    log("probe OK %s: latest candle %s close=%s" % (key, iso(batch[0][0]), batch[0][2]))


def fetch_candles(key, start_ms, end_ms, max_pages=100):
    """Ascending pagination (sort=1 + start cursor) until an empty page."""
    rows = {}
    cursor = start_ms
    for page in range(1, max_pages + 1):
        batch = api_get("/candles/%s/hist" % key,
                        {"limit": CANDLE_LIMIT, "sort": 1, "start": cursor, "end": end_ms})
        if not batch:
            break
        for r in batch:
            rows[int(r[0])] = r
        log("  %s page %d: %d candles %s .. %s"
            % (key, page, len(batch), iso(batch[0][0]), iso(batch[-1][0])))
        nxt = int(batch[-1][0]) + 1
        if nxt <= cursor:
            raise RuntimeError("%s: pagination cursor stuck at %d" % (key, cursor))
        cursor = nxt
        if cursor > end_ms:
            break
    else:
        raise RuntimeError("%s: exceeded %d pages; aborting instead of silently truncating"
                           % (key, max_pages))
    return [rows[k] for k in sorted(rows)]


def do_candles(end_ms):
    jobs = [
        ("trade:1D:%s:p2" % SYMBOL, START_DAILY_MS, "candles_1D_p2.csv"),
        ("trade:1D:%s:p30" % SYMBOL, START_DAILY_MS, "candles_1D_p30.csv"),
        ("trade:1h:%s:p2" % SYMBOL, START_1H_MS, "candles_1h_p2.csv"),
    ]
    for key, start_ms, fname in jobs:
        probe_candles(key)
        rows = fetch_candles(key, start_ms, end_ms)
        if not rows:
            raise RuntimeError("no candles at all for %s" % key)
        csv_rows = [[int(r[0]), iso(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in rows]
        write_csv(os.path.join(DATA_DIR, fname), CANDLE_HEADER, csv_rows)
        log("%s: %d rows, %s .. %s" % (fname, len(rows), iso(rows[0][0]), iso(rows[-1][0])))


# ---------------------------------------------------------------- snapshots

def do_snapshots():
    now_iso = iso(time.time() * 1000)

    ticker = api_get("/ticker/%s" % SYMBOL)
    if not (isinstance(ticker, list) and len(ticker) >= 16):
        raise RuntimeError("ticker payload unexpected: %.200s" % (ticker,))
    named = dict(zip(TICKER_FIELDS, ticker))
    doc = {
        "fetched_at_utc": now_iso,
        "endpoint": BASE + "/ticker/" + SYMBOL,
        "fields": TICKER_FIELDS[:len(ticker)],
        "named": named,
        "rate_unit_note": ("FRR/BID/ASK/LAST_PRICE are simple per-day rates in decimal; "
                           "APR as shown on bitfinex.com = rate * 365. "
                           "BID_PERIOD/ASK_PERIOD are days."),
        "raw": ticker,
    }
    atomic_write(os.path.join(DATA_DIR, "ticker_snapshot.json"),
                 lambda f: json.dump(doc, f, indent=2))
    frr = ticker[0]
    log("ticker_snapshot.json written: FRR=%.8g per-day -> APR ~ %.2f%%" % (frr, frr * 365 * 100))

    book = api_get("/book/%s/P0" % SYMBOL, {"len": 100})
    if not (isinstance(book, list) and book and isinstance(book[0], list) and len(book[0]) == 4):
        raise RuntimeError("book payload unexpected: %.200s" % (book,))
    doc = {
        "fetched_at_utc": now_iso,
        "endpoint": BASE + "/book/" + SYMBOL + "/P0?len=100",
        "fields_per_entry": ["RATE", "PERIOD_DAYS", "COUNT", "AMOUNT"],
        "sign_convention": ("funding book: AMOUNT > 0 = ask (lend offer), "
                            "AMOUNT < 0 = bid (borrow demand); RATE is per-day decimal"),
        "entries": len(book),
        "raw": book,
    }
    atomic_write(os.path.join(DATA_DIR, "book_snapshot.json"),
                 lambda f: json.dump(doc, f, indent=2))
    log("book_snapshot.json written: %d entries" % len(book))


# ---------------------------------------------------------------- funding stats

def fetch_funding_stats(end_ms, max_pages=2000):
    """Newest-to-oldest pagination via `end` cursor (endpoint ignores sort=1)."""
    rows = {}
    cursor_end = end_ms
    for page in range(1, max_pages + 1):
        batch = api_get("/funding/stats/%s/hist" % SYMBOL,
                        {"limit": STATS_LIMIT, "end": cursor_end})
        if not batch:
            break
        new = 0
        oldest = None
        for r in batch:
            mts = int(r[0])
            if oldest is None or mts < oldest:
                oldest = mts
            if mts not in rows:
                rows[mts] = r
                new += 1
        if page == 1 or page % 25 == 0:
            log("  funding stats page %d: %d rows total, back to %s" % (page, len(rows), iso(oldest)))
        if new == 0:
            break
        cursor_end = oldest - 1
    else:
        raise RuntimeError("funding stats: exceeded %d pages; aborting instead of silently truncating"
                           % max_pages)
    return [rows[k] for k in sorted(rows)]


def do_stats(end_ms):
    probe = api_get("/funding/stats/%s/hist" % SYMBOL, {"limit": 3})
    if not (isinstance(probe, list) and probe and isinstance(probe[0], list)
            and len(probe[0]) == STATS_ROW_LEN):
        raise RuntimeError("funding stats probe unexpected payload: %.200s" % (probe,))
    log("probe OK funding stats: latest %s FRR(raw)=%s" % (iso(probe[0][0]), probe[0][3]))
    rows = fetch_funding_stats(end_ms)
    if not rows:
        raise RuntimeError("no funding stats rows at all")
    header = ["timestamp_ms", "date_iso", "frr", "frr_daily", "avg_period",
              "funding_amount", "funding_amount_used", "funding_below_threshold"]
    csv_rows = []
    for r in rows:
        frr = r[3]
        frr_daily = ("%.10g" % (frr * 365)) if isinstance(frr, (int, float)) else ""
        csv_rows.append([int(r[0]), iso(r[0]), frr, frr_daily, r[4], r[7], r[8], r[11]])
    write_csv(os.path.join(DATA_DIR, "funding_stats.csv"), header, csv_rows)
    log("funding_stats.csv: %d rows, %s .. %s" % (len(rows), iso(rows[0][0]), iso(rows[-1][0])))


# ---------------------------------------------------------------- summary

def summarize():
    """Read everything back FROM DISK: row counts, ranges, daily gaps, unit cross-check."""
    log("=== SUMMARY (read back from disk) ===")
    for fname in ["candles_1D_p2.csv", "candles_1D_p30.csv", "candles_1h_p2.csv",
                  "funding_stats.csv"]:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            log("%s: MISSING" % fname)
            continue
        with open(path, newline="", encoding="utf-8") as f:
            data = list(csv.reader(f))
        n = len(data) - 1
        if n <= 0:
            log("%s: EMPTY" % fname)
            continue
        log("%s: %d rows, %s .. %s" % (fname, n, data[1][1], data[-1][1]))
        if fname.startswith("candles_1D"):
            gaps = []
            for a, b in zip(data[1:], data[2:]):
                diff = int(b[0]) - int(a[0])
                if diff > GAP_THRESHOLD_DAYS * DAY_MS:
                    gaps.append((a[1][:10], b[1][:10], diff / DAY_MS - 1))
            if gaps:
                log("  gaps >%dd in %s: %d segment(s)" % (GAP_THRESHOLD_DAYS, fname, len(gaps)))
                for lo, hi, missing in gaps:
                    log("    %s -> %s (%.0f missing day(s))" % (lo, hi, missing))
            else:
                log("  gaps >%dd in %s: none" % (GAP_THRESHOLD_DAYS, fname))
    for fname in ["ticker_snapshot.json", "book_snapshot.json"]:
        path = os.path.join(DATA_DIR, fname)
        if os.path.exists(path):
            log("%s: present, %d bytes" % (fname, os.path.getsize(path)))
        else:
            log("%s: MISSING" % fname)
    # unit cross-check: three independent sources must tell the same story
    try:
        with open(os.path.join(DATA_DIR, "ticker_snapshot.json"), encoding="utf-8") as f:
            frr_t = json.load(f)["raw"][0]
        with open(os.path.join(DATA_DIR, "candles_1D_p2.csv"), newline="", encoding="utf-8") as f:
            close_p2 = float(list(csv.reader(f))[-1][3])
        with open(os.path.join(DATA_DIR, "funding_stats.csv"), newline="", encoding="utf-8") as f:
            frr_s = float(list(csv.reader(f))[-1][2])
        log("unit cross-check (all should be same order of magnitude as daily rates):")
        log("  ticker FRR            = %.8g /day -> APR %.2f%%" % (frr_t, frr_t * 365 * 100))
        log("  last 1D p2 close      = %.8g /day -> APR %.2f%%" % (close_p2, close_p2 * 365 * 100))
        log("  last stats FRR x 365  = %.8g /day -> APR %.2f%%  (raw stats FRR=%.4g)"
            % (frr_s * 365, frr_s * 365 * 365 * 100, frr_s))
    except (OSError, ValueError, KeyError, IndexError) as e:
        log("unit cross-check skipped: %r" % (e,))


def main():
    ap = argparse.ArgumentParser(description="Fetch Bitfinex fUSD funding history")
    ap.add_argument("--only", choices=["all", "candles", "snapshots", "stats"], default="all")
    args = ap.parse_args()
    os.makedirs(DATA_DIR, exist_ok=True)
    end_ms = int(time.time() * 1000)
    log("start --only=%s, data dir %s, end=%s" % (args.only, DATA_DIR, iso(end_ms)))

    steps = []
    if args.only in ("all", "snapshots"):
        steps.append(("snapshots", do_snapshots))
    if args.only in ("all", "candles"):
        steps.append(("candles", lambda: do_candles(end_ms)))
    if args.only in ("all", "stats"):
        steps.append(("stats", lambda: do_stats(end_ms)))

    failures = []
    for name, fn in steps:
        try:
            fn()
        except SemanticAPIError as e:
            failures.append((name, "semantic API error (not retried): %s" % e))
            log("!! %s FAILED: %s" % (name, e))
        except Exception as e:  # loud, collected, reported at the end
            failures.append((name, str(e)))
            log("!! %s FAILED: %s" % (name, e))

    summarize()
    if failures:
        log("=== FAILURES ===")
        for name, e in failures:
            log("  %s: %s" % (name, e))
        sys.exit(1)
    log("ALL DONE")


if __name__ == "__main__":
    main()
