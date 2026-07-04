# CTA Live Engine (`hlvault.cta`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is written to be implemented and reviewed in isolation: write the failing test first, watch it fail, implement, watch it pass, commit. Do NOT batch tasks.
>
> **RED-LINE (read `/Users/jim/projects/vault/CLAUDE.md` first):** `.env.cta` and `.env.research` are **real wallet/API keys**. The implementer must **never create, print, cat, copy, or load** either file, and must never write a test or example that loads them. Any step that touches real money — going live (`LIVE_TRADING=true`), class-transfers, flatten against a real wallet, starting/stopping the `hl-cta` service, running `scripts/setup_cta_wallet.py` against the real wallet — is marked **[OWNER/COORDINATOR DECISION — do not execute as implementer]**. The implementer builds and tests everything with mocks only.

**Goal:** Operationalize the phase-2b CTA short-carry family (`4h-p10-fuel24-short`) as a live engine managing a small ($1,000) real book on Hyperliquid perps, forward-testing an in-sample-best config with real skin per the owner's explicit override of the NO-GO verdict. Signals (EMA20/50 trend, rolling-90d LSR-percentile crowding, 24h OI-fuel) are computed from Binance-venue data (Coinalyze OI+LSR, Binance klines) and MUST reproduce the backtest's signal for the same bar; execution is on Hyperliquid via the proven IoC-limit path. Per-side switches (`ENABLE_LONG=false`, `ENABLE_SHORT=true`) honor the evidence that the long leg is negative.

**Architecture:** New `src/hlvault/cta/` subpackage mirroring `hlvault/momentum/`'s proven layout: isolated `dotenv_values` config, JSON state (`last_rebalance_ms` family), pure decision functions (`signals.py` — the same math as `scripts/research_cta_positioning_phase2b.py`), a data layer (`data.py`) that fetches Coinalyze + Binance through `io.source.resilient_read` with caching and staleness detection, a risk layer (`risk.py`) that reuses `gridbot.exchange_utils.get_account_equity` for the MDD breaker (this wallet is USDC + HL perp only — gridbot's basis is correct here, NOT carry's) plus position sizing and the 2×ATR stop, and a live loop (`live.py`) that re-reads exchange state every cycle, runs the drawdown breaker every `SYNC_INTERVAL_SECONDS`, and rebalances aligned to 4h bar close. Reuses `gridbot.exchange_utils` (`get_account_equity`, `get_mid_price`, `get_sz_decimals`, `round_price`, `round_size`), `gridbot.resilience.ResilientExchange`, `notify.telegram.send_alert`, `io.source.resilient_read`.

**Tech Stack:** Python 3.9+, `hyperliquid-python-sdk` (`Exchange.order` aggressive-IoC-limit shape, `Info.user_state`/`spot_user_state`/`all_mids`/`meta`), `pandas`/`numpy` (already used in the backtest), `python-dotenv` (`dotenv_values`), stdlib `urllib` for Coinalyze/Binance HTTP, `pytest`.

**Resolved facts (from the reference files):**
- Coinalyze: base URL `https://api.coinalyze.net/v1`; auth header `api_key` (from `.env.research` `COINALYZE_API_KEY`); throttle 1.6s (40 req/min); endpoints `/future-markets`, `/open-interest-history`, `/long-short-ratio-history`; params `symbols`, `interval="4hour"`, `from`/`to` in **unix seconds**; response is a one-item list `[{symbol, history:[...]}]`; history rows have `t` (**unix seconds**), OI: `o,h,l,c`; LSR: `r` (ratio), `l` (long %), `s` (short %). Binance `.A` symbols end `USDTUSDT_PERP.A`… actually `{COIN}USDT_PERP.A` (e.g. `BTCUSDT_PERP.A`); `base_asset` is the coin.
- Binance USDT-M klines: `https://fapi.binance.com/fapi/v1/klines`, params `symbol` (e.g. `BTCUSDT`), `interval="4h"`, `startTime`/`endTime` in **ms**, `limit` (max 1500); rows are arrays `[openTime, o, h, l, c, v, closeTime, ...]`, `openTime`/`closeTime` in ms. Symbol map: `{BTC:BTCUSDT, ETH:ETHUSDT, SOL:SOLUSDT, HYPE:HYPEUSDT, DOGE:DOGEUSDT, XRP:XRPUSDT}`.
- Backtest constants (must match): EMA spans 20/50, `TREND_WARMUP_BARS=50`, crowd window 90d / warmup 30d (in bars: `bars_per_day=6` at 4h), percentile 10 (crowd_long = `lpct >= 100-p = 90`; crowd_short = `lpct <= p = 10`), fuel lookback 24h (`lb_bars = round(24/24*6) = 6`), `STOP_ATR_MULT=2.0`, ATR(14) via `ewm(alpha=1/14)`, `NOTIONAL=100`, `MAX_HOLD=14d`.
- Signal direction (do not invert): **SHORT** = down-trend (EMA50 > EMA20) AND crowd_long (retail crowded long, high LSR percentile) AND fuel (OI rising). **LONG** = up-trend AND crowd_short AND fuel. PIT: signal computed on closed bar `t-1`, acted at bar `t` — the live engine reads only closed bars.
- `get_account_equity(info, address)` = spot USDC + Σ(marginUsed + unrealizedPnl) across perp positions — the correct basis for this pure-USDC-perp wallet. **Do NOT** add `withdrawable` (that was carry's different-wallet basis; double-counting it caused the 2026-07-04 carry bug).
- `Exchange.order(coin, is_buy, size, limit_px, order_type={"limit":{"tif":"Ioc"}}, reduce_only=...)`; "market" = aggressive IoC limit at mid ± 5% slippage, rounded via `round_price`/`round_size`. `send_alert(bot_token, chat_id, message)`.

---

## File structure

```
src/hlvault/cta/__init__.py          # CREATE (empty)
src/hlvault/cta/config.py            # CREATE: .env.cta via dotenv_values
src/hlvault/cta/state.py             # CREATE: halted/peak_equity/flags/last_rebalance_ms
src/hlvault/cta/signals.py           # CREATE: pure EMA/percentile/fuel + per-coin decision
src/hlvault/cta/data.py              # CREATE: Coinalyze + Binance fetch, cached, staleness
src/hlvault/cta/risk.py              # CREATE: sizing + 2xATR stop + MDD breaker (reuse get_account_equity)
src/hlvault/cta/live.py              # CREATE: CtaEngine loop + main()
scripts/setup_cta_wallet.py          # CREATE (thin): verify pure-USDC perp funding (no transfer)
deploy/hl-cta.service                # CREATE
deploy/setup-cta.sh                  # CREATE
pyproject.toml                       # MODIFY: hl-cta entry point
.gitignore                           # (already contains .env.cta and .env.research — verify only)
tests/test_cta_state.py              # CREATE
tests/test_cta_signals.py            # CREATE
tests/test_cta_data.py               # CREATE
tests/test_cta_risk.py               # CREATE
tests/test_cta_live.py               # CREATE
```

`.env.cta` itself is created by the coordinator (holds real credentials — never by an implementer, never committed). `.gitignore` already lists `.env.cta` and `.env.research` (verified); if a task ever finds them missing, add them — do not create the env files.

---

### Task 1: config + state

**Files:**
- Create: `src/hlvault/cta/__init__.py` (empty)
- Create: `src/hlvault/cta/config.py`
- Create: `src/hlvault/cta/state.py`
- Test: `tests/test_cta_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cta_state.py
from hlvault.cta.state import default_state, load_state, save_state


def test_default_state_shape():
    assert default_state() == {
        "halted": False,
        "peak_equity": 0.0,
        "_alerted_this_halt": False,
        "_flatten_complete": False,
        "last_rebalance_ms": 0,
        "entries": {},
    }


def test_load_missing_file_returns_default(tmp_path):
    assert load_state(tmp_path / "nope.json") == default_state()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = default_state()
    s["peak_equity"] = 1234.5
    s["entries"] = {"BTC": {"dir": -1, "entry_px": 65000.0, "stop": 68000.0,
                            "entry_ms": 1720000000000}}
    save_state(p, s)
    assert load_state(p) == s
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_cta_state.py -v` — expect `ModuleNotFoundError: hlvault.cta`.

- [ ] **Step 3: Implement**

`src/hlvault/cta/__init__.py` — empty file.

`src/hlvault/cta/state.py` (atomic-write pattern from momentum/state.py; adds `entries` — per-coin entry bookkeeping so the 2×ATR stop and 14d-max-hold can be evaluated against the entry price/time even though HL positions are re-read from the exchange each cycle):

```python
"""JSON persistence for the live CTA engine. Live perp positions are always
re-read from the exchange (source of truth) each cycle; only circuit-breaker
bookkeeping and per-coin entry metadata (entry price/stop/time — needed by the
strategy-level 2xATR stop and the 14d max-hold, which the exchange does not
track for us) persist here."""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "halted": False,
        "peak_equity": 0.0,
        "_alerted_this_halt": False,
        "_flatten_complete": False,
        "last_rebalance_ms": 0,
        "entries": {},   # coin -> {dir, entry_px, stop, entry_ms}
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return default_state()
    with open(path) as f:
        return json.load(f)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(path)
```

`src/hlvault/cta/config.py` (mirrors momentum's isolated-dict pattern — read `hlvault/momentum/config.py`'s docstring for why `dotenv_values`, not `load_dotenv`):

```python
"""Env-driven config for the live CTA engine. Reads .env.cta via
dotenv_values() into a private dict (NEVER os.environ) — see
hlvault/momentum/config.py's docstring for the shared-os.environ collision
this prevents (multiple bots' env files define same-named keys like
WALLET_ADDRESS/LIVE_TRADING). The Coinalyze API key is read from the SEPARATE
.env.research file (same file the research scripts use), also via an isolated
dotenv_values dict.

Per-side switches (owner design requirement): ENABLE_LONG defaults false,
ENABLE_SHORT defaults true — phase-2b evidence shows the long leg is deeply
negative on 4h while shorts carry the edge. The full both-sides logic is built
and tested so this is a real, reversible one-env-var flip."""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

_ROOT = Path(__file__).resolve().parents[3]
_ENV_PATH = _ROOT / ".env.cta"
_FILE_VALUES = dotenv_values(_ENV_PATH)          # isolated dict; never touches os.environ
_RESEARCH_VALUES = dotenv_values(_ROOT / ".env.research")


def _clean(val):
    if val is None:
        return val
    return val.split("#", 1)[0].strip()


def _raw(key: str, default: str) -> str:
    val = _FILE_VALUES.get(key)
    return val if val is not None else default


def _env_str(key: str, default: str) -> str:
    return _clean(_raw(key, default))


def _env_bool(key: str, default: str) -> bool:
    return _clean(_raw(key, default)).lower() == "true"


def _env_float(key: str, default: str) -> float:
    return float(_clean(_raw(key, default)))


def _env_int(key: str, default: str) -> int:
    return int(float(_clean(_raw(key, default))))


# ---- wallet / network -------------------------------------------------
WALLET_PRIVATE_KEY = _env_str("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS = _env_str("WALLET_ADDRESS", "")
LIVE_TRADING = _env_bool("LIVE_TRADING", "false")
NETWORK = _env_str("NETWORK", "mainnet")
HL_API_URL = "https://api.hyperliquid.xyz" if NETWORK == "mainnet" else "https://api.hyperliquid-testnet.xyz"

# ---- universe ---------------------------------------------------------
COIN_UNIVERSE = [c.strip() for c in _env_str(
    "COIN_UNIVERSE", "BTC,ETH,SOL,HYPE,DOGE,XRP").split(",") if c.strip()]

# ---- per-side switches (honor phase-2b evidence) ----------------------
ENABLE_LONG = _env_bool("ENABLE_LONG", "false")
ENABLE_SHORT = _env_bool("ENABLE_SHORT", "true")

# ---- signal params (MUST match research_cta_positioning_phase2b.py) ---
TIMEFRAME = _env_str("TIMEFRAME", "4h")          # trend/execution bar
EMA_FAST = _env_int("EMA_FAST", "20")
EMA_SLOW = _env_int("EMA_SLOW", "50")
TREND_WARMUP_BARS = _env_int("TREND_WARMUP_BARS", "50")
CROWD_PCTILE = _env_float("CROWD_PCTILE", "10")  # p10 config: crowd_long>=90, crowd_short<=10
CROWD_WINDOW_DAYS = _env_int("CROWD_WINDOW_DAYS", "90")
CROWD_WARMUP_DAYS = _env_int("CROWD_WARMUP_DAYS", "30")
BARS_PER_DAY = _env_int("BARS_PER_DAY", "6")     # 4h -> 6 bars/day
FUEL_LOOKBACK_HOURS = _env_int("FUEL_LOOKBACK_HOURS", "24")
ATR_PERIOD = _env_int("ATR_PERIOD", "14")
STOP_ATR_MULT = _env_float("STOP_ATR_MULT", "2.0")
MAX_HOLD_DAYS = _env_float("MAX_HOLD_DAYS", "14")

# ---- sizing / risk ----------------------------------------------------
NOTIONAL_PER_TRADE = _env_float("NOTIONAL_PER_TRADE", "100")
MAX_DRAWDOWN_PCT = _env_float("MAX_DRAWDOWN_PCT", "0.20")
MIN_ORDER_NOTIONAL = _env_float("MIN_ORDER_NOTIONAL", "12")
ORDER_SLIPPAGE = _env_float("ORDER_SLIPPAGE", "0.05")

# ---- cadence ----------------------------------------------------------
SYNC_INTERVAL_SECONDS = _env_float("SYNC_INTERVAL_SECONDS", "300")
REBALANCE_INTERVAL_HOURS = _env_float("REBALANCE_INTERVAL_HOURS", "4")
DATA_STALENESS_HOURS = _env_float("DATA_STALENESS_HOURS", "8")  # cross-venue freshness guard

# ---- Coinalyze / Binance ----------------------------------------------
COINALYZE_API_KEY = _clean(_RESEARCH_VALUES.get("COINALYZE_API_KEY") or "")
COINALYZE_BASE_URL = "https://api.coinalyze.net/v1"
COINALYZE_THROTTLE_SECONDS = _env_float("COINALYZE_THROTTLE_SECONDS", "1.6")  # 40 req/min
BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
# coin -> Binance USDT-M symbol (klines) ; Coinalyze future-market symbol resolved at runtime
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
                   "HYPE": "HYPEUSDT", "DOGE": "DOGEUSDT", "XRP": "XRPUSDT"}

# ---- notify / state ---------------------------------------------------
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID", "")
STATE_FILE = _ROOT / "data" / "cache" / "cta_state.json"
CACHE_DIR = _ROOT / "data" / "cache" / "cta_live"
```

- [ ] **Step 4: Run tests + import check**

Run: `.venv/bin/pytest tests/test_cta_state.py -v` — expect 3 PASS.
Run: `.venv/bin/python -c "from hlvault.cta import config as c; print(c.COIN_UNIVERSE, c.ENABLE_LONG, c.ENABLE_SHORT, c.CROWD_PCTILE, c.LIVE_TRADING)"` — expect `['BTC', 'ETH', 'SOL', 'HYPE', 'DOGE', 'XRP'] False True 10.0 False`.

- [ ] **Step 5: Verify `.gitignore`** already contains `.env.cta` and `.env.research` (it does — `grep -n '.env.cta\|.env.research' .gitignore`). If either is missing, add the line; never create the file itself.

- [ ] **Step 6: Commit**

```bash
git add src/hlvault/cta/__init__.py src/hlvault/cta/config.py src/hlvault/cta/state.py tests/test_cta_state.py
git commit -m "feat: CTA engine config + state persistence (sub-project G)"
```

---

### Task 2: `signals.py` — pure trend / crowding / fuel / decision

**Files:**
- Create: `src/hlvault/cta/signals.py`
- Test: `tests/test_cta_signals.py`

The math here MUST match `scripts/research_cta_positioning_phase2b.py` (`raw_indicators` / `shifted_signals` / `simulate`'s entry condition). These are pure functions on pandas frames/series so they can be unit-tested against synthetic data verifying **direction** — especially the contrarian crowded-long → SHORT rule, which must not be inverted.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cta_signals.py
import numpy as np
import pandas as pd

from hlvault.cta import signals


def _bars(closes, oi, long_pct, highs=None, lows=None):
    n = len(closes)
    idx = pd.date_range("2025-08-01", periods=n, freq="4h")
    return pd.DataFrame({
        "open": closes, "high": highs or [c * 1.001 for c in closes],
        "low": lows or [c * 0.999 for c in closes], "close": closes,
        "oi_level": oi, "long_pct": long_pct,
    }, index=idx)


def test_ema_trend_up_and_down_direction():
    up = signals.ema_trend(pd.Series(100 * 1.01 ** np.arange(120)), 20, 50, 50)
    assert up["trend_up"].iloc[-1] and not up["trend_dn"].iloc[-1]
    dn = signals.ema_trend(pd.Series(100 * 0.99 ** np.arange(120)), 20, 50, 50)
    assert dn["trend_dn"].iloc[-1] and not dn["trend_up"].iloc[-1]


def test_ema_trend_warmup_suppresses_early_bars():
    up = signals.ema_trend(pd.Series(100 * 1.01 ** np.arange(120)), 20, 50, 50)
    assert not up["trend_up"].iloc[10] and not up["trend_dn"].iloc[10]


def test_crowding_percentile_last_value_rank():
    # last value is the max of a rising series -> percentile ~100
    s = pd.Series(np.arange(200.0))
    pct = signals.crowd_percentile(s, window_bars=90 * 6, warmup_bars=30 * 6)
    assert pct.iloc[-1] > 99.0


def test_crowd_flags_high_pct_is_crowd_long_low_is_crowd_short():
    # rising long_pct -> latest is top decile -> crowd_long True, crowd_short False
    lp_rising = pd.Series(np.arange(200.0))
    pr = signals.crowd_percentile(lp_rising, 90 * 6, 30 * 6)
    assert signals.is_crowd_long(pr.iloc[-1], pctile=10) is True
    assert signals.is_crowd_short(pr.iloc[-1], pctile=10) is False
    # falling long_pct -> latest is bottom decile -> crowd_short True
    lp_falling = pd.Series(np.arange(200.0)[::-1].astype(float))
    pf = signals.crowd_percentile(lp_falling, 90 * 6, 30 * 6)
    assert signals.is_crowd_short(pf.iloc[-1], pctile=10) is True
    assert signals.is_crowd_long(pf.iloc[-1], pctile=10) is False


def test_fuel_ok_true_when_oi_rose_over_lookback():
    oi = pd.Series([10.0] * 10 + [11.0])  # rose vs 6 bars ago
    assert signals.fuel_ok(oi, lookback_bars=6) is True
    oi_flat = pd.Series([10.0] * 11)
    assert signals.fuel_ok(oi_flat, lookback_bars=6) is False


def test_atr_positive_on_volatile_series():
    closes = list(100 + np.cumsum(np.random.default_rng(1).normal(0, 2, 80)))
    bars = _bars(closes, [10.0] * 80, [50.0] * 80)
    atr = signals.atr(bars, period=14, warmup_bars=50)
    assert atr.iloc[-1] > 0 and np.isnan(atr.iloc[10])


def test_decide_crowded_long_downtrend_fuel_gives_SHORT():
    # THE reversal rule: retail crowded long + downtrend + OI rising -> SHORT
    d = signals.decide(trend_up=False, trend_dn=True, crowd_long=True,
                       crowd_short=False, fuel=True,
                       enable_long=True, enable_short=True)
    assert d == "short"


def test_decide_crowded_short_uptrend_fuel_gives_LONG():
    d = signals.decide(trend_up=True, trend_dn=False, crowd_long=False,
                       crowd_short=True, fuel=True,
                       enable_long=True, enable_short=True)
    assert d == "long"


def test_decide_short_disabled_returns_flat_even_when_short_conditions_met():
    d = signals.decide(trend_up=False, trend_dn=True, crowd_long=True,
                       crowd_short=False, fuel=True,
                       enable_long=True, enable_short=False)
    assert d == "flat"


def test_decide_long_disabled_is_default_live_config():
    # live default: long off, short on -> long setup yields flat, short setup shorts
    long_setup = signals.decide(True, False, False, True, True,
                                enable_long=False, enable_short=True)
    short_setup = signals.decide(False, True, True, False, True,
                                 enable_long=False, enable_short=True)
    assert long_setup == "flat" and short_setup == "short"


def test_decide_no_fuel_is_flat():
    assert signals.decide(False, True, True, False, fuel=False,
                          enable_long=True, enable_short=True) == "flat"


def test_should_exit_on_trend_flip_fuel_fail_and_maxhold():
    # short position: trend no longer down -> exit
    assert signals.should_exit(direction=-1, trend_up=False, trend_dn=False,
                               fuel=True, held_days=1.0, max_hold_days=14) == "flip"
    # short position: fuel fails -> exit
    assert signals.should_exit(-1, False, True, fuel=False, held_days=1.0,
                               max_hold_days=14) == "fuel"
    # held too long -> exit
    assert signals.should_exit(-1, False, True, fuel=True, held_days=15.0,
                               max_hold_days=14) == "maxhold"
    # healthy short -> hold (None)
    assert signals.should_exit(-1, False, True, fuel=True, held_days=1.0,
                               max_hold_days=14) is None


def test_compute_signals_end_to_end_matches_direction():
    # 120 downtrend bars, rising long_pct (crowded long), rising OI -> SHORT
    closes = list(100 * 0.99 ** np.arange(120))
    oi = list(np.arange(120.0) + 10)
    long_pct = list(np.arange(120.0))
    bars = _bars(closes, oi, long_pct)
    out = signals.compute_signals(bars, ema_fast=20, ema_slow=50,
                                  trend_warmup_bars=50, crowd_pctile=10,
                                  crowd_window_bars=90 * 6, crowd_warmup_bars=30 * 6,
                                  fuel_lookback_bars=6, atr_period=14)
    assert out["trend_dn"] and out["crowd_long"] and out["fuel"]
    assert out["atr"] > 0
    d = signals.decide(out["trend_up"], out["trend_dn"], out["crowd_long"],
                       out["crowd_short"], out["fuel"],
                       enable_long=False, enable_short=True)
    assert d == "short"
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_cta_signals.py -v` — expect `ModuleNotFoundError` / `AttributeError`.

- [ ] **Step 3: Implement**

```python
"""Pure CTA signal functions — the SAME math as
scripts/research_cta_positioning_phase2b.py (raw_indicators / shifted_signals /
the entry condition in simulate), so the live signal reproduces the backtest's
signal for the same bar (a hard spec requirement).

Direction (do NOT invert — contrarian by design):
  SHORT = down-trend (EMA50 > EMA20) AND retail crowded-long (LSR percentile
          high, >= 100-p) AND fuel (OI rising).
  LONG  = up-trend AND retail crowded-short (LSR percentile low, <= p) AND fuel.
Point-in-time: callers pass CLOSED-bar frames; compute_signals reads the last
closed bar (equivalent to the backtest's shift(1)-then-act-next-bar, since the
live engine only ever sees closed bars)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema_trend(close: pd.Series, fast: int, slow: int, warmup_bars: int) -> pd.DataFrame:
    """EMA{fast}/EMA{slow} trend flags. trend_up = fast>slow, trend_dn =
    slow>fast, both False until `warmup_bars` of history exist (matches the
    backtest's TREND_WARMUP_BARS gate)."""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    valid = pd.Series(np.arange(len(close)) >= warmup_bars, index=close.index)
    return pd.DataFrame({
        "trend_up": (ema_f > ema_s) & valid,
        "trend_dn": (ema_s > ema_f) & valid,
    })


def _pct_rank_last(w: np.ndarray) -> float:
    """Percentile of the CURRENT (last) value within the trailing window —
    identical to the backtest's _pct_rank_last."""
    cur = w[-1]
    if np.isnan(cur):
        return np.nan
    w = w[~np.isnan(w)]
    return float((w <= cur).mean() * 100.0)


def crowd_percentile(long_pct: pd.Series, window_bars: int, warmup_bars: int) -> pd.Series:
    """Rolling trailing percentile of the long-account-% series (matches the
    backtest's rolling(CROWD_WINDOW*bpd, min_periods=CROWD_WARMUP*bpd) apply)."""
    return long_pct.rolling(window_bars, min_periods=warmup_bars).apply(
        _pct_rank_last, raw=True)


def is_crowd_long(pct_rank: float, pctile: float) -> bool:
    """Retail crowded LONG when the long-% percentile is in the top decile
    (>= 100 - pctile). NaN (warmup) -> False."""
    if pct_rank is None or (isinstance(pct_rank, float) and np.isnan(pct_rank)):
        return False
    return bool(pct_rank >= 100 - pctile)


def is_crowd_short(pct_rank: float, pctile: float) -> bool:
    """Retail crowded SHORT when the long-% percentile is in the bottom decile
    (<= pctile). NaN -> False."""
    if pct_rank is None or (isinstance(pct_rank, float) and np.isnan(pct_rank)):
        return False
    return bool(pct_rank <= pctile)


def fuel_ok(oi_level: pd.Series, lookback_bars: int) -> bool:
    """OI rose over the trailing lookback (last value > value lookback_bars
    ago). Matches the backtest's oi_level > oi_level.shift(lb_bars)."""
    if len(oi_level) <= lookback_bars:
        return False
    cur = oi_level.iloc[-1]
    prev = oi_level.iloc[-1 - lookback_bars]
    if np.isnan(cur) or np.isnan(prev):
        return False
    return bool(cur > prev)


def atr(bars: pd.DataFrame, period: int, warmup_bars: int) -> pd.Series:
    """ATR via Wilder EWM (alpha=1/period) on high/low/close — matches the
    backtest's atr_raw; NaN for the first `warmup_bars` bars."""
    prev_close = bars["close"].shift(1)
    tr = pd.concat([
        bars["high"] - bars["low"],
        (bars["high"] - prev_close).abs(),
        (bars["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out = tr.ewm(alpha=1 / period, adjust=False).mean()
    out.iloc[:warmup_bars] = np.nan
    return out


def compute_signals(bars: pd.DataFrame, *, ema_fast: int, ema_slow: int,
                    trend_warmup_bars: int, crowd_pctile: float,
                    crowd_window_bars: int, crowd_warmup_bars: int,
                    fuel_lookback_bars: int, atr_period: int) -> dict:
    """Reduce a per-coin closed-bar frame (columns: open/high/low/close/
    oi_level/long_pct) to the last-bar signal booleans + atr. All flags are
    evaluated on the final (most recent CLOSED) row."""
    trend = ema_trend(bars["close"], ema_fast, ema_slow, trend_warmup_bars)
    crowd = crowd_percentile(bars["long_pct"], crowd_window_bars, crowd_warmup_bars)
    atr_series = atr(bars, atr_period, trend_warmup_bars)
    last_pct = crowd.iloc[-1]
    atr_last = atr_series.iloc[-1]
    return {
        "trend_up": bool(trend["trend_up"].iloc[-1]),
        "trend_dn": bool(trend["trend_dn"].iloc[-1]),
        "crowd_long": is_crowd_long(last_pct, crowd_pctile),
        "crowd_short": is_crowd_short(last_pct, crowd_pctile),
        "fuel": fuel_ok(bars["oi_level"], fuel_lookback_bars),
        "atr": float(atr_last) if not np.isnan(atr_last) else float("nan"),
        "close": float(bars["close"].iloc[-1]),
    }


def decide(trend_up: bool, trend_dn: bool, crowd_long: bool, crowd_short: bool,
           fuel: bool, *, enable_long: bool, enable_short: bool) -> str:
    """Per-coin entry decision -> 'short' | 'long' | 'flat'. Side switches
    applied here (disabled side collapses to flat). SHORT wins ties only if it
    is uniquely satisfied — both cannot be satisfied at once (a bar cannot be
    both down-trend+crowd-long and up-trend+crowd-short)."""
    want_short = enable_short and trend_dn and crowd_long and fuel
    want_long = enable_long and trend_up and crowd_short and fuel
    if want_short:
        return "short"
    if want_long:
        return "long"
    return "flat"


def should_exit(direction: int, trend_up: bool, trend_dn: bool, fuel: bool,
                held_days: float, max_hold_days: float) -> str | None:
    """Exit reason for an OPEN position (direction: 1 long, -1 short), or None
    to hold. Order matches the backtest: trend flip, then fuel fail, then max
    hold. The 2xATR hard stop is evaluated separately against the live price in
    risk.stop_hit (it needs the entry-relative stop level, not just flags)."""
    flip = (direction == 1 and not trend_up) or (direction == -1 and not trend_dn)
    if flip:
        return "flip"
    if not fuel:
        return "fuel"
    if held_days >= max_hold_days:
        return "maxhold"
    return None
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_cta_signals.py -v` — expect all PASS. The direction tests (`test_decide_crowded_long_downtrend_fuel_gives_SHORT`, `test_decide_long_disabled_is_default_live_config`) are the load-bearing ones: if they fail, the reversal logic is inverted — fix `decide`, never the test's expectation.

- [ ] **Step 5: Commit** — `git add src/hlvault/cta/signals.py tests/test_cta_signals.py && git commit -m "feat: CTA pure signals (EMA trend / LSR crowding / OI fuel / decision)"`

---

### Task 3: `data.py` — Coinalyze + Binance fetch, cached, staleness-aware

**Files:**
- Create: `src/hlvault/cta/data.py`
- Test: `tests/test_cta_data.py`

Builds, per coin, the closed-bar frame that `signals.compute_signals` consumes: Binance 4h klines (open/high/low/close) joined with Coinalyze OI (`oi_level`, last-of-period) and long-% (`long_pct`, mean-of-period), matching the backtest's `bar_frame`. Both fetches go through `io.source.resilient_read` (429/5xx transient → retry, 4xx semantic → surface — CLAUDE.md #2/#5). Fetches are cached in-process for one cycle (a `CtaData` instance is created per rebalance). **Cross-venue staleness** is the spec's hard part: `build_frame` reports the age of the most recent data point per source; `is_stale` decides whether new entries must be skipped this cycle (existing positions are still managed from HL state and the drawdown breaker still runs — that lives in live.py, but data.py exposes the freshness signal it needs).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cta_data.py
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from hlvault.cta import data
from hlvault.io.source import SemanticError, TransientError


def _kline_row(open_ms, o, h, l, c):
    # Binance kline array shape (only indices 0-6 used)
    return [open_ms, str(o), str(h), str(l), str(c), "1.0", open_ms + 4 * 3600_000,
            "0", 0, "0", "0", "0"]


def _klines(n, start_ms, price0=100.0):
    return [_kline_row(start_ms + i * 4 * 3600_000, price0 + i, price0 + i + 1,
                       price0 + i - 1, price0 + i) for i in range(n)]


def _coinalyze_hist(n, start_s, kind):
    rows = []
    for i in range(n):
        t = start_s + i * 4 * 3600
        if kind == "oi":
            rows.append({"t": t, "o": "10", "h": "11", "l": "9", "c": str(10 + i)})
        else:  # lsr
            rows.append({"t": t, "r": "1.0", "l": str(50 + i), "s": str(50 - i)})
    return [{"symbol": "BTCUSDT_PERP.A", "history": rows}]


def test_parse_klines_builds_ohlc_frame_indexed_by_open_time():
    df = data.parse_klines(_klines(3, 1_700_000_000_000))
    assert list(df.columns) == ["open", "high", "low", "close"]
    assert len(df) == 3
    assert isinstance(df.index, pd.DatetimeIndex)


def test_parse_coinalyze_oi_and_lsr_seconds_to_naive_ts():
    oi = data.parse_coinalyze_oi(_coinalyze_hist(3, 1_700_000_000, "oi"))
    lsr = data.parse_coinalyze_long_pct(_coinalyze_hist(3, 1_700_000_000, "lsr"))
    assert len(oi) == 3 and len(lsr) == 3
    assert oi.iloc[-1] == 12.0        # 10 + 2
    assert lsr.iloc[0] == 50.0        # long %


def test_build_frame_joins_klines_with_oi_and_long_pct():
    start_ms, start_s = 1_700_000_000_000, 1_700_000_000
    kl = data.parse_klines(_klines(60, start_ms))
    oi = data.parse_coinalyze_oi(_coinalyze_hist(60, start_s, "oi"))
    lp = data.parse_coinalyze_long_pct(_coinalyze_hist(60, start_s, "lsr"))
    frame = data.build_frame(kl, oi, lp, rule="4h")
    assert {"open", "high", "low", "close", "oi_level", "long_pct"} <= set(frame.columns)
    assert frame["oi_level"].notna().any()
    assert frame["long_pct"].notna().any()


def test_data_age_hours_measures_last_point_staleness():
    now_ms = int(time.time() * 1000)
    fresh = data.parse_klines(_klines(3, now_ms - 3 * 4 * 3600_000))
    assert data.data_age_hours(fresh) < 6.0
    stale = data.parse_klines(_klines(3, now_ms - 100 * 3600_000))
    assert data.data_age_hours(stale) > 24.0


def test_is_stale_flags_old_data_beyond_threshold():
    now = pd.Timestamp.utcnow().tz_localize(None)
    assert data.is_stale(now - pd.Timedelta(hours=2), staleness_hours=8) is False
    assert data.is_stale(now - pd.Timedelta(hours=20), staleness_hours=8) is True
    assert data.is_stale(None, staleness_hours=8) is True  # no data at all -> stale


def test_fetch_klines_retries_transient_then_raises_semantic():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("429")
        return _klines(2, 1_700_000_000_000)

    with patch("hlvault.cta.data._http_get_json", side_effect=lambda *a, **k: flaky()):
        rows = data.fetch_klines("BTCUSDT", "4h", 1_700_000_000_000,
                                 1_700_100_000_000, limit=1500)
    assert calls["n"] == 3 and len(rows) == 2

    def semantic():
        raise SemanticError("400 bad symbol")

    with patch("hlvault.cta.data._http_get_json", side_effect=lambda *a, **k: semantic()):
        with pytest.raises(SemanticError):
            data.fetch_klines("NOPE", "4h", 1, 2, limit=1500)


def test_ctadata_caches_within_instance(monkeypatch):
    calls = {"kl": 0, "oi": 0, "lp": 0}
    monkeypatch.setattr(data, "fetch_klines",
                        lambda *a, **k: (calls.__setitem__("kl", calls["kl"] + 1),
                                         _klines(60, 1_700_000_000_000))[1])
    monkeypatch.setattr(data, "fetch_coinalyze",
                        lambda endpoint, symbol, start_s, end_s: (
                            calls.__setitem__("oi", calls["oi"] + 1),
                            _coinalyze_hist(60, 1_700_000_000, "oi"))[1]
                        if "open-interest" in endpoint else (
                            calls.__setitem__("lp", calls["lp"] + 1),
                            _coinalyze_hist(60, 1_700_000_000, "lsr"))[1])
    monkeypatch.setattr(data, "resolve_coinalyze_symbol", lambda coin: "BTCUSDT_PERP.A")

    d = data.CtaData(coins=["BTC"], lookback_bars=200)
    f1 = d.frame_for("BTC")
    f2 = d.frame_for("BTC")
    assert f1 is f2                    # cached, not refetched
    assert calls["kl"] == 1 and calls["oi"] == 1 and calls["lp"] == 1
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_cta_data.py -v`.

- [ ] **Step 3: Implement**

```python
"""Live data layer for the CTA engine: Binance 4h klines (trend/price) +
Coinalyze OI and long-% (crowding/fuel), both through the single read
resilience boundary (io.source.resilient_read — CLAUDE.md #2/#5: 429/5xx are
transient and retried, 4xx are semantic and surfaced).

Cross-venue staleness (spec requirement): the signal comes from Binance-venue
data while execution is on Hyperliquid. If either source is stale (its most
recent point is older than DATA_STALENESS_HOURS) the live engine must NOT open
new positions on that coin this cycle — but it still manages existing HL
positions and runs the drawdown breaker. data_age_hours / is_stale expose the
freshness the loop needs; the skip decision itself lives in live.py.

Coinalyze specifics reused from scripts/pull_coinalyze_data.py: header
`api_key`, 40 req/min -> 1.6s throttle, from/to in unix SECONDS, `t` in
history rows is unix SECONDS, response is a one-item list with a `history`
list, OI close field `c`, LSR long-% field `l`, Binance `.A` symbols end
`USDT_PERP.A` with base_asset = coin."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from hlvault.io.source import SemanticError, TransientError, resilient_read

from . import config as cfg

_last_coinalyze_call = [0.0]  # module-level throttle clock (40 req/min)


def _http_get_json(url: str, headers: dict | None = None, timeout: int = 25):
    """Single HTTP GET returning parsed JSON, classifying failures for the
    resilience boundary. 429/5xx -> TransientError; other 4xx -> SemanticError."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status >= 500:
                raise TransientError(f"5xx {r.status}")
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code >= 500 or e.code == 429:
            raise TransientError(str(e))
        raise SemanticError(str(e))
    except (TimeoutError, ConnectionError) as e:
        raise TransientError(str(e))
    except urllib.error.URLError as e:
        raise TransientError(str(e))


def _throttle_coinalyze() -> None:
    elapsed = time.time() - _last_coinalyze_call[0]
    if elapsed < cfg.COINALYZE_THROTTLE_SECONDS:
        time.sleep(cfg.COINALYZE_THROTTLE_SECONDS - elapsed)
    _last_coinalyze_call[0] = time.time()


# ---------------------------------------------------------------- fetch
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                 limit: int = 1500) -> list:
    params = urllib.parse.urlencode({"symbol": symbol, "interval": interval,
                                     "startTime": start_ms, "endTime": end_ms,
                                     "limit": limit})
    url = f"{cfg.BINANCE_KLINES_URL}?{params}"
    return resilient_read(lambda: _http_get_json(url), max_attempts=6, base_delay=1.0)


def fetch_coinalyze(endpoint: str, symbol: str, start_s: int, end_s: int) -> list:
    _throttle_coinalyze()
    params = urllib.parse.urlencode({"symbols": symbol, "interval": "4hour",
                                     "from": start_s, "to": end_s})
    url = f"{cfg.COINALYZE_BASE_URL}{endpoint}?{params}"
    headers = {"api_key": cfg.COINALYZE_API_KEY}
    return resilient_read(lambda: _http_get_json(url, headers=headers),
                          max_attempts=6, base_delay=2.0)


def resolve_coinalyze_symbol(coin: str) -> str:
    """Find the Binance (.A) USDT-perp Coinalyze symbol for a coin, matching
    pull_coinalyze_data.get_future_markets (base_asset == coin, symbol ends
    USDT_PERP.A)."""
    _throttle_coinalyze()
    url = f"{cfg.COINALYZE_BASE_URL}/future-markets"
    markets = resilient_read(
        lambda: _http_get_json(url, headers={"api_key": cfg.COINALYZE_API_KEY}),
        max_attempts=6, base_delay=2.0)
    for m in markets:
        if m.get("base_asset") == coin and str(m.get("symbol", "")).endswith("USDT_PERP.A"):
            return m["symbol"]
    raise SemanticError(f"no Binance .A Coinalyze symbol for {coin}")


# ---------------------------------------------------------------- parse
def parse_klines(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df = pd.DataFrame(rows)
    idx = pd.to_datetime(df[0].astype("int64"), unit="ms")
    out = pd.DataFrame({
        "open": pd.to_numeric(df[1]), "high": pd.to_numeric(df[2]),
        "low": pd.to_numeric(df[3]), "close": pd.to_numeric(df[4]),
    })
    out.index = idx
    return out.sort_index()


def _coinalyze_series(payload: list, field: str) -> pd.Series:
    if not payload or not payload[0].get("history"):
        return pd.Series(dtype=float)
    hist = payload[0]["history"]
    idx = pd.to_datetime([int(r["t"]) for r in hist], unit="s")  # seconds -> naive UTC
    s = pd.Series([float(r[field]) for r in hist], index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def parse_coinalyze_oi(payload: list) -> pd.Series:
    return _coinalyze_series(payload, "c")     # OI close (base-asset units)


def parse_coinalyze_long_pct(payload: list) -> pd.Series:
    return _coinalyze_series(payload, "l")     # long % of accounts


# ---------------------------------------------------------------- assemble
def build_frame(klines: pd.DataFrame, oi: pd.Series, long_pct: pd.Series,
                rule: str) -> pd.DataFrame:
    """Join klines with per-bar OI (last-of-period) and long-% (mean-of-period),
    keeping only bars covered by Coinalyze data — matches the backtest's
    bar_frame. Returns a frame with columns open/high/low/close/oi_level/
    long_pct indexed by bar open time."""
    bars = klines.copy()
    if not oi.empty and not long_pct.empty:
        cov_start = max(oi.index.min(), long_pct.index.min())
        bars = bars[bars.index >= cov_start]
    oi_bar = oi.resample(rule, label="left", closed="left").last() if not oi.empty else oi
    lp_bar = (long_pct.resample(rule, label="left", closed="left").mean()
              if not long_pct.empty else long_pct)
    bars["oi_level"] = oi_bar.reindex(bars.index) if not oi.empty else np.nan
    bars["long_pct"] = lp_bar.reindex(bars.index) if not long_pct.empty else np.nan
    return bars


# ---------------------------------------------------------------- freshness
def data_age_hours(frame_or_series) -> float:
    """Hours between now (UTC) and the most recent index timestamp. Empty ->
    +inf (treated as maximally stale)."""
    if frame_or_series is None or len(frame_or_series) == 0:
        return float("inf")
    last = frame_or_series.index.max()
    now = pd.Timestamp.utcnow().tz_localize(None)
    return (now - last).total_seconds() / 3600.0


def is_stale(last_ts, staleness_hours: float) -> bool:
    """True when the last data point is older than the threshold (or missing).
    last_ts may be a pandas Timestamp or None."""
    if last_ts is None:
        return True
    now = pd.Timestamp.utcnow().tz_localize(None)
    return (now - last_ts).total_seconds() / 3600.0 > staleness_hours


# ---------------------------------------------------------------- per-cycle cache
class CtaData:
    """One instance per rebalance cycle. Fetches and caches each coin's joined
    frame + per-source freshness so the loop pulls each source once per cycle
    (respecting the 40 req/min Coinalyze budget)."""

    def __init__(self, coins: list, lookback_bars: int):
        self.coins = coins
        self.lookback_bars = lookback_bars
        self._frames: dict[str, pd.DataFrame] = {}
        self._freshness: dict[str, dict] = {}
        self._symbols: dict[str, str] = {}

    def _coinalyze_symbol(self, coin: str) -> str:
        if coin not in self._symbols:
            self._symbols[coin] = resolve_coinalyze_symbol(coin)
        return self._symbols[coin]

    def frame_for(self, coin: str) -> pd.DataFrame:
        if coin in self._frames:
            return self._frames[coin]
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - self.lookback_bars * 4 * 3600_000
        start_s, end_s = start_ms // 1000, now_ms // 1000

        klines = parse_klines(fetch_klines(cfg.BINANCE_SYMBOLS[coin], cfg.TIMEFRAME,
                                           start_ms, now_ms, limit=1500))
        sym = self._coinalyze_symbol(coin)
        oi = parse_coinalyze_oi(fetch_coinalyze("/open-interest-history", sym, start_s, end_s))
        lp = parse_coinalyze_long_pct(fetch_coinalyze("/long-short-ratio-history", sym, start_s, end_s))

        frame = build_frame(klines, oi, lp, rule=cfg.TIMEFRAME)
        self._frames[coin] = frame
        self._freshness[coin] = {
            "klines_last": klines.index.max() if len(klines) else None,
            "oi_last": oi.index.max() if len(oi) else None,
            "long_pct_last": lp.index.max() if len(lp) else None,
        }
        return frame

    def is_coin_stale(self, coin: str, staleness_hours: float) -> bool:
        """True if ANY of the coin's three sources is stale/missing — a stale
        signal on any leg means we must not open new exposure on it."""
        f = self._freshness.get(coin, {})
        return any(is_stale(f.get(k), staleness_hours)
                   for k in ("klines_last", "oi_last", "long_pct_last"))
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_cta_data.py -v` — expect all PASS. The staleness tests are spec-critical.

- [ ] **Step 5: Commit** — `git add src/hlvault/cta/data.py tests/test_cta_data.py && git commit -m "feat: CTA data layer (Coinalyze + Binance, cached, cross-venue staleness)"`

---

### Task 4: `risk.py` — sizing, 2×ATR stop, MDD breaker (reuse `get_account_equity`)

**Files:**
- Create: `src/hlvault/cta/risk.py`
- Test: `tests/test_cta_risk.py`

Position sizing is fixed-notional (`NOTIONAL_PER_TRADE`), so sizing is trivial; the load-bearing pieces are the 2×ATR stop level/hit test and the MDD circuit breaker. The breaker **reuses** `gridbot.exchange_utils.get_account_equity` unchanged — this wallet holds only USDC + HL perp (no spot coin leg), which is exactly that function's basis; re-deriving it (or adding `withdrawable`) would re-open the carry double-count bug. `check_drawdown` is kept pure (returns updated state; the live loop persists — the caller obligation matches momentum's).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cta_risk.py
import pytest

from hlvault.cta import risk


class _FakeInfo:
    def __init__(self, positions, spot_usdc):
        self._positions = positions
        self._spot_usdc = spot_usdc

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}


def test_position_size_is_notional_over_price():
    assert abs(risk.position_size(100.0, price=50.0) - 2.0) < 1e-9
    assert risk.position_size(100.0, price=0.0) == 0.0  # guard divide-by-zero


def test_stop_level_short_is_above_entry_long_is_below():
    # SHORT (dir -1): stop = entry + mult*atr (above); LONG (dir 1): below
    assert risk.stop_level(direction=-1, entry_px=100.0, atr=5.0, mult=2.0) == 110.0
    assert risk.stop_level(direction=1, entry_px=100.0, atr=5.0, mult=2.0) == 90.0


def test_stop_hit_short_triggers_when_price_rises_to_stop():
    # short stop at 110; price 111 -> hit ; price 105 -> not hit
    assert risk.stop_hit(direction=-1, stop=110.0, price=111.0) is True
    assert risk.stop_hit(direction=-1, stop=110.0, price=105.0) is False


def test_stop_hit_long_triggers_when_price_falls_to_stop():
    assert risk.stop_hit(direction=1, stop=90.0, price=89.0) is True
    assert risk.stop_hit(direction=1, stop=90.0, price=95.0) is False


def test_account_equity_uses_gridbot_basis_usdc_plus_perp_only():
    # equity = spot USDC + sum(marginUsed + upnl). NO withdrawable (carry bug guard).
    info = _FakeInfo(positions=[
        {"coin": "BTC", "szi": "-0.01", "marginUsed": "300", "unrealizedPnl": "-5"},
    ], spot_usdc=700.0)
    assert abs(risk.account_equity(info, "0xabc") - (700.0 + 300.0 - 5.0)) < 1e-9


def test_check_drawdown_sets_peak_then_halts_past_threshold():
    info_peak = _FakeInfo([{"coin": "BTC", "szi": "-0.01", "marginUsed": "1000",
                            "unrealizedPnl": "0"}], spot_usdc=0.0)
    state = {"halted": False, "peak_equity": 0.0}
    halted, state = risk.check_drawdown(info_peak, "0xabc", state, 0.20)
    assert halted is False and state["peak_equity"] == 1000.0

    info_down = _FakeInfo([{"coin": "BTC", "szi": "-0.01", "marginUsed": "790",
                            "unrealizedPnl": "0"}], spot_usdc=0.0)
    halted, state = risk.check_drawdown(info_down, "0xabc", state, 0.20)
    assert halted is True and state["halted"] is True  # 21% dd


def test_check_drawdown_returns_true_immediately_when_already_halted():
    state = {"halted": True, "peak_equity": 1000.0}
    halted, out = risk.check_drawdown(_FakeInfo([], 0.0), "0xabc", state, 0.20)
    assert halted is True and out is state
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_cta_risk.py -v`.

- [ ] **Step 3: Implement**

```python
"""Position sizing, the strategy-level 2xATR hard stop, and the portfolio MDD
circuit breaker for the CTA engine.

Equity basis (CLAUDE.md #1): the MDD breaker's current and peak equity both
come from ONE call to gridbot.exchange_utils.get_account_equity (spot USDC +
sum(marginUsed + unrealizedPnl) across perp positions). This wallet holds only
USDC + HL perp positions (no spot-coin leg), so that basis is exactly right —
this is deliberately NOT carry's spot-coin-inclusive basis, and it does NOT add
`withdrawable` (adding withdrawable + margin + upnl is precisely the carry
double-count bug fixed 2026-07-04). Reuse get_account_equity; do not hand-roll."""
from __future__ import annotations

import logging

from hlvault.gridbot.exchange_utils import get_account_equity

logger = logging.getLogger("cta")


def position_size(notional: float, price: float) -> float:
    """Coin units for a fixed-notional entry. Non-positive price -> 0 (no
    order), NaN-safe via `not (price > 0)`."""
    if not (price > 0):
        return 0.0
    return notional / price


def stop_level(direction: int, entry_px: float, atr: float, mult: float) -> float:
    """2xATR hard-stop price. SHORT (dir -1): stop ABOVE entry (entry + mult*atr).
    LONG (dir 1): stop BELOW entry (entry - mult*atr). Matches the backtest's
    `entry_px - dir * STOP_ATR_MULT * atr`."""
    return entry_px - direction * mult * atr


def stop_hit(direction: int, stop: float, price: float) -> bool:
    """True when the live price has reached/breached the stop. SHORT stops out
    when price rises to/above stop; LONG stops out when price falls to/below."""
    if direction == -1:
        return price >= stop
    if direction == 1:
        return price <= stop
    return False


def account_equity(info, address: str) -> float:
    """Single equity basis for this wallet — see module docstring."""
    return get_account_equity(info, address)


def check_drawdown(info, address: str, state: dict, max_drawdown_pct: float):
    """Returns (should_halt, updated_state). Pure w.r.t. persistence: does NOT
    write state (kept testable) — the caller MUST persist immediately, ideally
    before any flatten, so a crash mid-flatten cannot lose the halt flag (same
    caller obligation as momentum.risk.check_drawdown). Current and peak equity
    come from the same account_equity call (CLAUDE.md #1)."""
    if state.get("halted"):
        return True, state
    current = account_equity(info, address)
    peak = max(state.get("peak_equity", 0.0), current)
    state["peak_equity"] = peak
    drawdown = (peak - current) / peak if peak > 0 else 0.0
    if drawdown >= max_drawdown_pct:
        logger.error(f"CTA DRAWDOWN CIRCUIT BREAKER: {drawdown:.1%} "
                    f"(peak ${peak:,.2f} -> now ${current:,.2f})")
        state["halted"] = True
        return True, state
    return False, state
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_cta_risk.py -v` — expect all PASS. `test_account_equity_uses_gridbot_basis_usdc_plus_perp_only` is the carry-bug regression guard.

- [ ] **Step 5: Commit** — `git add src/hlvault/cta/risk.py tests/test_cta_risk.py && git commit -m "feat: CTA risk (fixed-notional sizing, 2xATR stop, MDD breaker reusing get_account_equity)"`

---

### Task 5: `live.py` — CtaEngine loop + entry point

**Files:**
- Create: `src/hlvault/cta/live.py`
- Modify: `pyproject.toml` (`hl-cta = "hlvault.cta.live:main"` under `[project.scripts]`)
- Test: `tests/test_cta_live.py`

Key requirements (all proven patterns from momentum/live.py + carry/live.py — read both first):
- `check_drawdown`: delegate to `risk.check_drawdown`; persist halt BEFORE flatten; alert once (`_alerted_this_halt`); retry flatten until `_flatten_complete`; second alert on incomplete flatten (momentum's exact pattern).
- `_flatten_everything`: close every open HL position via `self.exchange.market_close` (reduce-only, idempotent, retried by ResilientExchange), dry-run gated, returns bool success; clears `state["entries"]` on full success.
- `_place_order(coin, is_buy, size, reduce_only)`: dry-run gated; aggressive IoC-limit at mid ± `ORDER_SLIPPAGE` rounded via `round_price`/`round_size`/`get_sz_decimals` (the momentum shape) through `ResilientExchange.order` (non-reduce-only opens are non-idempotent → single attempt, reconcile next cycle; reduce-only closes retry — the ResilientExchange handles this by `reduce_only`).
- `maybe_rebalance`: only every `REBALANCE_INTERVAL_HOURS`; build a `CtaData(universe, lookback)`; re-read HL positions as source of truth; for each coin, drop the last (possibly-open) bar so only CLOSED bars feed the signal, compute signals, then:
  - **exits/stops first, always** (even on stale data): for a coin with an open HL position, evaluate `signals.should_exit` + `risk.stop_hit` (live mid vs stored stop) + max-hold; close reduce-only if triggered; remove its `entries` record.
  - **new entries only when fresh**: if `data.is_coin_stale(coin, DATA_STALENESS_HOURS)`, skip NEW entry for that coin (log it) but never skip the exit/stop management above. Otherwise `signals.decide(...)` → if short/long and no existing position, size via `risk.position_size`, place the open order, and record `entries[coin] = {dir, entry_px, stop, entry_ms}`.
- `run_once`: bootstrap peak → drawdown gate (returns early if halted) → `maybe_rebalance`. `run_forever`: loop with `SYNC_INTERVAL_SECONDS` sleep so the breaker polls faster than the 4h rebalance.
- `main()` with `--once/--dry-run/--status`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cta_live.py
import pandas as pd
import pytest

from hlvault.cta import config as cfg
from hlvault.cta.live import CtaEngine


class _FakeInfo:
    def __init__(self, mid=100.0, positions=None, spot_usdc=1000.0, sz_decimals=3):
        self.mid = mid
        self._positions = positions or []
        self._spot_usdc = spot_usdc
        self._sz = sz_decimals

    def all_mids(self):
        return {c: str(self.mid) for c in ("BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP")}

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}

    def meta(self):
        return {"universe": [{"name": c, "szDecimals": self._sz, "maxLeverage": 20}
                             for c in ("BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP")]}


class _FakeExchange:
    def __init__(self):
        self.orders = []
        self.closed = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders.append({"coin": coin, "is_buy": is_buy, "size": size,
                            "px": px, "reduce_only": reduce_only})
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    def market_close(self, coin, size):
        self.closed.append((coin, size))
        return {"status": "ok"}


def _engine(info, exchange, live=True, state=None):
    e = CtaEngine.__new__(CtaEngine)
    e.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    e.exchange = ResilientExchange(exchange)
    e.live_trading = live
    e.state = state or {"halted": False, "peak_equity": 0.0,
                        "_alerted_this_halt": False, "_flatten_complete": False,
                        "last_rebalance_ms": 0, "entries": {}}
    return e


def test_place_order_dry_run_does_nothing(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=False)
    e._place_order("BTC", is_buy=False, size=1.0, reduce_only=False)
    assert ex.orders == []


def test_place_order_short_open_is_sell_not_reduce_only(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0, sz_decimals=3), ex, live=True)
    e._place_order("BTC", is_buy=False, size=1.23456, reduce_only=False)
    o = ex.orders[0]
    assert o["coin"] == "BTC" and o["is_buy"] is False and o["reduce_only"] is False
    assert o["size"] == 1.234  # rounded to szDecimals=3


def test_flatten_everything_closes_all_and_clears_entries(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(positions=[
        {"coin": "BTC", "szi": "-0.5", "marginUsed": "10", "unrealizedPnl": "0"},
        {"coin": "ETH", "szi": "-1.0", "marginUsed": "10", "unrealizedPnl": "0"},
    ])
    ex = _FakeExchange()
    e = _engine(info, ex, live=True,
                state={"halted": True, "peak_equity": 100.0, "_alerted_this_halt": True,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1}, "ETH": {"dir": -1}}})
    ok = e._flatten_everything()
    assert ok is True
    assert ("BTC", 0.5) in ex.closed and ("ETH", 1.0) in ex.closed


def test_flatten_dry_run_skips(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(positions=[{"coin": "BTC", "szi": "-0.5", "marginUsed": "10",
                                 "unrealizedPnl": "0"}])
    ex = _FakeExchange()
    e = _engine(info, ex, live=False)
    e._flatten_everything()
    assert ex.closed == []


def test_drawdown_halt_persists_before_flatten(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _Crashing(_FakeExchange):
        def market_close(self, coin, size):
            raise RuntimeError("boom")

    calls = {"n": 0}

    class _DropInfo(_FakeInfo):
        def user_state(self, address):
            calls["n"] += 1
            eq = 1000.0 if calls["n"] == 1 else 790.0
            return {"assetPositions": [{"position": {"coin": "BTC", "szi": "-0.5",
                    "marginUsed": str(eq), "unrealizedPnl": "0"}}]}

        def spot_user_state(self, address):
            return {"balances": []}

    e = _engine(_DropInfo(), _Crashing(), live=True)
    assert e.check_drawdown() is False   # sets peak 1000
    assert e.check_drawdown() is True    # 21% dd -> halt, flatten crashes
    from hlvault.cta.state import load_state
    assert load_state(cfg.STATE_FILE)["halted"] is True
    assert load_state(cfg.STATE_FILE)["_flatten_complete"] is False


def test_run_once_skips_rebalance_when_halted(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=True,
                state={"halted": True, "peak_equity": 1000.0, "_alerted_this_halt": True,
                       "_flatten_complete": True, "last_rebalance_ms": 0, "entries": {}})
    e.run_once()
    assert ex.orders == []


def _short_signal_frame():
    # downtrend + rising long_pct (crowd_long) + rising OI (fuel) over 130 4h bars
    import numpy as np
    n = 130
    idx = pd.date_range(pd.Timestamp.utcnow().floor("h") - pd.Timedelta(hours=4 * n),
                        periods=n, freq="4h")
    closes = 100 * 0.99 ** np.arange(n)
    return pd.DataFrame({"open": closes, "high": closes * 1.001, "low": closes * 0.999,
                         "close": closes, "oi_level": np.arange(n) + 10.0,
                         "long_pct": np.arange(n).astype(float)}, index=idx)


def test_maybe_rebalance_opens_short_on_fresh_short_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", ["BTC"])
    monkeypatch.setattr(cfg, "ENABLE_LONG", False)
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "REBALANCE_INTERVAL_HOURS", 4)
    monkeypatch.setattr(cfg, "NOTIONAL_PER_TRADE", 100.0)
    monkeypatch.setattr(cfg, "DATA_STALENESS_HOURS", 8)

    from hlvault.cta import data as data_mod

    class _FakeData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return False

    monkeypatch.setattr(data_mod, "CtaData", _FakeData)

    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=50.0, positions=[], sz_decimals=3), ex, live=True)
    e.maybe_rebalance()

    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["coin"] == "BTC" and o["is_buy"] is False and o["reduce_only"] is False
    assert "BTC" in e.state["entries"] and e.state["entries"]["BTC"]["dir"] == -1


def test_maybe_rebalance_skips_new_entry_when_stale_but_still_manages_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", ["BTC"])
    monkeypatch.setattr(cfg, "ENABLE_SHORT", True)
    monkeypatch.setattr(cfg, "REBALANCE_INTERVAL_HOURS", 4)
    monkeypatch.setattr(cfg, "DATA_STALENESS_HOURS", 8)
    monkeypatch.setattr(cfg, "STOP_ATR_MULT", 2.0)

    from hlvault.cta import data as data_mod

    class _StaleData:
        def __init__(self, coins, lookback_bars):
            pass

        def frame_for(self, coin):
            return _short_signal_frame()

        def is_coin_stale(self, coin, staleness_hours):
            return True   # stale -> no new entry

    monkeypatch.setattr(data_mod, "CtaData", _StaleData)

    # existing SHORT position whose stop (110) is breached by live mid 120 -> must close
    ex = _FakeExchange()
    info = _FakeInfo(mid=120.0, positions=[{"coin": "BTC", "szi": "-1.0",
                     "marginUsed": "50", "unrealizedPnl": "0"}], sz_decimals=3)
    e = _engine(info, ex, live=True,
                state={"halted": False, "peak_equity": 1000.0, "_alerted_this_halt": False,
                       "_flatten_complete": False, "last_rebalance_ms": 0,
                       "entries": {"BTC": {"dir": -1, "entry_px": 100.0, "stop": 110.0,
                                           "entry_ms": int(pd.Timestamp.utcnow().timestamp() * 1000)}}})
    e.maybe_rebalance()

    # no NEW open order, but the stopped-out short WAS closed (reduce-only) and entry cleared
    opens = [o for o in ex.orders if not o["reduce_only"]]
    assert opens == []
    assert ("BTC", 1.0) in ex.closed
    assert "BTC" not in e.state["entries"]


def test_init_raises_when_wallet_missing(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_PRIVATE_KEY", "")
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "")
    with pytest.raises(RuntimeError, match="WALLET_PRIVATE_KEY"):
        CtaEngine(live_trading=False)
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_cta_live.py -v`.

- [ ] **Step 3: Implement**

```python
"""Live CTA engine (sub-project G): short-carry family from phase-2b. Signals
from Binance-venue data (Coinalyze OI+LSR, Binance klines) via data.py;
execution on Hyperliquid perps via the aggressive-IoC-limit shape proven in
momentum/carry. The drawdown breaker is polled every SYNC_INTERVAL_SECONDS; the
signal recomputes/rebalances only every REBALANCE_INTERVAL_HOURS (4h bars —
rebalancing more often just churns on an unclosed bar).

Order shape: "market" = aggressive IoC limit at mid +/- ORDER_SLIPPAGE, rounded
to venue tick rules (round_price/round_size), the same shape momentum/live.py
documents. Non-reduce-only OPENS are non-idempotent -> single attempt through
ResilientExchange.order (a lost response self-heals next cycle when positions
are re-read from HL); reduce-only CLOSES are idempotent -> ResilientExchange
retries them.

Cross-venue staleness (spec): if a coin's Binance/Coinalyze data is stale we
skip NEW entries for it this cycle but STILL manage its existing exits/stops
from HL state and STILL run the portfolio drawdown breaker."""
from __future__ import annotations

import argparse
import logging
import time

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from hlvault.gridbot.exchange_utils import get_mid_price, get_sz_decimals, round_price, round_size
from hlvault.gridbot.resilience import ResilientExchange
from hlvault.notify.telegram import send_alert

from . import config as cfg
from . import data, risk, signals
from .state import load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cta")

LOOKBACK_BARS = 400  # >= crowd window (90d*6=540?) — see note below


class CtaEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.cta")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw)
        self.state = load_state(cfg.STATE_FILE)

    # ---- safety ------------------------------------------------------
    def bootstrap_if_needed(self) -> None:
        if self.state.get("peak_equity", 0.0) > 0:
            return
        equity = risk.account_equity(self.info, cfg.WALLET_ADDRESS)
        self.state["peak_equity"] = equity
        save_state(cfg.STATE_FILE, self.state)
        logger.info(f"bootstrap: starting equity ${equity:,.2f}")

    def check_drawdown(self) -> bool:
        halted, self.state = risk.check_drawdown(
            self.info, cfg.WALLET_ADDRESS, self.state, cfg.MAX_DRAWDOWN_PCT)
        if not halted:
            save_state(cfg.STATE_FILE, self.state)
            return False
        # persist halt BEFORE flatten (crash mid-flatten must not lose it)
        save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_alerted_this_halt"):
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                      "CTA DRAWDOWN CIRCUIT BREAKER TRIPPED — flattening and halting.")
            self.state["_alerted_this_halt"] = True
            save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_flatten_complete"):
            if self._flatten_everything():
                self.state["_flatten_complete"] = True
            else:
                send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                          "CTA FLATTEN INCOMPLETE — positions may remain, will retry next cycle.")
            save_state(cfg.STATE_FILE, self.state)
        return True

    def _flatten_everything(self) -> bool:
        """Close every open HL position (reduce-only, idempotent -> retried by
        ResilientExchange). Dry-run logs and skips. Returns True only when all
        confirmed closed; clears entries bookkeeping on full success."""
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        any_failed = False
        for p in user_state.get("assetPositions", []):
            pos = p["position"]
            size = float(pos["szi"])
            coin = pos["coin"]
            if abs(size) < 1e-9:
                continue
            if not self.live_trading:
                logger.info(f"[DRY RUN] would flatten {coin} size={abs(size)}")
                continue
            try:
                self.exchange.market_close(coin, abs(size))
            except Exception as e:
                any_failed = True
                logger.error(f"SAFETY-CRITICAL: flatten failed for {coin}: {e}")
        if not any_failed and self.live_trading:
            self.state["entries"] = {}
        return not any_failed

    # ---- execution ---------------------------------------------------
    def _place_order(self, coin: str, is_buy: bool, size: float, reduce_only: bool) -> None:
        if not self.live_trading:
            logger.info(f"[DRY RUN] {coin} is_buy={is_buy} size={size} reduce_only={reduce_only}")
            return
        try:
            mid = get_mid_price(self.info, coin)
            if mid <= 0:
                logger.warning(f"{coin}: no mid, skipping order this cycle")
                return
            sz_dec = get_sz_decimals(self.info, coin)
            raw_px = mid * (1 + cfg.ORDER_SLIPPAGE) if is_buy else mid * (1 - cfg.ORDER_SLIPPAGE)
            limit_px = round_price(raw_px, sz_dec)
            sz = round_size(size, sz_dec)
            if sz <= 0:
                return
            self.exchange.order(coin, is_buy, sz, limit_px,
                                order_type={"limit": {"tif": "Ioc"}}, reduce_only=reduce_only)
            logger.info(f"{coin}: placed is_buy={is_buy} size={sz} @ {limit_px} reduce_only={reduce_only}")
        except Exception as e:
            logger.error(f"{coin}: order failed: {e} (next cycle re-reconciles)")

    # ---- rebalance ---------------------------------------------------
    def maybe_rebalance(self) -> None:
        now_ms = int(time.time() * 1000)
        interval_ms = int(cfg.REBALANCE_INTERVAL_HOURS * 3600 * 1000)
        if now_ms - self.state.get("last_rebalance_ms", 0) < interval_ms:
            return

        feed = data.CtaData(cfg.COIN_UNIVERSE, LOOKBACK_BARS)
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        pos_by_coin = {p["position"]["coin"]: float(p["position"]["szi"])
                       for p in user_state.get("assetPositions", [])}
        entries = self.state.get("entries", {})

        crowd_window_bars = cfg.CROWD_WINDOW_DAYS * cfg.BARS_PER_DAY
        crowd_warmup_bars = cfg.CROWD_WARMUP_DAYS * cfg.BARS_PER_DAY
        fuel_lb_bars = max(1, round(cfg.FUEL_LOOKBACK_HOURS / 24 * cfg.BARS_PER_DAY))

        for coin in cfg.COIN_UNIVERSE:
            try:
                frame = feed.frame_for(coin)
            except Exception as e:
                logger.error(f"{coin}: data fetch failed ({e}); managing existing pos only")
                frame = None

            mid = get_mid_price(self.info, coin)
            cur_sz = pos_by_coin.get(coin, 0.0)
            direction = 1 if cur_sz > 0 else (-1 if cur_sz < 0 else 0)

            # closed-bar signal: drop the final (still-forming) bar
            sig = None
            if frame is not None and len(frame) > cfg.TREND_WARMUP_BARS + 2:
                closed = frame.iloc[:-1]
                sig = signals.compute_signals(
                    closed, ema_fast=cfg.EMA_FAST, ema_slow=cfg.EMA_SLOW,
                    trend_warmup_bars=cfg.TREND_WARMUP_BARS, crowd_pctile=cfg.CROWD_PCTILE,
                    crowd_window_bars=crowd_window_bars, crowd_warmup_bars=crowd_warmup_bars,
                    fuel_lookback_bars=fuel_lb_bars, atr_period=cfg.ATR_PERIOD)

            # 1. ALWAYS manage exits/stops on an existing position (even if stale)
            if abs(cur_sz) > 1e-9 and coin in entries:
                ent = entries[coin]
                held_days = (now_ms - ent.get("entry_ms", now_ms)) / 86400_000
                exit_reason = None
                if risk.stop_hit(direction, ent.get("stop", 0.0), mid):
                    exit_reason = "stop"
                elif sig is not None:
                    exit_reason = signals.should_exit(
                        direction, sig["trend_up"], sig["trend_dn"], sig["fuel"],
                        held_days, cfg.MAX_HOLD_DAYS)
                if exit_reason is not None:
                    logger.info(f"{coin}: exiting ({exit_reason})")
                    self._place_order(coin, is_buy=(direction == -1),
                                      size=abs(cur_sz), reduce_only=True)
                    entries.pop(coin, None)
                    continue  # exited; do not also open this cycle

            # 2. NEW entries only when data is fresh and no existing position
            if abs(cur_sz) > 1e-9:
                continue
            if frame is None or sig is None or feed.is_coin_stale(coin, cfg.DATA_STALENESS_HOURS):
                logger.info(f"{coin}: stale/no data -> skipping new entry this cycle")
                continue
            decision = signals.decide(
                sig["trend_up"], sig["trend_dn"], sig["crowd_long"], sig["crowd_short"],
                sig["fuel"], enable_long=cfg.ENABLE_LONG, enable_short=cfg.ENABLE_SHORT)
            if decision == "flat" or mid <= 0:
                continue
            d = -1 if decision == "short" else 1
            atr = sig["atr"]
            if atr != atr or atr <= 0:  # NaN or non-positive ATR -> can't set a stop, skip
                logger.info(f"{coin}: no valid ATR, skipping entry")
                continue
            size = risk.position_size(cfg.NOTIONAL_PER_TRADE, mid)
            if size <= 0:
                continue
            self._place_order(coin, is_buy=(d == 1), size=size, reduce_only=False)
            entries[coin] = {"dir": d, "entry_px": mid,
                             "stop": risk.stop_level(d, mid, atr, cfg.STOP_ATR_MULT),
                             "entry_ms": now_ms}

        self.state["entries"] = entries
        self.state["last_rebalance_ms"] = now_ms
        self.state["_alerted_this_halt"] = False
        self.state["_flatten_complete"] = False
        save_state(cfg.STATE_FILE, self.state)

    # ---- loop --------------------------------------------------------
    def run_once(self) -> None:
        self.bootstrap_if_needed()
        if self.check_drawdown():
            return
        self.maybe_rebalance()

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("cta cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = CtaEngine(live_trading=False if args.dry_run else None)
    if args.status:
        equity = risk.account_equity(engine.info, cfg.WALLET_ADDRESS)
        print(f"equity ${equity:,.2f} | halted={engine.state.get('halted')} "
              f"peak={engine.state.get('peak_equity')} "
              f"open_entries={list(engine.state.get('entries', {}).keys())} "
              f"long={cfg.ENABLE_LONG} short={cfg.ENABLE_SHORT}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
```

> **Implementer note on `LOOKBACK_BARS`:** the crowding percentile needs a
> full trailing window (`CROWD_WINDOW_DAYS * BARS_PER_DAY` = 90×6 = 540 bars)
> plus the 30d warmup before the rank is trusted. Set `LOOKBACK_BARS` to at
> least `CROWD_WINDOW_DAYS * BARS_PER_DAY + TREND_WARMUP_BARS + 8` (≈ 600) so
> the last closed bar has a fully-formed percentile window; one Binance klines
> request (limit 1500) and one Coinalyze chunk cover this comfortably. Adjust
> the constant to `cfg.CROWD_WINDOW_DAYS * cfg.BARS_PER_DAY + 60` computed at
> import if you prefer — either is fine, just ensure it is not smaller than the
> crowd window, or `crowd_percentile` returns NaN and no coin ever trades. The
> tests use a 130-bar synthetic frame with `crowd_window_bars=90*6`; because
> `min_periods=30*6=180 > 130`, verify the signal test frames are sized so the
> percentile is non-NaN — the provided `_short_signal_frame` uses 130 bars, so
> in `test_maybe_rebalance_opens_short_on_fresh_short_signal` the percentile
> min_periods must be satisfied: if the open-short test yields flat because the
> percentile is NaN, increase the synthetic frame length to ≥ `30*6+1` bars
> (fix the TEST fixture length, not the production window).

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_cta_live.py -v`. The two `maybe_rebalance` tests are load-bearing: the fresh-signal test proves a short opens with `entries` recorded; the stale test proves new entries are skipped while the stopped-out short is still closed reduce-only (the spec's cross-venue-staleness behavior).

- [ ] **Step 5: Add entry point + reinstall + full suite**

Add under `[project.scripts]` in `pyproject.toml`: `hl-cta = "hlvault.cta.live:main"`.
Run: `.venv/bin/pip install -e . -q && .venv/bin/pytest -q` — all green.

- [ ] **Step 6: Commit** — `git add src/hlvault/cta/live.py tests/test_cta_live.py pyproject.toml && git commit -m "feat: CTA live engine + hl-cta entry point (sub-project G)"`

---

### Task 6: wallet setup helper (thin) + deploy files

**Files:**
- Create: `scripts/setup_cta_wallet.py`
- Create: `deploy/hl-cta.service` (mirror `deploy/hl-momentum.service`)
- Create: `deploy/setup-cta.sh` (mirror `deploy/setup-momentum.sh`)

The setup helper is **thin and read-only by design**: the agent key cannot do class-transfers (documented in the spec), so it does NOT move funds — it only verifies the wallet is pure-USDC perp-funded and reports the equity/margin picture and how many concurrent $NOTIONAL_PER_TRADE positions it can support. Any actual funding decision is an owner/coordinator action at execution time.

- [ ] **Step 1: Write `scripts/setup_cta_wallet.py`**

```python
"""Read-only wallet check for the CTA engine. The agent key CANNOT perform
USD class-transfers (master-key only — same limit hit by the carry setup), so
this helper deliberately moves NOTHING. It verifies the wallet is funded with
USDC + HL perp margin (the basis risk.account_equity expects) and reports how
many concurrent NOTIONAL_PER_TRADE positions the current equity supports, so a
human can decide funding at execution time.

    python scripts/setup_cta_wallet.py          # print the picture (never transfers)

RED-LINE: never prints private keys; reads only public account state.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hyperliquid.info import Info  # noqa: E402

from hlvault.cta import config as cfg  # noqa: E402
from hlvault.cta import risk  # noqa: E402


def main() -> None:
    if not cfg.WALLET_ADDRESS:
        print("WALLET_ADDRESS not set in .env.cta — nothing to check.")
        return
    info = Info(cfg.HL_API_URL, skip_ws=True)
    equity = risk.account_equity(info, cfg.WALLET_ADDRESS)

    perp = info.user_state(cfg.WALLET_ADDRESS)
    spot = info.spot_user_state(cfg.WALLET_ADDRESS)
    spot_usdc = next((float(b.get("total", 0.0)) for b in spot.get("balances", [])
                      if b.get("coin") == "USDC"), 0.0)
    spot_non_usdc = [b for b in spot.get("balances", [])
                     if b.get("coin") != "USDC" and float(b.get("total", 0.0)) > 0]
    open_positions = [p["position"]["coin"] for p in perp.get("assetPositions", [])
                      if abs(float(p["position"]["szi"])) > 1e-9]

    print(f"CTA wallet {cfg.WALLET_ADDRESS}")
    print(f"  account equity (USDC + perp margin+upnl): ${equity:,.2f}")
    print(f"  spot USDC: ${spot_usdc:,.2f}")
    print(f"  open perp positions: {open_positions or 'none'}")
    print(f"  NOTIONAL_PER_TRADE ${cfg.NOTIONAL_PER_TRADE:,.0f} -> "
          f"~{int(equity // cfg.NOTIONAL_PER_TRADE) if cfg.NOTIONAL_PER_TRADE else 0} "
          f"concurrent positions supportable")
    if spot_non_usdc:
        coins = ", ".join(f"{b['coin']}={b['total']}" for b in spot_non_usdc)
        print(f"  WARNING: non-USDC spot balances present ({coins}). This engine "
              f"expects a pure-USDC perp-funded wallet; equity basis assumes no "
              f"spot-coin leg. Resolve before going live.")
    else:
        print("  OK: no non-USDC spot balances (pure-USDC perp basis holds).")
    print("\nThis helper does NOT transfer funds (agent key cannot class-transfer). "
          "Any funding/transfer is an owner decision at execution time.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create the two deploy files** by copying the momentum ones and substituting names: `hl-momentum` → `hl-cta`, `.env.momentum` → `.env.cta`, `hlvault.momentum` → `hlvault.cta`, `momentum-trading` → `cta-short-carry`. In `deploy/hl-cta.service` set `Description=Hyperliquid independent CTA short-carry bot (hlvault.cta)`, `EnvironmentFile=/home/ubuntu/vault/.env.cta`, `ExecStart=/home/ubuntu/vault/.venv/bin/hl-cta`, `SyslogIdentifier=hl-cta`, keep `MemoryMax=256M`. In `deploy/setup-cta.sh` substitute every `momentum` → `cta` (variable names, paths, service name, tips). `chmod +x deploy/setup-cta.sh`. Validate: `bash -n deploy/setup-cta.sh`.

- [ ] **Step 3: Commit** — `git add scripts/setup_cta_wallet.py deploy/hl-cta.service deploy/setup-cta.sh && git commit -m "chore: CTA wallet check helper + deploy files (sub-project G)"`

---

### Task 7 (OWNER/COORDINATOR DECISION — do not execute as implementer): `.env.cta`, go-live gate

Every step here touches real money or real credentials and is explicitly reserved for the owner/main conversation per CLAUDE.md's 實盤紅線. The implementer must NOT perform any of these; leave them unchecked for the coordinator.

- [ ] **[COORDINATOR]** Create `.env.cta` (repurposed carry wallet creds after the carry health check; `LIVE_TRADING=false`, `ENABLE_LONG=false`, `ENABLE_SHORT=true`, Coinalyze key already lives in `.env.research`, Telegram keys). Never committed; chmod 600.
- [ ] **[COORDINATOR]** `.venv/bin/python scripts/setup_cta_wallet.py` → confirm pure-USDC perp basis and supportable position count. (Read-only; safe, but interprets a real wallet — coordinator runs it.)
- [ ] **[COORDINATOR]** Signal-reproduction check: run the phase-2b script's signal on a fixed fixture and confirm `signals.compute_signals` yields the same trend/crowd/fuel/decision for that bar (execution-correctness gate, not a PnL gate).
- [ ] **[COORDINATOR]** `.venv/bin/hl-cta --status` then `.venv/bin/hl-cta --dry-run --once`: sane `[DRY RUN]` short-only intended orders, correct equity readout, no exceptions, staleness handling logged.
- [ ] **[COORDINATOR / OWNER]** Flip `LIVE_TRADING=true` (short-only), start `hl-cta`, watch the first live cycle, verify the entry order(s) landed and `--status` shows the expected open short(s). Deploying/starting the service is a red-line action.
- [ ] **[COORDINATOR]** Report to owner; note this is a labeled forward-test of an in-sample-best config (NO-GO on the multiple-testing bar), capped by the 20% MDD breaker and the small book.

---

## Self-review

**Spec requirement → task coverage:**

| Spec requirement | Task / symbol |
| --- | --- |
| `.env.cta` via `dotenv_values` isolated dict; Coinalyze key from `.env.research` | Task 1 `config.py` (`_FILE_VALUES`, `_RESEARCH_VALUES`) |
| `ENABLE_LONG`/`ENABLE_SHORT` default long=false/short=true | Task 1 `config.py`; enforced in Task 2 `signals.decide` |
| EMA periods, percentile, fuel lookback, NOTIONAL_PER_TRADE, universe, 20% MDD, SYNC_INTERVAL, Coinalyze/Binance/Telegram/STATE_FILE | Task 1 `config.py` (all named constants) |
| state schema mirrors momentum + `last_rebalance_ms` | Task 1 `state.py` (+ `entries` for stop/max-hold) |
| pure EMA20/50 trend, rolling-90d percentile crowding, OI-fuel gate, per-coin long/short/flat with side switches; matches phase-2b | Task 2 `signals.py` (`ema_trend`/`crowd_percentile`/`fuel_ok`/`atr`/`compute_signals`/`decide`/`should_exit`) |
| contrarian crowded-long → short not inverted | Task 2 tests `test_decide_crowded_long_downtrend_fuel_gives_SHORT`, `test_compute_signals_end_to_end_matches_direction` |
| Coinalyze OI+LSR + Binance klines fetch, cached, via `resilient_read`; freshness check | Task 3 `data.py` (`fetch_klines`/`fetch_coinalyze`/`build_frame`/`CtaData`/`data_age_hours`/`is_stale`/`is_coin_stale`) |
| position sizing, 2×ATR(14) stop, MDD breaker reusing `gridbot.get_account_equity` (no carry double-count) | Task 4 `risk.py` (`position_size`/`stop_level`/`stop_hit`/`account_equity`/`check_drawdown`); test `test_account_equity_uses_gridbot_basis_usdc_plus_perp_only` |
| CtaEngine cycle loop, entry/exit/stop, reconciliation, halt/flatten/alert/dry-run gate | Task 5 `live.py` (`run_once`/`maybe_rebalance`/`check_drawdown`/`_flatten_everything`/`_place_order`) |
| cross-venue stale data → skip new entries, still manage existing + run breaker | Task 5 `maybe_rebalance` (exits/stops before staleness check; entry gated on `is_coin_stale`); test `test_maybe_rebalance_skips_new_entry_when_stale_but_still_manages_exits` |
| `hl-cta` entry point | Task 5 `pyproject.toml` |
| thin setup helper (no transfer, agent key can't transfer) | Task 6 `scripts/setup_cta_wallet.py` |
| deploy service + setup script | Task 6 `deploy/hl-cta.service`, `deploy/setup-cta.sh` |
| execution-correctness go-live gate (signal reproduction, dry-run, then live short-only) | Task 7 (coordinator-only) |

**Type / signature consistency across tasks:**
- `signals.compute_signals(bars, *, ema_fast, ema_slow, trend_warmup_bars, crowd_pctile, crowd_window_bars, crowd_warmup_bars, fuel_lookback_bars, atr_period) -> dict{trend_up,trend_dn,crowd_long,crowd_short,fuel,atr,close}` — same keyword names in Task 2 tests and Task 5 `maybe_rebalance` call site.
- `signals.decide(trend_up, trend_dn, crowd_long, crowd_short, fuel, *, enable_long, enable_short) -> str` — identical in Task 2 tests and Task 5.
- `signals.should_exit(direction, trend_up, trend_dn, fuel, held_days, max_hold_days) -> str|None` — Task 2 tests and Task 5.
- `risk.position_size(notional, price)`, `risk.stop_level(direction, entry_px, atr, mult)`, `risk.stop_hit(direction, stop, price)`, `risk.account_equity(info, address)`, `risk.check_drawdown(info, address, state, max_drawdown_pct) -> (bool, dict)` — Task 4 tests and Task 5 call sites match.
- `data.CtaData(coins, lookback_bars)` with `.frame_for(coin)` and `.is_coin_stale(coin, staleness_hours)` — Task 3 tests and Task 5 (patched in Task 5 tests) match.
- `state.default_state()` keys (`halted/peak_equity/_alerted_this_halt/_flatten_complete/last_rebalance_ms/entries`) — Task 1 and every engine `_engine(...)` fixture in Task 5.
- `entries[coin] = {"dir", "entry_px", "stop", "entry_ms"}` — written in Task 5 `maybe_rebalance`, read in the stop/max-hold block, asserted in Task 1 roundtrip and Task 5 tests.
- Equity basis is single-sourced: `risk.account_equity` → `gridbot.exchange_utils.get_account_equity`; the breaker's current and peak both derive from it (CLAUDE.md #1).

**Placeholder scan:** run `grep -niE "TODO|placeholder|fill in|TBD" docs/superpowers/plans/2026-07-04-cta-live-engine-plan.md` — expect no matches (the string "fill" only appears as "filled"/"formed" in prose, which does not match "fill in").
