"""Read-only wallet check for the CTA engine. The agent key CANNOT perform
USD class-transfers (master-key only — same limit hit by the carry setup), so
this helper deliberately moves NOTHING. It verifies the wallet is funded with
USDC + HL perp margin (the basis risk.account_equity expects) and reports how
many concurrent NOTIONAL_PER_TRADE positions the current equity supports, so a
human can decide funding at execution time.

    python scripts/setup_cta_wallet.py          # print the picture (never transfers)

RED-LINE: never prints private keys; reads only public account state.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hyperliquid.info import Info  # noqa: E402

from hlvault.cta import config as cfg  # noqa: E402
from hlvault.cta import risk  # noqa: E402


def main() -> None:
    if not cfg.WALLET_ADDRESS:
        print("WALLET_ADDRESS not set in .env.cta — nothing to check.")
        return
    info = Info(cfg.HL_API_URL, skip_ws=True)
    equity = risk.account_equity(info, cfg.WALLET_ADDRESS)

    perp = info.user_state(cfg.WALLET_ADDRESS)
    spot = info.spot_user_state(cfg.WALLET_ADDRESS)
    spot_usdc = next((float(b.get("total", 0.0)) for b in spot.get("balances", [])
                      if b.get("coin") == "USDC"), 0.0)
    spot_non_usdc = [b for b in spot.get("balances", [])
                     if b.get("coin") != "USDC" and float(b.get("total", 0.0)) > 0]
    open_positions = [p["position"]["coin"] for p in perp.get("assetPositions", [])
                      if abs(float(p["position"]["szi"])) > 1e-9]

    print(f"CTA wallet {cfg.WALLET_ADDRESS}")
    print(f"  account equity (spot USDC + perp marginUsed + withdrawable): ${equity:,.2f}")
    print(f"  spot USDC: ${spot_usdc:,.2f}")
    print(f"  open perp positions: {open_positions or 'none'}")
    print(f"  NOTIONAL_PER_TRADE ${cfg.NOTIONAL_PER_TRADE:,.0f} -> "
          f"~{int(equity // cfg.NOTIONAL_PER_TRADE) if cfg.NOTIONAL_PER_TRADE else 0} "
          f"concurrent positions supportable")
    if spot_non_usdc:
        coins = ", ".join(f"{b['coin']}={b['total']}" for b in spot_non_usdc)
        print(f"  WARNING: non-USDC spot balances present ({coins}). This engine "
              f"expects a pure-USDC perp-funded wallet; equity basis assumes no "
              f"spot-coin leg. Resolve before going live.")
    else:
        print("  OK: no non-USDC spot balances (pure-USDC perp basis holds).")
    print("\nThis helper does NOT transfer funds (agent key cannot class-transfer). "
          "Any funding/transfer is an owner decision at execution time.")


if __name__ == "__main__":
    main()
