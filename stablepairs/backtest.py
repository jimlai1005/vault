"""Honest backtest that mirrors the hardened Pine logic:

  * trade the chosen instrument OUTRIGHT, timed by the spread z-score
  * one-bar delayed fills: signals on close i execute at close i+1 (no same-bar lookahead)
  * REGIME GATE: only enter in the revert state (toggle to measure its value)
  * real protective stop on the traded price (not a limit that never fills)
  * z take-profit, z signal-stop, time stop, regime-flip flatten
  * DEPEG breaker: flatten + block when |price-1| exceeds a threshold
  * per-side fees + slippage

Returns an equity curve, a trade blotter, and summary metrics.
"""
import numpy as np
import pandas as pd


def backtest(z: pd.Series, traded: pd.Series, is_revert: pd.Series, cfg,
             use_regime: bool = True, depeg_ref: float = 1.0) -> dict:
    idx = z.index
    z = z.values
    px = traded.reindex(idx).values
    rev = is_revert.reindex(idx).fillna(False).values.astype(bool)
    ret = np.concatenate([[0.0], np.diff(px) / px[:-1]])

    fee = (cfg.fee_bps + cfg.slippage_bps) / 1e4
    depeg = cfg.depeg_bps / 1e4

    q = cfg.qty_pct / 100.0
    pos = 0          # -1/0/+1
    pending = None   # (target_pos, exit_reason_tag) decided on the PREVIOUS bar's close
    entry_px = np.nan
    entry_bar = -1
    equity = cfg.capital
    curve, trades = [], []
    reasons = {"TP": 0, "STOPz": 0, "PRICE": 0, "TIME": 0, "FLIP": 0, "DEPEG": 0}

    for i in range(len(idx)):
        # 1) accrue PnL on the position held over bar i (before any fill at this close)
        if pos != 0:
            equity *= (1.0 + pos * ret[i] * q)

        # 2) execute the transition decided at the previous bar's close, at THIS close
        if pending is not None:
            new_pos, tag = pending
            pending = None
            if pos == 0 and new_pos != 0:
                pos, entry_px, entry_bar = new_pos, px[i], i
                equity *= (1.0 - fee * q)
                trades.append({"entry_bar": i, "side": "long" if pos > 0 else "short",
                               "equity": equity})
            elif pos != 0 and new_pos == 0:
                equity *= (1.0 - fee * q)
                trades.append({"exit_bar": i, "reason": tag, "equity": equity})
                reasons[tag] += 1
                pos, entry_px, entry_bar = 0, np.nan, -1

        # 3) decide the NEXT transition on this bar's close
        halted = abs(px[i] - depeg_ref) / depeg_ref > depeg
        can_enter = (not halted) and (rev[i] if use_regime else True)
        if pos != 0 and pending is None:
            reason = None
            if halted:
                reason = "DEPEG"
            elif use_regime and not rev[i]:
                reason = "FLIP"
            elif (i - entry_bar) >= cfg.max_hold_bars:
                reason = "TIME"
            elif pos > 0 and z[i] >= -cfg.exit_z:
                reason = "TP"
            elif pos < 0 and z[i] <= cfg.exit_z:
                reason = "TP"
            elif pos > 0 and z[i] <= -cfg.stop_z:
                reason = "STOPz"
            elif pos < 0 and z[i] >= cfg.stop_z:
                reason = "STOPz"
            else:
                adverse = (px[i] - entry_px) / entry_px * (1 if pos > 0 else -1)
                if adverse <= -cfg.hard_stop_pct / 100.0:
                    reason = "PRICE"
            if reason is not None:
                pending = (0, reason)
        elif pos == 0 and pending is None and can_enter and np.isfinite(z[i]):
            if z[i] < -cfg.entry_z:
                pending = (+1, None)
            elif z[i] > cfg.entry_z:
                pending = (-1, None)

        curve.append(equity)

    curve = pd.Series(curve, index=idx)
    rets = curve.pct_change().fillna(0.0)
    ann = np.sqrt(cfg.bars_per_year)
    sharpe = float(rets.mean() / rets.std() * ann) if rets.std() > 0 else 0.0
    dd = float((curve / curve.cummax() - 1.0).min())
    n_trades = sum(1 for t in trades if "side" in t)
    return {
        "curve": curve,
        "total_return": float(curve.iloc[-1] / cfg.capital - 1.0),
        "sharpe": sharpe,
        "max_drawdown": dd,
        "n_trades": n_trades,
        "exit_reasons": reasons,
    }
