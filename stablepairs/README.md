# Stablecoin Pairs — Regime Calibration Pipeline

Offline calibration layer for the **Stay Cool C — Regime-Hardened** Pine strategy.
Python does the heavy estimation (2-state Markov-switching OU = "the Markov chain"),
Pine executes live. This is the estimation/execution split.

```
config.py        # everything tunable (exchange, stablecoin universe, tf, costs)
data.py          # ccxt OHLCV fetch + parquet cache            (needs internet)
discovery.py     # find LIVE stablecoin pairs, rank by cointegration (needs internet)
spread.py        # frozen-beta OLS spread, z-score, AR(1) half-life
regime_hmm.py    # 2-state MS-AR(1) -> per-regime OU params + SUGGESTED PINE INPUTS
backtest.py      # honest walk-forward: regime gate, real stop, fees, depeg breaker
run.py           # orchestrator: discover -> calibrate -> backtest -> print inputs
tests/test_synthetic.py   # offline end-to-end validation (no internet)
```

## Setup (M1 Pro, native arm64 — all pure-Python wheels)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python tests/test_synthetic.py     # validate offline first (no network)
python run.py                      # live: discover pairs, calibrate, backtest
```

`run.py` prints the tightest cointegrated stablecoin pair it can actually find on the
exchange, the fitted regimes, an honest backtest (regime ON vs OFF), and a block of
**suggested Pine inputs** (`kappaMin`, `maxHold`, ...) to paste into the strategy.

## Notes / reality checks

- **XUSD** was on Binance.US (`Binanceus:`), a different exchange from Binance.com.
  Discovery only keeps pairs the chosen venue actually lists — obscure stablecoins get
  dropped automatically. Swap the venue in `config.exchange` (binance/okx/bybit/hyperliquid).
- Set `config.fee_bps` to YOUR real taker fee. For a bp-edge stablecoin scalp, fees are
  usually the difference between edge and no edge — validate net, not gross.
- The MS-AR fit needs a genuinely stationary spread. If two "stablecoins" aren't really
  cointegrated, the fit falls back to a rolling AR(1) proxy and the pair is a weak candidate.
- Before risking capital: walk-forward OOS, check the Deflated Sharpe, don't trust an
  in-sample-picked pair. (Your vault's Go-No-Go discipline applies here.)
```
