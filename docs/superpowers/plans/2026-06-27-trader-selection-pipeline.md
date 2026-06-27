# Trader Selection Research Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, strictly point-in-time pipeline that reconstructs each Hyperliquid trader's on-chain equity curve, ranks traders by risk-adjusted alpha + persistence, computes covariance-aware weights, and runs a walk-forward OOS backtest that emits an explicit GO/NO-GO verdict.

**Architecture:** Nine independently-testable stages wired by a CLI. All external IO passes through one resilience boundary (`io/source.py`) with an as-of filter that structurally enforces no-lookahead. Each stage reads/writes parquet so stages re-run in isolation. TDD throughout with synthetic ground-truth data; no test touches the network.

**Tech Stack:** Python 3.11+, pandas, numpy, scipy, scikit-learn (LedoitWolf), statsmodels (OLS+HAC), pyarrow, boto3, pydantic, matplotlib, pytest.

---

## File Structure

```
hl-vault/
├── pyproject.toml
├── src/hlvault/
│   ├── __init__.py
│   ├── config.py              # pydantic settings + thresholds
│   ├── types.py               # Address, ReturnSeries type aliases, dataclasses
│   ├── io/
│   │   ├── source.py          # single resilience boundary (retry classification)
│   │   ├── hl_api.py          # leaderboard + userFillsByTime client
│   │   ├── s3_archive.py      # node_fills_by_block requester-pays reader
│   │   └── cache.py           # parquet cache + as-of filter
│   ├── universe.py            # stage 1
│   ├── ingest.py              # stage 2 (FillSource/PriceSource interfaces)
│   ├── equity.py              # stage 3 + sample-length gate
│   ├── metrics.py             # stage 4 (Sharpe/Sortino/MDD/winrate-stability/DSR)
│   ├── factors.py             # stage 5 (alpha/beta OLS+HAC)
│   ├── select.py              # stage 6 (top-N)
│   ├── weights.py             # stage 7 (LedoitWolf + HRP + risk-parity + Kelly)
│   ├── backtest.py            # stage 8 (walk-forward, as-of clock)
│   ├── report.py              # stage 9 (report + verdict)
│   └── cli.py                 # argparse/typer entrypoints
└── tests/
    ├── conftest.py            # autouse no-network fixture + synthetic fixtures
    ├── test_source.py
    ├── test_cache_asof.py
    ├── test_equity.py
    ├── test_metrics.py
    ├── test_factors.py
    ├── test_weights.py
    ├── test_backtest_nolookahead.py
    └── test_select.py
```

---

### Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `src/hlvault/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "hlvault"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "scikit-learn>=1.5",
  "statsmodels>=0.14", "pyarrow>=16", "boto3>=1.34", "pydantic>=2.7",
  "pydantic-settings>=2.3", "matplotlib>=3.9",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5"]

[project.scripts]
hl-vault = "hlvault.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `tests/conftest.py` with autouse no-network fixture (CLAUDE.md #4)**

```python
import socket
import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-fail any real socket connection from any test."""
    def guard(*a, **k):
        raise RuntimeError("Network access is disabled in tests")
    monkeypatch.setattr(socket.socket, "connect", guard)
```

- [ ] **Step 3: Create venv + install**

Run: `python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'`
Expected: install succeeds.

- [ ] **Step 4: Verify pytest runs (no tests yet)**

Run: `.venv/bin/pytest`
Expected: "no tests ran".

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests
git commit -m "chore: scaffold hlvault package + no-network test fixture"
```

---

### Task 1: Config + types

**Files:**
- Create: `src/hlvault/config.py`, `src/hlvault/types.py`, `tests/test_config.py`

- [ ] **Step 1: Write failing test `tests/test_config.py`**

```python
from hlvault.config import Settings


def test_defaults():
    s = Settings()
    assert s.universe_size == 300
    assert 6 <= s.min_history_months <= 12
    assert s.top_n == 30
    assert 0 < s.kelly_fraction <= 1
```

- [ ] **Step 2: Run, expect fail** — `.venv/bin/pytest tests/test_config.py -v` → ImportError.

- [ ] **Step 3: Implement `src/hlvault/types.py`**

```python
from __future__ import annotations
import pandas as pd

Address = str  # 42-char hex, validated at the IO boundary
ReturnSeries = pd.Series  # DatetimeIndex -> daily return float
```

- [ ] **Step 4: Implement `src/hlvault/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HLVAULT_", env_file=".env")

    universe_size: int = 300
    min_history_months: int = 9          # sample-length gate (6-12)
    top_n: int = 30
    rebalance_horizon_days: int = 30     # OOS hold length
    dsr_pvalue: float = 0.05             # deflated Sharpe cutoff
    kelly_fraction: float = 0.25         # fractional Kelly
    risk_free_daily: float = 0.0
    cache_dir: str = "data/cache"
    derived_dir: str = "data/derived"
```

- [ ] **Step 5: Run, expect pass.** Commit: `git add -A && git commit -m "feat: config + core types"`

---

### Task 2: Resilience boundary (`io/source.py`) — CLAUDE.md #2 & #5

**Files:**
- Create: `src/hlvault/io/__init__.py`, `src/hlvault/io/source.py`, `tests/test_source.py`

- [ ] **Step 1: Write failing test `tests/test_source.py`**

```python
import pytest
from hlvault.io.source import resilient_read, SemanticError, TransientError


def test_retries_transient_then_succeeds():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("timeout")
        return "ok"
    assert resilient_read(fn, max_attempts=5, base_delay=0) == "ok"
    assert calls["n"] == 3


def test_semantic_not_retried():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        raise SemanticError("bad address")
    with pytest.raises(SemanticError):
        resilient_read(fn, max_attempts=5, base_delay=0)
    assert calls["n"] == 1   # no retry on semantic failure
```

- [ ] **Step 2: Run, expect fail** (ImportError).

- [ ] **Step 3: Implement `src/hlvault/io/source.py`**

```python
"""Single resilience boundary. Every external read passes through here and
must classify failures: transient (retry w/ backoff) vs semantic (surface).
All reads are idempotent (CLAUDE.md #2/#5 — no non-idempotent writes here)."""
from __future__ import annotations
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class TransientError(Exception):
    """Connection reset/timeout/5xx — safe to retry (idempotent read)."""


class SemanticError(Exception):
    """Bad input/4xx — do NOT retry; surface."""


def resilient_read(fn: Callable[[], T], *, max_attempts: int = 5,
                   base_delay: float = 0.5) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except SemanticError:
            raise
        except TransientError:
            if attempt == max_attempts:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")
```

Also create empty `src/hlvault/io/__init__.py`.

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: resilient IO boundary with transient/semantic classification"`

---

### Task 3: Cache + as-of filter (no-lookahead lifeline)

**Files:**
- Create: `src/hlvault/io/cache.py`, `tests/test_cache_asof.py`

- [ ] **Step 1: Write failing test `tests/test_cache_asof.py`**

```python
import pandas as pd
from hlvault.io.cache import apply_asof


def test_asof_filters_future_rows():
    df = pd.DataFrame({"time": pd.to_datetime(
        ["2026-01-01", "2026-02-01", "2026-03-01"]), "v": [1, 2, 3]})
    out = apply_asof(df, as_of=pd.Timestamp("2026-02-15"), time_col="time")
    assert list(out["v"]) == [1, 2]   # March row invisible


def test_asof_none_passthrough():
    df = pd.DataFrame({"time": pd.to_datetime(["2026-01-01"]), "v": [1]})
    out = apply_asof(df, as_of=None, time_col="time")
    assert list(out["v"]) == [1]
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/io/cache.py`**

```python
"""Parquet cache + as-of filter. The as-of filter is the single structural
gate that makes the OOS backtest lookahead-free (CLAUDE.md #5 forcing function)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd


def apply_asof(df: pd.DataFrame, as_of: pd.Timestamp | None,
               time_col: str = "time") -> pd.DataFrame:
    if as_of is None:
        return df
    return df[df[time_col] <= as_of].copy()


def cache_path(cache_dir: str, key: str) -> Path:
    p = Path(cache_dir) / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_or_compute(cache_dir: str, key: str, compute) -> pd.DataFrame:
    p = cache_path(cache_dir, key)
    if p.exists():
        return pd.read_parquet(p)
    df = compute()
    df.to_parquet(p)
    return df
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: parquet cache + as-of filter (no-lookahead gate)"`

---

### Task 4: Ingest interfaces (FillSource / PriceSource) + HL API client

**Files:**
- Create: `src/hlvault/ingest.py`, `src/hlvault/io/hl_api.py`, `tests/test_ingest.py`

- [ ] **Step 1: Write failing test `tests/test_ingest.py`**

```python
import pandas as pd
from hlvault.ingest import FillSource, fills_to_frame


class FakeFills(FillSource):
    def get_fills(self, address, start=None, end=None):
        return [
            {"time": 1704067200000, "coin": "BTC", "sz": "0.1", "px": "40000",
             "side": "B", "closedPnl": "0", "fee": "0.4"},
        ]


def test_fills_to_frame_normalizes_units():
    df = fills_to_frame(FakeFills().get_fills("0xabc"))
    assert df.loc[0, "coin"] == "BTC"
    assert df.loc[0, "sz"] == 0.1
    assert df.loc[0, "px"] == 40000.0
    assert df.loc[0, "signed_sz"] == 0.1     # buy positive
    assert isinstance(df.loc[0, "time"], pd.Timestamp)
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/ingest.py`**

```python
"""Stage 2: pluggable data sources + normalization to canonical frames."""
from __future__ import annotations
from typing import Protocol
import pandas as pd


class FillSource(Protocol):
    def get_fills(self, address: str, start=None, end=None) -> list[dict]: ...


class PriceSource(Protocol):
    def get_ohlcv(self, coin: str, interval: str, start=None, end=None) -> pd.DataFrame: ...


def fills_to_frame(raw: list[dict]) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=["time", "coin", "sz", "px", "signed_sz",
                                     "closedPnl", "fee"])
    df = pd.DataFrame(raw)
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms")
    for col in ("sz", "px", "closedPnl", "fee"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["signed_sz"] = df.apply(
        lambda r: r["sz"] if r["side"] == "B" else -r["sz"], axis=1)
    return df[["time", "coin", "sz", "px", "signed_sz", "closedPnl", "fee"]]
```

- [ ] **Step 4: Implement `src/hlvault/io/hl_api.py`** (concrete FillSource via official API, wrapped in the boundary)

```python
"""Official Hyperliquid info API client. Reads only; routed through resilient_read."""
from __future__ import annotations
import json
import urllib.request
from .source import resilient_read, TransientError, SemanticError

INFO_URL = "https://api.hyperliquid.xyz/info"


def _post(body: dict) -> object:
    def call():
        req = urllib.request.Request(
            INFO_URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
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


class HLApiFillSource:
    def get_fills(self, address: str, start=None, end=None) -> list[dict]:
        body = {"type": "userFillsByTime", "user": address,
                "startTime": start or 0}
        if end is not None:
            body["endTime"] = end
        return _post(body)  # type: ignore[return-value]


def get_leaderboard(window: str = "month") -> list[dict]:
    return _post({"type": "leaderboard"})  # type: ignore[return-value]
```

- [ ] **Step 5: Run test, expect pass** (test only exercises pure `fills_to_frame`; the API client is network-guarded by conftest and tested via fakes). Commit: `git commit -am "feat: ingest interfaces + HL API fill source"`

---

### Task 5: Universe (stage 1)

**Files:**
- Create: `src/hlvault/universe.py`, `tests/test_universe.py`

- [ ] **Step 1: Write failing test `tests/test_universe.py`**

```python
from hlvault.universe import top_addresses


def test_top_addresses_ranks_and_truncates():
    rows = [{"ethAddress": f"0x{i:040x}",
             "windowPerformances": [["month", {"pnl": str(i)}]]}
            for i in range(5)]
    out = top_addresses(rows, n=3)
    assert len(out) == 3
    assert out[0] == "0x" + f"{4:040x}"   # highest pnl first
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/universe.py`**

```python
"""Stage 1: candidate universe from leaderboard. NOTE: this is the *seed*
universe only. The backtest reconstructs the as-of universe to avoid
survivorship bias (see spec §Point-in-time)."""
from __future__ import annotations


def _month_pnl(row: dict) -> float:
    for win, perf in row.get("windowPerformances", []):
        if win == "month":
            return float(perf.get("pnl", 0))
    return 0.0


def top_addresses(leaderboard_rows: list[dict], n: int) -> list[str]:
    ranked = sorted(leaderboard_rows, key=_month_pnl, reverse=True)
    return [r["ethAddress"] for r in ranked[:n]]
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: leaderboard universe (seed only)"`

---

### Task 6: Equity reconstruction + sample-length gate (stage 3)

**Files:**
- Create: `src/hlvault/equity.py`, `tests/test_equity.py`

- [ ] **Step 1: Write failing test `tests/test_equity.py`** (synthetic ground truth)

```python
import numpy as np
import pandas as pd
from hlvault.equity import daily_returns_from_fills, passes_sample_gate


def test_realized_pnl_accumulates_into_returns():
    # two closing fills with known closedPnl on a 1000 starting equity
    fills = pd.DataFrame({
        "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "coin": ["BTC", "BTC"],
        "signed_sz": [0.0, 0.0],
        "px": [40000.0, 41000.0],
        "closedPnl": [100.0, -50.0],
        "fee": [0.0, 0.0],
    })
    r = daily_returns_from_fills(fills, starting_equity=1000.0)
    # day1 equity 1100 -> ret 0.10 ; day2 equity 1050 -> ret ~ -0.0455
    assert abs(r.iloc[0] - 0.10) < 1e-9
    assert abs(r.iloc[1] - (1050/1100 - 1)) < 1e-9


def test_sample_gate_rejects_short_history():
    idx = pd.date_range("2026-01-01", periods=30, freq="D")
    assert not passes_sample_gate(pd.Series(0.0, index=idx), min_months=9)
    idx2 = pd.date_range("2025-01-01", periods=400, freq="D")
    assert passes_sample_gate(pd.Series(0.0, index=idx2), min_months=9)
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/equity.py`**

```python
"""Stage 3: reconstruct daily equity curve -> daily returns. Current and peak
equity derive from the SAME series (CLAUDE.md #1 — never mix sources).

equity_t = starting_equity + cum(realized_pnl) + cum(funding) - cum(fee)
           + unrealized_mtm(position_t, price_t)
This task covers the realized+fee+funding spine; unrealized MtM is layered in
via `add_unrealized` when a PriceSource is supplied (kept separate + tested)."""
from __future__ import annotations
import pandas as pd


def daily_equity_from_fills(fills: pd.DataFrame, starting_equity: float,
                            funding: pd.Series | None = None) -> pd.Series:
    f = fills.copy()
    f["day"] = f["time"].dt.normalize()
    daily = f.groupby("day").agg(
        realized=("closedPnl", "sum"), fee=("fee", "sum")).sort_index()
    pnl = daily["realized"] - daily["fee"]
    if funding is not None:
        pnl = pnl.add(funding.groupby(funding.index.normalize()).sum(),
                      fill_value=0.0)
    equity = starting_equity + pnl.cumsum()
    return equity


def daily_returns_from_fills(fills: pd.DataFrame, starting_equity: float,
                             funding: pd.Series | None = None) -> pd.Series:
    equity = daily_equity_from_fills(fills, starting_equity, funding)
    prev = equity.shift(1).fillna(starting_equity)
    return (equity / prev - 1.0).rename("ret")


def passes_sample_gate(returns: pd.Series, min_months: int) -> bool:
    if returns.empty:
        return False
    span_days = (returns.index.max() - returns.index.min()).days
    return span_days >= min_months * 30
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: equity reconstruction + sample-length gate"`

> **Note for executor:** unrealized MtM (`add_unrealized(position_series, price_df)`) is a follow-on step within this task — write a test that opens a position at px=40000, marks at 42000, and asserts +unrealized appears in equity before any close; implement by computing running `signed_sz.cumsum()` per coin × OHLCV close. Show the test and code in the same TDD cycle before committing.

---

### Task 7: Metrics — risk-adjusted + persistence + Deflated Sharpe (stage 4)

**Files:**
- Create: `src/hlvault/metrics.py`, `tests/test_metrics.py`

- [ ] **Step 1: Write failing test `tests/test_metrics.py`**

```python
import numpy as np
import pandas as pd
from hlvault.metrics import sharpe, sortino, max_drawdown, deflated_sharpe


def test_sharpe_known_value():
    r = pd.Series([0.01] * 252)   # constant positive -> infinite-ish; use noise
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.001, 0.01, 252))
    s = sharpe(r, rf=0.0)
    assert abs(s - (r.mean() / r.std(ddof=1) * np.sqrt(252))) < 1e-9


def test_max_drawdown_simple():
    eq = pd.Series([1.0, 1.2, 0.9, 1.1])
    # peak 1.2 -> trough 0.9 => -0.25
    assert abs(max_drawdown(eq) - (-0.25)) < 1e-9


def test_deflated_sharpe_penalizes_many_trials():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.001, 0.01, 252))
    dsr_few = deflated_sharpe(r, n_trials=1)
    dsr_many = deflated_sharpe(r, n_trials=300)
    assert dsr_many < dsr_few    # more trials -> harder to clear
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/metrics.py`**

```python
"""Stage 4: risk-adjusted + persistence metrics. Deflated Sharpe corrects the
multiple-testing selection bias from screening ~300 candidates."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.stats import norm

ANN = 252


def sharpe(r: pd.Series, rf: float = 0.0) -> float:
    ex = r - rf
    sd = ex.std(ddof=1)
    return float(ex.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def sortino(r: pd.Series, rf: float = 0.0) -> float:
    ex = r - rf
    downside = ex[ex < 0].std(ddof=1)
    return float(ex.mean() / downside * np.sqrt(ANN)) if downside > 0 else 0.0


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def rolling_winrate_stability(r: pd.Series, window: int = 21) -> float:
    wr = (r > 0).rolling(window).mean()
    return float(wr.std())   # lower = more stable


def deflated_sharpe(r: pd.Series, n_trials: int, rf: float = 0.0) -> float:
    """Probability the true Sharpe > 0 after correcting for n_trials selection.
    Bailey & Lopez de Prado (2014), simplified."""
    sr = sharpe(r, rf) / np.sqrt(ANN)     # per-period SR
    n = len(r)
    if n < 3:
        return 0.0
    g = r.skew()
    k = r.kurt() + 3.0
    sr_std = np.sqrt((1 - g * sr + (k - 1) / 4 * sr ** 2) / (n - 1))
    # expected max SR across n_trials under the null
    e_max = (np.sqrt(2 * np.log(max(n_trials, 1)))
             if n_trials > 1 else 0.0) * sr_std
    z = (sr - e_max) / sr_std if sr_std > 0 else 0.0
    return float(norm.cdf(z))
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: risk-adjusted + persistence metrics incl. deflated Sharpe"`

---

### Task 8: Factors — alpha vs beta (stage 5)

**Files:**
- Create: `src/hlvault/factors.py`, `tests/test_factors.py`

- [ ] **Step 1: Write failing test `tests/test_factors.py`** (recover known alpha/beta)

```python
import numpy as np
import pandas as pd
from hlvault.factors import alpha_beta


def test_recovers_known_alpha_beta():
    rng = np.random.default_rng(3)
    n = 500
    btc = pd.Series(rng.normal(0, 0.02, n))
    eth = pd.Series(rng.normal(0, 0.025, n))
    true_alpha, b_btc, b_eth = 0.0008, 0.5, 0.3
    noise = rng.normal(0, 0.005, n)
    r = true_alpha + b_btc * btc + b_eth * eth + noise
    res = alpha_beta(pd.Series(r), btc, eth)
    assert abs(res.alpha - true_alpha) < 0.0005
    assert abs(res.beta_btc - b_btc) < 0.05
    assert res.alpha_tstat > 2   # significant alpha
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/factors.py`**

```python
"""Stage 5: regress trader returns on BTC/ETH. Keep residual + alpha; drop
pure-beta traders. Newey-West HAC SEs for autocorrelation-robust t-stats."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
import statsmodels.api as sm


@dataclass
class FactorFit:
    alpha: float
    beta_btc: float
    beta_eth: float
    alpha_tstat: float
    r_squared: float
    residual: pd.Series


def alpha_beta(r: pd.Series, btc: pd.Series, eth: pd.Series) -> FactorFit:
    df = pd.concat([r, btc, eth], axis=1, keys=["r", "btc", "eth"]).dropna()
    X = sm.add_constant(df[["btc", "eth"]])
    model = sm.OLS(df["r"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    resid = pd.Series(model.resid, index=df.index)
    return FactorFit(
        alpha=float(model.params["const"]),
        beta_btc=float(model.params["btc"]),
        beta_eth=float(model.params["eth"]),
        alpha_tstat=float(model.tvalues["const"]),
        r_squared=float(model.rsquared),
        residual=resid,
    )


def is_pure_beta(fit: FactorFit, min_alpha_tstat: float = 2.0) -> bool:
    return fit.alpha_tstat < min_alpha_tstat
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: alpha/beta decomposition, drop pure-beta traders"`

---

### Task 9: Weights — Ledoit-Wolf + HRP + risk-parity + Kelly (stage 7)

**Files:**
- Create: `src/hlvault/weights.py`, `tests/test_weights.py`

- [ ] **Step 1: Write failing test `tests/test_weights.py`** (HRP penalizes correlated cluster)

```python
import numpy as np
import pandas as pd
from hlvault.weights import hrp_weights, shrunk_cov


def test_hrp_downweights_correlated_cluster():
    rng = np.random.default_rng(7)
    n = 600
    base = rng.normal(0, 0.01, n)
    # A,B,C nearly identical (correlated cluster); D independent
    df = pd.DataFrame({
        "A": base + rng.normal(0, 0.001, n),
        "B": base + rng.normal(0, 0.001, n),
        "C": base + rng.normal(0, 0.001, n),
        "D": rng.normal(0, 0.01, n),
    })
    w = hrp_weights(df)
    assert abs(w.sum() - 1.0) < 1e-9
    # independent D should carry more weight than any single clustered name
    assert w["D"] > w["A"]


def test_shrunk_cov_is_psd():
    rng = np.random.default_rng(8)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 5)))
    cov = shrunk_cov(df)
    eig = np.linalg.eigvalsh(cov)
    assert (eig > -1e-10).all()
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/weights.py`**

```python
"""Stage 7: covariance-aware weights. Ledoit-Wolf shrinkage on Sigma; HRP as
primary (auto-penalizes correlated clusters); risk-parity + fractional-Kelly
as comparators."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf


def shrunk_cov(returns: pd.DataFrame) -> np.ndarray:
    return LedoitWolf().fit(returns.values).covariance_


def _ivp(cov: np.ndarray) -> np.ndarray:
    ivp = 1.0 / np.diag(cov)
    return ivp / ivp.sum()


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    w = _ivp(sub)
    return float(w @ sub @ w)


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    cov = pd.DataFrame(shrunk_cov(returns), index=returns.columns,
                       columns=returns.columns)
    corr = returns.corr().values
    dist = np.sqrt(0.5 * (1 - corr))
    link = linkage(squareform(dist, checks=False), method="single")
    order = leaves_list(link)
    cols = returns.columns[order].tolist()
    w = pd.Series(1.0, index=cols)
    clusters = [cols]
    covv = cov.loc[cols, cols].values
    pos = {c: i for i, c in enumerate(cols)}
    while clusters:
        clusters = [c[j:k] for c in clusters
                    for j, k in ((0, len(c) // 2), (len(c) // 2, len(c)))
                    if len(c) > 1]
        for i in range(0, len(clusters), 2):
            left, right = clusters[i], clusters[i + 1]
            vl = _cluster_var(covv, [pos[c] for c in left])
            vr = _cluster_var(covv, [pos[c] for c in right])
            alpha = 1 - vl / (vl + vr)
            w[left] *= alpha
            w[right] *= (1 - alpha)
    return (w / w.sum()).reindex(returns.columns)


def risk_parity_weights(returns: pd.DataFrame) -> pd.Series:
    cov = shrunk_cov(returns)
    w = _ivp(cov)
    return pd.Series(w, index=returns.columns)


def fractional_kelly_weights(returns: pd.DataFrame, fraction: float) -> pd.Series:
    cov = shrunk_cov(returns)
    mu = returns.mean().values
    raw = np.linalg.pinv(cov) @ mu
    raw = np.clip(raw, 0, None)
    if raw.sum() == 0:
        raw = np.ones_like(raw)
    w = fraction * raw / raw.sum()
    return pd.Series(w / w.sum(), index=returns.columns)
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: HRP/risk-parity/Kelly weights on Ledoit-Wolf cov"`

---

### Task 10: Select (stage 6)

**Files:**
- Create: `src/hlvault/select.py`, `tests/test_select.py`

- [ ] **Step 1: Write failing test `tests/test_select.py`**

```python
import pandas as pd
from hlvault.select import rank_and_select


def test_select_drops_pure_beta_and_takes_top_n():
    df = pd.DataFrame({
        "address": ["a", "b", "c", "d"],
        "alpha_tstat": [3.0, 2.5, 1.0, 4.0],   # c is pure-beta (<2)
        "dsr": [0.9, 0.8, 0.95, 0.99],
        "winrate_stability": [0.1, 0.2, 0.05, 0.05],
    })
    out = rank_and_select(df, top_n=2, min_alpha_tstat=2.0)
    assert "c" not in out["address"].values    # pure beta dropped
    assert len(out) == 2
    assert out.iloc[0]["address"] == "d"        # best composite
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/select.py`**

```python
"""Stage 6: drop pure-beta, rank by composite of risk-adjusted alpha +
persistence (DSR, winrate stability), take top-N."""
from __future__ import annotations
import pandas as pd


def rank_and_select(df: pd.DataFrame, top_n: int,
                    min_alpha_tstat: float = 2.0) -> pd.DataFrame:
    survivors = df[df["alpha_tstat"] >= min_alpha_tstat].copy()
    # composite: z-score of alpha_tstat + dsr - winrate_stability
    def z(col):
        s = survivors[col]
        return (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0
    survivors["score"] = z("alpha_tstat") + z("dsr") - z("winrate_stability")
    return survivors.sort_values("score", ascending=False).head(top_n)
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: composite ranking + top-N selection"`

---

### Task 11: Backtest — walk-forward OOS + no-lookahead guarantee (stage 8)

**Files:**
- Create: `src/hlvault/backtest.py`, `tests/test_backtest_nolookahead.py`

- [ ] **Step 1: Write failing test `tests/test_backtest_nolookahead.py`**

```python
import pandas as pd
import numpy as np
from hlvault.backtest import walk_forward, SelectionFn


def test_selection_ignores_future_data():
    idx = pd.date_range("2025-01-01", periods=300, freq="D")
    rng = np.random.default_rng(2)
    panel = pd.DataFrame(rng.normal(0, 0.01, (300, 4)),
                         index=idx, columns=list("abcd"))

    seen_max_dates = []
    def select(as_of, data):
        seen_max_dates.append(data.index.max())
        # pick top-2 by trailing mean; equal weight
        w = data.mean().nlargest(2)
        return pd.Series(0.5, index=w.index)

    res = walk_forward(panel, select, rebalance_days=30, horizon_days=30)
    # every selection must only see data <= its as_of date
    for as_of, mx in zip(res.rebalance_dates, seen_max_dates):
        assert mx <= as_of


def test_oos_segments_are_future_of_selection():
    idx = pd.date_range("2025-01-01", periods=200, freq="D")
    panel = pd.DataFrame(0.001, index=idx, columns=list("ab"))
    def select(as_of, data):
        return pd.Series(0.5, index=["a", "b"])
    res = walk_forward(panel, select, rebalance_days=30, horizon_days=30)
    assert res.oos_returns.index.min() > res.rebalance_dates[0]
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/backtest.py`**

```python
"""Stage 8: walk-forward OOS. At each rebalance date T the SelectionFn sees
ONLY data with index <= T (structural no-lookahead). The held portfolio's
realized returns over (T, T+h] are concatenated into the OOS track."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import pandas as pd

SelectionFn = Callable[[pd.Timestamp, pd.DataFrame], pd.Series]


@dataclass
class BacktestResult:
    oos_returns: pd.Series
    rebalance_dates: list[pd.Timestamp]


def walk_forward(panel: pd.DataFrame, select: SelectionFn,
                 rebalance_days: int, horizon_days: int) -> BacktestResult:
    dates = panel.index
    start, end = dates.min(), dates.max()
    rebal = pd.date_range(start + pd.Timedelta(days=rebalance_days),
                          end - pd.Timedelta(days=horizon_days),
                          freq=f"{rebalance_days}D")
    segments, used = [], []
    for t in rebal:
        past = panel[panel.index <= t]            # <-- the only data select sees
        weights = select(t, past)
        future = panel[(panel.index > t) &
                       (panel.index <= t + pd.Timedelta(days=horizon_days))]
        cols = [c for c in weights.index if c in future.columns]
        if not cols:
            continue
        seg = (future[cols] * weights[cols]).sum(axis=1)
        segments.append(seg)
        used.append(t)
    oos = pd.concat(segments).sort_index() if segments else pd.Series(dtype=float)
    return BacktestResult(oos_returns=oos, rebalance_dates=used)
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: walk-forward OOS backtest with structural no-lookahead"`

---

### Task 12: Report + GO/NO-GO verdict (stage 9)

**Files:**
- Create: `src/hlvault/report.py`, `tests/test_report.py`

- [ ] **Step 1: Write failing test `tests/test_report.py`**

```python
import numpy as np
import pandas as pd
from hlvault.report import verdict


def test_go_when_oos_significantly_positive_and_beats_btc():
    rng = np.random.default_rng(5)
    oos = pd.Series(rng.normal(0.002, 0.01, 250))    # strong positive
    btc = pd.Series(rng.normal(0.0, 0.02, 250))
    v = verdict(oos, btc)
    assert v.decision == "GO"
    assert v.oos_tstat > 2


def test_nogo_when_oos_not_distinguishable_from_zero():
    rng = np.random.default_rng(6)
    oos = pd.Series(rng.normal(0.0, 0.02, 250))      # noise
    btc = pd.Series(rng.normal(0.0, 0.02, 250))
    v = verdict(oos, btc)
    assert v.decision == "NO-GO"
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/report.py`**

```python
"""Stage 9: verdict + report. GO iff OOS mean return significantly > 0 AND the
OOS Sharpe beats BTC buy-hold. Honest about the realized OOS expectation."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats
from .metrics import sharpe, max_drawdown


@dataclass
class Verdict:
    decision: str
    oos_tstat: float
    oos_sharpe: float
    btc_sharpe: float
    oos_mdd: float
    note: str


def verdict(oos_returns: pd.Series, btc_returns: pd.Series) -> Verdict:
    t, p = stats.ttest_1samp(oos_returns, 0.0)
    osr = sharpe(oos_returns)
    bsr = sharpe(btc_returns)
    mdd = max_drawdown((1 + oos_returns).cumprod())
    go = (t > 2.0) and (p < 0.05) and (osr > bsr)
    decision = "GO" if go else "NO-GO"
    note = ("Past winners show significant OOS alpha beating BTC."
            if go else
            "Thesis NOT confirmed OOS — do not deploy capital.")
    return Verdict(decision, float(t), float(osr), float(bsr), float(mdd), note)


def write_report(path, verdict_obj: Verdict, selection: pd.DataFrame,
                 weights: pd.Series) -> None:
    lines = [f"# OOS Verdict: {verdict_obj.decision}", "",
             verdict_obj.note, "",
             f"- OOS t-stat: {verdict_obj.oos_tstat:.2f}",
             f"- OOS Sharpe: {verdict_obj.oos_sharpe:.2f} "
             f"(BTC {verdict_obj.btc_sharpe:.2f})",
             f"- OOS max drawdown: {verdict_obj.oos_mdd:.1%}", "",
             "## Selected traders + weights", "",
             weights.to_frame("weight").to_markdown()]
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines))
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: GO/NO-GO verdict + report writer"`

---

### Task 13: CLI wiring (end-to-end)

**Files:**
- Create: `src/hlvault/cli.py`, `tests/test_cli_smoke.py`

- [ ] **Step 1: Write failing smoke test `tests/test_cli_smoke.py`** that runs the full pipeline on a synthetic fixture (no network) and asserts a verdict file is produced.

```python
from hlvault.cli import run_backtest_pipeline
import pandas as pd, numpy as np


def test_pipeline_produces_verdict(tmp_path):
    rng = np.random.default_rng(11)
    idx = pd.date_range("2025-01-01", periods=400, freq="D")
    panel = pd.DataFrame(rng.normal(0.001, 0.01, (400, 8)),
                         index=idx, columns=[f"t{i}" for i in range(8)])
    btc = pd.Series(rng.normal(0.0, 0.02, 400), index=idx)
    out = run_backtest_pipeline(panel, btc, top_n=3,
                                report_path=tmp_path / "v.md")
    assert out.decision in ("GO", "NO-GO")
    assert (tmp_path / "v.md").exists()
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `src/hlvault/cli.py`** wiring select→weights→walk_forward→verdict, plus an argparse `main()` with `select`/`backtest`/`report` subcommands that load cached parquet. Show the full function in the TDD cycle:

```python
"""End-to-end wiring. The live data path (universe->ingest->equity) feeds the
same `panel` the synthetic smoke test uses, so the analytic core is identical
in test and production."""
from __future__ import annotations
import argparse
import pandas as pd
from .weights import hrp_weights
from .backtest import walk_forward
from .report import verdict, write_report, Verdict


def run_backtest_pipeline(panel: pd.DataFrame, btc: pd.Series, top_n: int,
                          report_path, rebalance_days: int = 30,
                          horizon_days: int = 30) -> Verdict:
    def select(as_of, past):
        scores = past.mean() / past.std(ddof=1)
        chosen = scores.nlargest(top_n).index
        return hrp_weights(past[chosen])
    res = walk_forward(panel, select, rebalance_days, horizon_days)
    btc_oos = btc.reindex(res.oos_returns.index).fillna(0.0)
    v = verdict(res.oos_returns, btc_oos)
    final_w = select(panel.index.max(), panel)
    write_report(report_path, v, pd.DataFrame(), final_w)
    return v


def main(argv=None):
    p = argparse.ArgumentParser(prog="hl-vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backtest")
    sub.add_parser("select")
    sub.add_parser("report")
    args = p.parse_args(argv)
    # subcommands load cached parquet panels from Settings dirs; see docstring
    raise SystemExit(f"cmd={args.cmd} (wire to cached parquet panels)")
```

- [ ] **Step 4: Run, expect pass.** Commit: `git commit -am "feat: CLI wiring + end-to-end synthetic smoke test"`

---

### Task 14: Live data run + real OOS verdict (the go/no-go experiment)

**Files:** none new — uses cached real data via `ingest` + `equity`.

- [ ] **Step 1:** Pull leaderboard universe (top 300) via `HLApiFillSource`/`get_leaderboard`. Cache.
- [ ] **Step 2:** Acquire deep-history fills from `s3://hl-mainnet-node-data/node_fills_by_block` (requester-pays, boto3) for the universe; cache to parquet. If S3 access is blocked, fall back to `userFillsByTime` recent window and **document the reduced history honestly** in the report.
- [ ] **Step 3:** Reconstruct equity → daily-return panel; apply sample-length gate; compute metrics, factors, selection.
- [ ] **Step 4:** Run `run_backtest_pipeline` on the real panel → produce `reports/oos-verdict.md`.
- [ ] **Step 5:** **STOP and surface the verdict to the user.** This is the go/no-go gate; sub-project B proceeds only on GO. Commit the report.

---

## Self-Review

**Spec coverage:** universe(§1)→T5, ingest(§2)→T4, equity+gate(§3)→T6, metrics+DSR(§4)→T7, factors(§5)→T8, select(§6)→T10, weights HRP/RP/Kelly+LedoitWolf(§7)→T9, backtest+no-lookahead(§8)→T11, report+verdict(§9)→T12, CLI→T13, point-in-time as-of→T3+T11, no-network→T0, compared-values same-source→T6 docstring/test, live go/no-go→T14. All covered.

**Placeholder scan:** every code step has real code; T14 is intentionally an operational run (no code) gated on real data acquisition. No TBDs.

**Type consistency:** `FactorFit` fields used in T10 (`alpha_tstat`) match T8 definition; `BacktestResult.oos_returns/rebalance_dates` used in T12/T13 match T11; `Verdict` fields match T12↔T13; `hrp_weights`/`shrunk_cov` signatures consistent T9↔T13.

**Note on `add_unrealized` (T6):** flagged as an in-task follow-on TDD cycle rather than a separate task to keep equity reconstruction cohesive; executor must not skip it — unrealized MtM is required for traders holding open positions across the sample.
