"""Run the lending engine.

Examples:
  .venv/bin/python scripts/run_engine.py --dry-run --once
  .venv/bin/python scripts/run_engine.py --live --once     # real mutations
  .venv/bin/python scripts/run_engine.py --live --daemon
"""
from __future__ import annotations

import argparse
import logging
import sys

from compound import config
from compound.bfx.private import PrivateClient
from compound.bfx.public import PublicClient
from compound.bfx.transport import Transport
from compound.engine.journal import Journal
from compound.engine.loop import Engine


def main():
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    cadence = p.add_mutually_exclusive_group(required=True)
    cadence.add_argument("--once", action="store_true")
    cadence.add_argument("--daemon", action="store_true")
    p.add_argument("--params", default=None, help="JSON config overrides")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = config.load(overrides_path=args.params)
    cfg.require_credentials()
    tr = Transport(cfg.api_key, cfg.api_secret)
    engine = Engine(cfg, PublicClient(tr), PrivateClient(tr),
                    Journal(cfg.journal_path), dry_run=not args.live)

    if args.live and cfg.live_test_mode:
        logging.info("LIVE with live_test_mode caps: <=%.0f USD/offer, "
                     "period<=%dd, <=%d concurrent", cfg.live_test_max_offer,
                     cfg.live_test_max_period, cfg.live_test_max_concurrent)

    if args.once:
        engine.tick()
    else:
        engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
