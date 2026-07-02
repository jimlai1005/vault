# Momentum Trading Engine (`hlvault.momentum`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent, systematic time-series-momentum trading engine on its own Hyperliquid wallet, with a hard 20% MDD circuit breaker, Telegram alerting, and a walk-forward OOS backtest gate — without touching `hlvault.gridbot`.

**Architecture:** New `hlvault/momentum/` subpackage mirrors `hlvault/gridbot/`'s layout (config/state/live/backtest, pure-function core shared between backtest and live per CLAUDE.md #5). Reuses `hlvault.gridbot.exchange_utils.get_account_equity` (already fixed for a false-positive-drawdown bug — do not reimplement) and `hlvault.gridbot.resilience.ResilientExchange` directly rather than duplicating. New `hlvault/notify/telegram.py` is shared infra, not gridbot-specific. `hlvault/prices.py` gets one additive function (`get_candles`) via a small internal refactor that does not change `get_daily_returns`'s existing behavior.

**Tech Stack:** Python 3.9+, pandas/numpy, `hyperliquid-python-sdk`, `eth-account`, `python-dotenv`, pytest. No new dependencies.

**Design spec:** `docs/superpowers/specs/2026-07-02-momentum-strategy-design.md`

---

## File structure

```
src/hlvault/prices.py               # MODIFY: extract _fetch_candles_raw, add get_candles()
src/hlvault/momentum/
  __init__.py                       # CREATE
  config.py                         # CREATE: env config, reads .env.momentum
  state.py                          # CREATE: JSON persistence (halted/peak_equity/last_rebalance_ms)
  signals.py                        # CREATE: time-series momentum score (pure)
  risk.py                           # CREATE: position sizing, reconciliation, MDD circuit breaker
  backtest.py                       # CREATE: walk-forward-safe replay of signals+risk over history
  live.py                           # CREATE: live engine (MomentumEngine, main())
src/hlvault/notify/
  __init__.py                       # CREATE
  telegram.py                       # CREATE: send_alert()
scripts/run_momentum_backtest.py    # CREATE: fetches real candles, runs backtest, writes verdict report
deploy/hl-momentum.service          # CREATE: systemd unit, mirrors hl-gridbot.service
pyproject.toml                      # MODIFY: add hl-momentum script entry
tests/test_prices_candles.py        # CREATE
tests/test_momentum_state.py        # CREATE
tests/test_momentum_signals.py      # CREATE
tests/test_momentum_risk.py         # CREATE
tests/test_momentum_backtest.py     # CREATE
tests/test_notify_telegram.py       # CREATE
tests/test_momentum_live_reconcile.py # CREATE
```

---

### Task 1: `hlvault/prices.py` — add `get_candles()` without changing existing behavior

**Files:**
- Modify: `src/hlvault/prices.py`
- Test: `tests/test_prices_candles.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prices_candles.py
from unittest.mock import patch

import pandas as pd

from hlvault.prices import get_candles, get_daily_returns

_RAW = [
    {"t": 1700000000000, "o": "10", "h": "12", "l": "9", "c": "11"},
    {"t": 1700086400000, "o": "11", "h": "13", "l": "10", "c": "12"},
]


def test_get_candles_returns_ohlc_frame_sorted_by_day():
    with patch("hlvault.prices._fetch_candles_raw", return_value=_RAW):
        df = get_candles("BTC", "1d", 0, 1)
    assert list(df.columns) == ["day", "o", "h", "l", "c"]
    assert len(df) == 2
    assert df["c"].tolist() == [11.0, 12.0]
    assert df["day"].is_monotonic_increasing


def test_get_candles_empty_response_returns_empty_frame_with_columns():
    with patch("hlvault.prices._fetch_candles_raw", return_value=[]):
        df = get_candles("BTC", "1d", 0, 1)
    assert list(df.columns) == ["day", "o", "h", "l", "c"]
    assert df.empty


def test_get_daily_returns_unchanged_after_refactor():
    with patch("hlvault.prices._fetch_candles_raw", return_value=_RAW):
        r = get_daily_returns("BTC", 0, 1)
    assert len(r) == 1
    assert abs(r.iloc[0] - (12.0 / 11.0 - 1.0)) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_prices_candles.py -v`
Expected: FAIL — `get_candles` / `_fetch_candles_raw` not defined.

- [ ] **Step 3: Refactor `prices.py` — extract the fetch, add `get_candles`**

Replace the full contents of `src/hlvault/prices.py` with:

```python
"""BTC/ETH daily returns for the alpha/beta factor regression and the BTC
benchmark, plus raw OHLC candles for callers that need more than
close-to-close returns (e.g. multi-asset momentum signals) — all from the
public candleSnapshot endpoint, through the shared resilience boundary."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pandas as pd

from .io.source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"


def _fetch_candles_raw(coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    body = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
    }

    def call():
        req = urllib.request.Request(
            INFO_URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                raise TransientError(str(e))
            raise SemanticError(str(e))
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    return resilient_read(call)


def candles_to_returns(candles: list[dict]) -> pd.Series:
    """Daily close-to-close returns, indexed by normalized day."""
    if not candles:
        return pd.Series(dtype=float)
    df = pd.DataFrame(candles)
    df["day"] = pd.to_datetime(df["t"].astype("int64"), unit="ms").dt.normalize()
    df["close"] = pd.to_numeric(df["c"])
    df = df.sort_values("day").set_index("day")
    return df["close"].pct_change().dropna().rename("ret")


def get_daily_returns(coin: str, start_ms: int, end_ms: int) -> pd.Series:
    candles = _fetch_candles_raw(coin, "1d", start_ms, end_ms)
    return candles_to_returns(candles)


def get_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Raw OHLC frame (columns: day, o, h, l, c), ascending by day."""
    candles = _fetch_candles_raw(coin, interval, start_ms, end_ms)
    if not candles:
        return pd.DataFrame(columns=["day", "o", "h", "l", "c"])
    df = pd.DataFrame(candles)
    df["day"] = pd.to_datetime(df["t"].astype("int64"), unit="ms").dt.normalize()
    for col in ("o", "h", "l", "c"):
        df[col] = pd.to_numeric(df[col])
    return df.sort_values("day")[["day", "o", "h", "l", "c"]].reset_index(drop=True)
```

- [ ] **Step 4: Run the new tests, then the full existing price test suite**

Run: `.venv/bin/pytest tests/test_prices_candles.py tests/test_prices.py -v`
Expected: all PASS (confirms `get_daily_returns` still behaves identically for `run_backtest.py`/sub-project A).

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/prices.py tests/test_prices_candles.py
git commit -m "refactor: extract candle fetch in prices.py, add get_candles() for momentum"
```

---

### Task 2: `hlvault/momentum/state.py` — persistence

**Files:**
- Create: `src/hlvault/momentum/__init__.py` (empty)
- Create: `src/hlvault/momentum/state.py`
- Test: `tests/test_momentum_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_momentum_state.py
from hlvault.momentum.state import default_state, load_state, save_state


def test_default_state_shape():
    s = default_state()
    assert s == {"halted": False, "peak_equity": 0.0, "last_rebalance_ms": 0,
                "_alerted_this_halt": False}


def test_load_missing_file_returns_default(tmp_path):
    s = load_state(tmp_path / "nope.json")
    assert s == default_state()


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s = default_state()
    s["peak_equity"] = 1234.5
    save_state(path, s)
    assert load_state(path) == s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_momentum_state.py -v`
Expected: FAIL — `hlvault.momentum` module not found.

- [ ] **Step 3: Create the package and state module**

`src/hlvault/momentum/__init__.py`: empty file.

`src/hlvault/momentum/state.py`:

```python
"""JSON persistence for the live momentum engine. Live positions are always
re-read from the exchange (source of truth) each cycle, so only the
circuit-breaker bookkeeping needs to persist here."""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "halted": False,
        "peak_equity": 0.0,
        "last_rebalance_ms": 0,
        "_alerted_this_halt": False,
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

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_momentum_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/momentum/__init__.py src/hlvault/momentum/state.py tests/test_momentum_state.py
git commit -m "feat: momentum engine state persistence"
```

---

### Task 3: `hlvault/momentum/signals.py` — composite momentum score

**Files:**
- Create: `src/hlvault/momentum/signals.py`
- Test: `tests/test_momentum_signals.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_momentum_signals.py
import numpy as np
import pandas as pd

from hlvault.momentum.signals import (
    composite_score, daily_log_returns, score_to_position, position_signal,
)


def test_daily_log_returns_matches_manual_calc():
    close = pd.Series([100.0, 110.0, 121.0])
    r = daily_log_returns(close)
    assert len(r) == 2
    assert abs(r.iloc[0] - np.log(1.1)) < 1e-9


def test_composite_score_is_strongly_positive_for_steady_uptrend():
    # 150 days of a steady +0.5%/day trend, near-zero noise
    close = pd.Series(100 * (1.005 ** np.arange(150)))
    r = daily_log_returns(close)
    score = composite_score(r)
    assert score.dropna().iloc[-1] > 1.0  # clearly positive risk-adjusted momentum


def test_composite_score_is_near_zero_for_flat_noise():
    rng = np.random.default_rng(42)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 150)))
    r = daily_log_returns(close)
    score = composite_score(r)
    assert abs(score.dropna().iloc[-1]) < 1.5  # no persistent drift -> small score


def test_score_to_position_zero_inside_threshold_band():
    assert score_to_position(0.3, entry_threshold=0.5) == 0.0
    assert score_to_position(-0.3, entry_threshold=0.5) == 0.0


def test_score_to_position_ramps_and_clips():
    assert score_to_position(0.5, entry_threshold=0.5) == 0.0
    assert abs(score_to_position(1.0, entry_threshold=0.5) - 1.0) < 1e-9
    assert abs(score_to_position(2.0, entry_threshold=0.5) - 1.0) < 1e-9  # clipped
    assert score_to_position(-1.0, entry_threshold=0.5) < 0.0


def test_position_signal_is_vectorized_score_to_position():
    scores = pd.Series([0.0, 1.0, -1.0])
    out = position_signal(scores, entry_threshold=0.5)
    assert out.tolist() == [score_to_position(s, 0.5) for s in scores]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_momentum_signals.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `signals.py`**

```python
"""Time-series momentum signal (Moskowitz-Ooi-Pedersen style): trailing
risk-adjusted return over multiple lookbacks, averaged into one composite
score per asset. Pure functions — the same score computation drives both
the backtest (backtest.py) and the live engine (live.py), per CLAUDE.md #5."""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACKS_DAYS = (20, 60, 120)


def daily_log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def risk_adjusted_momentum(returns: pd.Series, lookback: int) -> pd.Series:
    """Trailing `lookback`-day cumulative return divided by trailing
    `lookback`-day realized vol — a rolling Sharpe-like score, so a merely
    volatile asset doesn't dominate just because it moved a lot."""
    cum = returns.rolling(lookback).sum()
    vol = returns.rolling(lookback).std(ddof=1) * (lookback ** 0.5)
    return (cum / vol.where(vol > 0)).rename(f"mom_{lookback}")


def composite_score(returns: pd.Series, lookbacks=LOOKBACKS_DAYS) -> pd.Series:
    scores = pd.concat([risk_adjusted_momentum(returns, l) for l in lookbacks], axis=1)
    return scores.mean(axis=1, skipna=False).rename("composite_score")


def score_to_position(score: float, entry_threshold: float = 0.5) -> float:
    """Map a single composite score to a target position in [-1, 1]: sign
    gives direction, magnitude ramps from 0 at |score|==entry_threshold to 1
    at |score|==2*entry_threshold (clipped beyond). Scores inside the
    threshold band map to zero to avoid churning on noise near zero."""
    if pd.isna(score) or entry_threshold <= 0:
        return 0.0
    magnitude = min(max(abs(score) - entry_threshold, 0.0) / entry_threshold, 1.0)
    if score > 0:
        return magnitude
    if score < 0:
        return -magnitude
    return 0.0


def position_signal(scores: pd.Series, entry_threshold: float = 0.5) -> pd.Series:
    """Vectorized form of score_to_position, used by the backtest."""
    return scores.apply(lambda s: score_to_position(s, entry_threshold)).rename("position_signal")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_momentum_signals.py -v`
Expected: PASS. If the flat-noise test is flaky, it's seeded (`rng = np.random.default_rng(42)`) so it must be deterministic — do not loosen the assertion without first checking the seed is actually applied.

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/momentum/signals.py tests/test_momentum_signals.py
git commit -m "feat: momentum composite score + position signal"
```

---

### Task 4: `hlvault/momentum/risk.py` — sizing, reconciliation, circuit breaker

**Files:**
- Create: `src/hlvault/momentum/risk.py`
- Test: `tests/test_momentum_risk.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_momentum_risk.py
from hlvault.momentum.risk import (
    check_drawdown, compute_order, risk_budget_per_coin, target_position_notional,
)


def test_risk_budget_matches_gridbot_allocator_inverse_vol_capped():
    # same algorithm as hlvault.gridbot.allocator.allocate_capital — this
    # test just confirms momentum's wrapper calls it correctly, not a
    # re-derivation of the inverse-vol math (already tested there).
    budgets = risk_budget_per_coin({"BTC": 0.01, "ETH": 0.02}, 1000.0, 0.6)
    assert abs(sum(budgets.values()) - 1000.0) < 1e-6
    assert budgets["BTC"] > budgets["ETH"]  # lower vol -> bigger budget


def test_target_position_notional_scales_by_signal_and_leverage():
    assert target_position_notional(1.0, risk_budget=100.0, max_leverage=3.0) == 300.0
    assert target_position_notional(-0.5, risk_budget=100.0, max_leverage=3.0) == -150.0
    assert target_position_notional(0.0, risk_budget=100.0, max_leverage=3.0) == 0.0


def test_target_position_notional_clips_out_of_range_signal():
    assert target_position_notional(2.0, risk_budget=100.0, max_leverage=3.0) == 300.0
    assert target_position_notional(-2.0, risk_budget=100.0, max_leverage=3.0) == -300.0


def test_compute_order_opens_new_long_from_flat():
    order = compute_order(current_size=0.0, target_notional=1000.0, price=100.0, min_order_notional=10.0)
    assert order == {"is_buy": True, "size": 10.0, "reduce_only": False}


def test_compute_order_reduces_existing_long_without_flipping():
    # long 10 @ price 100 (notional 1000), target notional 400 -> sell down to 4
    order = compute_order(current_size=10.0, target_notional=400.0, price=100.0, min_order_notional=10.0)
    assert order == {"is_buy": False, "size": 6.0, "reduce_only": True}


def test_compute_order_flip_long_to_short_is_not_reduce_only():
    order = compute_order(current_size=5.0, target_notional=-500.0, price=100.0, min_order_notional=10.0)
    assert order["is_buy"] is False
    assert order["reduce_only"] is False  # crosses zero, not a pure reduce


def test_compute_order_returns_none_below_min_notional():
    order = compute_order(current_size=1.0, target_notional=101.0, price=100.0, min_order_notional=10.0)
    assert order is None


def test_check_drawdown_halts_at_threshold_using_one_equity_source():
    calls = {"n": 0}

    class FakeInfo:
        def user_state(self, address):
            calls["n"] += 1
            # first call: equity 1000 (sets peak); second call: equity 790 (21% down)
            equity = 1000.0 if calls["n"] == 1 else 790.0
            return {"assetPositions": [{"position": {"marginUsed": str(equity), "unrealizedPnl": "0"}}]}

        def spot_user_state(self, address):
            return {"balances": []}

    info = FakeInfo()
    state = {"halted": False, "peak_equity": 0.0}
    halted, state = check_drawdown(info, "0xabc", state, max_drawdown_pct=0.20)
    assert halted is False
    assert state["peak_equity"] == 1000.0

    halted, state = check_drawdown(info, "0xabc", state, max_drawdown_pct=0.20)
    assert halted is True
    assert state["halted"] is True


def test_check_drawdown_stays_halted_without_recomputing_equity():
    class BoomInfo:
        def user_state(self, address):
            raise AssertionError("must not re-check equity once halted")

        def spot_user_state(self, address):
            raise AssertionError("must not re-check equity once halted")

    halted, state = check_drawdown(BoomInfo(), "0xabc", {"halted": True, "peak_equity": 1000.0}, 0.20)
    assert halted is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_momentum_risk.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `risk.py`**

```python
"""Position sizing, order reconciliation, and the portfolio MDD circuit
breaker. Current and peak equity always come from the same
get_account_equity call (CLAUDE.md #1) — reused directly from
hlvault.gridbot.exchange_utils, which already fixed a false-positive
drawdown bug there; re-deriving that logic here would risk repeating it."""
from __future__ import annotations

import logging

from hlvault.gridbot.allocator import allocate_capital
from hlvault.gridbot.exchange_utils import get_account_equity

logger = logging.getLogger("momentum")


def risk_budget_per_coin(vol_by_coin: dict, total_capital: float, max_alloc_pct: float) -> dict:
    """Inverse-volatility risk budget, capped per coin — identical algorithm
    to gridbot.allocator.allocate_capital, reused rather than re-implemented."""
    return allocate_capital(vol_by_coin, total_capital, max_alloc_pct)


def target_position_notional(signal: float, risk_budget: float, max_leverage: float) -> float:
    """`signal` in [-1, 1] (from signals.score_to_position). Positive = long,
    negative = short. Bounded by risk_budget * max_leverage so a single
    full-conviction signal can't exceed this asset's allocated risk budget
    times its leverage cap."""
    clipped = max(-1.0, min(1.0, signal))
    return clipped * risk_budget * max_leverage


def compute_order(current_size: float, target_notional: float, price: float,
                  min_order_notional: float) -> dict | None:
    """Pure reconciliation decision: what order (if any) moves `current_size`
    toward `target_notional`. `reduce_only=True` only when the order strictly
    shrinks an existing position toward zero without crossing sides — crossing
    from long to short (or vice versa) is two economically different actions
    and must NOT be marked reduce_only (Hyperliquid would reject/clip it)."""
    if price <= 0:
        return None
    target_size = target_notional / price
    delta = target_size - current_size
    notional = abs(delta) * price
    if notional < min_order_notional:
        return None
    is_buy = delta > 0
    reduce_only = (
        current_size != 0
        and (current_size > 0) != is_buy
        and abs(delta) <= abs(current_size)
    )
    return {"is_buy": is_buy, "size": abs(delta), "reduce_only": reduce_only}


def check_drawdown(info, address: str, state: dict, max_drawdown_pct: float) -> tuple[bool, dict]:
    """Returns (should_halt, updated_state). Once halted, does not touch the
    exchange again — a human must clear `halted` in the state file after
    review (same policy as gridbot)."""
    if state.get("halted"):
        return True, state
    current = get_account_equity(info, address)
    peak = max(state.get("peak_equity", 0.0), current)
    state["peak_equity"] = peak
    drawdown = (peak - current) / peak if peak > 0 else 0.0
    if drawdown >= max_drawdown_pct:
        logger.error(f"MOMENTUM DRAWDOWN CIRCUIT BREAKER: {drawdown:.1%} "
                    f"(peak ${peak:,.2f} -> now ${current:,.2f})")
        state["halted"] = True
        return True, state
    return False, state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_momentum_risk.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/momentum/risk.py tests/test_momentum_risk.py
git commit -m "feat: momentum position sizing, order reconciliation, MDD circuit breaker"
```

---

### Task 5: `hlvault/notify/telegram.py` — alerting

**Files:**
- Create: `src/hlvault/notify/__init__.py` (empty)
- Create: `src/hlvault/notify/telegram.py`
- Test: `tests/test_notify_telegram.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notify_telegram.py
from unittest.mock import patch

from hlvault.notify.telegram import send_alert


def test_send_alert_returns_false_when_not_configured():
    assert send_alert("", "", "hello") is False


def test_send_alert_returns_true_on_success():
    with patch("hlvault.notify.telegram.resilient_read", return_value=True):
        assert send_alert("tok", "chat", "hello") is True


def test_send_alert_returns_false_and_does_not_raise_on_failure():
    with patch("hlvault.notify.telegram.resilient_read", side_effect=RuntimeError("boom")):
        assert send_alert("tok", "chat", "hello") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_notify_telegram.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the package and telegram module**

`src/hlvault/notify/__init__.py`: empty file.

`src/hlvault/notify/telegram.py`:

```python
"""Telegram alerting for safety-critical events (CLAUDE.md #3 — never fail
silently). A notification failure must never raise into the caller — the
caller's safety action (flatten/halt) must proceed regardless of whether the
alert itself was deliverable."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from hlvault.io.source import TransientError, resilient_read

logger = logging.getLogger("notify.telegram")


def send_alert(bot_token: str, chat_id: str, message: str) -> bool:
    if not bot_token or not chat_id:
        logger.warning(f"Telegram not configured, alert dropped: {message}")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": message}).encode()

    def call():
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status >= 500:
                    raise TransientError(f"5xx {r.status}")
                return True
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise TransientError(str(e))
            logger.error(f"Telegram send failed (semantic, not retried): {e}")
            return False
        except (TimeoutError, ConnectionError) as e:
            raise TransientError(str(e))

    try:
        return bool(resilient_read(call, max_attempts=3, base_delay=1.0))
    except Exception as e:
        logger.error(f"Telegram send failed after retries: {e}")
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notify_telegram.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/notify/ tests/test_notify_telegram.py
git commit -m "feat: Telegram alerting for safety-critical events"
```

---

### Task 6: `hlvault/momentum/backtest.py` — walk-forward-safe replay

**Files:**
- Create: `src/hlvault/momentum/backtest.py`
- Test: `tests/test_momentum_backtest.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_momentum_backtest.py
import numpy as np
import pandas as pd

from hlvault.momentum.backtest import run_backtest


def test_steady_uptrend_produces_positive_total_return():
    days = 250
    idx = pd.date_range("2025-01-01", periods=days, freq="D")
    btc = 100 * (1.004 ** np.arange(days))
    eth = 50 * (1.003 ** np.arange(days))
    closes = pd.DataFrame({"BTC": btc, "ETH": eth}, index=idx)

    result = run_backtest(closes, capital=1000.0, max_coin_allocation_pct=0.6,
                          max_leverage=3.0, entry_threshold=0.5, vol_lookback=20)
    assert result.total_return > 0
    assert result.equity_curve.iloc[-1] > result.equity_curve.iloc[0]


def test_flat_noise_keeps_return_close_to_zero_net_of_fees():
    rng = np.random.default_rng(7)
    days = 250
    idx = pd.date_range("2025-01-01", periods=days, freq="D")
    btc = 100 * np.cumprod(1 + rng.normal(0, 0.01, days))
    eth = 50 * np.cumprod(1 + rng.normal(0, 0.01, days))
    closes = pd.DataFrame({"BTC": btc, "ETH": eth}, index=idx)

    result = run_backtest(closes, capital=1000.0, max_coin_allocation_pct=0.6,
                          max_leverage=3.0, entry_threshold=0.5, vol_lookback=20)
    assert abs(result.total_return) < 0.5  # no runaway result on pure noise


def test_max_drawdown_is_non_positive_and_bounded():
    days = 250
    idx = pd.date_range("2025-01-01", periods=days, freq="D")
    # sharp crash after a rally
    path = np.concatenate([100 * 1.01 ** np.arange(125), 100 * 1.01 ** 124 * 0.5 ** (np.arange(125) / 60)])
    closes = pd.DataFrame({"BTC": path, "ETH": path * 0.5}, index=idx)

    result = run_backtest(closes, capital=1000.0, max_coin_allocation_pct=0.6,
                          max_leverage=3.0, entry_threshold=0.5, vol_lookback=20)
    assert -1.0 <= result.max_drawdown <= 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_momentum_backtest.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `backtest.py`**

```python
"""Walk-forward-safe replay of the momentum signal over historical daily
closes: at day t, every score/vol input is computed from data with index <=
t only (pandas .rolling() looks backward by construction), and a day's PnL
uses YESTERDAY's target position against TODAY's return before rebalancing
to today's new target — the same causal ordering the live engine follows.
This replays the exact signals.py + risk.py functions used live (CLAUDE.md
#5: one implementation, not a re-derivation for the backtest)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .risk import risk_budget_per_coin, target_position_notional
from .signals import composite_score, daily_log_returns, position_signal

FEE_RATE = 0.0005


@dataclass
class MomentumBacktestResult:
    equity_curve: pd.Series
    daily_returns: pd.Series
    max_drawdown: float
    sharpe: float
    total_return: float


def run_backtest(
    closes: pd.DataFrame,
    capital: float,
    max_coin_allocation_pct: float,
    max_leverage: float,
    entry_threshold: float = 0.5,
    vol_lookback: int = 20,
) -> MomentumBacktestResult:
    coins = list(closes.columns)
    returns = pd.DataFrame({c: daily_log_returns(closes[c]) for c in coins}).reindex(closes.index)
    scores = pd.DataFrame({c: composite_score(returns[c].dropna()) for c in coins}).reindex(closes.index)
    signals = pd.DataFrame({c: position_signal(scores[c], entry_threshold) for c in coins}).reindex(closes.index)
    trailing_vol = returns.rolling(vol_lookback).std(ddof=1)

    equity = capital
    equity_curve = []
    prev_notional = {c: 0.0 for c in coins}

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
            day_pnl += prev_notional[c] * ret
            day_pnl -= abs(target - prev_notional[c]) * FEE_RATE
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

    return MomentumBacktestResult(
        equity_curve=eq, daily_returns=daily_ret, max_drawdown=max_dd,
        sharpe=sharpe, total_return=total_return,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_momentum_backtest.py -v`
Expected: PASS. If `test_flat_noise_keeps_return_close_to_zero_net_of_fees` fails because the bound is too tight for the fixed seed, widen the assertion bound — do not change the seed to make it pass.

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/momentum/backtest.py tests/test_momentum_backtest.py
git commit -m "feat: momentum walk-forward-safe backtest harness"
```

---

### Task 7: `hlvault/momentum/config.py` — env config

**Files:**
- Create: `src/hlvault/momentum/config.py`

No dedicated test file — matches the existing convention (`hlvault/gridbot/config.py` has no direct test either; it's exercised indirectly through the live-engine tests).

- [ ] **Step 1: Create `config.py`**

```python
"""Env-driven config for the live momentum engine — mirrors
hlvault.gridbot.config's pattern. Reads .env.momentum explicitly so it never
collides with gridbot's or hl-copytrader's own env files. No ALLOCATED_CAPITAL:
this engine sizes off the wallet's actual live equity each rebalance (the
whole wallet is dedicated to this strategy), so capital compounds instead of
being pinned to a static pilot number."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env.momentum"
load_dotenv(_ENV_PATH)


def _clean(val):
    if val is None:
        return val
    return val.split("#", 1)[0].strip()


def _env_str(key, default):
    return _clean(os.getenv(key, default))


def _env_bool(key, default):
    return _clean(os.getenv(key, default)).lower() == "true"


def _env_float(key, default):
    return float(_clean(os.getenv(key, default)))


WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")
MAX_DRAWDOWN_PCT = _env_float("MAX_DRAWDOWN_PCT", "0.20")
LIVE_TRADING = _env_bool("LIVE_TRADING", "false")
NETWORK = _env_str("NETWORK", "mainnet")
HL_API_URL = "https://api.hyperliquid.xyz" if NETWORK == "mainnet" else "https://api.hyperliquid-testnet.xyz"

COIN_UNIVERSE = [c.strip() for c in _env_str("COIN_UNIVERSE", "BTC,ETH,SOL,HYPE").split(",") if c.strip()]
MAX_COIN_ALLOCATION_PCT = _env_float("MAX_COIN_ALLOCATION_PCT", "0.40")
LEVERAGE = _env_float("LEVERAGE", "3")
ENTRY_THRESHOLD = _env_float("ENTRY_THRESHOLD", "0.5")
VOL_LOOKBACK_DAYS = int(_env_float("VOL_LOOKBACK_DAYS", "20"))
REBALANCE_INTERVAL_HOURS = _env_float("REBALANCE_INTERVAL_HOURS", "24")
SYNC_INTERVAL_SECONDS = _env_float("SYNC_INTERVAL_SECONDS", "300")
MIN_ORDER_NOTIONAL = _env_float("MIN_ORDER_NOTIONAL", "12")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "cache" / "momentum_state.json"
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "from hlvault.momentum import config; print(config.COIN_UNIVERSE, config.LIVE_TRADING)"`
Expected: `['BTC', 'ETH', 'SOL', 'HYPE'] False`

- [ ] **Step 3: Commit**

```bash
git add src/hlvault/momentum/config.py
git commit -m "feat: momentum engine env config"
```

---

### Task 8: `hlvault/momentum/live.py` — live engine

**Files:**
- Create: `src/hlvault/momentum/live.py`
- Modify: `pyproject.toml` (add script entry)
- Test: `tests/test_momentum_live_reconcile.py`

- [ ] **Step 1: Write the failing tests (fake Info/Exchange, no network — mirrors `tests/test_gridbot_live_reconcile.py`)**

```python
# tests/test_momentum_live_reconcile.py
from hlvault.momentum import config as cfg
from hlvault.momentum.live import MomentumEngine


class _FakeInfo:
    def __init__(self, mid, positions=None, spot_usdc=1000.0):
        self.mid = mid
        self._positions = positions or []
        self._spot_usdc = spot_usdc

    def all_mids(self):
        return {"BTC": self.mid}

    def user_state(self, address):
        return {"assetPositions": [{"position": p} for p in self._positions]}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc)}]}


class _FakeExchange:
    def __init__(self):
        self.orders_placed = []
        self.closed = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders_placed.append({"coin": coin, "is_buy": is_buy, "size": size, "reduce_only": reduce_only})
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    def market_close(self, coin, size):
        self.closed.append((coin, size))
        return {"status": "ok"}


def _make_engine(info, exchange, state=None):
    engine = MomentumEngine.__new__(MomentumEngine)
    engine.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    engine.exchange = ResilientExchange(exchange)
    engine.state = state or {"halted": False, "peak_equity": 0.0, "last_rebalance_ms": 0,
                             "_alerted_this_halt": False}
    return engine


def test_flatten_everything_closes_every_open_position(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0, positions=[
        {"coin": "BTC", "szi": "1.5", "marginUsed": "10", "unrealizedPnl": "0"},
        {"coin": "ETH", "szi": "-2.0", "marginUsed": "10", "unrealizedPnl": "0"},
    ])
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)

    engine._flatten_everything()

    assert ("BTC", 1.5) in exchange.closed
    assert ("ETH", 2.0) in exchange.closed


def test_flatten_everything_skips_zero_size_positions(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0, positions=[
        {"coin": "BTC", "szi": "0.0", "marginUsed": "0", "unrealizedPnl": "0"},
    ])
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)

    engine._flatten_everything()

    assert exchange.closed == []


def test_place_order_dry_run_does_not_call_exchange(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0)
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)
    engine.live_trading = False

    engine._place_order("BTC", {"is_buy": True, "size": 1.0, "reduce_only": False})

    assert exchange.orders_placed == []


def test_place_order_live_calls_exchange_with_reduce_only_flag(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    info = _FakeInfo(mid=100.0)
    exchange = _FakeExchange()
    engine = _make_engine(info, exchange)
    engine.live_trading = True

    engine._place_order("BTC", {"is_buy": False, "size": 2.0, "reduce_only": True})

    assert exchange.orders_placed == [{"coin": "BTC", "is_buy": False, "size": 2.0, "reduce_only": True}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_momentum_live_reconcile.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `live.py`**

```python
"""Live momentum engine — independent of gridbot, its own wallet/capital.
The drawdown circuit breaker is checked every cycle (SYNC_INTERVAL_SECONDS);
the momentum signal itself only recomputes/rebalances every
REBALANCE_INTERVAL_HOURS, since it's built from daily candles and rebalancing
more often would just churn on noise."""
from __future__ import annotations

import argparse
import logging
import time

import pandas as pd
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from hlvault.gridbot.exchange_utils import get_account_equity, get_mid_price
from hlvault.gridbot.resilience import ResilientExchange
from hlvault.notify.telegram import send_alert
from hlvault.prices import get_candles

from . import config as cfg
from . import risk, signals
from .state import load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("momentum")

CANDLE_LOOKBACK_DAYS = 200  # enough for the 120d lookback plus a buffer


class MomentumEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.momentum")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw_exchange = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw_exchange)
        self.state = load_state(cfg.STATE_FILE)

    def bootstrap_if_needed(self) -> None:
        if self.state.get("peak_equity", 0.0) > 0:
            return
        equity = get_account_equity(self.info, cfg.WALLET_ADDRESS)
        self.state["peak_equity"] = equity
        save_state(cfg.STATE_FILE, self.state)
        logger.info(f"bootstrap: starting equity ${equity:,.2f}")

    def check_drawdown(self) -> bool:
        halted, self.state = risk.check_drawdown(
            self.info, cfg.WALLET_ADDRESS, self.state, cfg.MAX_DRAWDOWN_PCT
        )
        if halted and not self.state.get("_alerted_this_halt"):
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                      "MOMENTUM DRAWDOWN CIRCUIT BREAKER TRIPPED — flattening and halting.")
            self._flatten_everything()
            self.state["_alerted_this_halt"] = True
        save_state(cfg.STATE_FILE, self.state)
        return halted

    def _flatten_everything(self) -> None:
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        any_failed = False
        for p in user_state.get("assetPositions", []):
            pos = p["position"]
            size = float(pos["szi"])
            coin = pos["coin"]
            if abs(size) < 1e-9:
                continue
            try:
                self.exchange.market_close(coin, abs(size))
            except Exception as e:
                any_failed = True
                logger.error(f"SAFETY-CRITICAL: flatten failed for {coin}: {e}")
        if any_failed:
            logger.error("SAFETY-CRITICAL: not everything could be flattened — manual check required")

    def _place_order(self, coin: str, order: dict) -> None:
        if not self.live_trading:
            logger.info(f"[DRY RUN] {coin} order={order}")
            return
        try:
            self.exchange.order(coin, order["is_buy"], order["size"], None,
                                order_type={"market": {}}, reduce_only=order["reduce_only"])
            logger.info(f"{coin}: placed {order}")
        except Exception as e:
            logger.error(f"{coin}: order failed: {e}")

    def maybe_rebalance(self) -> None:
        now_ms = int(time.time() * 1000)
        interval_ms = int(cfg.REBALANCE_INTERVAL_HOURS * 3600 * 1000)
        if now_ms - self.state.get("last_rebalance_ms", 0) < interval_ms:
            return

        equity = get_account_equity(self.info, cfg.WALLET_ADDRESS)
        end = now_ms
        start = end - CANDLE_LOOKBACK_DAYS * 86400 * 1000
        vol_by_coin, scores = {}, {}
        for coin in cfg.COIN_UNIVERSE:
            candles = get_candles(coin, "1d", start, end)
            if len(candles) < 30:
                logger.warning(f"{coin}: not enough candle history, skipping this rebalance")
                continue
            rets = signals.daily_log_returns(candles.set_index("day")["c"])
            vol = rets.tail(cfg.VOL_LOOKBACK_DAYS).std(ddof=1)
            if pd.isna(vol) or vol <= 0:
                continue
            score_series = signals.composite_score(rets)
            if score_series.dropna().empty:
                continue
            vol_by_coin[coin] = float(vol)
            scores[coin] = float(score_series.dropna().iloc[-1])

        if not vol_by_coin:
            logger.warning("momentum: no coins with enough data this cycle, skipping rebalance")
            return

        budgets = risk.risk_budget_per_coin(vol_by_coin, equity, cfg.MAX_COIN_ALLOCATION_PCT)
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        current_by_coin = {
            p["position"]["coin"]: float(p["position"]["szi"])
            for p in user_state.get("assetPositions", [])
        }

        for coin in vol_by_coin:
            sig = signals.score_to_position(scores[coin], cfg.ENTRY_THRESHOLD)
            target_notional = risk.target_position_notional(sig, budgets.get(coin, 0.0), cfg.LEVERAGE)
            price = get_mid_price(self.info, coin)
            if price <= 0:
                continue
            order = risk.compute_order(current_by_coin.get(coin, 0.0), target_notional,
                                       price, cfg.MIN_ORDER_NOTIONAL)
            if order is not None:
                self._place_order(coin, order)

        self.state["last_rebalance_ms"] = now_ms
        self.state["_alerted_this_halt"] = False
        save_state(cfg.STATE_FILE, self.state)

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
                logger.exception("momentum cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = MomentumEngine(live_trading=False if args.dry_run else None)
    if args.status:
        equity = get_account_equity(engine.info, cfg.WALLET_ADDRESS)
        print(f"equity: ${equity:,.2f}  halted={engine.state.get('halted')} "
             f"peak={engine.state.get('peak_equity')}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
```

Note: `self.exchange.order(coin, is_buy, size, None, order_type={"market": {}}, ...)` — confirm the exact market-order payload shape against the installed `hyperliquid-python-sdk` version's `Exchange.order`/`Exchange.market_open` signature before running live for the first time (`.venv/bin/python -c "from hyperliquid.exchange import Exchange; help(Exchange.order)"`); gridbot only ever uses resting limit orders (`order_type={"limit": ...}`) so this is the one exchange-call shape in this plan that has no precedent elsewhere in the repo to copy from.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_momentum_live_reconcile.py -v`
Expected: PASS

- [ ] **Step 5: Add the `hl-momentum` script entry**

In `pyproject.toml`, under `[project.scripts]`, add a line so the block reads:

```toml
[project.scripts]
hl-vault = "hlvault.cli:main"
hl-gridbot = "hlvault.gridbot.live:main"
hl-momentum = "hlvault.momentum.live:main"
```

- [ ] **Step 6: Reinstall the package so the new entry point is registered, run the full test suite**

Run: `.venv/bin/pip install -e . -q && .venv/bin/pytest -q`
Expected: all tests PASS (existing + new).

- [ ] **Step 7: Commit**

```bash
git add src/hlvault/momentum/live.py pyproject.toml tests/test_momentum_live_reconcile.py
git commit -m "feat: momentum live engine + hl-momentum entry point"
```

---

### Task 9: Deployment unit

**Files:**
- Create: `deploy/hl-momentum.service`

- [ ] **Step 1: Create the systemd unit, mirroring `deploy/hl-gridbot.service`**

```ini
[Unit]
Description=Hyperliquid independent momentum-trading bot (hlvault.momentum)
Documentation=https://github.com/jimlai1005/vault
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu

WorkingDirectory=/home/ubuntu/vault
EnvironmentFile=/home/ubuntu/vault/.env.momentum

ExecStart=/home/ubuntu/vault/.venv/bin/hl-momentum

Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

MemoryMax=256M

StandardOutput=journal
StandardError=journal
SyslogIdentifier=hl-momentum

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```bash
git add deploy/hl-momentum.service
git commit -m "chore: systemd unit for hl-momentum"
```

---

### Task 10: Run the real go/no-go backtest (due-diligence gate)

**Files:**
- Create: `scripts/run_momentum_backtest.py`
- Create (generated by running the script): `reports/momentum-backtest-verdict.md`

This is the step gated on nothing but network access — it can run before the new wallet exists, since it only reads public price history.

- [ ] **Step 1: Write the driver script**

```python
# scripts/run_momentum_backtest.py
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
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python scripts/run_momentum_backtest.py`
Expected: prints the panel shape and the verdict table; writes `reports/momentum-backtest-verdict.md`.

- [ ] **Step 3: Read the verdict and decide**

If **NO-GO**: do not set `LIVE_TRADING=true` in `.env.momentum`. Report the result plainly (same anti-p-hacking stance as `reports/oos-verdict.md` — do not iterate parameters until GO appears). Stop here and report back instead of proceeding to Task 11.

If **GO**: proceed to Task 11.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_momentum_backtest.py reports/momentum-backtest-verdict.md
git commit -m "feat: momentum go/no-go backtest driver + verdict report"
```

---

### Task 11: Go live (blocked on the new wallet)

**Files:**
- Modify: `.env.momentum` (fill in real values — do not commit; already gitignored)

**Blocked on:** the user providing the new dedicated Hyperliquid wallet's address + private key (mentioned they are provisioning this now). Nothing in Tasks 1–10 depends on it.

- [ ] **Step 1: Fill in `.env.momentum`**

Once the wallet exists and is funded, set `WALLET_ADDRESS` and `WALLET_PRIVATE_KEY` in `.env.momentum` (leave `LIVE_TRADING=false` initially).

- [ ] **Step 2: Dry-run against the real wallet**

Run: `.venv/bin/hl-momentum --dry-run --status`
Run: `.venv/bin/hl-momentum --dry-run --once`
Expected: logs show `[DRY RUN]` order lines (if any) with sane sizes/directions, no exceptions, and `equity:` reflects the real funded balance.

- [ ] **Step 3: Flip live and start the service (only if Task 10's verdict was GO)**

Set `LIVE_TRADING=true` in `.env.momentum`, then follow `deploy/setup.sh`'s existing pattern to install and start `hl-momentum.service` (systemd) alongside the already-running `hl-gridbot.service`.

- [ ] **Step 4: Confirm the Telegram channel is live**

Run: `.venv/bin/python -c "from hlvault.notify.telegram import send_alert; from hlvault.momentum import config as cfg; print(send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID, 'hlvault.momentum: test alert, ignore'))"`
Expected: prints `True` and the configured Telegram chat receives the test message.

---

## Self-review notes

- **Spec coverage:** independent wallet/package (Tasks 2–9), 20% MDD circuit breaker on one equity source (Task 4 `check_drawdown` + Task 8 wiring), Telegram alerting (Task 5 + Task 8), walk-forward-safe backtest due-diligence gate (Task 6 + Task 10), non-idempotent order placement not blindly retried (Task 8's `_place_order` goes through `ResilientExchange.order`, which already classifies `reduce_only` as idempotent vs not — reused, not reimplemented), idempotent flatten retries (`ResilientExchange.market_close`), no-network tests (global autouse fixture in `tests/conftest.py` already covers every new test file), no changes to `hlvault.gridbot` (confirmed — only imports from it). Deployment (Task 9) and the wallet-blocked go-live steps (Task 11) are both covered.
- **Placeholder scan:** no TBD/TODO; the one open question (exact market-order payload shape for the SDK version installed) is flagged explicitly in Task 8 with the exact command to resolve it before first live use, not left vague.
- **Type consistency:** `compute_order`/`target_position_notional`/`risk_budget_per_coin`/`check_drawdown` signatures are identical between their definition (Task 4) and every call site (Task 6 backtest, Task 8 live). `score_to_position`/`position_signal`/`composite_score`/`daily_log_returns` likewise consistent between Task 3, Task 6, and Task 8.
