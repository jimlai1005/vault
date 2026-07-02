"""Coin-selection gate for gridbot instance 2 (sub-project D).

Runs the SAME grid mechanic the live engine uses (hlvault.gridbot.backtest
replays hlvault.gridbot.strategy.step) over up to ~2 years of hourly candles
for each candidate coin, with the same vol-adaptive spacing and the live
engine's default risk parameters, sized to instance 2's budget
($1,000 / 3 coins).

Gate (from the spec): select top <=3 by Sharpe among coins with
  net PnL > 0  AND  backtest MDD <= 20% of the coin's budget.
Fewer than 2 qualifiers => NO-GO, do not deploy.

Writes reports/gridbot2-coin-selection.md. Research only — no orders.
    python scripts/select_gridbot2_coins.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.gridbot.backtest import run_backtest  # noqa: E402
from hlvault.gridbot.strategy import GridConfig  # noqa: E402
from hlvault.gridbot.volatility import adaptive_step_pct, atr_pct  # noqa: E402
from hlvault.prices import _fetch_candles_raw  # noqa: E402

CANDIDATES = ["SOL", "XRP", "DOGE", "BNB", "LINK", "LTC", "AVAX", "SUI",
              "AAVE", "UNI", "CRV", "TON", "TAO", "PENDLE"]
BASELINE = ["HYPE", "BTC", "ETH"]  # instance-1 coins, sanity check only

TOTAL_CAPITAL = 1000.0
N_COINS = 3
BUDGET = TOTAL_CAPITAL / N_COINS
LOOKBACK_DAYS = 730
CHUNK_DAYS = 180  # candleSnapshot caps ~5000 rows; 180d of 1h = 4320

# live-engine defaults (gridbot/config.py)
NUM_LEVELS = 6
VOL_K = 0.5
MIN_STEP_PCT = 0.003
MAX_STEP_PCT = 0.03
STOP_BUFFER_PCT = 0.15
COOLDOWN_CANDLES = 24  # 24h cooldown on 1h candles
MDD_BUDGET_PCT = 0.20

CACHE = Path("data/cache/candles_1h")


def hourly_candles(coin: str, days: int) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{coin}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    end = int(time.time() * 1000)
    start = end - days * 86400 * 1000
    frames = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + CHUNK_DAYS * 86400 * 1000, end)
        raw = _fetch_candles_raw(coin, "1h", cursor, chunk_end)
        if raw:
            df = pd.DataFrame(raw)
            for col in ("o", "h", "l", "c"):
                df[col] = pd.to_numeric(df[col])
            df["t"] = df["t"].astype("int64")
            frames.append(df[["t", "o", "h", "l", "c"]])
        cursor = chunk_end + 1
        time.sleep(0.2)
    if not frames:
        return pd.DataFrame(columns=["t", "o", "h", "l", "c"])
    out = (pd.concat(frames).drop_duplicates("t").sort_values("t").reset_index(drop=True))
    out.to_parquet(f)
    return out


def evaluate(coin: str) -> dict | None:
    candles = hourly_candles(coin, LOOKBACK_DAYS)
    if len(candles) < 24 * 90:
        print(f"{coin}: only {len(candles)} hourly candles, skipping")
        return None
    step = adaptive_step_pct(atr_pct(candles, lookback=24 * 14), VOL_K,
                             MIN_STEP_PCT, MAX_STEP_PCT)
    gc = GridConfig(coin=coin, step_pct=step, num_levels=NUM_LEVELS,
                    notional_per_level=BUDGET / NUM_LEVELS,
                    max_position_notional=BUDGET,
                    stop_buffer_pct=STOP_BUFFER_PCT,
                    cooldown_candles=COOLDOWN_CANDLES)
    r = run_backtest(candles, gc)
    days = len(candles) / 24
    return {
        "coin": coin, "step_pct": step, "days": days,
        "pnl": r.total_pnl, "ann_ret_on_budget": r.total_pnl / BUDGET * (365 / days),
        "sharpe": r.sharpe, "mdd_usd": r.max_drawdown,
        "mdd_pct_budget": abs(r.max_drawdown) / BUDGET,
        "fills": r.num_fills, "tps": r.num_tps, "stops": r.num_stops,
    }


def main() -> None:
    rows = []
    for coin in CANDIDATES + BASELINE:
        res = evaluate(coin)
        if res:
            res["baseline"] = coin in BASELINE
            rows.append(res)
            print(f"{coin:7s} step={res['step_pct']*100:.2f}% days={res['days']:.0f} "
                  f"pnl=${res['pnl']:+7.1f} annRet={res['ann_ret_on_budget']:+7.1%} "
                  f"sharpe={res['sharpe']:+5.2f} MDD={res['mdd_pct_budget']:5.1%} of budget "
                  f"fills={res['fills']} stops={res['stops']}")

    df = pd.DataFrame(rows)
    cand = df[~df["baseline"]]
    qual = cand[(cand["pnl"] > 0) & (cand["mdd_pct_budget"] <= MDD_BUDGET_PCT)]
    picked = qual.sort_values("sharpe", ascending=False).head(N_COINS)
    verdict = "GO" if len(picked) >= 2 else "NO-GO"

    lines = [
        f"# Gridbot instance-2 coin selection — {verdict}",
        "",
        f"Gate: net PnL > 0 AND backtest MDD <= {MDD_BUDGET_PCT:.0%} of the coin's "
        f"${BUDGET:.0f} budget; top {N_COINS} by Sharpe; >=2 required to deploy.",
        f"Window: ~{LOOKBACK_DAYS} days of 1h candles; live-engine default grid params; "
        "same strategy.step code path as production.",
        "",
        "| coin | step | days | net PnL | ann. on budget | Sharpe | MDD %budget | fills | stops | note |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for _, r in df.sort_values(["baseline", "sharpe"], ascending=[True, False]).iterrows():
        note = "baseline (live inst-1)" if r["baseline"] else (
            "**SELECTED**" if r["coin"] in set(picked["coin"]) else
            ("qualified" if r["coin"] in set(qual["coin"]) else "rejected"))
        lines.append(f"| {r['coin']} | {r['step_pct']*100:.2f}% | {r['days']:.0f} "
                     f"| ${r['pnl']:+.1f} | {r['ann_ret_on_budget']:+.1%} | {r['sharpe']:.2f} "
                     f"| {r['mdd_pct_budget']:.1%} | {r['fills']} | {r['stops']} | {note} |")
    lines += ["", f"**Verdict: {verdict}**" +
              (f" — deploy on {', '.join(picked['coin'])}" if verdict == "GO" else
               " — fewer than 2 qualifiers; do not deploy.")]
    Path("reports/gridbot2-coin-selection.md").write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines[-2:]))


if __name__ == "__main__":
    main()
