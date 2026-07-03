"""One-time wallet-split helper for the carry engine. Moves USDC between
spot and perp so the perp side holds enough margin for the target short
(target_ntl / MAX_SHORT_LEVERAGE, +5% buffer). Check-before-transfer:
re-runnable, transfers only the shortfall, never more than available.

    python scripts/setup_carry_wallet.py          # print plan (no transfer)
    python scripts/setup_carry_wallet.py --do-it  # execute the transfer
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from eth_account import Account  # noqa: E402
from hyperliquid.exchange import Exchange  # noqa: E402
from hyperliquid.info import Info  # noqa: E402

from hlvault.carry import config as cfg  # noqa: E402
from hlvault.carry.equity import take_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--do-it", action="store_true")
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
        return
    amount = round(min(shortfall, s.spot_usdc), 2)
    print(f"plan: transfer ${amount:,.2f} spot -> perp")
    if not args.do_it:
        print("(dry plan only — rerun with --do-it to execute)")
        return
    account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
    ex = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
    result = ex.usd_class_transfer(amount, True)
    print("transfer result:", result)
    s2 = take_snapshot(info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
    print(f"after: spot USDC ${s2.spot_usdc:,.2f} | perp withdrawable ${s2.perp_withdrawable:,.2f}")


if __name__ == "__main__":
    main()
