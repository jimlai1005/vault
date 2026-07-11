"""Central configuration for the stablecoin-pairs calibration pipeline.

Everything tunable lives here so the other modules stay dumb and testable.
Edit `exchange`, `stable_universe`, and `timeframe` to point it at what you want.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # ---- exchange / data (data.py, discovery.py) ----
    exchange: str = "binance"          # ccxt id: binance | okx | bybit | hyperliquid
    quote: str = "USDT"                # quote currency for the stablecoin legs
    timeframe: str = "5m"
    lookback_days: int = 120

    # Stablecoin bases to CONSIDER (paired vs `quote`). Discovery keeps only the ones
    # the exchange actually lists + that pass a liquidity floor. XUSD is kept in the
    # list but will almost certainly be dropped on binance.com — that's the point.
    stable_universe: List[str] = field(default_factory=lambda: [
        "USDC", "FDUSD", "DAI", "USDP", "TUSD", "USD1", "PYUSD", "XUSD",
    ])
    min_quote_volume_usd: float = 2_000_000.0   # 24h; drop illiquid legs

    # ---- estimation (spread.py) ----
    train_frac: float = 0.6            # walk-forward split; beta/mean/std frozen on train
    refit_bars: int = 100

    # ---- regime HMM (regime_hmm.py) ----
    k_regimes: int = 2

    # ---- backtest seed thresholds (backtest.py; HMM refines kappa_min etc.) ----
    entry_z: float = 1.0
    exit_z: float = 0.2
    stop_z: float = 3.0
    hard_stop_pct: float = 1.0         # catastrophe price stop on the traded leg (%)

    # ---- risk / costs ----
    fee_bps: float = 7.5               # PER SIDE, bps. Set to YOUR real taker fee.
    slippage_bps: float = 1.0
    depeg_bps: float = 100.0           # hard circuit breaker (|price-1| > this)
    max_hold_bars: int = 288           # time stop (288 x 5m = 24h)
    qty_pct: float = 100.0             # % of equity per trade; backtest scales PnL & fees by this
    capital: float = 100_000.0

    # ---- io ----
    cache_dir: str = "./cache"
    bars_per_year: int = 105_120       # 5m bars/yr, for annualizing Sharpe (tune per tf)
