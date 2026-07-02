"""Diagnose WHY the momentum backtest failed (research readout, not tuning).

Decomposes the exact NO-GO backtest's PnL: long vs short contribution,
per-coin contribution, and time-in-market — so the next strategy hypothesis
is informed by what actually lost money rather than guesswork.
    python scripts/diagnose_momentum.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.momentum import config as cfg  # noqa: E402
from hlvault.momentum.backtest import FEE_RATE  # noqa: E402
from hlvault.momentum.risk import risk_budget_per_coin, target_position_notional  # noqa: E402
from hlvault.momentum.signals import composite_score, daily_log_returns, position_signal  # noqa: E402
from hlvault.prices import get_candles  # noqa: E402

LOOKBACK_DAYS = 730


def main() -> None:
    end = int(time.time() * 1000)
    start = end - LOOKBACK_DAYS * 86400 * 1000
    closes = {}
    for coin in cfg.COIN_UNIVERSE:
        df = get_candles(coin, "1d", start, end)
        if len(df) >= 150:
            closes[coin] = df.set_index("day")["c"]
    panel = pd.DataFrame(closes).dropna(how="all")
    coins = list(panel.columns)

    returns = pd.DataFrame({c: daily_log_returns(panel[c]) for c in coins}).reindex(panel.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(panel.index)
    signals = pd.DataFrame({c: position_signal(scores[c], cfg.ENTRY_THRESHOLD) for c in coins}).reindex(panel.index)
    trailing_vol = returns.rolling(cfg.VOL_LOOKBACK_DAYS).std(ddof=1)

    equity = 10_000.0
    prev = {c: 0.0 for c in coins}
    attr = {c: {"long": 0.0, "short": 0.0, "fees": 0.0} for c in coins}
    days_long = {c: 0 for c in coins}
    days_short = {c: 0 for c in coins}
    days_flat = {c: 0 for c in coins}

    for t in panel.index:
        vol_by_coin = {c: float(trailing_vol.loc[t, c]) for c in coins
                       if pd.notna(trailing_vol.loc[t, c]) and trailing_vol.loc[t, c] > 0}
        if not vol_by_coin:
            continue
        budgets = risk_budget_per_coin(vol_by_coin, equity, cfg.MAX_COIN_ALLOCATION_PCT)
        day_pnl = 0.0
        for c in vol_by_coin:
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            target = target_position_notional(sig, budgets.get(c, 0.0), cfg.LEVERAGE)
            ret = float(returns.loc[t, c]) if pd.notna(returns.loc[t, c]) else 0.0
            pos_pnl = prev[c] * ret
            fee = abs(target - prev[c]) * FEE_RATE
            if prev[c] > 0:
                attr[c]["long"] += pos_pnl
                days_long[c] += 1
            elif prev[c] < 0:
                attr[c]["short"] += pos_pnl
                days_short[c] += 1
            else:
                days_flat[c] += 1
            attr[c]["fees"] += fee
            day_pnl += pos_pnl - fee
            prev[c] = target
        equity += day_pnl

    print(f"final equity: ${equity:,.0f}  (start $10,000)")
    print(f"\n{'coin':6s} {'long PnL':>10s} {'short PnL':>10s} {'fees':>8s} {'net':>10s} {'d-long':>6s} {'d-short':>7s} {'d-flat':>6s}")
    tot_l = tot_s = tot_f = 0.0
    for c in coins:
        a = attr[c]
        net = a["long"] + a["short"] - a["fees"]
        tot_l += a["long"]; tot_s += a["short"]; tot_f += a["fees"]
        print(f"{c:6s} {a['long']:>10,.0f} {a['short']:>10,.0f} {a['fees']:>8,.0f} {net:>10,.0f} "
              f"{days_long[c]:>6d} {days_short[c]:>7d} {days_flat[c]:>6d}")
    print(f"{'TOTAL':6s} {tot_l:>10,.0f} {tot_s:>10,.0f} {tot_f:>8,.0f} {tot_l+tot_s-tot_f:>10,.0f}")

    # buy-hold benchmark per coin over the same window
    print("\nbuy-hold total return over window:")
    for c in coins:
        px = panel[c].dropna()
        print(f"  {c:6s} {px.iloc[-1]/px.iloc[0]-1:+.1%}")


if __name__ == "__main__":
    main()
