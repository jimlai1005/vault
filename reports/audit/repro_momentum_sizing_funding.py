"""Read-only audit repro for reports/momentum-backtest-verdict.md
(see reports/audit/J-momentum-findings.md, Findings 1-2).

Does NOT write into the repo. Reuses hlvault.momentum.{signals,risk,backtest}
and hlvault.prices / hlvault.carry.funding unmodified (all public read-only HL
API calls) -- only the sizing scheme (flat LEVERAGE multiplier vs a portfolio
vol-target overlay) and/or a real funding PnL term are swapped in as
counterfactuals against the shipped run_backtest().

Run:
    .venv/bin/python reports/audit/repro_momentum_sizing_funding.py
(takes a few minutes: funding history is paginated per-coin over 731 days)
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/jim/projects/vault/src")

from hlvault.momentum import config as cfg
from hlvault.momentum.backtest import run_backtest, FEE_RATE
from hlvault.momentum.risk import risk_budget_per_coin, target_position_notional
from hlvault.momentum.signals import composite_score, daily_log_returns, position_signal
from hlvault.prices import get_candles
from hlvault.carry.funding import _fetch_funding

LOOKBACK_DAYS = 730


def load_panel():
    end = int(time.time() * 1000)
    start = end - LOOKBACK_DAYS * 86400 * 1000
    closes = {}
    for coin in cfg.COIN_UNIVERSE:
        df = get_candles(coin, "1d", start, end)
        if len(df) < 150:
            print(f"skip {coin}: {len(df)} days")
            continue
        closes[coin] = df.set_index("day")["c"]
    panel = pd.DataFrame(closes).dropna(how="all")
    return panel


def print_result(label, res):
    print(f"{label:32s} sharpe={res.sharpe:6.3f}  total_ret={res.total_return:8.1%}  mdd={res.max_drawdown:8.1%}")


def vol_target_backtest(closes: pd.DataFrame, capital: float, max_coin_allocation_pct: float,
                        entry_threshold: float, vol_lookback: int,
                        target_ann_vol: float = 0.20, max_gross_leverage: float = 3.0):
    """Custom variant: same signal/budget machinery as backtest.run_backtest,
    but instead of a fixed LEVERAGE multiplier, scales aggregate notional
    day-by-day to target a constant annualized realized-vol of the STRATEGY's
    own daily returns (causal: uses only trailing realized vol up to t-1,
    scale computed before day t's PnL is realized -- no lookahead)."""
    coins = list(closes.columns)
    returns = pd.DataFrame({c: daily_log_returns(closes[c]) for c in coins}).reindex(closes.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(closes.index)
    signals = pd.DataFrame({c: position_signal(scores[c], entry_threshold) for c in coins}).reindex(closes.index)
    trailing_vol = returns.rolling(vol_lookback).std(ddof=1)

    target_daily_vol = target_ann_vol / (365 ** 0.5)
    equity = capital
    equity_curve = []
    prev_notional = {c: 0.0 for c in coins}
    strat_ret_hist = []
    scale = 1.0

    for t in closes.index:
        vol_by_coin = {
            c: float(trailing_vol.loc[t, c]) for c in coins
            if pd.notna(trailing_vol.loc[t, c]) and trailing_vol.loc[t, c] > 0
        }
        if not vol_by_coin:
            equity_curve.append(equity)
            strat_ret_hist.append(0.0)
            continue
        budgets = risk_budget_per_coin(vol_by_coin, equity, max_coin_allocation_pct)
        raw_target = {}
        for c in vol_by_coin:
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            raw_target[c] = target_position_notional(sig, budgets.get(c, 0.0), 1.0)  # base leverage=1
        scaled_target = {c: v * scale for c, v in raw_target.items()}
        gross = sum(abs(v) for v in scaled_target.values())
        cap_notional = max_gross_leverage * equity
        if gross > cap_notional and gross > 0:
            shrink = cap_notional / gross
            scaled_target = {c: v * shrink for c, v in scaled_target.items()}

        day_pnl = 0.0
        for c in vol_by_coin:
            target = scaled_target.get(c, 0.0)
            ret = float(returns.loc[t, c]) if pd.notna(returns.loc[t, c]) else 0.0
            day_pnl += prev_notional[c] * ret
            day_pnl -= abs(target - prev_notional[c]) * FEE_RATE
            prev_notional[c] = target
        equity_prev = equity
        equity += day_pnl
        equity_curve.append(equity)
        strat_ret_hist.append(day_pnl / equity_prev if equity_prev else 0.0)

        recent = strat_ret_hist[-vol_lookback:]
        if len(recent) >= vol_lookback:
            realized = float(np.std(recent, ddof=1))
            if realized > 0:
                scale = min(max(target_daily_vol / realized, 0.0), max_gross_leverage)

    eq = pd.Series(equity_curve, index=closes.index)
    daily_ret = eq.pct_change().dropna()
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min()) if len(eq) else 0.0
    sharpe = 0.0
    if len(daily_ret) and daily_ret.std(ddof=1) > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * (365 ** 0.5))
    total_return = float(eq.iloc[-1] / capital - 1.0) if len(eq) else 0.0

    class R:
        pass
    r = R()
    r.equity_curve = eq
    r.daily_returns = daily_ret
    r.max_drawdown = max_dd
    r.sharpe = sharpe
    r.total_return = total_return
    return r


_FUNDING_CACHE: dict = {}


def get_funding_panel(closes: pd.DataFrame) -> pd.DataFrame:
    """Fetch+paginate real HL fundingHistory for every coin in `closes`,
    cached in-process so repeated sensitivity runs don't re-hit the API.
    NOTE: HL's fundingHistory endpoint caps each response at 500 rows
    (~20.8 days of hourly funding) -- carry/funding.py's _fetch_funding was
    written for a short trailing lookback (FUNDING_LOOKBACK_DAYS=7) and
    silently truncates if reused for a 2-year pull without pagination.
    Paginate here by advancing startTime past the last returned timestamp."""
    coins = list(closes.columns)
    key = (tuple(coins), closes.index.min(), closes.index.max())
    if key in _FUNDING_CACHE:
        return _FUNDING_CACHE[key]
    start_ms = int(closes.index.min().timestamp() * 1000)
    end_ms = int(closes.index.max().timestamp() * 1000) + 86400_000
    funding_daily = {}
    for c in coins:
        all_rows, cursor = [], start_ms
        while cursor < end_ms:
            rows = _fetch_funding(c, cursor)
            if not rows:
                break
            all_rows.extend(rows)
            last_t = int(rows[-1]["time"])
            if last_t <= cursor:
                break
            cursor = last_t + 1
            if len(rows) < 500:
                break  # short page = end of available history
        if not all_rows:
            funding_daily[c] = pd.Series(dtype=float)
            continue
        df = pd.DataFrame(all_rows).drop_duplicates(subset=["time"])
        df["day"] = pd.to_datetime(df["time"].astype("int64"), unit="ms").dt.normalize()
        df["fundingRate"] = pd.to_numeric(df["fundingRate"])
        daily = df.groupby("day")["fundingRate"].sum()
        print(f"  funding rows for {c}: {len(df)} ({df['day'].min().date()} -> {df['day'].max().date()})")
        funding_daily[c] = daily
    funding_panel = pd.DataFrame(funding_daily).reindex(closes.index).fillna(0.0)
    _FUNDING_CACHE[key] = funding_panel
    return funding_panel


def funding_overlay(closes: pd.DataFrame, capital: float, max_coin_allocation_pct: float,
                    max_leverage: float, entry_threshold: float, vol_lookback: int):
    """Same as backtest.run_backtest but ALSO adds funding PnL using real
    fundingHistory pulled from HL's public info endpoint. Sign convention:
    HL positive fundingRate => longs pay shorts (funding rate is paid by
    the side whose sign matches the rate's sign: long position * rate is a
    cost to the long, i.e. funding_pnl = -notional_signed * rate)."""
    coins = list(closes.columns)
    returns = pd.DataFrame({c: daily_log_returns(closes[c]) for c in coins}).reindex(closes.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(closes.index)
    signals = pd.DataFrame({c: position_signal(scores[c], entry_threshold) for c in coins}).reindex(closes.index)
    trailing_vol = returns.rolling(vol_lookback).std(ddof=1)
    funding_panel = get_funding_panel(closes)

    equity = capital
    equity_curve = []
    prev_notional = {c: 0.0 for c in coins}
    total_funding_pnl = 0.0
    total_fee = 0.0
    total_price_pnl = 0.0

    for t in closes.index:
        vol_by_coin = {
            c: float(trailing_vol.loc[t, c]) for c in coins
            if pd.notna(trailing_vol.loc[t, c]) and trailing_vol.loc[t, c] > 0
        }
        if not vol_by_coin:
            equity_curve.append(equity)
            continue
        budgets = risk_budget_per_coin(vol_by_coin, equity, max_coin_allocation_pct)
        day_pnl = 0.0
        for c in vol_by_coin:
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            target = target_position_notional(sig, budgets.get(c, 0.0), max_leverage)
            ret = float(returns.loc[t, c]) if pd.notna(returns.loc[t, c]) else 0.0
            price_pnl = prev_notional[c] * ret
            fee = abs(target - prev_notional[c]) * FEE_RATE
            frate = float(funding_panel.loc[t, c]) if t in funding_panel.index else 0.0
            fpnl = -prev_notional[c] * frate
            day_pnl += price_pnl - fee + fpnl
            total_price_pnl += price_pnl
            total_fee += fee
            total_funding_pnl += fpnl
            prev_notional[c] = target
        equity += day_pnl
        equity_curve.append(equity)

    eq = pd.Series(equity_curve, index=closes.index)
    daily_ret = eq.pct_change().dropna()
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min()) if len(eq) else 0.0
    sharpe = 0.0
    if len(daily_ret) and daily_ret.std(ddof=1) > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * (365 ** 0.5))
    total_return = float(eq.iloc[-1] / capital - 1.0) if len(eq) else 0.0
    print(f"  total_price_pnl=${total_price_pnl:,.0f}  total_fee=${total_fee:,.0f}  "
          f"total_funding_pnl=${total_funding_pnl:,.0f}")
    years = len(closes.index) / 365.0
    print(f"  funding pnl annualized: ${total_funding_pnl/years:,.0f}/yr "
          f"({total_funding_pnl/capital/years:+.2%}/yr of starting capital)")

    class R:
        pass
    r = R()
    r.sharpe = sharpe
    r.total_return = total_return
    r.max_drawdown = max_dd
    return r


def vol_target_with_funding(closes: pd.DataFrame, capital: float, max_coin_allocation_pct: float,
                            entry_threshold: float, vol_lookback: int,
                            target_ann_vol: float = 0.20, max_gross_leverage: float = 3.0):
    """Combined counterfactual: vol-target sizing overlay AND real funding PnL,
    together -- the single most policy-relevant number (does the sizing fix
    survive once realistic funding cost is also added back in?)."""
    coins = list(closes.columns)
    returns = pd.DataFrame({c: daily_log_returns(closes[c]) for c in coins}).reindex(closes.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(closes.index)
    signals = pd.DataFrame({c: position_signal(scores[c], entry_threshold) for c in coins}).reindex(closes.index)
    trailing_vol = returns.rolling(vol_lookback).std(ddof=1)
    funding_panel = get_funding_panel(closes)

    target_daily_vol = target_ann_vol / (365 ** 0.5)
    equity = capital
    equity_curve = []
    prev_notional = {c: 0.0 for c in coins}
    strat_ret_hist = []
    scale = 1.0

    for t in closes.index:
        vol_by_coin = {
            c: float(trailing_vol.loc[t, c]) for c in coins
            if pd.notna(trailing_vol.loc[t, c]) and trailing_vol.loc[t, c] > 0
        }
        if not vol_by_coin:
            equity_curve.append(equity)
            strat_ret_hist.append(0.0)
            continue
        budgets = risk_budget_per_coin(vol_by_coin, equity, max_coin_allocation_pct)
        raw_target = {}
        for c in vol_by_coin:
            sig = float(signals.loc[t, c]) if pd.notna(signals.loc[t, c]) else 0.0
            raw_target[c] = target_position_notional(sig, budgets.get(c, 0.0), 1.0)
        scaled_target = {c: v * scale for c, v in raw_target.items()}
        gross = sum(abs(v) for v in scaled_target.values())
        cap_notional = max_gross_leverage * equity
        if gross > cap_notional and gross > 0:
            shrink = cap_notional / gross
            scaled_target = {c: v * shrink for c, v in scaled_target.items()}

        day_pnl = 0.0
        for c in vol_by_coin:
            target = scaled_target.get(c, 0.0)
            ret = float(returns.loc[t, c]) if pd.notna(returns.loc[t, c]) else 0.0
            frate = float(funding_panel.loc[t, c]) if t in funding_panel.index else 0.0
            day_pnl += prev_notional[c] * ret
            day_pnl -= abs(target - prev_notional[c]) * FEE_RATE
            day_pnl -= prev_notional[c] * frate
            prev_notional[c] = target
        equity_prev = equity
        equity += day_pnl
        equity_curve.append(equity)
        strat_ret_hist.append(day_pnl / equity_prev if equity_prev else 0.0)

        recent = strat_ret_hist[-vol_lookback:]
        if len(recent) >= vol_lookback:
            realized = float(np.std(recent, ddof=1))
            if realized > 0:
                scale = min(max(target_daily_vol / realized, 0.0), max_gross_leverage)

    eq = pd.Series(equity_curve, index=closes.index)
    daily_ret = eq.pct_change().dropna()
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min()) if len(eq) else 0.0
    sharpe = 0.0
    if len(daily_ret) and daily_ret.std(ddof=1) > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * (365 ** 0.5))
    total_return = float(eq.iloc[-1] / capital - 1.0) if len(eq) else 0.0

    class R:
        pass
    r = R()
    r.sharpe = sharpe
    r.total_return = total_return
    r.max_drawdown = max_dd
    return r


if __name__ == "__main__":
    panel = load_panel()
    print(f"panel: {panel.shape[0]} days x {panel.shape[1]} coins "
         f"({panel.index.min().date()} -> {panel.index.max().date()})")
    print()

    baseline = run_backtest(panel, capital=10_000.0,
                            max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                            max_leverage=cfg.LEVERAGE,
                            entry_threshold=cfg.ENTRY_THRESHOLD,
                            vol_lookback=cfg.VOL_LOOKBACK_DAYS)
    print_result("baseline (3x leverage, as shipped)", baseline)

    lev1 = run_backtest(panel, capital=10_000.0,
                        max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                        max_leverage=1.0,
                        entry_threshold=cfg.ENTRY_THRESHOLD,
                        vol_lookback=cfg.VOL_LOOKBACK_DAYS)
    print_result("counterfactual: 1x leverage cap", lev1)

    lev2 = run_backtest(panel, capital=10_000.0,
                        max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                        max_leverage=2.0,
                        entry_threshold=cfg.ENTRY_THRESHOLD,
                        vol_lookback=cfg.VOL_LOOKBACK_DAYS)
    print_result("counterfactual: 2x leverage cap", lev2)

    vt = vol_target_backtest(panel, capital=10_000.0,
                             max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                             entry_threshold=cfg.ENTRY_THRESHOLD,
                             vol_lookback=cfg.VOL_LOOKBACK_DAYS,
                             target_ann_vol=0.20, max_gross_leverage=3.0)
    print_result("counterfactual: 20% vol-target overlay", vt)

    for tv in (0.15, 0.25, 0.30):
        vt_s = vol_target_backtest(panel, capital=10_000.0,
                                   max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                                   entry_threshold=cfg.ENTRY_THRESHOLD,
                                   vol_lookback=cfg.VOL_LOOKBACK_DAYS,
                                   target_ann_vol=tv, max_gross_leverage=3.0)
        print_result(f"  sensitivity: vol-target={tv:.0%}", vt_s)
    for vl in (10, 40):
        vt_s = vol_target_backtest(panel, capital=10_000.0,
                                   max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                                   entry_threshold=cfg.ENTRY_THRESHOLD,
                                   vol_lookback=vl,
                                   target_ann_vol=0.20, max_gross_leverage=3.0)
        print_result(f"  sensitivity: vol_lookback={vl}d", vt_s)

    print()
    print("--- fee cost drag ---")
    years = panel.shape[0] / 365.0
    # crude turnover estimate: rerun baseline internals to sum fee $ -- reuse diagnose logic inline
    print(f"FEE_RATE = {FEE_RATE} ({FEE_RATE*1e4:.1f} bps per notional traded)")

    print()
    print("--- funding overlay (baseline leverage, real HL fundingHistory) ---")
    fund = funding_overlay(panel, capital=10_000.0,
                          max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                          max_leverage=cfg.LEVERAGE,
                          entry_threshold=cfg.ENTRY_THRESHOLD,
                          vol_lookback=cfg.VOL_LOOKBACK_DAYS)
    print_result("with funding PnL added", fund)
    print_result("baseline (no funding, for comparison)", baseline)

    print()
    print("--- combined: vol-target sizing AND real funding together ---")
    combo = vol_target_with_funding(panel, capital=10_000.0,
                                    max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                                    entry_threshold=cfg.ENTRY_THRESHOLD,
                                    vol_lookback=cfg.VOL_LOOKBACK_DAYS,
                                    target_ann_vol=0.20, max_gross_leverage=3.0)
    print_result("vol-target(20%) + funding", combo)
    for tv in (0.15, 0.25, 0.30):
        c = vol_target_with_funding(panel, capital=10_000.0,
                                    max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                                    entry_threshold=cfg.ENTRY_THRESHOLD,
                                    vol_lookback=cfg.VOL_LOOKBACK_DAYS,
                                    target_ann_vol=tv, max_gross_leverage=3.0)
        print_result(f"  sensitivity: vol-target={tv:.0%} + funding", c)
    for vl in (10, 40):
        c = vol_target_with_funding(panel, capital=10_000.0,
                                    max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
                                    entry_threshold=cfg.ENTRY_THRESHOLD,
                                    vol_lookback=vl,
                                    target_ann_vol=0.20, max_gross_leverage=3.0)
        print_result(f"  sensitivity: vol_lookback={vl}d + funding", c)
