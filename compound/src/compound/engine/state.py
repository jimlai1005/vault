"""Account + market state assembly with reconciliation checks.

Equity identity (engineering principle 1): every tick we verify that the
funding-wallet USD balance from the exchange equals available + amounts on
ALL open offers + all credits/loans (each bucket counted once, all from the
same wallets/offers/credits/loans read). A mismatch beyond tolerance is
journaled at ERROR level — never silently absorbed.
"""
from __future__ import annotations

import logging
import time

from compound.bfx.boundary import TransientError
from compound.strategy.base import AccountState, MarketState

log = logging.getLogger("compound.state")

IDENTITY_TOLERANCE = 1.0   # USD


def fetch_account(priv, journal, symbol="fUSD"):
    wallets = priv.get_wallets()
    offers = priv.get_funding_offers(symbol)
    credits_ = priv.get_funding_credits(symbol)
    loans = priv.get_funding_loans(symbol)

    fw = [w for w in wallets if w.wallet_type == "funding" and w.currency == "USD"]
    balance = fw[0].balance if fw else 0.0
    available = fw[0].available_balance if fw and fw[0].available_balance is not None else 0.0

    # fill attribution: an owned offer id that vanished without a cancel = fill
    live_ids = {o.id for o in offers}
    for oid in journal.owned_ids - live_ids:
        info = journal.record_filled(oid)
        if info:
            log.info("offer %s attributed as FILLED (%s @ %s for %sd)",
                     oid, info["amount"], info["rate"], info["period"])

    own = [o for o in offers if o.id in journal.owned_ids]
    foreign = [o for o in offers if o.id not in journal.owned_ids]

    # early-repayment reconciliation: attributed fills with no matching live
    # credit/loan have been repaid — release their budget
    dropped = journal.reconcile_fills(list(credits_) + list(loans))
    if dropped:
        log.info("released %d repaid fill(s) from committed budget", dropped)
        journal.log("fills_repaid", {"count": dropped})

    # identity check — same source (this snapshot), each bucket once
    on_offers = sum(o.amount or 0.0 for o in offers)
    out_lent = sum(c.amount or 0.0 for c in credits_) + \
        sum(l.amount or 0.0 for l in loans)
    identity_gap = balance - (available + on_offers + out_lent)
    if abs(identity_gap) > IDENTITY_TOLERANCE:
        log.error("EQUITY IDENTITY MISMATCH: balance=%.2f vs available=%.2f + "
                  "offers=%.2f + lent=%.2f (gap %.2f)",
                  balance, available, on_offers, out_lent, identity_gap)
        journal.log("identity_mismatch", {
            "balance": balance, "available": available,
            "on_offers": on_offers, "out_lent": out_lent, "gap": identity_gap,
        })

    return AccountState(
        available=available,
        own_offers=own,
        foreign_offers=foreign,
        own_committed=journal.committed_amount(),
        wallet_total=balance,
    )


def fetch_market(pub, symbol="fUSD", window_days=30):
    ticker = pub.get_ticker(symbol)
    book = pub.get_book(symbol, length=25)
    asks = [e for e in book if e.is_ask]
    bids = [e for e in book if not e.is_ask]

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - window_days * 86400 * 1000
    h2 = pub.get_candles("trade:1h:%s:p2" % symbol, start=start_ms,
                         limit=window_days * 24, sort=-1)
    h30 = pub.get_candles("trade:1D:%s:p30" % symbol, start=start_ms,
                          limit=window_days + 2, sort=-1)

    # Window sanity: candles must cover the recent window at BOTH ends — some
    # backend nodes intermittently return short backfills (observed live: the
    # low-rate old half missing, q30 jumping while q90 held). A bad window
    # skews every quantile the strategy uses, so abort the tick as transient
    # (retryable — another node usually serves the full window).
    def _check_window(cs, label, max_age_h, min_bars):
        if not cs:
            raise TransientError("no %s candles returned" % label)
        newest = max(c.mts for c in cs if c.mts)
        age_h = (now_ms - newest) / 3600e3
        if age_h > max_age_h:
            raise TransientError("stale %s candles: newest is %.1fh old"
                                 % (label, age_h))
        if len(cs) < min_bars:
            raise TransientError("short %s backfill: %d bars < %d expected"
                                 % (label, len(cs), min_bars))

    _check_window(h2, "1h-p2", 6.0, int(window_days * 24 * 0.9))
    # p30 trades don't print every day; a loose floor still catches truncation
    _check_window(h30, "1D-p30", 72.0, max(5, int(window_days * 0.5)))

    return MarketState(
        frr=ticker.frr or 0.0,
        last=ticker.last or 0.0,
        best_ask=asks[0].rate if asks else None,
        best_bid=bids[0].rate if bids else None,
        highs2=[c.high for c in h2 if c.high is not None],
        highs30=[c.high for c in h30 if c.high is not None],
    )
