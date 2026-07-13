"""Regime decomposition for CTA Phase 2b backtest.

Extracts all trades from the 4h-p10-fuel24 production config (crowd-ON),
labels each with:
  - Regime A: BTC price vs 200d SMA (risk-on/off)
  - Regime B: BTC 30d realized vol percentile (low/mid/high)
  - Year-Month

Then groups by (side, RegimeA, RegimeB), computes aggregate stats, and validates
sum-back against known anchor metrics.

Output: trades.csv (one row per trade with all details + regime labels)
        regime_analysis.txt (summary tables and validation)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parent / "src"))

# Import phase-2b engine.
_spec = importlib.util.spec_from_file_location(
    "p2b", _SCRIPTS / "research_cta_positioning_phase2b.py")
p2b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2b)

SYMBOLS = p2b.SYMBOLS
PORT_BASE = p2b.PORT_BASE
SCRATCHPAD = Path("/private/tmp/claude-501/-Users-jim-projects-vault/"
                  "0ff46c12-78c6-41dc-9589-4de23502fb49/scratchpad")


def _profit_factor(trades: list[dict]) -> float:
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def build_frames():
    """Load all data and compute raw indicators."""
    frames, cov_starts, cov_ends = {}, [], []
    for sym, coin in SYMBOLS.items():
        kls = p2b.load_klines(sym)
        oi, long_pct = p2b.load_coinalyze(coin)
        for tf in p2b.TFS:
            bars = p2b.bar_frame(kls[tf], oi, long_pct, tf)
            frames[(coin, tf)] = p2b.raw_indicators(bars, tf)
        b4 = frames[(coin, "4h")]
        cov_starts.append(b4.index.min())
        cov_ends.append(b4.index.max())
    window_start = max(cov_starts)
    window_end = min(cov_ends)
    stats_start = (window_start + pd.Timedelta(days=p2b.CROWD_WARMUP_DAYS)).ceil("D")
    return frames, window_start, window_end, stats_start


def extract_trades_crowd_on(frames, stats_start):
    """Extract all trades (crowd-ON) for short and long sides.
    Returns dict: {side -> list of dicts with [side, coin, entry_time, exit_time, pnl]}
    """
    tf, p, fl = "4h", 10, 24
    trades_by_side = {"short": [], "long": []}

    for side in ("short", "long"):
        per_coin_trades = {}
        for sym, coin in SYMBOLS.items():
            sig = p2b.shifted_signals(frames[(coin, tf)], p, fl)
            bar_pnl, trades = p2b.simulate(sig, side)
            for t in trades:
                if t["exit_time"] >= stats_start:
                    t["coin"] = coin
                    per_coin_trades.setdefault(coin, []).append(t)
            trades_by_side[side].extend(per_coin_trades.get(coin, []))

    return trades_by_side


def load_btc_klines():
    """Load BTC klines and return 4h series of close prices."""
    kcache = Path("data/cache/cta")
    df = pd.read_parquet(kcache / "BTCUSDT_4h.parquet")
    df = df.copy()
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms")
    return df


def compute_vol_percentiles(btc_klines):
    """Pre-compute the 33% and 67% percentiles of 30d rolling vol for categorization."""
    btc_close = btc_klines["close"].sort_index()
    rolling_vols = []
    for i in range(30, len(btc_close)):
        recent_30 = btc_close.iloc[i-30:i].values
        rets = np.diff(np.log(recent_30))
        vol = np.std(rets) * np.sqrt(365)  # annualized
        rolling_vols.append(vol)
    p33 = np.percentile(rolling_vols, 33)
    p67 = np.percentile(rolling_vols, 67)
    return p33, p67


def add_regime_labels(trades_list, btc_klines, vol_p33, vol_p67):
    """Add regimeA (BTC price vs 200d SMA) and regimeB (30d vol percentile) to each trade.

    Regime A: computed at entry_time, using only bars BEFORE entry_time.
    Regime B: computed at entry_time, using only bars BEFORE entry_time.
    Returns modified trades list.
    """
    btc_close = btc_klines["close"]

    for trade in trades_list:
        entry_time = trade["entry_time"]

        # Regime A: BTC price vs 200d SMA at entry
        # Use only closes strictly before entry_time
        prior_closes = btc_close[btc_close.index < entry_time]
        if len(prior_closes) >= 200:
            sma200 = prior_closes.tail(200).mean()
            last_price = prior_closes.iloc[-1]
            regime_a = "risk-on" if last_price > sma200 else "risk-off"
        else:
            regime_a = "unknown"

        # Regime B: 30d realized vol percentile at entry
        # Compute realized vol from 30d of prior closes
        if len(prior_closes) >= 30:
            recent_30d = prior_closes.tail(30).values
            rets = np.diff(np.log(recent_30d))
            vol30d = np.std(rets) * np.sqrt(365)  # annualized
            # Categorize using pre-computed percentiles
            if vol30d < vol_p33:
                regime_b = "low"
            elif vol30d < vol_p67:
                regime_b = "mid"
            else:
                regime_b = "high"
        else:
            regime_b = "unknown"

        trade["regime_a"] = regime_a
        trade["regime_b"] = regime_b
        trade["entry_month"] = entry_time.strftime("%Y-%m")

    return trades_list


def main():
    SCRATCHPAD.mkdir(parents=True, exist_ok=True)

    print("Loading data and building frames...")
    frames, w_start, w_end, stats_start = build_frames()
    print(f"Window: {w_start:%Y-%m-%d} to {w_end:%Y-%m-%d}, stats from {stats_start:%Y-%m-%d}")

    print("Extracting trades (crowd-ON, 4h-p10-fuel24)...")
    trades_by_side = extract_trades_crowd_on(frames, stats_start)

    print("Loading BTC klines for regime labeling...")
    btc_klines = load_btc_klines()

    print("Computing vol percentiles...")
    vol_p33, vol_p67 = compute_vol_percentiles(btc_klines)
    print(f"  Vol p33={vol_p33:.4f}, p67={vol_p67:.4f}")

    # Combine all trades and add regime labels
    all_trades = []
    for side in ("short", "long"):
        side_trades = trades_by_side[side]
        side_trades = add_regime_labels(side_trades, btc_klines, vol_p33, vol_p67)
        all_trades.extend(side_trades)

    print(f"Total trades extracted: {len(all_trades)}")
    print(f"  short: {len(trades_by_side['short'])}")
    print(f"  long: {len(trades_by_side['long'])}")

    # Output trades to CSV
    trades_df = pd.DataFrame([
        {
            "entry_time": t["entry_time"],
            "exit_time": t["exit_time"],
            "side": t["side"],
            "coin": t["coin"],
            "regime_a": t["regime_a"],
            "regime_b": t["regime_b"],
            "entry_month": t["entry_month"],
            "pnl": t["pnl"],
            "reason": t["reason"],
        }
        for t in all_trades
    ])
    trades_df = trades_df.sort_values("entry_time")
    csv_path = SCRATCHPAD / "cta_trades.csv"
    trades_df.to_csv(csv_path, index=False)
    print(f"\nTrades CSV written to: {csv_path}")

    # Regime analysis: group by (side, regime_a, regime_b)
    lines = [
        "=== CTA Regime Analysis (4h-p10-fuel24, crowd-ON) ===",
        f"Data window: {w_start:%Y-%m-%d} to {w_end:%Y-%m-%d}",
        f"Stats from: {stats_start:%Y-%m-%d}",
        f"Total trades: {len(all_trades)}",
        "",
    ]

    for side in ("short", "long"):
        lines.append(f"\n--- {side.upper()} SIDE ---")
        side_trades = [t for t in all_trades if t["side"] == side]

        # Group by (regime_a, regime_b)
        groups = {}
        for t in side_trades:
            key = (t["regime_a"], t["regime_b"])
            if key not in groups:
                groups[key] = []
            groups[key].append(t)

        # Summary table
        lines.append(f"{'Regime A':<10s}{'Regime B':<8s}{'Trades':<8s}{'PnL $':<12s}{'PnL %':<10s}{'PF':<8s}{'Win %':<8s}{'Avg PnL':<12s}")
        lines.append("-" * 90)

        total_pnl = 0
        total_trades = 0
        for (regime_a, regime_b), group in sorted(groups.items()):
            n = len(group)
            pnl_total = sum(t["pnl"] for t in group)
            pnl_pct = (pnl_total / (PORT_BASE * n / len(side_trades) * 100)) * 100 if len(side_trades) > 0 else 0
            pf = _profit_factor(group)
            win_pct = 100.0 * sum(1 for t in group if t["pnl"] > 0) / n if n > 0 else 0
            avg_pnl = pnl_total / n if n > 0 else 0

            total_pnl += pnl_total
            total_trades += n

            pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
            lines.append(f"{regime_a:<10s}{regime_b:<8s}{n:<8d}{pnl_total:<12.2f}{pnl_pct:<10.2f}{pf_str:<8s}{win_pct:<8.1f}{avg_pnl:<12.2f}")

        lines.append("-" * 90)
        lines.append(f"{'TOTAL':<10s}{'':<8s}{total_trades:<8d}{total_pnl:<12.2f}")

        # Validation against anchor
        if side == "short":
            anchor_pnl, anchor_trades = 183.67, 172
            lines.append(f"\n  Anchor (expected): ${anchor_pnl:.2f}, {anchor_trades} trades")
            lines.append(f"  Actual:             ${total_pnl:.2f}, {total_trades} trades")
            lines.append(f"  Match: {abs(total_pnl - anchor_pnl) < 1 and total_trades == anchor_trades}")
        elif side == "long":
            anchor_pnl, anchor_trades = -70.21, 149
            lines.append(f"\n  Anchor (expected): ${anchor_pnl:.2f}, {anchor_trades} trades")
            lines.append(f"  Actual:             ${total_pnl:.2f}, {total_trades} trades")
            lines.append(f"  Match: {abs(total_pnl - anchor_pnl) < 1 and total_trades == anchor_trades}")

    # Write summary
    out_path = SCRATCHPAD / "regime_analysis.txt"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Regime analysis written to: {out_path}")


if __name__ == "__main__":
    main()
