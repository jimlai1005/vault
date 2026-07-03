"""Wallet-split PLANNER for the carry engine — manual-transfer edition.

Hyperliquid agent/API keys CANNOT perform usdClassTransfer (spot<->perp USDC
moves): it is a user-signed action that only the master wallet key can sign.
Observed live 2026-07-03 when this script executed the transfer with the
agent key:

    Must deposit before performing actions

So this script no longer transfers anything. It computes the same margin
target as before (target_ntl / MAX_SHORT_LEVERAGE, +5% buffer) and PRINTS
the manual instruction: the operator transfers that amount spot -> perp in
the Hyperliquid UI, signed with the master wallet.

    python scripts/setup_carry_wallet.py          # print the manual plan
    python scripts/setup_carry_wallet.py --do-it  # refuses and exits non-zero
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hyperliquid.info import Info  # noqa: E402

from hlvault.carry import config as cfg  # noqa: E402
from hlvault.carry.equity import take_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--do-it", action="store_true",
                        help="(disabled) agent keys cannot usd_class_transfer; "
                             "kept so old automation fails loudly instead of "
                             "silently succeeding")
    args = parser.parse_args()

    info = Info(cfg.HL_API_URL, skip_ws=True)
    s = take_snapshot(info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
    target_ntl = s.equity * cfg.DEPLOY_FRACTION
    margin_target = target_ntl / cfg.MAX_SHORT_LEVERAGE * 1.05
    perp_equity = s.perp_margin_used + s.perp_upnl + s.perp_withdrawable
    shortfall = margin_target - perp_equity

    print(f"equity ${s.equity:,.2f} | target ntl ${target_ntl:,.2f} | "
          f"margin target ${margin_target:,.2f} | perp now ${perp_equity:,.2f}")
    if shortfall <= 1.0:
        print("perp side already funded — nothing to do")
    else:
        amount = round(min(shortfall, s.spot_usdc), 2)
        print(f"MANUAL ACTION REQUIRED: in the Hyperliquid UI, transfer "
              f"${amount:,.2f} USDC from spot to perp for wallet "
              f"{cfg.WALLET_ADDRESS} (master wallet signs it — agent keys "
              f"cannot usd_class_transfer).")
    if args.do_it:
        # Exit non-zero so automation can't silently believe a transfer
        # happened: the old --do-it path called usd_class_transfer, which now
        # fails with "Must deposit before performing actions" on agent keys.
        print("manual transfer required — agent keys cannot do this")
        sys.exit(1)


if __name__ == "__main__":
    main()
