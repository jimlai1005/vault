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


def get_portfolio_account_value(info, address: str) -> tuple[float, int]:
    """HL's own whole-wallet account value (the web UI number) and its
    timestamp (ms), from the `portfolio` endpoint's latest "day" point.
    Measured 2026-10-05: the last point is computed at query time (age 0.2s)
    and moves with spot-coin mids; includes spot coins, perp (all dexes),
    unified-account hold handling, staking and vault equity. Raises ValueError
    if the response has no usable point - the caller treats that as a failed
    read (skip cycle, never flatten)."""
    resp = info.post("/info", {"type": "portfolio", "user": address})
    periods = dict(resp) if isinstance(resp, list) else dict(resp or {})
    hist = (periods.get("day") or {}).get("accountValueHistory") or []
    if not hist:
        raise ValueError("portfolio endpoint returned no accountValueHistory")
    ts, val = hist[-1]
    return float(val), int(ts)


def equity_breakdown(info, address: str) -> dict:
    """Informational buckets for --status so the owner can reconcile against the
    exchange UI. Never raises on an unpriceable coin (lists it instead). NOT the
    circuit-breaker basis - see get_full_account_equity."""
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
    abstraction = info.post("/info", {"type": "userAbstraction", "user": address})
    held = [(b.get("coin"), int(b.get("token", -1)), float(b.get("total", 0.0)))
            for b in balances if b.get("coin") != "USDC" and float(b.get("total", 0.0)) > 0.0]
    spot_coins = 0.0
    unpriced: list[str] = []
    if held:
        pairs = _usdc_pair_names(info.spot_meta())
        mids = info.all_mids()
        for coin, token, total in held:
            pair = pairs.get(token)
            mid = mids.get(pair) if pair is not None else None
            if mid is None:
                unpriced.append(coin)
            else:
                spot_coins += total * float(mid)
    try:
        portfolio_value, portfolio_ts = get_portfolio_account_value(info, address)
    except Exception:  # informational only - show the failure, don't hide the rest
        portfolio_value, portfolio_ts = float("nan"), 0
    return {
        "spot_usdc_total": spot_usdc,
        "spot_usdc_hold": usdc_hold,
        "spot_coins": spot_coins,
        "perp_account_value": account_value,
        "portfolio_value": portfolio_value,
        "portfolio_ts_ms": portfolio_ts,
        "unpriced_coins": unpriced,
        "abstraction": abstraction,
    }


def get_full_account_equity(info, address: str, spot_basis: str | None = None) -> float:
    """The gridbot circuit breaker's ONE equity basis (CLAUDE.md #1: current and
    peak always from this same function).

    EQUITY_SPOT_BASIS=all (default): HL `portfolio` latest account value - the
    web-UI number, every bucket counted once by the exchange itself. 2026-09-22
    incident: a $699 USDC->UBTC spot buy read as a -45% drawdown through the
    USDC-only basis and tripped a phantom flatten+halt. A point older than
    PORTFOLIO_MAX_AGE_SECONDS raises (failed read upstream: skip cycle, never flatten).

    EQUITY_SPOT_BASIS=usdc: spot USDC total + perp accountValue, the 2026-07-25
    basis, unchanged (measured then against the UI with no spot coins held).

    get_account_equity above is momentum's basis for ITS wallet shape - untouched."""
    import time as _time
    from hlvault.gridbot import config as cfg
    if spot_basis is None:
        spot_basis = cfg.EQUITY_SPOT_BASIS
    if spot_basis == "usdc":
        perp = info.user_state(address)
        account_value = float(perp.get("marginSummary", {}).get("accountValue", 0.0))
        spot_usdc = 0.0
        for bal in info.spot_user_state(address).get("balances", []):
            if bal.get("coin") == "USDC":
                spot_usdc = float(bal.get("total", 0.0))
                break
        return spot_usdc + account_value
    if spot_basis != "all":
        raise ValueError(f"spot_basis must be 'all' or 'usdc', got {spot_basis!r}")
    value, ts = get_portfolio_account_value(info, address)
    age_s = _time.time() - ts / 1000.0
    if age_s > cfg.PORTFOLIO_MAX_AGE_SECONDS:
        raise ValueError(f"portfolio account value is stale ({age_s:.0f}s old > {cfg.PORTFOLIO_MAX_AGE_SECONDS:.0f}s)")
    return value
