# CTA Second Instance — Alpha+Beta Wallet (`hlvault.cta`, instance B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax. Write the failing test first, watch it fail, implement, watch it pass, commit. Do NOT batch tasks.
>
> **RED-LINE (read `/Users/jim/projects/vault/CLAUDE.md` first):** `.env.cta` (wallet A) and `.env.cta2` (wallet B) are **real wallet keys**; `.env.research` is a real API key. The implementer must **never create, print, cat, copy, or load** any of them, and must never write a test/example that loads them. Every step that touches real money — creating `.env.cta2`, funding wallet B, `LIVE_TRADING=true`, flatten against a real wallet, starting/stopping/restarting the `hl-cta` or `hl-cta2` services — is marked **[OWNER/COORDINATOR DECISION — do not execute as implementer]**. Build and test everything with mocks only.

---

## Goal

The CTA short-carry engine currently runs one live forward-test: **wallet A** (`0xbAC652…3662`, `.env.cta`, `hl-cta` service) — a pure short-only alpha book over 6 coins (BTC, ETH, SOL, HYPE, DOGE, XRP). A client wants "a bit of Beta" added. The owner's decision (already made — do not re-open):

- **Wallet A stays pure alpha, completely untouched** — its `.env`, state file, behavior, and Telegram text must not change by a single byte.
- **A new wallet B** (owner opens it, fills keys later) runs the **same short-only alpha book plus a persistent BTC-perp long "beta sleeve"** sized to `equity × BETA_TARGET_FRACTION` (default 0.25).
- Beta form is fixed by the owner as a **constant long sleeve**, NOT the crowd-filtered `ENABLE_LONG` long book — prior research判定 that path unfavorable (真 crowd 11-month long-side Sharpe −1.61).

Both wallets run the **same code**. Instance B is selected purely by a process env var (`CTA_ENV_FILE`) injected by systemd. The default of every new knob leaves wallet A's behavior identical.

## Architecture

Three surgical changes to the shared engine plus mirrored deploy artifacts. Blast radius is deliberately tiny — `risk.py`, `state.py`, `signals.py`, `data.py` are **not touched**:

1. **`config.py` — instance parametrization + beta config.** Read the env-file path from the `CTA_ENV_FILE` **process** env var (default `.env.cta`); derive `INSTANCE_LABEL` and `STATE_FILE`/`CACHE_DIR` from the env-file name so two instances never collide. Add `BETA_*` knobs (default OFF). A structural import-time guard forbids the beta coin from also being an alpha universe coin.
2. **`live.py` — beta sleeve + instance-aware alerts.** A new `_maybe_rebalance_beta()` step (no-op when the sleeve is disabled) maintains the BTC long at target inside the existing 4h rebalance, reusing the existing execution path and the existing account-equity source. Telegram alerts gain an instance-label prefix that is byte-identical for wallet A.
3. **Deploy mirror + `.gitignore` + template.** `deploy/hl-cta2.service` (with `Environment=CTA_ENV_FILE=…`), `deploy/setup-cta2.sh`, a `.gitignore` entry for `.env.cta2`, and a committed `.env.cta2` **template** (placeholders only — the real file is owner-created).

**No new entry point.** Both instances run the same `hl-cta` console script; only `CTA_ENV_FILE` differs (mirrors the gridbot-second-instance blueprint's `GRIDBOT_ENV_FILE` idea).

**Reuses unchanged:** `risk.account_equity` / `risk.check_drawdown` (MDD basis), `_place_order` (single execution boundary), `ResilientExchange.order` (idempotency classification), `get_mid_price`, `send_alert`.

## Resolved facts (verified against the current tree, 2026-07-09)

- **State-file name must derive from the env-file suffix, NOT `Path.stem`.** Verified: `Path(".env.cta").stem == ".env"` and `Path(".env.cta2").stem == ".env"` — `.stem` collides both instances and breaks wallet A. The correct label is `Path(env).suffix.lstrip(".")` → `.env.cta`→`"cta"`, `.env.cta2`→`"cta2"`, absolute paths too. `"cta"` reproduces the current `cta_state.json` exactly (backward compatible). **The gridbot blueprint (`2026-07-03-gridbot-second-instance-design.md:56`) states `.stem`; that detail is wrong — this plan uses `suffix`.**
- **MDD equity source = `risk.account_equity`** (`src/hlvault/cta/risk.py:72-120`): spot USDC + perp `totalMarginUsed` + perp `withdrawable`. `check_drawdown` (`risk.py:123-141`) and the gross-leverage cap (`live.py:226`) already use it. The beta sleeve **must** size against this same value (engineering principle #1).
- **Idempotency classification is structural in `ResilientExchange.order`** (`src/hlvault/gridbot/resilience.py`, bottom): `idem = bool(reduce_only)`. `reduce_only=True` → retried (idempotent); `reduce_only=False` → single attempt (non-idempotent, self-heals next cycle). Beta *grow* = non-reduce-only open (single); beta *trim* = reduce-only (retried).
- **Gross-leverage already counts every account position** (`live.py:229` iterates `assetPositions`, not just `COIN_UNIVERSE`), so an existing beta BTC long is automatically in `gross`. Same-cycle beta adjustments are charged into the cycle `gross_state` the way alpha opens are (`live.py:414`).
- **MDD flatten already closes everything** (`live.py:106-126`, `for p in user_state["assetPositions"]`) — including the beta leg. No change needed for "flatten beta on halt".
- **`.gitignore` has NO `.env.*` wildcard** — only explicit per-file lines (`.gitignore:19-23`). `.env.cta2` is **not** covered by any existing rule and must be added explicitly.

---

## One-coin-one-owner: verification (design constraint #3)

Wallet B's alpha `COIN_UNIVERSE` **excludes BTC** (`ETH,SOL,HYPE,DOGE,XRP`); BTC belongs to the beta sleeve alone. This is not merely tidy — sharing BTC between an alpha short and a beta long on one wallet is a **correctness bug**, because Hyperliquid nets perp positions per coin into a single `szi`. Verified against `live.py`:

- `pos_by_coin` is the **net** `szi` per coin (`live.py:210-211`), and `_process_coin` derives `cur_sz`/`direction` from that net (`live.py:281-282`). If alpha shorts BTC (−300) while beta longs BTC (+2500), the alpha step sees a **+2200 long** and mis-manages it against a short's stop/exit.
- The alpha exit closes `abs(cur_sz)` (`live.py:341`) — it would flatten the **entire net position**, destroying the beta sleeve when alpha only wanted to exit its short.
- `_reconcile_orphans` (`live.py:183-199`, gate at `:185`) flattens any `COIN_UNIVERSE` coin that has a position but no `entries` record. Beta writes **no** `entries` record, so if BTC were in the universe, the orphan path would nuke the beta sleeve every rebalance.

**Conclusion:** excluding BTC from wallet B's alpha universe is required. It is also structurally safe: with BTC out of `COIN_UNIVERSE`, the alpha per-coin loop (`live.py:247`) and `_reconcile_orphans` (`live.py:183`) never touch BTC, while the gross loop (`live.py:229`) and `_flatten_everything` (`live.py:108`) still see it because they iterate **all** positions. To make the bad configuration impossible rather than merely documented, Task 1 adds an **import-time guard** that refuses to start if the beta coin is also an alpha universe coin (engineering principle #5 forcing-function).

---

## Backward-compatibility guarantee (design constraint #1)

Wallet A runs the same binary. Every new/changed default must reproduce today's behavior exactly. Each row below has a regression test in Task 1/Task 2.

| Surface | Wallet A value (unchanged) | Mechanism | Regression test |
| --- | --- | --- | --- |
| Env file loaded | `.env.cta` | `CTA_ENV_FILE` **default** `".env.cta"` | `test_default_env_file_is_env_cta` |
| `INSTANCE_LABEL` | `"cta"` | `suffix.lstrip(".")` of `.env.cta` | `test_instance_label_default_cta` |
| `STATE_FILE` | `data/cache/cta_state.json` | `f"{INSTANCE_LABEL}_state.json"` → `cta_state.json` | `test_state_file_default_unchanged` |
| `CACHE_DIR` | `data/cache/cta_live` | `f"{INSTANCE_LABEL}_live"` → `cta_live` | `test_cache_dir_default_unchanged` |
| Beta sleeve | inactive | `BETA_TARGET_FRACTION` **default `0.0`**; `<=0` ⇒ `_maybe_rebalance_beta` returns immediately | `test_beta_disabled_by_default_places_no_orders` |
| Alpha universe | `BTC,ETH,SOL,HYPE,DOGE,XRP` | `COIN_UNIVERSE` default unchanged | `test_coin_universe_default_unchanged` |
| Telegram text | `"CTA …"` | alerts use `f"{INSTANCE_LABEL.upper()} …"`; `"cta".upper()=="CTA"` | `test_alert_prefix_is_CTA_for_wallet_a` |
| `entries` / state schema | unchanged | beta is **stateless** (no `state.py` change) | `test_state_default_schema_unchanged` (existing `test_cta_state.py`) |

**Single-knob decision (why `BETA_TARGET_FRACTION=0` disables, not a separate `BETA_ENABLED`):** one knob removes contradictory states ("enabled but fraction 0", "disabled but 0.25") and makes the OFF path *structural* — fraction 0 ⇒ target notional 0 ⇒ nothing to trade. Wallet A simply never sets the var (default 0.0) and the whole sleeve is a guaranteed no-op. A stray nonzero value cannot appear on wallet A because `.env.cta` does not contain the key. The import-time one-coin-one-owner guard is the safety net against a *misconfigured* nonzero on any instance.

---

## File structure

```
src/hlvault/cta/config.py     # MODIFY: CTA_ENV_FILE, INSTANCE_LABEL, STATE_FILE/CACHE_DIR derivation, BETA_* + guard
src/hlvault/cta/live.py       # MODIFY: _maybe_rebalance_beta + hook; instance-label alert prefix; --status label
deploy/hl-cta2.service        # CREATE: mirror hl-cta.service + Environment=CTA_ENV_FILE=/home/ubuntu/vault/.env.cta2
deploy/setup-cta2.sh          # CREATE: mirror setup-cta.sh (cta -> cta2)
.gitignore                    # MODIFY: add `.env.cta2` (NO wildcard exists today)
.env.cta2                     # CREATE (template committed? NO): OWNER creates the REAL file; this plan gives the template text
tests/test_cta_config.py      # CREATE: env-file parametrization, label derivation, backward-compat defaults, one-coin-one-owner guard
tests/test_cta_live.py        # MODIFY: beta rebalance behavior (reuse existing _engine/_FakeInfo/_FakeExchange helpers)

# UNCHANGED (do not touch): risk.py, state.py, signals.py, data.py, __init__.py, deploy/hl-cta.service, deploy/setup-cta.sh, .env.cta
```

The real `.env.cta2` is **owner-created** (holds real credentials; never by an implementer, never committed). The plan's template (Task 4) uses placeholder keys only.

---

### Task 1: `config.py` — instance parametrization + beta knobs + one-coin-one-owner guard

**Files:** MODIFY `src/hlvault/cta/config.py`; CREATE `tests/test_cta_config.py`.

- [ ] **Step 1: Write the failing tests** (`tests/test_cta_config.py`). No network, no real env files. Reload the config module under a monkeypatched `CTA_ENV_FILE` pointing at a `tmp_path` env file (a nonexistent key yields defaults; `dotenv_values` on a real temp file supplies overrides). Restore the default in teardown so other tests see wallet-A config.

```python
# tests/test_cta_config.py
import importlib
import pytest


def _reload_config(monkeypatch, env_path: str | None):
    """Reload hlvault.cta.config with CTA_ENV_FILE set (or unset)."""
    import hlvault.cta.config as cfg
    if env_path is None:
        monkeypatch.delenv("CTA_ENV_FILE", raising=False)
    else:
        monkeypatch.setenv("CTA_ENV_FILE", env_path)
    return importlib.reload(cfg)


@pytest.fixture(autouse=True)
def _restore_default_config():
    yield
    import hlvault.cta.config as cfg
    import os
    os.environ.pop("CTA_ENV_FILE", None)
    importlib.reload(cfg)  # leave wallet-A config loaded for the rest of the suite


# ---- backward compatibility (wallet A) --------------------------------
def test_default_env_file_is_env_cta(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg._ENV_PATH.name == ".env.cta"

def test_instance_label_default_cta(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.INSTANCE_LABEL == "cta"

def test_state_file_default_unchanged(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.STATE_FILE.name == "cta_state.json"
    assert cfg.STATE_FILE.parent.name == "cache"

def test_cache_dir_default_unchanged(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.CACHE_DIR.name == "cta_live"

def test_coin_universe_default_unchanged(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.COIN_UNIVERSE == ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP"]

def test_beta_disabled_by_default(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.BETA_TARGET_FRACTION == 0.0


# ---- instance B derivation --------------------------------------------
def test_instance_label_and_state_file_for_cta2(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta2"
    env.write_text("COIN_UNIVERSE=ETH,SOL,HYPE,DOGE,XRP\nBETA_TARGET_FRACTION=0.25\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.INSTANCE_LABEL == "cta2"
    assert cfg.STATE_FILE.name == "cta2_state.json"
    assert cfg.CACHE_DIR.name == "cta2_live"
    assert cfg.BETA_TARGET_FRACTION == 0.25
    assert "BTC" not in cfg.COIN_UNIVERSE

def test_absolute_env_path_label(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta2"
    env.write_text("BETA_TARGET_FRACTION=0.25\nCOIN_UNIVERSE=ETH,SOL\n")
    cfg = _reload_config(monkeypatch, str(env.resolve()))
    assert cfg.INSTANCE_LABEL == "cta2"


# ---- one-coin-one-owner forcing function ------------------------------
def test_beta_coin_in_universe_raises(monkeypatch, tmp_path):
    env = tmp_path / ".env.cta2"
    env.write_text("BETA_TARGET_FRACTION=0.25\nBETA_COIN=BTC\nCOIN_UNIVERSE=BTC,ETH,SOL\n")
    with pytest.raises(RuntimeError, match="one-coin-one-owner|COIN_UNIVERSE"):
        _reload_config(monkeypatch, str(env))

def test_beta_coin_in_universe_ok_when_beta_off(monkeypatch, tmp_path):
    # fraction 0 => guard does not fire even if BETA_COIN is in the universe
    env = tmp_path / ".env.cta"  # wallet-A-shaped: BTC in universe, beta off
    env.write_text("BETA_TARGET_FRACTION=0\nCOIN_UNIVERSE=BTC,ETH\n")
    cfg = _reload_config(monkeypatch, str(env))
    assert cfg.BETA_TARGET_FRACTION == 0.0
```

- [ ] **Step 2: Implement.** Change `config.py:19-22` (env-file selection) and `config.py:108-109` (state/cache derivation); append the beta block + guard after the sizing/risk section. Keep everything else byte-identical.

Replace lines 19–22:

```python
import os  # add to the existing imports at top of file

_ROOT = Path(__file__).resolve().parents[3]
# Instance selection: a PROCESS env var chooses which env FILE to read. This is
# the ONE deliberate os.environ read — it selects a path only; every config
# VALUE still comes from the isolated dotenv_values dict below, so the shared-
# os.environ collision the module docstring warns about cannot reappear.
_ENV_NAME = os.environ.get("CTA_ENV_FILE", ".env.cta")
_ENV_PATH = Path(_ENV_NAME) if os.path.isabs(_ENV_NAME) else _ROOT / _ENV_NAME
_FILE_VALUES = dotenv_values(_ENV_PATH)          # isolated dict; never touches os.environ
_RESEARCH_VALUES = dotenv_values(_ROOT / ".env.research")

# Instance label from the env-file SUFFIX (NOT Path.stem — `.env.cta`.stem is
# ".env", which would collide every instance and break wallet A's state file).
# `.env.cta` -> "cta" (reproduces cta_state.json exactly), `.env.cta2` -> "cta2".
INSTANCE_LABEL = _ENV_PATH.suffix.lstrip(".") or "cta"
```

Replace lines 108–109:

```python
STATE_FILE = _ROOT / "data" / "cache" / f"{INSTANCE_LABEL}_state.json"
CACHE_DIR = _ROOT / "data" / "cache" / f"{INSTANCE_LABEL}_live"
```

Append after the `# ---- sizing / risk ----` block (after `config.py:89`):

```python
# ---- beta sleeve (Alpha+Beta instances only; default OFF => wallet A intact) ---
# A persistent long in BETA_COIN sized to equity * BETA_TARGET_FRACTION. <=0
# disables the sleeve entirely (no reads, no orders): wallet A never sets the
# key and is a guaranteed no-op. BETA_REBALANCE_TOLERANCE is the |actual-target|
# / target deadband that suppresses churn (see live._maybe_rebalance_beta).
BETA_TARGET_FRACTION = _env_float("BETA_TARGET_FRACTION", "0")
BETA_COIN = _env_str("BETA_COIN", "BTC")
BETA_REBALANCE_TOLERANCE = _env_float("BETA_REBALANCE_TOLERANCE", "0.10")

# Structural one-coin-one-owner guard (engineering principle #5 forcing
# function): if the beta sleeve is active, its coin must NOT also be an alpha
# universe coin. Otherwise the net perp szi on that coin fuses an alpha short
# and a beta long, and the exit/stop/orphan logic mis-manages the fused
# position (see the plan's one-coin-one-owner section, live.py:210/281/341/185).
# Fail loudly at import rather than silently create the ambiguity.
if BETA_TARGET_FRACTION > 0 and BETA_COIN in COIN_UNIVERSE:
    raise RuntimeError(
        f"CTA beta sleeve active (BETA_TARGET_FRACTION={BETA_TARGET_FRACTION}) but "
        f"BETA_COIN={BETA_COIN!r} is also in COIN_UNIVERSE {COIN_UNIVERSE}. Remove "
        f"{BETA_COIN} from COIN_UNIVERSE (one-coin-one-owner).")
```

- [ ] **Step 3: Run** `.venv/bin/pytest tests/test_cta_config.py -q` (all green) and `.venv/bin/pytest tests/test_cta_state.py tests/test_cta_risk.py tests/test_cta_signals.py tests/test_cta_data.py -q` (existing CTA tests unchanged — wallet-A regression). Commit: `git commit -am "feat(cta): instance-parametrized config + beta knobs (sub-project G2)"`.

---

### Task 2: `live.py` — beta sleeve + instance-aware alerts

**Files:** MODIFY `src/hlvault/cta/live.py`; MODIFY `tests/test_cta_live.py`.

- [ ] **Step 1: Write the failing tests** in `tests/test_cta_live.py`, reusing the existing `_engine`, `_FakeInfo`, `_FakeExchange` helpers (`test_cta_live.py:11-69`). All patch `cfg` attributes via monkeypatch — never load a real env file. Cover:

```python
# additions to tests/test_cta_live.py

def _beta_engine(monkeypatch, info, ex, *, frac=0.25, universe=("ETH","SOL","HYPE","DOGE","XRP"),
                 tol=0.10, live=True, state=None):
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    monkeypatch.setattr(cfg, "BETA_TARGET_FRACTION", frac)
    monkeypatch.setattr(cfg, "BETA_COIN", "BTC")
    monkeypatch.setattr(cfg, "BETA_REBALANCE_TOLERANCE", tol)
    monkeypatch.setattr(cfg, "COIN_UNIVERSE", list(universe))
    monkeypatch.setattr(cfg, "MIN_ORDER_NOTIONAL", 12.0)
    return _engine(info, ex, live=live, state=state)


def test_beta_disabled_places_no_beta_order(monkeypatch):
    # frac=0 => _maybe_rebalance_beta returns immediately (wallet-A regression)
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0, spot_usdc=1000.0), ex, frac=0.0)
    e._maybe_rebalance_beta(equity=1000.0, pos_by_coin={}, gross_state={"equity":1000.0,"gross":0.0})
    assert ex.orders == [] and ex.closed == []

def test_beta_opens_to_target_when_flat(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    gs = {"equity":1000.0, "gross":0.0}
    e._maybe_rebalance_beta(equity=1000.0, pos_by_coin={}, gross_state=gs)
    # target $250 @ mid100 -> buy ~2.5 BTC, non-reduce-only (idempotent-open)
    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["coin"] == "BTC" and o["is_buy"] is True and o["reduce_only"] is False
    assert abs(o["size"] - 2.5) < 0.05
    assert abs(gs["gross"] - 250.0) < 1.0   # gross charged by the beta target

def test_beta_within_tolerance_no_order(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25, tol=0.10)
    # current BTC long = 2.4 @100 = $240 vs target $250 -> 4% dev < 10% band
    e._maybe_rebalance_beta(1000.0, {"BTC": 2.4}, {"equity":1000.0,"gross":240.0})
    assert ex.orders == [] and ex.closed == []

def test_beta_trims_with_reduce_only_when_over_target(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25, tol=0.05)
    # current $400 vs target $250 -> trim $150 as a reduce-only sell (idempotent)
    gs = {"equity":1000.0, "gross":400.0}
    e._maybe_rebalance_beta(1000.0, {"BTC": 4.0}, gs)
    assert len(ex.orders) == 1
    o = ex.orders[0]
    assert o["is_buy"] is False and o["reduce_only"] is True
    assert abs(gs["gross"] - 250.0) < 1.0

def test_beta_adjustment_below_min_notional_skipped(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25, tol=0.0)
    # target $250 vs current $245 -> $5 adjustment < MIN_ORDER_NOTIONAL $12
    e._maybe_rebalance_beta(1000.0, {"BTC": 2.45}, {"equity":1000.0,"gross":245.0})
    assert ex.orders == []

def test_beta_short_position_is_anomaly_no_trade(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    e._maybe_rebalance_beta(1000.0, {"BTC": -1.0}, {"equity":1000.0,"gross":100.0})
    assert ex.orders == [] and ex.closed == []   # alerts + skips, never flips a short

def test_beta_nonpositive_equity_skips(monkeypatch):
    ex = _FakeExchange()
    e = _beta_engine(monkeypatch, _FakeInfo(mid=100.0), ex, frac=0.25)
    e._maybe_rebalance_beta(0.0, {}, {"equity":0.0,"gross":0.0})
    assert ex.orders == []

def test_flatten_everything_closes_beta_btc(monkeypatch):
    # MDD halt: _flatten_everything iterates ALL positions incl. the beta BTC long
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    pos = [{"coin":"BTC","szi":"2.5","marginUsed":"25","unrealizedPnl":"0"}]
    ex = _FakeExchange()
    e = _engine(_FakeInfo(mid=100.0, positions=pos), ex, live=True)
    assert e._flatten_everything() is True
    assert ("BTC", 2.5) in ex.closed

def test_alert_prefix_is_CTA_for_wallet_a(monkeypatch):
    # INSTANCE_LABEL "cta" -> alert prefix "CTA": wallet-A text unchanged
    monkeypatch.setattr(cfg, "INSTANCE_LABEL", "cta")
    sent = []
    monkeypatch.setattr("hlvault.cta.live.send_alert",
                        lambda tok, cid, msg: sent.append(msg))
    monkeypatch.setattr(cfg, "WALLET_ADDRESS", "0xabc")
    e = _engine(_FakeInfo(), _FakeExchange(), live=True,
                state={"halted":False,"peak_equity":1e9,"_alerted_this_halt":False,
                       "_flatten_complete":False,"last_rebalance_ms":0,"entries":{}})
    # drive a halt so the drawdown alert fires (peak >> current)
    e.check_drawdown()
    assert sent and sent[0].startswith("CTA ")
```

- [ ] **Step 2: Implement `_maybe_rebalance_beta`** (new method on `CtaEngine`, place after `_reconcile_orphans`, before `maybe_rebalance` ~ `live.py:200`):

```python
    def _maybe_rebalance_beta(self, equity: float, pos_by_coin: dict, gross_state: dict) -> None:
        """Maintain the persistent BETA_COIN long at equity * BETA_TARGET_FRACTION.
        No-op when BETA_TARGET_FRACTION <= 0 (wallet A / any instance without a
        sleeve is completely unaffected).

        Equity basis (principle #1): `equity` is the SAME value passed down from
        maybe_rebalance (risk.account_equity, computed once) that the MDD breaker
        and the gross-leverage cap use — the sleeve is sized against the exact
        basis the safety net measures, never a second read that could disagree.

        Idempotency (principle #2): GROWING the long is a non-idempotent open
        (reduce_only=False -> single attempt via ResilientExchange; a lost
        response self-heals next cycle when the true BTC size is re-read).
        TRIMMING the long is an idempotent reduce-only order (retried). The
        tolerance band keeps normal price/equity drift from churning fees every
        4h. Beta is STATELESS: target from live equity, current from live
        exchange state — no beta bookkeeping to crash-corrupt. BETA_COIN is
        excluded from COIN_UNIVERSE (one-coin-one-owner, enforced at config
        import), so pos_by_coin[BETA_COIN] is the beta leg alone."""
        frac = cfg.BETA_TARGET_FRACTION
        if frac <= 0:
            return
        coin = cfg.BETA_COIN
        if equity <= 0:
            logger.error(f"beta: equity ${equity:,.2f} <= 0 — skipping beta rebalance this cycle")
            return
        mid = get_mid_price(self.info, coin)
        if mid <= 0:
            logger.warning(f"beta: no mid for {coin} — skipping beta rebalance this cycle")
            return
        cur_sz = pos_by_coin.get(coin, 0.0)
        # A SHORT on the beta coin is impossible under normal operation (BETA_COIN
        # is not in COIN_UNIVERSE and beta only ever buys/reduce-only-sells a
        # long). Treat it as an anomaly: never reduce-only a short toward a long —
        # alert loudly (principle #3) and skip for an operator to investigate.
        if cur_sz < -1e-9:
            logger.error(f"SAFETY-CRITICAL: beta coin {coin} holds a SHORT ({cur_sz}); "
                         "beta manages a LONG only — skipping, manual review needed")
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                       f"{cfg.INSTANCE_LABEL.upper()} BETA ANOMALY: {coin} holds a short "
                       f"({cur_sz}); beta expects a long only. Skipped — investigate.")
            return
        target_notional = equity * frac
        cur_notional = abs(cur_sz) * mid
        deviation = abs(cur_notional - target_notional) / target_notional  # target>0 here
        if deviation <= cfg.BETA_REBALANCE_TOLERANCE:
            logger.info(f"beta: {coin} ${cur_notional:,.2f} within "
                        f"{cfg.BETA_REBALANCE_TOLERANCE:.0%} of target ${target_notional:,.2f} — hold")
            return
        delta_notional = target_notional - cur_notional      # >0 grow long, <0 trim
        if abs(delta_notional) < cfg.MIN_ORDER_NOTIONAL:
            logger.info(f"beta: adjustment ${abs(delta_notional):,.2f} below MIN_ORDER_NOTIONAL "
                        f"${cfg.MIN_ORDER_NOTIONAL:.2f} — skipping this cycle")
            return
        is_buy = delta_notional > 0
        reduce_only = not is_buy      # trim = reduce-only (idempotent); grow = open (single attempt)
        size = abs(delta_notional) / mid
        logger.info(f"beta: {coin} {'BUY' if is_buy else 'SELL'} ${abs(delta_notional):,.2f} "
                    f"(cur ${cur_notional:,.2f} -> target ${target_notional:,.2f}) reduce_only={reduce_only}")
        if not self._place_order(coin, is_buy=is_buy, size=size, reduce_only=reduce_only):
            logger.warning(f"beta: {coin} adjustment not confirmed placed — self-heals next rebalance")
            return
        # Charge the change into the cycle gross budget so alpha entries this
        # cycle see the post-beta gross (mirrors the per-open charge at the
        # bottom of _process_coin; same-basis accounting, principle #1).
        gross_state["gross"] += (target_notional - cur_notional)
```

- [ ] **Step 3: Hook it into `maybe_rebalance`.** After `_reconcile_orphans` (`live.py:245`) and before the alpha per-coin loop (`live.py:247`), insert:

```python
        self._reconcile_orphans(pos_by_coin, entries)

        # Beta sleeve BEFORE the alpha loop so alpha entries this cycle see
        # beta's gross draw. No-op when BETA_TARGET_FRACTION <= 0 (wallet A).
        self._maybe_rebalance_beta(equity, pos_by_coin, gross_state)

        for coin in cfg.COIN_UNIVERSE:
```

(`equity` and `gross_state` already exist at `live.py:226` and `live.py:243`.)

- [ ] **Step 4: Instance-label the Telegram alerts.** Replace the literal `"CTA "` prefix in every `send_alert` message with `f"{cfg.INSTANCE_LABEL.upper()} "`. Wallet A's `INSTANCE_LABEL` is `"cta"` → `"CTA"`, so its text is byte-identical. Sites: `live.py:87-88`, `live.py:95-96`, `live.py:189-191`, `live.py:316-319`, `live.py:351-353`. Example (`live.py:87-88`):

```python
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                       f"{cfg.INSTANCE_LABEL.upper()} DRAWDOWN CIRCUIT BREAKER TRIPPED — flattening and halting.")
```

Also extend the `--status` print (`live.py:462-466`) with the instance for operator clarity:

```python
        print(f"[{cfg.INSTANCE_LABEL}] equity ${equity:,.2f} | halted={engine.state.get('halted')} "
              f"peak={engine.state.get('peak_equity')} "
              f"open_entries={list(engine.state.get('entries', {}).keys())} "
              f"beta_frac={cfg.BETA_TARGET_FRACTION} long={cfg.ENABLE_LONG} short={cfg.ENABLE_SHORT}")
```

(Leave `risk.py:137`'s internal *log* line as-is — journald is already split per service via `SyslogIdentifier`.)

- [ ] **Step 5: Run** `.venv/bin/pytest tests/test_cta_live.py -q` (all green, incl. the pre-existing wallet-A tests) then the full CTA suite `.venv/bin/pytest tests/test_cta_*.py -q`. Commit: `git commit -am "feat(cta): persistent BTC beta sleeve + instance-aware alerts (sub-project G2)"`.

---

### Task 3: deploy mirror + `.gitignore`

**Files:** CREATE `deploy/hl-cta2.service`, `deploy/setup-cta2.sh`; MODIFY `.gitignore`.

- [ ] **Step 1: `deploy/hl-cta2.service`** — copy `deploy/hl-cta.service` and change: `Description=Hyperliquid CTA Alpha+Beta bot (hlvault.cta, instance cta2)`; add `Environment=CTA_ENV_FILE=/home/ubuntu/vault/.env.cta2` in `[Service]`; `EnvironmentFile=/home/ubuntu/vault/.env.cta2`; keep `ExecStart=/home/ubuntu/vault/.venv/bin/hl-cta` (same binary — the env var selects the instance); `SyslogIdentifier=hl-cta2`; keep `MemoryMax=256M`. The load-bearing line is `Environment=CTA_ENV_FILE=…` (config reads it); `EnvironmentFile` is kept only for parity and is harmless (config uses `dotenv_values`, not `os.environ`, for values — separate processes, no collision). Full file:

```ini
[Unit]
Description=Hyperliquid CTA Alpha+Beta bot (hlvault.cta, instance cta2)
Documentation=https://github.com/jimlai1005/vault
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu

WorkingDirectory=/home/ubuntu/vault
Environment=CTA_ENV_FILE=/home/ubuntu/vault/.env.cta2
EnvironmentFile=/home/ubuntu/vault/.env.cta2

ExecStart=/home/ubuntu/vault/.venv/bin/hl-cta

Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

MemoryMax=256M

StandardOutput=journal
StandardError=journal
SyslogIdentifier=hl-cta2

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: `deploy/setup-cta2.sh`** — copy `deploy/setup-cta.sh` and substitute `cta`→`cta2` in: `ENV_FILE="$PROJECT_DIR/.env.cta2"`, `SERVICE_TPL="$PROJECT_DIR/deploy/hl-cta2.service"`, `SYSTEMD_DST="/etc/systemd/system/hl-cta2.service"`, all `hl-cta`→`hl-cta2` (enable/start/status/tips), the `.env.cta` messages → `.env.cta2`, and the header. Keep the `sed` unit-templating block (`setup-cta.sh:64-68`) unchanged — it rewrites `/home/ubuntu/vault` and `User`/`Group`, and passes `Environment=CTA_ENV_FILE=…` through verbatim. `chmod +x deploy/setup-cta2.sh`; validate `bash -n deploy/setup-cta2.sh`.

- [ ] **Step 3: `.gitignore`** — append `.env.cta2` after `.env.cta` (`.gitignore:22`). **Required:** there is no `.env.*` wildcard today (only explicit lines `.gitignore:19-23`), so `.env.cta2` is otherwise tracked. Verify: `git check-ignore .env.cta2` must print `.env.cta2`.

- [ ] **Step 4: Commit** — `git add deploy/hl-cta2.service deploy/setup-cta2.sh .gitignore && git commit -m "chore(cta): deploy mirror + gitignore for instance cta2 (sub-project G2)"`.

---

### Task 4: `.env.cta2` template (implementer supplies TEXT only; OWNER creates the real file)

The real `.env.cta2` holds wallet-B credentials — **owner-created, chmod 600, never committed**. The plan provides the exact template below; the implementer must NOT write this to disk as a real env file. Note the differences from `.env.cta`: `COIN_UNIVERSE` **excludes BTC**, and the `BETA_*` block is present. `LIVE_TRADING=false` and `ENABLE_LONG=false` per red-line defaults. Coinalyze key stays in `.env.research` (not here).

```dotenv
# .env.cta2 — CTA instance B (Alpha+Beta wallet). chmod 600. NEVER commit.
# Selected by systemd: Environment=CTA_ENV_FILE=/home/ubuntu/vault/.env.cta2

# ---- wallet / network ----
WALLET_PRIVATE_KEY=<fill-me>
WALLET_ADDRESS=<fill-me>
LIVE_TRADING=false            # OWNER flips true only after dry-run passes
NETWORK=mainnet

# ---- universe (BTC EXCLUDED — owned by the beta sleeve; one-coin-one-owner) ----
COIN_UNIVERSE=ETH,SOL,HYPE,DOGE,XRP

# ---- per-side switches (alpha book is short-only, same as wallet A) ----
ENABLE_LONG=false
ENABLE_SHORT=true

# ---- beta sleeve (constant BTC long = equity * fraction) ----
BETA_TARGET_FRACTION=0.25     # 25% of equity as a persistent BTC-perp long
BETA_COIN=BTC
BETA_REBALANCE_TOLERANCE=0.10 # rebalance only when |actual-target|/target > 10%

# ---- signal params (MUST match wallet A / phase-2b) ----
TIMEFRAME=4h
EMA_FAST=20
EMA_SLOW=50
TREND_WARMUP_BARS=50
CROWD_PCTILE=10
CROWD_WINDOW_DAYS=90
CROWD_WARMUP_DAYS=30
BARS_PER_DAY=6
FUEL_LOOKBACK_HOURS=24
ATR_PERIOD=14
STOP_ATR_MULT=2.0
MAX_HOLD_DAYS=14

# ---- sizing / risk ----
NOTIONAL_PER_TRADE=300
MAX_GROSS_LEVERAGE=2.0
MAX_DRAWDOWN_PCT=0.20
MIN_ORDER_NOTIONAL=12
ORDER_SLIPPAGE=0.05

# ---- cadence ----
SYNC_INTERVAL_SECONDS=300
REBALANCE_INTERVAL_HOURS=4
DATA_STALENESS_HOURS=8
COINALYZE_THROTTLE_SECONDS=1.6

# ---- notify ----
TELEGRAM_BOT_TOKEN=<fill-me>
TELEGRAM_CHAT_ID=<fill-me>
```

**`BETA_REBALANCE_TOLERANCE=0.10` rationale:** on a ~$1,000 wallet the target sleeve is ~$250; a 10% band means an adjustment only fires past ~$25 of drift, comfortably above `MIN_ORDER_NOTIONAL` ($12) so no triggered rebalance is dust. HL taker fee on a ~$25 adjust is ~$0.01 — the band is primarily a churn/log-noise guard (the 4h cadence plus equity drift would otherwise trim on every cycle), not a fee concern. Owner-tunable; widen to reduce trades, tighten to track more closely.

---

### Task 5 [OWNER/COORDINATOR DECISION — do not execute as implementer]: rollout + go-live gate

Every step here touches real money/credentials or restarts a live service — reserved for the owner/main conversation per CLAUDE.md 實盤紅線. The implementer must NOT perform any of these.

**Phase A — land code (no money):**
- [ ] Implementer: Tasks 1–4 merged; full suite green locally (`.venv/bin/pytest -q`), including all pre-existing wallet-A CTA tests. Evidence = pytest tail.
- [ ] **[OWNER, RED-LINE]** Server `git pull`. Then **restart `hl-cta`** (wallet A) to pick up the new code. State persists to `cta_state.json`; positions re-reconcile from the exchange each cycle — a brief restart is routine. **Restarting a live service is a red-line action — owner approves and executes.**
- [ ] **[OWNER]** Verify wallet A unaffected: `.venv/bin/hl-cta --status` shows the expected equity, `halted=False`, and the same open alpha entries as before; `journalctl -u hl-cta -n 50` shows normal cycles and (crucially) NO `beta:` log lines (beta off by default) and NO change in Telegram alert text.

**Phase B — bring up wallet B:**
- [ ] **[OWNER, RED-LINE]** Open wallet B; create `/home/ubuntu/vault/.env.cta2` from the Task 4 template with real keys; `chmod 600`; keep `LIVE_TRADING=false`. Fund the wallet (USDC → perp, owner decides amount). Confirm `.env.cta2` is gitignored (`git check-ignore .env.cta2`).
- [ ] **[OWNER]** **Before starting `hl-cta2`**, resolve the shared-Coinalyze-key rate risk (both instances read `COINALYZE_API_KEY` from `.env.research` unless overridden, and each rebalance burst is `3 * len(COIN_UNIVERSE)` Coinalyze calls — two processes sharing the 40 req/min free-tier budget can jointly 429-degrade BOTH instances, including wallet A). Pick one, per `.env.cta2`'s template comment: (a) give wallet B its own `COINALYZE_API_KEY` in `.env.cta2` (preferred — removes the shared budget entirely), **or** (b) set `COINALYZE_THROTTLE_SECONDS=3.75` on **both** the server's `.env.cta` and `.env.cta2` (derivation in the template comment — keeps the worst-case combined rate ≤32 req/min, ~20% under the 40 req/min cap). Raising only one side does not bound the combined rate.
- [ ] **[OWNER]** Install the service read-only first: `sudo bash deploy/setup-cta2.sh` will install+enable `hl-cta2`; with `LIVE_TRADING=false` it runs dry. Alternatively run one dry cycle manually: `CTA_ENV_FILE=/home/ubuntu/vault/.env.cta2 .venv/bin/hl-cta --dry-run --once`.
- [ ] **[OWNER]** Dry-run validation on wallet B: `[DRY RUN]` output shows (a) alpha decisions over `ETH,SOL,HYPE,DOGE,XRP` only — **no BTC alpha line**; (b) a `beta:` line proposing a BTC BUY toward `equity*0.25`; (c) correct `--status` with `[cta2]` label and `beta_frac=0.25`; (d) `cta2_state.json` created (NOT `cta_state.json` — confirm wallet A's state file is untouched); (e) no exceptions.
- [ ] **[OWNER / RED-LINE]** Flip `.env.cta2` `LIVE_TRADING=true`; `sudo systemctl restart hl-cta2`; watch the first live cycle: the beta BTC long lands near target, alpha shorts (if any signal) land on non-BTC coins, `--status` shows the expected book. **Going live is a red-line action.**
- [ ] **[OWNER]** Confirm both services independent: `systemctl status hl-cta hl-cta2`, distinct `journalctl` streams (`hl-cta` vs `hl-cta2`), distinct state files, distinct Telegram prefixes (`CTA …` vs `CTA2 …`).

**Rollback plan:**
- Wallet B misbehaves → `sudo systemctl stop hl-cta2` (leaves positions; the 20% MDD breaker is inert while stopped, so if flattening is wanted, run `CTA_ENV_FILE=…/.env.cta2 .venv/bin/hl-cta --status` then decide, or let the owner flatten manually). Wallet A is entirely independent and keeps running.
- Code regression affects wallet A → `git revert` the Task 1/2 commits and restart `hl-cta`; the new defaults are backward-compatible, so reverting is clean. `cta_state.json` schema is unchanged, so no state migration on rollback.

---

## Client communication note

- **Wallet B composition:** the same short-only alpha book as wallet A but over **5 coins (ETH, SOL, HYPE, DOGE, XRP)** — it gives up the BTC short slot — **plus a constant BTC-perp long equal to ~25% of the wallet's equity** (the "beta"). That long is rebalanced back toward 25% at the 4h cadence with a 10% deadband, so it tracks equity without churning.
- **Difference vs wallet A:** wallet A is pure alpha over 6 coins including a BTC short. Wallet B trades one fewer alpha coin (no BTC short — BTC is reserved for the beta long) and carries the always-on BTC long. So in a broad crypto rally wallet B participates via beta; wallet A does not.
- **What "beta" really means:** it is directional market exposure, deliberately. **In a bear market the 25% BTC long will take roughly the full 25%-weighted drawdown of BTC** — that is the point of adding beta, not a malfunction. The account-level 20% MDD breaker still flattens *everything* (alpha and beta) if total equity draws down 20% from its peak.
- **Funding cost:** the BTC long pays/earns perp **funding**; in the usual positive-funding regime it is a **holding cost of the beta** (a small continuous drag), distinct from the alpha book's edge. It is a cost of carrying market exposure, budgeted as such.
- Wallet A is untouched by this change; the two run as fully independent services.

---

## Self-review

**Requirement → coverage:**

| Requirement (from the task) | Where |
| --- | --- |
| Wallet A behavior byte-identical | Backward-compat table; `test_cta_config.py` default tests; `test_alert_prefix_is_CTA_for_wallet_a`; existing CTA suite must stay green |
| `CTA_ENV_FILE` process-env instance selection | Task 1 config `_ENV_NAME`/`_ENV_PATH` |
| `STATE_FILE` from env-file name (`.env.cta`→`cta_state.json`) | Task 1 `INSTANCE_LABEL` via `suffix.lstrip(".")` (NOT `.stem`); `test_state_file_default_unchanged`, `test_instance_label_and_state_file_for_cta2` |
| `CACHE_DIR` consistent | Task 1 `f"{INSTANCE_LABEL}_live"` |
| Instance label in Telegram | Task 2 Step 4 `f"{cfg.INSTANCE_LABEL.upper()} …"` |
| Beta = constant BTC long, target = equity×fraction, same equity source as MDD | Task 2 `_maybe_rebalance_beta` reuses `equity` (risk.account_equity) |
| Rebalance tolerance band | Task 2 `BETA_REBALANCE_TOLERANCE`; `test_beta_within_tolerance_no_order` |
| Beta via existing execution path; loud failure; idempotency classified | Task 2 uses `_place_order`→`ResilientExchange.order` (`idem=bool(reduce_only)`); anomaly + not-placed alerts; grow=single/trim=retried |
| Beta counted in gross; flattened on MDD | gross loop `live.py:229` + same-cycle charge; `_flatten_everything` `live.py:108`; `test_flatten_everything_closes_beta_btc` |
| One-coin-one-owner verified + enforced | verification section (line anchors 210/281/341/185); config guard + `test_beta_coin_in_universe_raises` |
| Deploy mirror | Task 3 `hl-cta2.service` (+`Environment=CTA_ENV_FILE`), `setup-cta2.sh` |
| `.env.cta2` template | Task 4 (placeholders; owner creates real) |
| `.gitignore` covers `.env.cta2` | Task 3 Step 3 (no wildcard exists — explicit add + `git check-ignore` proof) |
| Tests mock the world | reuse autouse `_no_network` (`tests/conftest.py`); `_FakeInfo`/`_FakeExchange`; no real env files |
| Rollout marks money steps | Task 5 `[OWNER/COORDINATOR — RED-LINE]` on restart/live/fund |
| Client note | Client communication section |

**Engineering-principles pass (five):**
1. *Same source/basis:* beta target uses the exact `equity` local the MDD breaker and gross cap use (`live.py:226`, `risk.account_equity`) — no second read.
2. *Transient vs semantic / idempotent retry:* beta grow = `reduce_only=False` (single attempt, self-heals); trim = `reduce_only=True` (retried) — enforced by `ResilientExchange.order`'s `idem=bool(reduce_only)`.
3. *Fail loudly:* not-placed beta order logs + returns; a short on the beta coin alerts and skips (never flips a short into a long).
4. *Tests never touch the world:* autouse socket guard + fakes + no real env; config tests use `tmp_path`.
5. *Single resilience boundary + forcing function:* beta trades only through `_place_order`→`ResilientExchange`; the one-coin-one-owner guard is an import-time `raise`, not a reminder.

**Placeholder scan:** `grep -niE "TODO|FIXME|TBD|placeholder" docs/superpowers/plans/2026-07-09-cta-alpha-beta-second-instance-plan.md` — the only intended matches are the `<fill-me>` credential placeholders in the Task 4 template and the word "placeholder" in this line.

**Non-touch list (must show zero diff):** `src/hlvault/cta/{risk,state,signals,data,__init__}.py`, `deploy/hl-cta.service`, `deploy/setup-cta.sh`, `.env.cta`. Beta is stateless (no `state.py` change) and signal-independent (no `signals.py`/`data.py` change).
