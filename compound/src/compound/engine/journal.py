"""Tick journal (JSONL) + persistent ownership registry.

The ownership registry is the engine's memory of which offer ids IT placed —
the account is shared with a legacy system, so this set is the only thing
standing between reconcile and someone else's money. It is persisted on every
mutation (crash-safe via tmp+rename).

Attribution of fills: when one of our offers disappears without us canceling
it, we assume it filled and move its amount to `committed` alongside its
(rate, period) signature; matching credits/loans seen later confirm. Expiry
returns are detected when available balance grows back — see state.py notes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class Journal:
    def __init__(self, journal_dir):
        self.dir = Path(journal_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._owned_path = self.dir / "owned.json"
        self._state = self._load()

    # ---- ownership registry ----

    def _load(self):
        if self._owned_path.exists():
            return json.loads(self._owned_path.read_text())
        return {"offers": {}, "fills": []}   # offers: id -> {rate, period, amount}

    def _persist(self):
        tmp = self._owned_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=1))
        os.replace(tmp, self._owned_path)

    @property
    def owned_ids(self):
        return {int(k) for k in self._state["offers"]}

    def record_placed(self, offer):
        self._state["offers"][str(offer.id)] = {
            "rate": offer.rate, "period": offer.period,
            "amount": offer.amount_orig or offer.amount, "ts": time.time(),
        }
        self._persist()

    def record_canceled(self, offer_id, filled_amount=0.0):
        """Remove a canceled offer; any partially-filled portion moves to
        fills so it keeps counting against the capital budget (review F2)."""
        info = self._state["offers"].pop(str(offer_id), None)
        if info and filled_amount > 0:
            fill = dict(info)
            fill["amount"] = filled_amount
            fill["offer_id"] = offer_id
            fill["filled_ts"] = time.time()
            self._state["fills"].append(fill)
        self._persist()

    def record_filled(self, offer_id):
        info = self._state["offers"].pop(str(offer_id), None)
        if info:
            info["offer_id"] = offer_id
            info["filled_ts"] = time.time()
            self._state["fills"].append(info)
        self._persist()
        return info

    def reconcile_fills(self, live_credits_and_loans, grace_seconds=600):
        """Drop attributed fills that no longer have a matching live credit or
        loan — the borrower repaid early, so the capital is back in available
        and must stop counting against the budget (observed live: early
        repayment idled 164 USD for what would have been 3 days).

        Match on (rate, amount, period); each live item backs at most one
        fill. Our rates are quantile-derived long decimals, so accidental
        matches against the legacy system's loans are unlikely. Fills younger
        than grace_seconds are kept unconditionally to ride out any lag
        between the offer vanishing and the credit appearing."""
        import time as _time

        pool = []
        for it in live_credits_and_loans:
            if it.rate is not None and it.amount is not None:
                pool.append([it.rate, it.amount, it.period])
        kept = []
        now = _time.time()
        for f in self._state["fills"]:
            if now - f["filled_ts"] < grace_seconds:
                kept.append(f)
                continue
            match_idx = None
            for i, (r, a, p) in enumerate(pool):
                if (abs(r - f["rate"]) < 1e-9 and abs(a - f["amount"]) < 0.01
                        and p == f["period"]):
                    match_idx = i
                    break
            if match_idx is not None:
                pool.pop(match_idx)
                kept.append(f)
        if len(kept) != len(self._state["fills"]):
            dropped = len(self._state["fills"]) - len(kept)
            self._state["fills"] = kept
            self._persist()
            return dropped
        return 0

    def committed_amount(self):
        """Engine capital assumed out on loans from attributed fills. Cleared
        manually or by expiry sweep (fills older than period + 1d dropped)."""
        now = time.time()
        alive = []
        total = 0.0
        for f in self._state["fills"]:
            if now - f["filled_ts"] < (f["period"] + 1) * 86400:
                alive.append(f)
                total += f["amount"]
        if len(alive) != len(self._state["fills"]):
            self._state["fills"] = alive
            self._persist()
        return total

    # ---- tick log ----

    def log(self, kind, payload):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        path = self.dir / ("%s.jsonl" % day)
        rec = {"ts": time.time(), "kind": kind}
        rec.update(payload)
        with open(path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
