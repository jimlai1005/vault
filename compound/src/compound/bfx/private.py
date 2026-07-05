"""Authenticated endpoints, typed and routed through the boundary.

Currency-format trap (api ref §6): submit/offers/loans/credits take the
f-prefixed symbol ('fUSD'); cancel-all and ledgers take the bare currency
('USD'). This inconsistency is encapsulated HERE — every public method of
PrivateClient accepts the f-symbol and converts where needed.

Offer submission/cancellation are non-idempotent or reconciliation-sensitive
writes touching real money: both are declared critical so failures are loud.
"""
from __future__ import annotations

import logging

from compound.bfx import models
from compound.bfx.boundary import CallSpec, SemanticError, call

log = logging.getLogger("compound.private")

LEDGER_CATEGORY_FUNDING_INTEREST = 28


def _bare(symbol):
    models.require_funding_symbol(symbol)
    return symbol[1:]


class PrivateClient:
    def __init__(self, transport):
        self._t = transport

    # ---- reads ----

    def get_wallets(self):
        spec = CallSpec("auth/r/wallets", kind="read", idempotent=True)
        payload = call(spec, self._t.auth_post, "auth/r/wallets")
        return [models.Wallet.from_array(row) for row in payload]

    def get_funding_offers(self, symbol="fUSD"):
        models.require_funding_symbol(symbol)
        spec = CallSpec("auth/r/funding/offers", kind="read", idempotent=True)
        payload = call(spec, self._t.auth_post, "auth/r/funding/offers/%s" % symbol)
        return [models.FundingOffer.from_array(row) for row in payload]

    def get_funding_credits(self, symbol="fUSD"):
        models.require_funding_symbol(symbol)
        spec = CallSpec("auth/r/funding/credits", kind="read", idempotent=True)
        payload = call(spec, self._t.auth_post, "auth/r/funding/credits/%s" % symbol)
        return [models.FundingCredit.from_array(row) for row in payload]

    def get_funding_loans(self, symbol="fUSD"):
        models.require_funding_symbol(symbol)
        spec = CallSpec("auth/r/funding/loans", kind="read", idempotent=True)
        payload = call(spec, self._t.auth_post, "auth/r/funding/loans/%s" % symbol)
        return [models.FundingLoan.from_array(row) for row in payload]

    def get_interest_ledgers(self, symbol="fUSD", start_ms=None, end_ms=None,
                             limit=500):
        body = {"category": LEDGER_CATEGORY_FUNDING_INTEREST, "limit": limit}
        if start_ms is not None:
            body["start"] = int(start_ms)
        if end_ms is not None:
            body["end"] = int(end_ms)
        spec = CallSpec("auth/r/ledgers", kind="read", idempotent=True)
        payload = call(spec, self._t.auth_post,
                       "auth/r/ledgers/%s/hist" % _bare(symbol), body)
        return [models.LedgerEntry.from_array(row) for row in payload]

    # ---- writes ----

    def submit_offer(self, symbol, amount, rate, period, hidden=False):
        """Submit a LIMIT lend offer. amount USD (positive = lend), rate is the
        DAILY decimal, period integer days 2..120. NON-IDEMPOTENT: a transient
        failure may still have landed; caller must reconcile, never blind-retry.
        """
        models.require_funding_symbol(symbol)
        if amount <= 0:
            raise ValueError("lend amount must be positive, got %r" % amount)
        if not 2 <= int(period) <= 120:
            raise ValueError("period out of range 2..120: %r" % period)
        if not 0 < rate < 0.02:   # 0.02/day = 730% APR: fat-finger guard
            raise ValueError("rate %r outside sane daily range" % rate)
        body = {
            "type": "LIMIT",
            "symbol": symbol,
            "amount": "%.8f" % amount,   # API wants strings for amount/rate
            "rate": "%.8f" % rate,
            "period": int(period),
        }
        if hidden:
            body["flags"] = 64
        spec = CallSpec("auth/w/funding/offer/submit", kind="write",
                        idempotent=False, critical=True)
        notif = call(spec, self._t.auth_post, "auth/w/funding/offer/submit", body)
        return self._offer_from_notification(notif, "submit")

    def cancel_offer(self, offer_id):
        """Cancel one of OUR offers by id. Idempotent in intent: the goal state
        is 'offer gone'. If the exchange says it doesn't exist (already filled
        or already canceled), we log and return None — the next reconcile pass
        reads back truth. Any other semantic error still raises."""
        spec = CallSpec("auth/w/funding/offer/cancel", kind="write",
                        idempotent=True, critical=True)
        try:
            notif = call(spec, self._t.auth_post,
                         "auth/w/funding/offer/cancel", {"id": int(offer_id)})
        except SemanticError as exc:
            text = str(exc).lower()
            # Narrow match only: a broad match (e.g. any "invalid") would also
            # swallow auth failures as "offer gone".
            if "not found" in text or "no such offer" in text:
                log.info("cancel_offer(%s): already gone (%s)", offer_id, exc)
                return None
            raise
        return self._offer_from_notification(notif, "cancel")

    @staticmethod
    def _offer_from_notification(notif, action):
        """Notification wrapper (api ref §4.2): [6]=STATUS, [4]=offer array.
        Branch on STATUS, never on the TYPE string."""
        if not isinstance(notif, list) or len(notif) < 7:
            raise SemanticError("%s: malformed notification %r" % (action, notif))
        status = notif[6]
        if status != "SUCCESS":
            raise SemanticError("%s rejected: status=%r text=%r"
                                % (action, status, notif[7] if len(notif) > 7 else None))
        offer_arr = notif[4]
        return models.FundingOffer.from_array(offer_arr) if offer_arr else None
