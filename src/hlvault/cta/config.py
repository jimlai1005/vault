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

import os
from pathlib import Path

from dotenv import dotenv_values

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
# Structural entry cap (owner-approved sizing-ladder guard): a NEW entry is
# refused when total account notional would exceed this multiple of equity.
# Entries only — exits/stops/orphan flattening are never gated.
MAX_GROSS_LEVERAGE = _env_float("MAX_GROSS_LEVERAGE", "2.0")
MAX_DRAWDOWN_PCT = _env_float("MAX_DRAWDOWN_PCT", "0.20")
MIN_ORDER_NOTIONAL = _env_float("MIN_ORDER_NOTIONAL", "12")
ORDER_SLIPPAGE = _env_float("ORDER_SLIPPAGE", "0.05")

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
STATE_FILE = _ROOT / "data" / "cache" / f"{INSTANCE_LABEL}_state.json"
CACHE_DIR = _ROOT / "data" / "cache" / f"{INSTANCE_LABEL}_live"
