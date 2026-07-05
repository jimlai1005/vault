"""Manual smoke test against the REAL public API (not part of pytest).

Verifies models parse live payloads sanely. Read-only, no credentials needed.
"""
from __future__ import annotations

import argparse

from compound import rates
from compound.bfx.public import PublicClient
from compound.bfx.transport import Transport


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="fUSD")
    args = p.parse_args()
    pub = PublicClient(Transport())

    t = pub.get_ticker(args.symbol)
    print("ticker %s:" % args.symbol)
    print("  FRR   %.6f/day = %5.2f%% APR (queue %.1fM)" %
          (t.frr, rates.daily_to_apr(t.frr) * 100, (t.frr_amount_available or 0) / 1e6))
    print("  bid   %.6f @ %sd   ask %.6f @ %sd   last %.6f (%5.2f%% APR)" %
          (t.bid, t.bid_period, t.ask, t.ask_period, t.last,
           rates.daily_to_apr(t.last) * 100))

    book = pub.get_book(args.symbol, length=25)
    bids = [e for e in book if not e.is_ask]
    asks = [e for e in book if e.is_ask]
    print("book: %d bids / %d asks; top bids:" % (len(bids), len(asks)))
    for e in bids[:5]:
        print("  bid %.6f (%5.2f%% APR) @ %3dd  $%.0f" %
              (e.rate, rates.daily_to_apr(e.rate) * 100, e.period, -e.amount))
    for e in asks[:3]:
        print("  ask %.6f (%5.2f%% APR) @ %3dd  $%.0f" %
              (e.rate, rates.daily_to_apr(e.rate) * 100, e.period, e.amount))

    candles = pub.get_candles("trade:1h:%s:a30:p2:p30" % args.symbol, limit=3)
    print("last 1h candles (aggregate p2-p30):")
    for c in candles:
        print("  mts=%d close=%.6f high=%.6f vol=%.0f" %
              (c.mts, c.close, c.high, c.volume))

    stats = pub.get_funding_stats(args.symbol, limit=2)
    for s in stats:
        print("stats: frr_daily=%.6f (%5.2f%% APR) utilization=%.0f%%" %
              (s.frr_daily, rates.daily_to_apr(s.frr_daily) * 100,
               (s.utilization or 0) * 100))


if __name__ == "__main__":
    main()
