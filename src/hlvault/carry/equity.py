"""One equity basis for the carry wallet (CLAUDE.md #1): all fields read in
one cycle from the same Info client.

DELIBERATE DIVERGENCE from gridbot.exchange_utils.get_account_equity:
gridbot's basis (spot USDC + perp position economics) is correct for a
wallet whose value lives in spot USDC, but the carry wallet's value is
mostly spot HYPE plus perp free margin, so it additionally counts
spot-coin-at-mark and perp `withdrawable`. Do not "unify" these two
functions — their wallets hold different things."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CarrySnapshot:
    mid: float
    spot_usdc: float
    spot_coin_size: float
    spot_coin_ntl: float
    perp_short_size: float    # abs size when short; negative when (wrongly) long
    perp_short_ntl: float
    perp_margin_used: float
    perp_upnl: float
    perp_withdrawable: float
    equity: float
    short_leverage: float     # short ntl / perp-side equity, 0 when no short
    delta_ntl: float          # spot ntl - short ntl (want ~0)


def take_snapshot(info, address: str, coin: str, spot_pair: str) -> CarrySnapshot:
    mids = info.all_mids()
    mid = float(mids.get(coin) or 0.0)

    spot = info.spot_user_state(address)
    spot_usdc = 0.0
    spot_coin = 0.0
    for b in spot.get("balances", []):
        if b.get("coin") == "USDC":
            spot_usdc = float(b.get("total", 0.0))
        elif b.get("coin") == coin:
            spot_coin = float(b.get("total", 0.0))

    perp = info.user_state(address)
    szi = 0.0
    margin_used = 0.0
    upnl = 0.0
    for p in perp.get("assetPositions", []):
        pos = p["position"]
        if pos.get("coin") == coin:
            szi = float(pos["szi"])
            margin_used = float(pos["marginUsed"])
            upnl = float(pos["unrealizedPnl"])
    withdrawable = float(perp.get("withdrawable", 0.0))

    spot_ntl = spot_coin * mid
    short_size = -szi  # szi<0 = short -> positive; szi>0 (long) -> negative flag
    short_ntl = max(short_size, 0.0) * mid
    # perp_equity = margin_used + withdrawable, NOT + upnl: Hyperliquid's
    # `withdrawable` already has unrealized pnl baked in (verified against
    # the real API identity accountValue == totalMarginUsed + withdrawable,
    # exact to the cent). Adding upnl again double-counts it — e.g. a losing
    # short's upnl got subtracted from withdrawable AND subtracted again
    # here, understating equity by 2x the unrealized loss and tripping the
    # 20% drawdown circuit breaker on a phantom loss. upnl is kept as its own
    # CarrySnapshot field for display/direction only, never summed into
    # equity.
    perp_equity = margin_used + withdrawable
    leverage = short_ntl / perp_equity if (short_ntl > 0 and perp_equity > 0) else 0.0
    equity = spot_usdc + spot_ntl + perp_equity

    return CarrySnapshot(
        mid=mid, spot_usdc=spot_usdc, spot_coin_size=spot_coin,
        spot_coin_ntl=spot_ntl, perp_short_size=short_size,
        perp_short_ntl=short_ntl, perp_margin_used=margin_used, perp_upnl=upnl,
        perp_withdrawable=withdrawable, equity=equity,
        short_leverage=leverage, delta_ntl=spot_ntl - short_ntl,
    )
