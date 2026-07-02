"""Research: does a long-term trend filter fix the grid's alt-coin bleed?

Hypothesis (declared before running, from two independent observations):
  1. momentum diagnosis: long side +$1,710 / short side -$3,155 -> longs work.
  2. plain-grid selection gate: only the uptrending coin (HYPE) was positive.
  => run the grid ONLY while the coin trades above its long-term trend
     (close > N-day SMA, computed point-in-time from daily closes);
     below trend: flatten everything and stand aside.

Pass gate (declared in advance; ALL must hold for the filtered variant):
  - aggregate PnL across the 14 candidate coins positive on BOTH bar configs
    (1h/~208d and 4h/~730d — the 730d window spans multiple regimes);
  - >=60% of coins non-negative under the filter;
  - aggregate MDD <= 20% of total allocated budget;
  - sign robust across filter lengths {90, 120, 150} days.
Fails => abandon the hypothesis (fallback: funding carry), no tuning.

    python scripts/research_trend_filtered_grid.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.gridbot.strategy import GridConfig, init_state, step  # noqa: E402
from hlvault.gridbot.volatility import adaptive_step_pct, atr_pct  # noqa: E402
from hlvault.prices import _fetch_candles_raw  # noqa: E402

COINS = ["SOL", "XRP", "DOGE", "BNB", "LINK", "LTC", "AVAX", "SUI",
         "AAVE", "UNI", "CRV", "TON", "TAO", "PENDLE"]
BASELINE = ["HYPE", "BTC", "ETH"]

BUDGET = 1000.0 / 3
NUM_LEVELS = 6
VOL_K = 0.5
MIN_STEP, MAX_STEP = 0.003, 0.03
STOP_BUFFER = 0.15
FEE = 0.0003
FILTER_LENGTHS = [90, 120, 150]
CACHE = Path("data/cache/candles_multi")


def fetch(coin: str, interval: str, days: int) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{coin}_{interval}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    end = int(time.time() * 1000)
    start = end - days * 86400 * 1000
    per_chunk = {"1h": 180, "4h": 720, "1d": 4000}[interval]
    frames, cursor = [], start
    while cursor < end:
        chunk_end = min(cursor + per_chunk * 86400 * 1000, end)
        raw = _fetch_candles_raw(coin, interval, cursor, chunk_end)
        if raw:
            df = pd.DataFrame(raw)
            for col in ("o", "h", "l", "c"):
                df[col] = pd.to_numeric(df[col])
            df["t"] = df["t"].astype("int64")
            frames.append(df[["t", "o", "h", "l", "c"]])
        cursor = chunk_end + 1
        time.sleep(0.2)
    out = (pd.concat(frames).drop_duplicates("t").sort_values("t").reset_index(drop=True)
           if frames else pd.DataFrame(columns=["t", "o", "h", "l", "c"]))
    if not out.empty:
        out.to_parquet(f)
    return out


def replay(candles: pd.DataFrame, daily_close: pd.Series, filter_days: int,
           cooldown_candles: int) -> tuple[pd.Series, int]:
    """Grid replay with a point-in-time trend gate. filter_days=0 => always on.
    Returns (per-candle cumulative pnl series indexed by t, n_filter_flips)."""
    stp = adaptive_step_pct(atr_pct(candles, lookback=min(len(candles), 24 * 14)),
                            VOL_K, MIN_STEP, MAX_STEP)
    gc = GridConfig(coin="X", step_pct=stp, num_levels=NUM_LEVELS,
                    notional_per_level=BUDGET / NUM_LEVELS, max_position_notional=BUDGET,
                    stop_buffer_pct=STOP_BUFFER, cooldown_candles=cooldown_candles,
                    fee_rate=FEE)
    sma = daily_close.rolling(filter_days).mean() if filter_days else None
    state = None
    on = False
    flips = 0
    cum = 0.0
    rows = []
    for _, row in candles.iterrows():
        day = pd.to_datetime(int(row["t"]), unit="ms").normalize()
        if filter_days:
            # strictly point-in-time: gate uses the SMA of days BEFORE this one
            past_sma = sma.loc[:day - pd.Timedelta(days=1)]
            past_px = daily_close.loc[:day - pd.Timedelta(days=1)]
            gate = (not past_sma.empty and pd.notna(past_sma.iloc[-1])
                    and not past_px.empty and past_px.iloc[-1] > past_sma.iloc[-1])
        else:
            gate = True
        if gate and not on:
            state = init_state(float(row["c"]))
            on = True
            flips += 1
        elif not gate and on:
            # flatten open lots at this candle's close, cancel everything
            for lot in state.open_lots.values():
                cum += (float(row["c"]) - lot.entry_price) * lot.size
                cum -= float(row["c"]) * lot.size * FEE
            state, on = None, False
            flips += 1
        if on:
            state, events = step(state, {"h": row["h"], "l": row["l"], "c": row["c"]}, gc)
            for ev in events:
                cum += ev.pnl
        rows.append({"t": row["t"], "cum": cum})
    return pd.DataFrame(rows).set_index("t")["cum"], flips


def run_config(interval: str, days: int, cooldown: int) -> None:
    print(f"\n===== bars={interval} window~{days}d =====")
    daily = {c: None for c in COINS + BASELINE}
    for c in COINS + BASELINE:
        d = fetch(c, "1d", 1200)
        daily[c] = d.set_index(pd.to_datetime(d["t"], unit="ms").dt.normalize())["c"] if not d.empty else pd.Series(dtype=float)

    header = f"{'coin':7s} {'unfilt':>9s}" + "".join(f" {'f'+str(fd):>9s}" for fd in FILTER_LENGTHS)
    print(header)
    agg: dict[object, pd.Series] = {}
    per_coin: dict[object, dict[str, float]] = {0: {}, **{fd: {} for fd in FILTER_LENGTHS}}
    for c in COINS + BASELINE:
        candles = fetch(c, interval, days)
        if len(candles) < 200 or daily[c].empty:
            print(f"{c:7s} insufficient data, skipped")
            continue
        cells = []
        for fd in [0] + FILTER_LENGTHS:
            cum, flips = replay(candles, daily[c], fd, cooldown)
            per_coin[fd][c] = float(cum.iloc[-1])
            cells.append(f"{cum.iloc[-1]:>+9.1f}")
            if fd == 120 and c in COINS:
                agg[c] = cum
        print(f"{c:7s} " + " ".join(cells))

    for fd in [0] + FILTER_LENGTHS:
        vals = [v for k, v in per_coin[fd].items() if k in COINS]
        if vals:
            nonneg = sum(1 for v in vals if v >= 0) / len(vals)
            tag = "unfiltered" if fd == 0 else f"filter={fd}d"
            print(f"candidates {tag:11s}: total ${sum(vals):+8.1f}   non-negative {nonneg:.0%}")

    if agg:
        # aggregate equity (union of timestamps, ffill each coin's cum pnl)
        eq = pd.concat(agg.values(), axis=1).sort_index().ffill().fillna(0.0).sum(axis=1)
        peak = eq.cummax()
        mdd = float((eq - peak).min())
        print(f"aggregate (filter=120d, candidates): final ${eq.iloc[-1]:+.1f}, "
              f"maxDD ${mdd:.1f} = {abs(mdd)/1000.0:.1%} of $1000")


def main() -> None:
    run_config("1h", 208, cooldown=24)
    run_config("4h", 730, cooldown=6)


if __name__ == "__main__":
    main()
