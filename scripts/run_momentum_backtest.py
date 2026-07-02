"""Real-data go/no-go driver for the momentum strategy. Pulls ~2 years of
daily candles for the configured coin universe, runs the walk-forward-safe
backtest, and writes reports/momentum-backtest-verdict.md with an explicit
verdict. Mirrors scripts/run_backtest.py's role for sub-project A.

Run:
    python scripts/run_momentum_backtest.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.momentum import config as cfg  # noqa: E402
from hlvault.momentum.backtest import run_backtest  # noqa: E402
from hlvault.prices import get_candles  # noqa: E402

LOOKBACK_DAYS = 730  # ~2 years


def main() -> None:
    end = int(time.time() * 1000)
    start = end - LOOKBACK_DAYS * 86400 * 1000
    closes = {}
    for coin in cfg.COIN_UNIVERSE:
        df = get_candles(coin, "1d", start, end)
        if len(df) < 150:
            print(f"skipping {coin}: only {len(df)} days of history")
            continue
        closes[coin] = df.set_index("day")["c"]
    if not closes:
        raise SystemExit("no coins had enough history to backtest")

    panel = pd.DataFrame(closes).dropna(how="all")
    print(f"panel: {panel.shape[0]} days x {panel.shape[1]} coins "
         f"({panel.index.min().date()} -> {panel.index.max().date()})")

    result = run_backtest(
        panel, capital=10_000.0,
        max_coin_allocation_pct=cfg.MAX_COIN_ALLOCATION_PCT,
        max_leverage=cfg.LEVERAGE,
        entry_threshold=cfg.ENTRY_THRESHOLD,
        vol_lookback=cfg.VOL_LOOKBACK_DAYS,
    )

    verdict = "GO" if (result.sharpe > 0.5 and result.total_return > 0
                      and result.max_drawdown > -cfg.MAX_DRAWDOWN_PCT) else "NO-GO"

    report = f"""# Momentum Backtest Verdict: {verdict}

**Universe:** {", ".join(closes.keys())}
**Window:** {panel.index.min().date()} -> {panel.index.max().date()} ({panel.shape[0]} days)
**Capital (hypothetical):** $10,000 · **Leverage cap:** {cfg.LEVERAGE}x · **Entry threshold:** {cfg.ENTRY_THRESHOLD}

| Metric | Value |
|---|---:|
| Total return | {result.total_return:.1%} |
| Sharpe (ann.) | {result.sharpe:.2f} |
| Max drawdown | {result.max_drawdown:.1%} |

**Verdict logic:** GO iff Sharpe > 0.5 AND total return > 0 AND max drawdown stays inside the
live circuit-breaker budget ({cfg.MAX_DRAWDOWN_PCT:.0%}). This is a backtest sanity gate, not a
substitute for the circuit breaker itself, which remains enforced live regardless of this verdict.

**Recommendation:** {"Proceed to live trading once the wallet is funded." if verdict == "GO" else "Do not enable LIVE_TRADING yet — revisit universe/parameters or gather more history before going live."}
"""
    Path("reports").mkdir(exist_ok=True)
    Path("reports/momentum-backtest-verdict.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
