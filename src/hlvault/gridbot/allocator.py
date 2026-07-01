"""Capital allocation across the grid's coin universe.

The target wallet put 74% of realized PnL activity into a single coin (HYPE)
with no apparent systematic reason. This allocates by inverse-volatility
(more capital to calmer, more grid-friendly coins) capped per-coin so no
single market can sink the whole pilot."""
from __future__ import annotations


def allocate_capital(
    vol_by_coin: dict, total_capital: float, max_alloc_pct: float = 0.40
) -> dict:
    """Inverse-volatility weights, capped at max_alloc_pct per coin, remainder
    redistributed proportionally among uncapped coins (a couple of passes is
    enough in practice for small universes)."""
    coins = list(vol_by_coin)
    if not coins:
        return {}
    inv = {c: 1.0 / max(vol_by_coin[c], 1e-9) for c in coins}
    weights = {c: inv[c] / sum(inv.values()) for c in coins}
    cap = max_alloc_pct
    for _ in range(len(coins)):
        over = {c: w for c, w in weights.items() if w > cap + 1e-12}
        if not over:
            break
        freed = sum(w - cap for w in over.values())
        for c in over:
            weights[c] = cap
        under = {c: w for c, w in weights.items() if c not in over}
        under_total = sum(under.values())
        if under_total <= 0:
            break
        for c in under:
            weights[c] += freed * (under[c] / under_total)
    return {c: weights[c] * total_capital for c in coins}
