"""Research: how big is the delta-neutral funding-carry opportunity on Hyperliquid?

Pulls ~12 months of hourly funding history for the most liquid perp markets,
then reports per-coin annualized funding, persistence, and a naive
top-N rotating carry backtest (long spot / short perp assumed perfectly
delta-neutral; PnL = funding collected − rebalance fees).

Pure research readout — no trading, no wallet needed.
    python scripts/research_funding_carry.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.io.source import TransientError, SemanticError, resilient_read  # noqa: E402

INFO_URL = "https://api.hyperliquid.xyz/info"
LOOKBACK_DAYS = 365
CACHE = Path("data/cache/funding")

# liquid-ish HL perps: majors + the coins gridbot/momentum already track + high-OI alts
UNIVERSE = ["BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "BNB", "AVAX", "LINK",
            "LTC", "ARB", "OP", "SUI", "APT", "WLD", "TIA", "SEI", "JUP",
            "PENDLE", "ENA", "TAO", "AAVE", "CRV", "UNI", "TON"]


def _post(body: dict) -> object:
    def call():
        req = urllib.request.Request(INFO_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))
    return resilient_read(call, max_attempts=6, base_delay=1.0)


def funding_history(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginate fundingHistory forward from start_ms; cache per coin."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"{coin}.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        if not df.empty and df["time"].max() >= end_ms - 3 * 3600 * 1000:
            return df
    rows: list[dict] = []
    cursor = start_ms
    for _ in range(60):  # 60 pages x 500 h ≈ 3.4 years max
        page = _post({"type": "fundingHistory", "coin": coin, "startTime": cursor,
                      "endTime": end_ms})
        if not page:
            break
        rows.extend(page)
        if len(page) < 500:
            break
        cursor = page[-1]["time"] + 1
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fundingRate"] = pd.to_numeric(df["fundingRate"])
        df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
        df.to_parquet(cache_file)
    return df


def main() -> None:
    end = int(time.time() * 1000)
    start = end - LOOKBACK_DAYS * 86400 * 1000
    hourly: dict[str, pd.Series] = {}
    for coin in UNIVERSE:
        try:
            df = funding_history(coin, start, end)
        except Exception as e:
            print(f"{coin}: fetch failed ({e}), skipping")
            continue
        if df.empty or len(df) < 24 * 60:
            print(f"{coin}: only {0 if df.empty else len(df)} hours, skipping")
            continue
        s = df.set_index(pd.to_datetime(df["time"], unit="ms"))["fundingRate"]
        hourly[coin] = s
        ann = s.mean() * 24 * 365
        pos_share = (s > 0).mean()
        print(f"{coin:8s} hours={len(s):5d} annualized={ann:+7.1%} positive-share={pos_share:.0%}")

    if not hourly:
        raise SystemExit("no funding data")

    panel = pd.DataFrame(hourly)
    daily = panel.resample("1D").sum()  # daily funding accrual per coin

    # naive rotating carry: each day pick top-3 coins by trailing 7d funding,
    # hold short-perp/long-spot 1x on each (equal weight), collect next day's funding.
    # fees: assume full position turnover costs 4*0.045% taker (spot+perp, in+out legs
    # amortized) whenever a coin enters/exits the basket.
    trail = daily.rolling(7).sum().shift(1)  # info available at day start (no lookahead)
    N = 3
    FEE_PER_SWAP = 4 * 0.00045
    picks_prev: set = set()
    rows = []
    for day in daily.index[8:]:
        ranked = trail.loc[day].dropna().sort_values(ascending=False)
        picks = set(ranked.head(N).index[ranked.head(N) > 0])
        turnover = len(picks - picks_prev) + len(picks_prev - picks)
        fee = turnover / max(len(picks), 1) * FEE_PER_SWAP / 2 if picks else 0.0
        pnl = daily.loc[day, list(picks)].mean() - fee if picks else 0.0
        rows.append({"day": day, "pnl": pnl, "n": len(picks), "turnover": turnover})
        picks_prev = picks
    bt = pd.DataFrame(rows).set_index("day")
    eq = (1 + bt["pnl"]).cumprod()
    ann_ret = eq.iloc[-1] ** (365 / len(eq)) - 1
    sharpe = bt["pnl"].mean() / bt["pnl"].std(ddof=1) * (365 ** 0.5) if bt["pnl"].std(ddof=1) > 0 else 0
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    print("\n==== naive top-3 rotating carry (delta-neutral, fees included) ====")
    print(f"days={len(bt)}  annualized return={ann_ret:+.1%}  sharpe={sharpe:.2f}  maxDD={mdd:.1%}")
    print(f"avg daily basket size={bt['n'].mean():.1f}  avg daily turnover={bt['turnover'].mean():.2f}")


if __name__ == "__main__":
    main()
