"""Small stateless helpers around the Info client: size rounding, mid prices,
and account equity — current and baseline/peak always computed the same way
from the same call, per CLAUDE.md #1 (never mix equity sources)."""
from __future__ import annotations


def get_sz_decimals(info, coin: str) -> int:
    meta = info.meta()
    for a in meta.get("universe", []):
        if a.get("name") == coin:
            return int(a.get("szDecimals", 3))
    return 3


# fallback when maxLeverage can't be looked up (hl-copytrader uses the same default)
MAX_LEVERAGE_FALLBACK = 20


def get_max_leverage(info, coin: str) -> int:
    meta = info.meta()
    for a in meta.get("universe", []):
        if a.get("name") == coin:
            return int(a.get("maxLeverage", 0))
    return 0


def round_size(size: float, sz_decimals: int) -> float:
    factor = 10 ** sz_decimals
    return int(size * factor) / factor


def round_price(px: float, sz_decimals: int) -> float:
    """Hyperliquid perp price rule: <= 5 significant figures AND
    <= (6 - szDecimals) decimal places."""
    if px <= 0:
        return 0.0
    sig = float(f"{px:.5g}")
    max_decimals = max(6 - sz_decimals, 0)
    return round(sig, max_decimals)


def get_mid_price(info, coin: str) -> float:
    mids = info.all_mids()
    px = mids.get(coin)
    return float(px) if px is not None else 0.0


def get_account_equity(info, address: str) -> float:
    """Perp accountValue + spot USDC — our own account's risk basis always
    includes spot (this is a unified account, funds start in spot)."""
    perp = info.user_state(address)
    perp_value = float(perp.get("marginSummary", {}).get("accountValue", 0.0))
    spot = info.spot_user_state(address)
    spot_usdc = 0.0
    for bal in spot.get("balances", []):
        if bal.get("coin") == "USDC":
            spot_usdc = float(bal.get("total", 0.0))
            break
    return perp_value + spot_usdc
