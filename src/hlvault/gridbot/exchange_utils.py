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
    """Spot USDC + sum(marginUsed + unrealizedPnl) across open perp positions.

    NOT `marginSummary.accountValue` from clearinghouseState — on this unified
    account that field swings with the NUMBER/size of merely-resting orders
    (observed $0 -> $335 -> $53 -> $6.58 with zero or one position open, no
    deposits/withdrawals happening), because it appears to reflect a
    provisional margin-reservation snapshot rather than settled equity. Using
    it as the circuit breaker's "current equity" produced a false-positive
    23.6% drawdown halt with real equity flat around $1000. Summing actual
    position economics (margin tied up + floating pnl) instead stays stable
    regardless of how many unfilled orders are resting."""
    perp = info.user_state(address)
    positions_equity = sum(
        float(p["position"]["marginUsed"]) + float(p["position"]["unrealizedPnl"])
        for p in perp.get("assetPositions", [])
    )
    spot = info.spot_user_state(address)
    spot_usdc = 0.0
    for bal in spot.get("balances", []):
        if bal.get("coin") == "USDC":
            spot_usdc = float(bal.get("total", 0.0))
            break
    return spot_usdc + positions_equity


def _usdc_pair_names(spot_meta: dict) -> dict[int, str]:
    """base token index -> spot pair name quoted in USDC (token 0), e.g. 197 -> "@142"."""
    out: dict[int, str] = {}
    for pair in spot_meta.get("universe", []):
        toks = pair.get("tokens") or []
        if len(toks) == 2 and int(toks[1]) == 0 and int(toks[0]) not in out:
            out[int(toks[0])] = pair["name"]
    return out


def equity_breakdown(info, address: str, spot_basis: str | None = None) -> dict[str, float]:
    """The whole wallet, every bucket counted exactly once, as separate buckets
    so --status can be checked against the exchange UI bucket by bucket:

      spot_usdc          spot USDC balance `total`
      spot_hold_adjust   minus USDC `hold` on a unified account (that hold IS the
                         perp margin already inside accountValue - counting both
                         double-counts it; 2026-10-05 measured: hold 176.38 vs
                         accountValue 173.03 with manual positions open). 0 on a
                         non-unified account, where hold is resting spot orders.
      spot_coins         every other spot coin with total > 0 at its coin/USDC mid
                         (EQUITY_SPOT_BASIS=all) or 0 (EQUITY_SPOT_BASIS=usdc).
                         2026-09-22 incident: a $699 USDC->UBTC spot buy read as a
                         -45% drawdown through the old USDC-only basis and tripped
                         a phantom flatten+halt. A coin with no USDC pair raises -
                         undercounting is the dangerous direction (phantom halt),
                         a raised read is handled as a failed read upstream
                         (skip cycle, never flatten).
      perp_account_value perp marginSummary.accountValue (2026-07-21 incident:
                         cash parked as perp free margin must count).

    get_account_equity above is momentum's basis for ITS wallet shape - untouched."""
    if spot_basis is None:
        from hlvault.gridbot import config as cfg
        spot_basis = cfg.EQUITY_SPOT_BASIS
    if spot_basis not in ("all", "usdc"):
        raise ValueError(f"spot_basis must be 'all' or 'usdc', got {spot_basis!r}")

    perp = info.user_state(address)
    account_value = float(perp.get("marginSummary", {}).get("accountValue", 0.0))

    spot = info.spot_user_state(address)
    balances = spot.get("balances", [])
    spot_usdc = 0.0
    usdc_hold = 0.0
    for bal in balances:
        if bal.get("coin") == "USDC":
            spot_usdc = float(bal.get("total", 0.0))
            usdc_hold = float(bal.get("hold", 0.0))
            break

    hold_adjust = 0.0
    abstraction = info.post("/info", {"type": "userAbstraction", "user": address})
    if abstraction == "unifiedAccount":
        hold_adjust = -usdc_hold

    spot_coins = 0.0
    if spot_basis == "all":
        held = [(b.get("coin"), int(b.get("token", -1)), float(b.get("total", 0.0)))
                for b in balances if b.get("coin") != "USDC" and float(b.get("total", 0.0)) > 0.0]
        if held:
            pairs = _usdc_pair_names(info.spot_meta())
            mids = info.all_mids()
            for coin, token, total in held:
                pair = pairs.get(token)
                mid = mids.get(pair) if pair is not None else None
                if mid is None:
                    raise ValueError(
                        f"spot coin {coin} (token {token}) has no USDC pair/mid - cannot value equity"
                    )
                spot_coins += total * float(mid)

    return {
        "spot_usdc": spot_usdc,
        "spot_hold_adjust": hold_adjust,
        "spot_coins": spot_coins,
        "perp_account_value": account_value,
    }


def get_full_account_equity(info, address: str, spot_basis: str | None = None) -> float:
    """Sum of equity_breakdown() - the gridbot circuit breaker's one equity basis
    (CLAUDE.md #1: current and peak always from this same function)."""
    return sum(equity_breakdown(info, address, spot_basis).values())
