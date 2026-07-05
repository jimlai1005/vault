"""Engine tick loop: observe -> decide -> reconcile -> execute -> journal.

dry_run: the tick record carries dry_run=true and planned mutations are
logged to stdout but never sent.
Any TransientError aborts the tick (next tick re-derives everything from
exchange truth); SemanticErrors on placement skip that offer and continue.
"""
from __future__ import annotations

import logging
import time

from compound.bfx.boundary import SemanticError, TransientError
from compound.engine import reconcile, state
from compound.strategy import ladder

log = logging.getLogger("compound.loop")


class Engine:
    def __init__(self, cfg, pub, priv, journal, dry_run=True):
        self.cfg = cfg
        self.pub = pub
        self.priv = priv
        self.journal = journal
        self.dry_run = dry_run

    def tick(self):
        cfg = self.cfg
        account = state.fetch_account(self.priv, self.journal, cfg.symbol)
        market = state.fetch_market(self.pub, cfg.symbol)
        targets = ladder.decide(market, account, cfg)
        p = reconcile.plan(targets, account.own_offers, account, cfg)

        self.journal.log("tick", {
            "dry_run": self.dry_run,
            "available": account.available,
            "wallet_total": account.wallet_total,
            "own_offers": [(o.id, o.rate, o.period, o.amount) for o in account.own_offers],
            "foreign_offers": len(account.foreign_offers),
            "own_committed": account.own_committed,
            "frr": market.frr, "last": market.last,
            "targets": [(t.tag, t.rate, t.period, round(t.amount, 2)) for t in targets],
            "plan_cancels": [o.id for o in p.cancels],
            "plan_places": [(t.tag, t.rate, t.period, round(t.amount, 2)) for t in p.places],
            "plan_skipped": [(r, t.tag) for r, t in p.skipped],
        })

        if self.dry_run:
            for o in p.cancels:
                log.info("[dry] cancel offer %s (%.6f @ %sd)", o.id, o.rate, o.period)
            for t in p.places:
                log.info("[dry] place %s: %.2f USD @ %.6f (%.2f%% APR) %sd",
                         t.tag, t.amount, t.rate, t.rate * 365 * 100, t.period)
            return p

        for o in p.cancels:
            try:
                ret = self.priv.cancel_offer(o.id)
                filled = 0.0
                if ret is not None and ret.amount_orig and ret.amount is not None:
                    filled = max(0.0, ret.amount_orig - ret.amount)
                self.journal.record_canceled(o.id, filled_amount=filled)
                self.journal.log("canceled", {"offer_id": o.id, "filled": filled})
                log.info("canceled offer %s (%.6f @ %sd, filled portion %.2f)",
                         o.id, o.rate or 0.0, o.period, filled)
            except TransientError as exc:
                # may or may not have landed; next tick re-reads truth
                log.error("cancel %s transient failure: %s", o.id, exc)
                self.journal.log("cancel_failed", {"offer_id": o.id, "err": str(exc)})
                return p
        for t in p.places:
            try:
                off = self.priv.submit_offer(cfg.symbol, amount=t.amount,
                                             rate=t.rate, period=t.period)
                if off is not None and off.id:
                    self.journal.record_placed(off)
                    self.journal.log("placed", {
                        "offer_id": off.id, "tag": t.tag, "rate": t.rate,
                        "period": t.period, "amount": t.amount})
                    log.info("placed %s: id=%s %.2f USD @ %.6f %sd",
                             t.tag, off.id, t.amount, t.rate, t.period)
                else:
                    log.error("submit returned no offer for %s — reconcile next tick", t.tag)
                    self.journal.log("place_no_offer", {"tag": t.tag})
            except SemanticError as exc:
                log.error("place %s rejected: %s", t.tag, exc)
                self.journal.log("place_rejected", {"tag": t.tag, "err": str(exc)})
            except TransientError as exc:
                log.error("place %s transient failure (may have landed): %s", t.tag, exc)
                self.journal.log("place_failed", {"tag": t.tag, "err": str(exc)})
                return p
        return p

    def run_forever(self):
        while True:
            started = time.time()
            try:
                self.tick()
            except TransientError as exc:
                log.warning("tick aborted (transient): %s", exc)
                self.journal.log("tick_transient", {"err": str(exc)})
            except SemanticError as exc:
                # config/auth level problem: loud, and keep trying (it may be
                # a maintenance window) but the normal cadence sleep below
                # already spaces the retries out
                log.error("tick failed (semantic): %s", exc)
                self.journal.log("tick_semantic", {"err": str(exc)})
            except Exception as exc:   # structural backstop (review F5):
                # one bad payload must never kill the daemon overnight
                log.exception("tick crashed (unexpected)")
                self.journal.log("tick_error",
                                 {"err": "%s: %s" % (type(exc).__name__, exc)})
            elapsed = time.time() - started
            time.sleep(max(5.0, self.cfg.tick_seconds - elapsed))
