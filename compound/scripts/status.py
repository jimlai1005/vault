"""One-shot account + market snapshot (read-only)."""
from __future__ import annotations

import logging

from compound import config, rates
from compound.bfx.private import PrivateClient
from compound.bfx.public import PublicClient
from compound.bfx.transport import Transport
from compound.engine.journal import Journal
from compound.engine.state import fetch_account, fetch_market


def main():
    logging.basicConfig(level=logging.WARNING)
    cfg = config.load()
    cfg.require_credentials()
    tr = Transport(cfg.api_key, cfg.api_secret)
    acct = fetch_account(PrivateClient(tr), Journal(cfg.journal_path), cfg.symbol)
    m = fetch_market(PublicClient(tr), cfg.symbol)

    print("wallet total %.2f USD | available %.2f | engine committed %.2f | budget %.0f"
          % (acct.wallet_total, acct.available, acct.own_committed, cfg.capital_budget))
    print("own offers: %d | foreign offers: %d" %
          (len(acct.own_offers), len(acct.foreign_offers)))
    for o in acct.own_offers:
        print("  #%s %.2f USD @ %.6f (%.2f%% APR) %sd %s" %
              (o.id, o.amount, o.rate, rates.daily_to_apr(o.rate) * 100,
               o.period, o.status))
    print("market: FRR %.2f%% APR | last %.2f%% | best ask %.2f%% | best bid %.2f%%"
          % tuple(rates.daily_to_apr(x or 0) * 100
                  for x in (m.frr, m.last, m.best_ask, m.best_bid)))


if __name__ == "__main__":
    main()
