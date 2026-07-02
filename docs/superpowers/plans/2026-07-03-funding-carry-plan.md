# Funding-Carry Engine (`hlvault.carry`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delta-neutral HYPE funding-carry engine (long spot HYPE `@107` + short HYPE perp, collect funding) on the ex-momentum wallet, with liquidation-defense rebalancing and the established 20%-MDD/alerting/dry-run safety family.

**Architecture:** New `hlvault/carry/` subpackage mirroring `hlvault/momentum/`'s proven layout: isolated `dotenv_values` config, JSON state, pure decision functions (`engine.py`), pure funding signal (`funding.py`), a dedicated equity snapshot (`equity.py` — deliberately different basis from gridbot's, documented), and a live loop (`live.py`) that re-reads exchange state every cycle (exchange = source of truth) and executes at most a short list of idempotent-ish actions per cycle. Reuses `gridbot.resilience.ResilientExchange`, `notify.telegram.send_alert`, `io.source.resilient_read`.

**Tech Stack:** Python 3.9, `hyperliquid-python-sdk` (`Exchange.order`, `Exchange.usd_class_transfer(amount, to_perp)` — signature verified), pandas only where already used, pytest.

**Resolved facts (verified live, 2026-07-03):**
- HYPE/USDC spot pair name: `"@107"`; HYPE spot `szDecimals=2`; spot price rule: ≤5 sig figs AND ≤(8−szDecimals) decimals (spot differs from perp's 6−szDecimals).
- Spot & perp mids track within bps (65.944 vs 65.94).
- The wallet's $1,000 USDC currently sits in **spot** (perp withdrawable 0.0) — setup helper must move ~⅓ to perp for short margin.
- Perp state fields: `clearinghouseState.withdrawable`, `marginSummary`, `assetPositions[].position.{szi,marginUsed,unrealizedPnl}`; spot via `spotClearinghouseState.balances[].{coin,total,hold}`.

---

## File structure

```
src/hlvault/carry/__init__.py        # CREATE (empty)
src/hlvault/carry/config.py          # CREATE: .env.carry via dotenv_values
src/hlvault/carry/state.py           # CREATE: halted/peak_equity/flags persistence
src/hlvault/carry/funding.py         # CREATE: funding history fetch + trailing signal (pure-ish)
src/hlvault/carry/equity.py          # CREATE: CarrySnapshot + carry_equity() (one basis)
src/hlvault/carry/engine.py          # CREATE: pure decision functions (plan_actions)
src/hlvault/carry/live.py            # CREATE: CarryEngine loop + main()
scripts/setup_carry_wallet.py        # CREATE: one-time spot<->perp USDC split helper
deploy/hl-carry.service              # CREATE
deploy/setup-carry.sh                # CREATE
pyproject.toml                       # MODIFY: hl-carry entry point
.gitignore                           # MODIFY: add .env.carry
tests/test_carry_state.py            # CREATE
tests/test_carry_funding.py          # CREATE
tests/test_carry_equity.py           # CREATE
tests/test_carry_engine.py           # CREATE  (incl. liquidation-defense sim)
tests/test_carry_live.py             # CREATE
```

`.env.carry` itself is created by the coordinator (holds real credentials — never by a subagent, never committed).

---

### Task 1: config + state + gitignore

**Files:**
- Create: `src/hlvault/carry/__init__.py` (empty)
- Create: `src/hlvault/carry/config.py`
- Create: `src/hlvault/carry/state.py`
- Modify: `.gitignore` (add `.env.carry` line after `.env.momentum`)
- Test: `tests/test_carry_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_carry_state.py
from hlvault.carry.state import default_state, load_state, save_state


def test_default_state_shape():
    assert default_state() == {
        "halted": False, "peak_equity": 0.0, "_alerted_this_halt": False,
        "_flatten_complete": False, "last_funding_check_ms": 0,
        "funding_ok": False,
    }


def test_load_missing_file_returns_default(tmp_path):
    assert load_state(tmp_path / "nope.json") == default_state()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = default_state()
    s["peak_equity"] = 999.5
    save_state(p, s)
    assert load_state(p) == s
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_carry_state.py -v` — expect ModuleNotFoundError.

- [ ] **Step 3: Implement**

`src/hlvault/carry/state.py` (same atomic-write pattern as momentum/state.py):

```python
"""JSON persistence for the live carry engine. Positions are always re-read
from the exchange each cycle (source of truth); only circuit-breaker and
signal bookkeeping persists here."""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "halted": False,
        "peak_equity": 0.0,
        "_alerted_this_halt": False,
        "_flatten_complete": False,
        "last_funding_check_ms": 0,
        "funding_ok": False,
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

`src/hlvault/carry/config.py` (mirrors momentum's isolated-dict pattern — read that file's docstring for why `dotenv_values`, not `load_dotenv`):

```python
"""Env-driven config for the live carry engine. Reads .env.carry via
dotenv_values() into a private dict (NEVER os.environ) — see
hlvault/momentum/config.py's docstring for the shared-os.environ collision
this prevents (three bots' env files define same-named keys)."""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env.carry"
_FILE_VALUES = dotenv_values(_ENV_PATH)


def _clean(val: str) -> str:
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


WALLET_PRIVATE_KEY = _env_str("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS = _env_str("WALLET_ADDRESS", "")
MAX_DRAWDOWN_PCT = _env_float("MAX_DRAWDOWN_PCT", "0.20")
LIVE_TRADING = _env_bool("LIVE_TRADING", "false")
NETWORK = _env_str("NETWORK", "mainnet")
HL_API_URL = "https://api.hyperliquid.xyz" if NETWORK == "mainnet" else "https://api.hyperliquid-testnet.xyz"

COIN = _env_str("COIN", "HYPE")               # perp market name
SPOT_PAIR = _env_str("SPOT_PAIR", "@107")      # HYPE/USDC spot pair
SPOT_SZ_DECIMALS = int(_env_float("SPOT_SZ_DECIMALS", "2"))

DEPLOY_FRACTION = _env_float("DEPLOY_FRACTION", "0.60")     # of equity into each leg
MAX_SHORT_LEVERAGE = _env_float("MAX_SHORT_LEVERAGE", "2.0")
REBALANCE_LEVERAGE = _env_float("REBALANCE_LEVERAGE", "2.5")  # act above this
MIN_SHORT_LEVERAGE = _env_float("MIN_SHORT_LEVERAGE", "1.2")  # act below this
DELTA_TOLERANCE = _env_float("DELTA_TOLERANCE", "0.02")       # |spot-short|/target
FUNDING_LOOKBACK_DAYS = _env_float("FUNDING_LOOKBACK_DAYS", "7")
EXIT_FUNDING_APR = _env_float("EXIT_FUNDING_APR", "0.0")      # unwind below this
FUNDING_REFRESH_SECONDS = _env_float("FUNDING_REFRESH_SECONDS", "3600")

SYNC_INTERVAL_SECONDS = _env_float("SYNC_INTERVAL_SECONDS", "300")
MIN_ORDER_NOTIONAL = _env_float("MIN_ORDER_NOTIONAL", "12")
ORDER_SLIPPAGE = _env_float("ORDER_SLIPPAGE", "0.05")

TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID", "")

STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "cache" / "carry_state.json"
```

- [ ] **Step 4: Run tests + import check**

Run: `.venv/bin/pytest tests/test_carry_state.py -v` — expect 3 PASS.
Run: `.venv/bin/python -c "from hlvault.carry import config; print(config.COIN, config.SPOT_PAIR, config.LIVE_TRADING)"` — expect `HYPE @107 False`.

- [ ] **Step 5: Add `.env.carry` to `.gitignore`** (one line, after `.env.momentum`).

- [ ] **Step 6: Commit**

```bash
git add src/hlvault/carry/__init__.py src/hlvault/carry/config.py src/hlvault/carry/state.py tests/test_carry_state.py .gitignore
git commit -m "feat: carry engine config + state persistence"
```

---

### Task 2: `funding.py` — trailing funding signal

**Files:**
- Create: `src/hlvault/carry/funding.py`
- Test: `tests/test_carry_funding.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_carry_funding.py
from unittest.mock import patch

from hlvault.carry.funding import trailing_funding_apr, funding_ok


def _rates(hourly_rate, hours):
    return [{"fundingRate": str(hourly_rate), "time": 1000 + i} for i in range(hours)]


def test_trailing_funding_apr_annualizes_hourly_mean():
    # 1bp/hour = 0.0001 * 24 * 365 = 87.6% APR
    with patch("hlvault.carry.funding._fetch_funding", return_value=_rates(0.0001, 168)):
        apr = trailing_funding_apr("HYPE", days=7)
    assert abs(apr - 0.0001 * 24 * 365) < 1e-9


def test_trailing_funding_apr_empty_history_is_zero():
    with patch("hlvault.carry.funding._fetch_funding", return_value=[]):
        assert trailing_funding_apr("HYPE", days=7) == 0.0


def test_funding_ok_thresholds():
    assert funding_ok(0.05, exit_apr=0.0) is True
    assert funding_ok(-0.01, exit_apr=0.0) is False
    assert funding_ok(0.0, exit_apr=0.0) is False  # strictly greater required
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_carry_funding.py -v`.

- [ ] **Step 3: Implement**

```python
"""Trailing funding signal. Shorts RECEIVE funding when the rate is
positive; the engine holds the carry while trailing funding stays positive
and unwinds when it turns negative (low turnover by design — the naive
daily-rotation variant lost to fees in research)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from hlvault.io.source import SemanticError, TransientError, resilient_read

INFO_URL = "https://api.hyperliquid.xyz/info"
HOURS_PER_YEAR = 24 * 365


def _fetch_funding(coin: str, start_ms: int) -> list[dict]:
    body = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}

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


def trailing_funding_apr(coin: str, days: float) -> float:
    start = int(time.time() * 1000) - int(days * 86400 * 1000)
    rows = _fetch_funding(coin, start)
    if not rows:
        return 0.0
    rates = [float(r["fundingRate"]) for r in rows]
    return sum(rates) / len(rates) * HOURS_PER_YEAR


def funding_ok(apr: float, exit_apr: float) -> bool:
    return apr > exit_apr
```

- [ ] **Step 4: Run tests** — expect 3 PASS.
- [ ] **Step 5: Commit** — `git add src/hlvault/carry/funding.py tests/test_carry_funding.py && git commit -m "feat: carry trailing funding signal"`

---

### Task 3: `equity.py` — CarrySnapshot, one equity basis

**Files:**
- Create: `src/hlvault/carry/equity.py`
- Test: `tests/test_carry_equity.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_carry_equity.py
from hlvault.carry.equity import CarrySnapshot, take_snapshot


class _FakeInfo:
    def __init__(self, spot_usdc="400.0", spot_hype="9.0", hype_mid="66.0",
                 szi="-9.0", margin_used="200.0", upnl="-5.0", withdrawable="95.0"):
        self._spot_usdc, self._spot_hype = spot_usdc, spot_hype
        self._mid, self._szi = hype_mid, szi
        self._margin, self._upnl, self._withdrawable = margin_used, upnl, withdrawable

    def spot_user_state(self, address):
        return {"balances": [
            {"coin": "USDC", "total": self._spot_usdc, "hold": "0.0"},
            {"coin": "HYPE", "total": self._spot_hype, "hold": "0.0"},
        ]}

    def user_state(self, address):
        pos = [] if float(self._szi) == 0 else [{"position": {
            "coin": "HYPE", "szi": self._szi,
            "marginUsed": self._margin, "unrealizedPnl": self._upnl}}]
        return {"assetPositions": pos, "withdrawable": self._withdrawable}

    def all_mids(self):
        return {"HYPE": self._mid, "@107": self._mid}


def test_snapshot_totals_and_equity_from_one_read():
    info = _FakeInfo()
    s = take_snapshot(info, "0xabc", coin="HYPE", spot_pair="@107")
    assert s.spot_usdc == 400.0
    assert s.spot_coin_size == 9.0
    assert abs(s.spot_coin_ntl - 9.0 * 66.0) < 1e-9
    assert s.perp_short_size == 9.0           # abs of szi, short
    assert abs(s.perp_short_ntl - 9.0 * 66.0) < 1e-9
    assert s.perp_margin_used == 200.0
    assert s.perp_withdrawable == 95.0
    # equity = spot USDC + spot HYPE ntl + margin + upnl + withdrawable
    assert abs(s.equity - (400.0 + 594.0 + 200.0 - 5.0 + 95.0)) < 1e-9


def test_short_leverage_and_delta():
    s = take_snapshot(_FakeInfo(), "0xabc", coin="HYPE", spot_pair="@107")
    # leverage = short notional / (margin + upnl + withdrawable)
    assert abs(s.short_leverage - 594.0 / (200.0 - 5.0 + 95.0)) < 1e-9
    assert abs(s.delta_ntl - (594.0 - 594.0)) < 1e-9


def test_flat_wallet_has_zero_leverage_not_crash():
    info = _FakeInfo(spot_hype="0.0", szi="0.0", margin_used="0.0",
                     upnl="0.0", withdrawable="0.0", spot_usdc="1000.0")
    s = take_snapshot(info, "0xabc", coin="HYPE", spot_pair="@107")
    assert s.equity == 1000.0
    assert s.short_leverage == 0.0
    assert s.perp_short_size == 0.0


def test_long_perp_position_is_reported_negative_short():
    # a LONG perp position (szi > 0) must not masquerade as a short
    s = take_snapshot(_FakeInfo(szi="3.0"), "0xabc", coin="HYPE", spot_pair="@107")
    assert s.perp_short_size == -3.0  # signed: negative means "not short"
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

```python
"""One equity basis for the carry wallet (CLAUDE.md #1): all fields read in
one cycle from the same Info client.

DELIBERATE DIVERGENCE from gridbot.exchange_utils.get_account_equity:
gridbot's basis (spot USDC + perp position economics) is correct for a
wallet whose value lives in spot USDC, but the carry wallet's value is
mostly spot HYPE plus perp free margin, so it additionally counts
spot-coin-at-mark and perp `withdrawable`. Do not "unify" these two
functions — their wallets hold different things."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CarrySnapshot:
    mid: float
    spot_usdc: float
    spot_coin_size: float
    spot_coin_ntl: float
    perp_short_size: float    # abs size when short; negative when (wrongly) long
    perp_short_ntl: float
    perp_margin_used: float
    perp_upnl: float
    perp_withdrawable: float
    equity: float
    short_leverage: float     # short ntl / perp-side equity, 0 when no short
    delta_ntl: float          # spot ntl - short ntl (want ~0)


def take_snapshot(info, address: str, coin: str, spot_pair: str) -> CarrySnapshot:
    mids = info.all_mids()
    mid = float(mids.get(coin) or 0.0)

    spot = info.spot_user_state(address)
    spot_usdc = 0.0
    spot_coin = 0.0
    for b in spot.get("balances", []):
        if b.get("coin") == "USDC":
            spot_usdc = float(b.get("total", 0.0))
        elif b.get("coin") == coin:
            spot_coin = float(b.get("total", 0.0))

    perp = info.user_state(address)
    szi = 0.0
    margin_used = 0.0
    upnl = 0.0
    for p in perp.get("assetPositions", []):
        pos = p["position"]
        if pos.get("coin") == coin:
            szi = float(pos["szi"])
            margin_used = float(pos["marginUsed"])
            upnl = float(pos["unrealizedPnl"])
    withdrawable = float(perp.get("withdrawable", 0.0))

    spot_ntl = spot_coin * mid
    short_size = -szi  # szi<0 = short -> positive; szi>0 (long) -> negative flag
    short_ntl = max(short_size, 0.0) * mid
    perp_equity = margin_used + upnl + withdrawable
    leverage = short_ntl / perp_equity if (short_ntl > 0 and perp_equity > 0) else 0.0
    equity = spot_usdc + spot_ntl + perp_equity

    return CarrySnapshot(
        mid=mid, spot_usdc=spot_usdc, spot_coin_size=spot_coin,
        spot_coin_ntl=spot_ntl, perp_short_size=short_size,
        perp_short_ntl=short_ntl, perp_margin_used=margin_used, perp_upnl=upnl,
        perp_withdrawable=withdrawable, equity=equity,
        short_leverage=leverage, delta_ntl=spot_ntl - short_ntl,
    )
```

- [ ] **Step 4: Run tests** — expect 4 PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: carry wallet equity snapshot (one basis)"`

---

### Task 4: `engine.py` — pure decisions + liquidation-defense simulation

**Files:**
- Create: `src/hlvault/carry/engine.py`
- Test: `tests/test_carry_engine.py`

The engine returns a short ordered list of `Action`s per cycle; the live
loop executes them and the NEXT cycle re-reads exchange state (self-correcting
reconciliation, one step at a time — no multi-step local bookkeeping).

Action kinds: `buy_spot` / `sell_spot` (size in coin), `open_short` /
`close_short` (size in coin), `to_perp` / `to_spot` (USDC amount).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_carry_engine.py
from dataclasses import replace

from hlvault.carry.engine import Action, plan_actions
from hlvault.carry.equity import CarrySnapshot


def snap(mid=100.0, spot_usdc=1000.0, spot_coin=0.0, short=0.0,
         margin=0.0, upnl=0.0, withdrawable=0.0):
    spot_ntl = spot_coin * mid
    short_ntl = max(short, 0.0) * mid
    perp_eq = margin + upnl + withdrawable
    lev = short_ntl / perp_eq if (short_ntl > 0 and perp_eq > 0) else 0.0
    return CarrySnapshot(mid=mid, spot_usdc=spot_usdc, spot_coin_size=spot_coin,
                         spot_coin_ntl=spot_ntl, perp_short_size=short,
                         perp_short_ntl=short_ntl, perp_margin_used=margin,
                         perp_upnl=upnl, perp_withdrawable=withdrawable,
                         equity=spot_usdc + spot_ntl + perp_eq,
                         short_leverage=lev, delta_ntl=spot_ntl - short_ntl)


CFG = dict(deploy_fraction=0.6, max_short_leverage=2.0, rebalance_leverage=2.5,
           min_short_leverage=1.2, delta_tolerance=0.02, min_order_notional=12.0)


def test_flat_and_funding_ok_enters_in_order():
    # $1000 all in spot USDC, funding positive -> move margin, buy spot, open short
    actions = plan_actions(snap(), funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["to_perp", "buy_spot", "open_short"]
    to_perp = actions[0]
    # target ntl = 0.6*1000 = 600; margin needed = 600/2.0 = 300
    assert abs(to_perp.amount - 300.0) < 1e-6
    assert abs(actions[1].size - 6.0) < 1e-6   # $600 / $100
    assert abs(actions[2].size - 6.0) < 1e-6


def test_funding_bad_unwinds_everything():
    s = snap(spot_usdc=100.0, spot_coin=6.0, short=6.0, margin=250.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=False, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["close_short", "sell_spot", "to_spot"]
    assert abs(actions[0].size - 6.0) < 1e-6
    assert abs(actions[1].size - 6.0) < 1e-6


def test_balanced_position_produces_no_actions():
    # 6 HYPE spot vs 6 short at ~1.71x leverage, delta 0 -> hold
    s = snap(spot_usdc=50.0, spot_coin=6.0, short=6.0, margin=300.0,
             withdrawable=50.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


def test_pump_pushes_leverage_up_and_triggers_margin_topup():
    # price doubled: short ntl 1200, perp equity 350-600=-250+600=350... construct:
    # margin 300, upnl -600 (short lost), withdrawable 50 -> perp eq -250 (!) --
    # use milder pump: mid 140 -> short ntl 840, upnl -240, perp eq 110, lev 7.6
    s = snap(mid=140.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=-240.0, withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["sell_spot", "to_perp"]
    sell = actions[0]
    # sells enough spot so that transferring the proceeds restores <= max leverage:
    # need perp equity >= 840/2 = 420; have 110 -> shortfall 310 -> sell >= $310 of spot
    assert sell.size * 140.0 >= 310.0 - 1e-6
    # never sells more spot than needed to ALSO stay delta-neutral-ish: the
    # matching short reduction is planned next cycle by the delta guard; here
    # we only require the sale is bounded by what exists
    assert sell.size <= 6.0


def test_price_drop_pulls_excess_margin_back_and_tops_up():
    # price fell to 60: short ntl 360, upnl +240, perp eq 590, lev 0.61 < 1.2
    s = snap(mid=60.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=240.0, withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert actions and actions[0].kind == "to_spot"
    # move excess so remaining perp equity ~= 360/2 = 180: excess = 590-180 = 410
    assert abs(actions[0].amount - 410.0) < 1.0


def test_delta_drift_trims_larger_leg():
    # spot 6.5 vs short 6.0 at mid 100: delta $50 > 2% of target(600)=12
    s = snap(spot_usdc=10.0, spot_coin=6.5, short=6.0, margin=300.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert actions[0].kind == "sell_spot"
    assert abs(actions[0].size - 0.5) < 1e-6


def test_dust_actions_below_min_notional_are_suppressed():
    # tiny delta ($5 < $12 min): no action
    s = snap(spot_usdc=10.0, spot_coin=6.05, short=6.0, margin=300.0,
             withdrawable=50.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


def test_liquidation_defense_simulation_2x_pump():
    """Feed a synthetic pump from $100 to $200 in 5% steps; apply the
    engine's planned actions to a simulated wallet each step; assert perp
    equity never drops below HYPE maintenance margin (ntl / (2*5) = 10% ntl,
    5x max leverage) — i.e. the rebalancer acts before liquidation."""
    mid, spot_usdc, spot_coin, short = 100.0, 40.0, 6.0, 6.0
    margin, withdrawable = 300.0, 60.0
    entry = mid
    while mid < 200.0:
        mid *= 1.05
        upnl = (entry - mid) * short
        s = snap(mid=mid, spot_usdc=spot_usdc, spot_coin=spot_coin,
                 short=short, margin=margin, upnl=upnl,
                 withdrawable=withdrawable)
        perp_equity = margin + upnl + withdrawable
        maintenance = 0.10 * short * mid
        assert perp_equity > maintenance, f"liquidated at mid={mid:.1f}"
        for a in plan_actions(s, funding_is_ok=True, **CFG):
            if a.kind == "sell_spot":
                sell = min(a.size, spot_coin)
                spot_coin -= sell
                spot_usdc += sell * mid
            elif a.kind == "to_perp":
                amt = min(a.amount, spot_usdc)
                spot_usdc -= amt
                withdrawable += amt
            elif a.kind == "close_short":
                # realize upnl on the closed fraction into margin pool
                frac = min(a.size, short) / short if short else 0.0
                withdrawable += upnl * frac
                short -= min(a.size, short)
                entry = mid  # remaining position re-marked for sim simplicity
            # buy_spot / open_short / to_spot not expected during a pump
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `engine.py`**

```python
"""Pure per-cycle decision function for the carry engine. Returns a SHORT
ordered action list; the live loop executes it and the next cycle re-plans
from fresh exchange state (self-correcting — no local multi-step plans).

Priority order (first match wins the cycle):
  1. funding turned bad -> full unwind sequence
  2. leverage too high (pump) -> sell spot, top up perp margin  [liquidation defense]
  3. leverage too low (dump) -> pull excess margin back to spot
  4. delta drift -> trim the larger leg
  5. flat + funding ok -> enter (margin over, buy spot, open short)
"""
from __future__ import annotations

from dataclasses import dataclass

from .equity import CarrySnapshot


@dataclass(frozen=True)
class Action:
    kind: str            # buy_spot|sell_spot|open_short|close_short|to_perp|to_spot
    size: float = 0.0    # coin units (spot/perp orders)
    amount: float = 0.0  # USDC (transfers)


def plan_actions(s: CarrySnapshot, funding_is_ok: bool, *, deploy_fraction: float,
                 max_short_leverage: float, rebalance_leverage: float,
                 min_short_leverage: float, delta_tolerance: float,
                 min_order_notional: float) -> list[Action]:
    if s.mid <= 0:
        return []
    target_ntl = s.equity * deploy_fraction
    perp_equity = s.perp_margin_used + s.perp_upnl + s.perp_withdrawable
    has_position = s.perp_short_ntl > min_order_notional or s.spot_coin_ntl > min_order_notional

    # 1. funding bad -> unwind everything (close short first: it's the leg
    #    that can be liquidated; spot can wait a cycle if something fails)
    if not funding_is_ok:
        if not has_position:
            return []
        acts = []
        if s.perp_short_size * s.mid > min_order_notional:
            acts.append(Action("close_short", size=s.perp_short_size))
        if s.spot_coin_ntl > min_order_notional:
            acts.append(Action("sell_spot", size=s.spot_coin_size))
        if perp_equity > min_order_notional:
            acts.append(Action("to_spot", amount=perp_equity))
        return acts

    # 2. leverage too high -> liquidation defense: sell spot, move USDC to perp
    if s.short_leverage > rebalance_leverage:
        needed_equity = s.perp_short_ntl / max_short_leverage
        shortfall = needed_equity - perp_equity
        sellable_usd = min(shortfall, s.spot_coin_ntl)
        acts = []
        if sellable_usd > min_order_notional:
            acts.append(Action("sell_spot", size=sellable_usd / s.mid))
        transfer = min(shortfall, s.spot_usdc + sellable_usd)
        if transfer > min_order_notional:
            acts.append(Action("to_perp", amount=transfer))
        if acts:
            return acts
        # nothing left to sell/transfer -> shrink the short itself
        excess_ntl = s.perp_short_ntl - perp_equity * max_short_leverage
        if excess_ntl > min_order_notional:
            return [Action("close_short", size=excess_ntl / s.mid)]
        return []

    # 3. leverage far too low with a live position -> recycle idle margin
    if has_position and 0 < s.short_leverage < min_short_leverage:
        excess = perp_equity - s.perp_short_ntl / max_short_leverage
        if excess > min_order_notional:
            return [Action("to_spot", amount=excess)]

    # 4. delta drift -> trim the larger leg toward the smaller
    if has_position:
        tol = max(delta_tolerance * max(target_ntl, 1.0), min_order_notional)
        if s.delta_ntl > tol:
            return [Action("sell_spot", size=s.delta_ntl / s.mid)]
        if -s.delta_ntl > tol:
            return [Action("close_short", size=-s.delta_ntl / s.mid)]

    # 5. flat -> enter
    if not has_position:
        margin_needed = target_ntl / max_short_leverage
        size = target_ntl / s.mid
        if target_ntl <= min_order_notional:
            return []
        acts = []
        if margin_needed - perp_equity > min_order_notional:
            acts.append(Action("to_perp", amount=margin_needed - perp_equity))
        acts.append(Action("buy_spot", size=size))
        acts.append(Action("open_short", size=size))
        return acts

    return []
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_carry_engine.py -v` — expect all PASS, especially the simulation. If the simulation fails, the ENGINE is wrong (the test models exchange mechanics) — fix the engine, do not weaken the maintenance-margin assertion.
- [ ] **Step 5: Commit** — `git commit -m "feat: carry decision engine + liquidation-defense simulation"`

---

### Task 5: `live.py` — CarryEngine loop

**Files:**
- Create: `src/hlvault/carry/live.py`
- Modify: `pyproject.toml` (`hl-carry = "hlvault.carry.live:main"` under `[project.scripts]`)
- Test: `tests/test_carry_live.py`

Key requirements (all proven patterns from momentum/live.py — read it first):
- `check_drawdown`: compute equity via `take_snapshot`, track peak in state, halt at `MAX_DRAWDOWN_PCT`; persist halt BEFORE flatten; alert once (`_alerted_this_halt`); retry flatten until `_flatten_complete`; second alert on failed attempts.
- `_flatten_everything`: unwind = close short (perp IoC reduce_only), sell all spot coin, both dry-run-gated; returns bool success.
- `_execute(action)`: dry-run gated; spot orders use `cfg.SPOT_PAIR` name with spot price rule (≤5 sig figs, ≤(8−`SPOT_SZ_DECIMALS`) decimals — implement a local `_round_spot_price`; document divergence from perp's 6−szDecimals rule); perp orders reuse `round_price`/`round_size`/`get_sz_decimals` from gridbot.exchange_utils; transfers call `self.exchange_raw.usd_class_transfer(amount, to_perp)` through `gridbot.resilience.run(fn, what="usd_class_transfer", idempotent=False)` (single attempt, surface errors, next cycle self-corrects).
- `run_once`: snapshot → drawdown gate → hourly funding-signal refresh (persisted `funding_ok` + `last_funding_check_ms`) → `plan_actions` → execute in order → save state.
- `main()` with `--once/--dry-run/--status`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_carry_live.py
from hlvault.carry import config as cfg
from hlvault.carry.live import CarryEngine, _round_spot_price


class _FakeInfo:
    def __init__(self, mid=100.0, spot_usdc=1000.0, spot_hype=0.0, szi=0.0,
                 margin="0.0", upnl="0.0", withdrawable="0.0"):
        self.mid, self._szi = mid, szi
        self._spot_usdc, self._spot_hype = spot_usdc, spot_hype
        self._margin, self._upnl, self._wd = margin, upnl, withdrawable

    def all_mids(self):
        return {"HYPE": str(self.mid), "@107": str(self.mid)}

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": str(self._spot_usdc), "hold": "0"},
                             {"coin": "HYPE", "total": str(self._spot_hype), "hold": "0"}]}

    def user_state(self, address):
        pos = [] if float(self._szi) == 0 else [{"position": {
            "coin": "HYPE", "szi": str(self._szi), "marginUsed": self._margin,
            "unrealizedPnl": self._upnl}}]
        return {"assetPositions": pos, "withdrawable": self._wd}

    def meta(self):
        return {"universe": [{"name": "HYPE", "szDecimals": 2, "maxLeverage": 5}]}


class _FakeExchange:
    def __init__(self):
        self.orders = []
        self.transfers = []

    def order(self, coin, is_buy, size, px, order_type=None, reduce_only=False):
        self.orders.append({"coin": coin, "is_buy": is_buy, "size": size,
                            "px": px, "reduce_only": reduce_only})
        return {"response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}

    def market_close(self, coin, size):
        self.orders.append({"coin": coin, "market_close": size})
        return {"status": "ok"}

    def usd_class_transfer(self, amount, to_perp):
        self.transfers.append((amount, to_perp))
        return {"status": "ok"}


def _engine(info, exchange, live=True, state=None):
    e = CarryEngine.__new__(CarryEngine)
    e.info = info
    from hlvault.gridbot.resilience import ResilientExchange
    e.exchange = ResilientExchange(exchange)
    e.exchange_raw = exchange
    e.live_trading = live
    e.state = state or {"halted": False, "peak_equity": 0.0,
                        "_alerted_this_halt": False, "_flatten_complete": False,
                        "last_funding_check_ms": 0, "funding_ok": True}
    return e


def test_round_spot_price_rule():
    # spot rule: <=5 sig figs AND <=(8-szDecimals)=6 decimals for HYPE
    assert _round_spot_price(66.123456789, 2) == 66.123
    assert _round_spot_price(0.00012345678, 2) == 0.00012346


def test_dry_run_executes_nothing(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=False)
    from hlvault.carry.engine import Action
    e._execute(Action("buy_spot", size=1.0))
    e._execute(Action("to_perp", amount=100.0))
    assert ex.orders == [] and ex.transfers == []


def test_execute_buy_spot_uses_spot_pair_and_rounding(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "SPOT_PAIR", "@107")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=66.123456), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("buy_spot", size=1.23456))
    o = ex.orders[0]
    assert o["coin"] == "@107"
    assert o["is_buy"] is True
    assert o["size"] == 1.23   # spot szDecimals=2
    assert o["reduce_only"] is False


def test_execute_open_short_is_perp_not_reduce_only(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("open_short", size=2.0))
    o = ex.orders[0]
    assert o["coin"] == "HYPE" and o["is_buy"] is False and o["reduce_only"] is False


def test_execute_close_short_is_reduce_only(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0, szi=-2.0, margin="100", withdrawable="50"), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("close_short", size=2.0))
    assert ex.orders[0]["reduce_only"] is True


def test_transfer_calls_usd_class_transfer(monkeypatch):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=True)
    from hlvault.carry.engine import Action
    e._execute(Action("to_perp", amount=300.0))
    e._execute(Action("to_spot", amount=50.0))
    assert ex.transfers == [(300.0, True), (50.0, False)]


def test_drawdown_halt_persists_before_flatten(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "")

    class _CrashingExchange(_FakeExchange):
        def market_close(self, coin, size):
            raise RuntimeError("boom")

    calls = {"n": 0}

    class _DropInfo(_FakeInfo):
        def spot_user_state(self, address):
            calls["n"] += 1
            usdc = "1000.0" if calls["n"] <= 1 else "750.0"
            return {"balances": [{"coin": "USDC", "total": usdc, "hold": "0"},
                                 {"coin": "HYPE", "total": "1.0", "hold": "0"}]}

    info = _DropInfo(mid=10.0, szi=-1.0, margin="20", withdrawable="10")
    e = _engine(info, _CrashingExchange(), live=True)
    assert e.check_drawdown() is False   # first: sets peak (1000+10+20+10=1040)
    assert e.check_drawdown() is True    # second: 790/1040 -> ~24% dd -> halt
    from hlvault.carry.state import load_state
    assert load_state(cfg.STATE_FILE)["halted"] is True
    assert load_state(cfg.STATE_FILE)["_flatten_complete"] is False


def test_run_once_skips_planning_when_halted(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "s.json")
    ex = _FakeExchange()
    e = _engine(_FakeInfo(), ex, live=True,
                state={"halted": True, "peak_equity": 1000.0,
                       "_alerted_this_halt": True, "_flatten_complete": True,
                       "last_funding_check_ms": 0, "funding_ok": True})
    e.run_once()
    assert ex.orders == [] and ex.transfers == []
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `live.py`**

```python
"""Live carry engine: delta-neutral HYPE carry (long spot @107 / short perp),
funding-gated, with liquidation-defense rebalancing. Cycle: snapshot ->
drawdown gate -> hourly funding refresh -> plan_actions -> execute -> save.

Transfers (usd_class_transfer) are NON-idempotent: executed with a single
attempt through gridbot.resilience.run (no blind retry — a lost response
self-corrects next cycle when the snapshot re-reads real balances)."""
from __future__ import annotations

import argparse
import logging
import time

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from hlvault.gridbot.exchange_utils import get_sz_decimals, round_price, round_size
from hlvault.gridbot.resilience import ResilientExchange, run as resilient_run
from hlvault.notify.telegram import send_alert

from . import config as cfg
from .engine import Action, plan_actions
from .equity import take_snapshot
from .funding import funding_ok, trailing_funding_apr
from .state import load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("carry")


def _round_spot_price(px: float, spot_sz_decimals: int) -> float:
    """HL SPOT price rule: <=5 significant figures AND <=(8 - szDecimals)
    decimals — differs from the perp rule (6 - szDecimals) implemented in
    gridbot.exchange_utils.round_price, hence a local helper."""
    if px <= 0:
        return 0.0
    sig = float(f"{px:.5g}")
    return round(sig, max(8 - spot_sz_decimals, 0))


class CarryEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.carry")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw)
        self.exchange_raw = raw
        self.state = load_state(cfg.STATE_FILE)

    # ---- safety ------------------------------------------------------
    def bootstrap_if_needed(self, snapshot) -> None:
        if self.state.get("peak_equity", 0.0) > 0:
            return
        self.state["peak_equity"] = snapshot.equity
        save_state(cfg.STATE_FILE, self.state)
        logger.info(f"bootstrap: starting equity ${snapshot.equity:,.2f}")

    def check_drawdown(self) -> bool:
        snapshot = take_snapshot(self.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        self.bootstrap_if_needed(snapshot)
        if not self.state.get("halted"):
            peak = max(self.state.get("peak_equity", 0.0), snapshot.equity)
            self.state["peak_equity"] = peak
            dd = (peak - snapshot.equity) / peak if peak > 0 else 0.0
            if dd < cfg.MAX_DRAWDOWN_PCT:
                save_state(cfg.STATE_FILE, self.state)
                return False
            logger.error(f"CARRY DRAWDOWN BREAKER: {dd:.1%} "
                        f"(peak ${peak:,.2f} -> ${snapshot.equity:,.2f})")
            self.state["halted"] = True
        # persist halt BEFORE flatten (crash mid-flatten must not lose it)
        save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_alerted_this_halt"):
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                      "CARRY DRAWDOWN CIRCUIT BREAKER TRIPPED — unwinding and halting.")
            self.state["_alerted_this_halt"] = True
            save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_flatten_complete"):
            if self._flatten_everything():
                self.state["_flatten_complete"] = True
            else:
                send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                          "CARRY UNWIND INCOMPLETE — will retry next cycle.")
            save_state(cfg.STATE_FILE, self.state)
        return True

    def _flatten_everything(self) -> bool:
        """Close the short, sell all spot coin. Returns True only when both
        legs confirmed flat (or already flat). Dry-run logs and skips."""
        s = take_snapshot(self.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        ok = True
        if s.perp_short_size * s.mid > cfg.MIN_ORDER_NOTIONAL:
            if not self.live_trading:
                logger.info(f"[DRY RUN] would close short {s.perp_short_size}")
            else:
                try:
                    self.exchange.market_close(cfg.COIN, s.perp_short_size)
                except Exception as e:
                    ok = False
                    logger.error(f"SAFETY-CRITICAL: close short failed: {e}")
        if s.spot_coin_ntl > cfg.MIN_ORDER_NOTIONAL:
            if not self.live_trading:
                logger.info(f"[DRY RUN] would sell spot {s.spot_coin_size}")
            else:
                try:
                    self._spot_order(is_buy=False, size=s.spot_coin_size, mid=s.mid)
                except Exception as e:
                    ok = False
                    logger.error(f"SAFETY-CRITICAL: spot sell failed: {e}")
        return ok

    # ---- execution ---------------------------------------------------
    def _spot_order(self, is_buy: bool, size: float, mid: float) -> None:
        raw_px = mid * (1 + cfg.ORDER_SLIPPAGE) if is_buy else mid * (1 - cfg.ORDER_SLIPPAGE)
        px = _round_spot_price(raw_px, cfg.SPOT_SZ_DECIMALS)
        sz = round_size(size, cfg.SPOT_SZ_DECIMALS)
        self.exchange.order(cfg.SPOT_PAIR, is_buy, sz, px,
                            order_type={"limit": {"tif": "Ioc"}}, reduce_only=False)

    def _perp_order(self, is_buy: bool, size: float, mid: float, reduce_only: bool) -> None:
        sz_dec = get_sz_decimals(self.info, cfg.COIN)
        raw_px = mid * (1 + cfg.ORDER_SLIPPAGE) if is_buy else mid * (1 - cfg.ORDER_SLIPPAGE)
        px = round_price(raw_px, sz_dec)
        sz = round_size(size, sz_dec)
        self.exchange.order(cfg.COIN, is_buy, sz, px,
                            order_type={"limit": {"tif": "Ioc"}}, reduce_only=reduce_only)

    def _execute(self, action: Action) -> None:
        if not self.live_trading:
            logger.info(f"[DRY RUN] {action}")
            return
        mids = self.info.all_mids()
        mid = float(mids.get(cfg.COIN) or 0.0)
        if mid <= 0:
            logger.warning("no mid price; skipping action this cycle")
            return
        try:
            if action.kind == "buy_spot":
                self._spot_order(True, action.size, mid)
            elif action.kind == "sell_spot":
                self._spot_order(False, action.size, mid)
            elif action.kind == "open_short":
                self._perp_order(False, action.size, mid, reduce_only=False)
            elif action.kind == "close_short":
                self._perp_order(True, action.size, mid, reduce_only=True)
            elif action.kind == "to_perp":
                resilient_run(lambda: self.exchange_raw.usd_class_transfer(action.amount, True),
                              what="usd_class_transfer", idempotent=False)
            elif action.kind == "to_spot":
                resilient_run(lambda: self.exchange_raw.usd_class_transfer(action.amount, False),
                              what="usd_class_transfer", idempotent=False)
            logger.info(f"executed {action}")
        except Exception as e:
            logger.error(f"action {action} failed: {e} (next cycle re-plans)")

    # ---- signal ------------------------------------------------------
    def _refresh_funding_if_due(self) -> bool:
        now_ms = int(time.time() * 1000)
        if now_ms - self.state.get("last_funding_check_ms", 0) >= cfg.FUNDING_REFRESH_SECONDS * 1000:
            apr = trailing_funding_apr(cfg.COIN, cfg.FUNDING_LOOKBACK_DAYS)
            self.state["funding_ok"] = funding_ok(apr, cfg.EXIT_FUNDING_APR)
            self.state["last_funding_check_ms"] = now_ms
            save_state(cfg.STATE_FILE, self.state)
            logger.info(f"funding refresh: trailing {cfg.FUNDING_LOOKBACK_DAYS:.0f}d "
                       f"APR={apr:+.1%} -> ok={self.state['funding_ok']}")
        return bool(self.state.get("funding_ok"))

    # ---- loop --------------------------------------------------------
    def run_once(self) -> None:
        if self.check_drawdown():
            return
        is_ok = self._refresh_funding_if_due()
        s = take_snapshot(self.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        actions = plan_actions(
            s, funding_is_ok=is_ok,
            deploy_fraction=cfg.DEPLOY_FRACTION,
            max_short_leverage=cfg.MAX_SHORT_LEVERAGE,
            rebalance_leverage=cfg.REBALANCE_LEVERAGE,
            min_short_leverage=cfg.MIN_SHORT_LEVERAGE,
            delta_tolerance=cfg.DELTA_TOLERANCE,
            min_order_notional=cfg.MIN_ORDER_NOTIONAL,
        )
        for a in actions:
            self._execute(a)

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("carry cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = CarryEngine(live_trading=False if args.dry_run else None)
    if args.status:
        s = take_snapshot(engine.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        print(f"equity ${s.equity:,.2f} | spot {s.spot_coin_size} {cfg.COIN} "
             f"(${s.spot_coin_ntl:,.2f}) + ${s.spot_usdc:,.2f} USDC | "
             f"short ${s.perp_short_ntl:,.2f} @ {s.short_leverage:.2f}x | "
             f"delta ${s.delta_ntl:+.2f} | halted={engine.state.get('halted')}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
```

Note for the implementer: `test_drawdown_halt_persists_before_flatten` expects
`check_drawdown` to return False on the first call while equity is at its
peak — verify the arithmetic in the fake matches (peak 1040 vs second read
790+30 = 820... compute the exact numbers from the fake's fields and adjust
the FAKE (not the implementation) if the intended ~24% drawdown doesn't come
out; the test's INTENT is: first call no-halt, second call halt + persisted
halt flag with `_flatten_complete` False after the crashing flatten).

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_carry_live.py -v`.
- [ ] **Step 5: Add `hl-carry = "hlvault.carry.live:main"` to `[project.scripts]`, reinstall, full suite**

Run: `.venv/bin/pip install -e . -q && .venv/bin/pytest -q` — all green.

- [ ] **Step 6: Commit** — `git commit -m "feat: carry live engine + hl-carry entry point"`

---

### Task 6: wallet setup helper + deploy files

**Files:**
- Create: `scripts/setup_carry_wallet.py`
- Create: `deploy/hl-carry.service` (mirror `deploy/hl-momentum.service`, s/momentum/carry/g)
- Create: `deploy/setup-carry.sh` (mirror `deploy/setup-momentum.sh`, s/momentum/carry/g, chmod +x)

- [ ] **Step 1: Write `scripts/setup_carry_wallet.py`**

```python
"""One-time wallet-split helper for the carry engine. Moves USDC between
spot and perp so the perp side holds enough margin for the target short
(target_ntl / MAX_SHORT_LEVERAGE, +5% buffer). Check-before-transfer:
re-runnable, transfers only the shortfall, never more than available.

    python scripts/setup_carry_wallet.py          # print plan (no transfer)
    python scripts/setup_carry_wallet.py --do-it  # execute the transfer
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from eth_account import Account  # noqa: E402
from hyperliquid.exchange import Exchange  # noqa: E402
from hyperliquid.info import Info  # noqa: E402

from hlvault.carry import config as cfg  # noqa: E402
from hlvault.carry.equity import take_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--do-it", action="store_true")
    args = parser.parse_args()

    info = Info(cfg.HL_API_URL, skip_ws=True)
    s = take_snapshot(info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
    target_ntl = s.equity * cfg.DEPLOY_FRACTION
    margin_target = target_ntl / cfg.MAX_SHORT_LEVERAGE * 1.05
    perp_equity = s.perp_margin_used + s.perp_upnl + s.perp_withdrawable
    shortfall = margin_target - perp_equity

    print(f"equity ${s.equity:,.2f} | target ntl ${target_ntl:,.2f} | "
         f"margin target ${margin_target:,.2f} | perp now ${perp_equity:,.2f}")
    if shortfall <= 1.0:
        print("perp side already funded — nothing to do")
        return
    amount = round(min(shortfall, s.spot_usdc), 2)
    print(f"plan: transfer ${amount:,.2f} spot -> perp")
    if not args.do_it:
        print("(dry plan only — rerun with --do-it to execute)")
        return
    account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
    ex = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
    result = ex.usd_class_transfer(amount, True)
    print("transfer result:", result)
    s2 = take_snapshot(info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
    print(f"after: spot USDC ${s2.spot_usdc:,.2f} | perp withdrawable ${s2.perp_withdrawable:,.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create the two deploy files** by copying the momentum ones and substituting names (`hl-momentum`→`hl-carry`, `.env.momentum`→`.env.carry`, `hlvault.momentum`→`hlvault.carry`, `momentum-trading`→`funding-carry`). `chmod +x deploy/setup-carry.sh`. Validate with `bash -n deploy/setup-carry.sh`.

- [ ] **Step 3: Commit** — `git commit -m "chore: carry wallet setup helper + deploy files"`

---

### Task 7 (coordinator-only, blocked on credentials): `.env.carry`, dry-run gate, go-live

- [ ] Coordinator creates `.env.carry` (momentum wallet's credentials, `LIVE_TRADING=false`, Telegram keys).
- [ ] `python scripts/setup_carry_wallet.py` → review plan → `--do-it`.
- [ ] `.venv/bin/hl-carry --status` then `.venv/bin/hl-carry --dry-run --once` twice: sane `[DRY RUN]` actions, correct equity/leverage readout, no exceptions.
- [ ] Flip `LIVE_TRADING=true`, start `hl-carry` as a local background process (matching how instance-1 gridbot runs), watch first live cycle logs, verify entry orders landed and delta ≈ 0 via `--status`.
- [ ] Commit any doc updates; report to user.

---

## Self-review

- **Spec coverage:** config/state (Task 1), funding signal (2), one-basis equity (3), pure engine + liquidation-defense sim (4), live loop with halt/flatten/alert/dry-run + entry point (5), setup helper + deploy (6), execution-correctness gate (7). Spec's "unwind when trailing 7d funding < EXIT_FUNDING_APR" → `funding_ok` + priority-1 unwind. Spec's delta guard/leverage bands → engine priorities 2–4. Equity divergence documented in `equity.py` docstring.
- **Placeholder scan:** none.
- **Type consistency:** `Action(kind, size, amount)` consistent across engine/live/tests; `CarrySnapshot` fields consistent between equity.py and both test fakes; `plan_actions` keyword signature matches all call sites.
