"""Env-driven config for the live gridbot — mirrors hl-copytrader's src/config.py
pattern (proven in production) but for an independent grid strategy, not a mirror.
Reads .env.gridbot explicitly so it never collides with hl-copytrader's own .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env.gridbot"
load_dotenv(_ENV_PATH)


def _clean(val: str) -> str:
    if val is None:
        return val
    return val.split("#", 1)[0].strip()


def _env_str(key: str, default: str) -> str:
    return _clean(os.getenv(key, default))


def _env_bool(key: str, default: str) -> bool:
    return _clean(os.getenv(key, default)).lower() == "true"


def _env_float(key: str, default: str) -> float:
    return float(_clean(os.getenv(key, default)))


WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")
ALLOCATED_CAPITAL = _env_float("ALLOCATED_CAPITAL", "1000")
MAX_DRAWDOWN_PCT = _env_float("MAX_DRAWDOWN_PCT", "0.20")
LIVE_TRADING = _env_bool("LIVE_TRADING", "false")
NETWORK = _env_str("NETWORK", "mainnet")
HL_API_URL = "https://api.hyperliquid.xyz" if NETWORK == "mainnet" else "https://api.hyperliquid-testnet.xyz"

# coin universe for the pilot — kept small and liquid on purpose (CLAUDE.md-aligned:
# don't scale scope beyond what's been backtested/validated).
COIN_UNIVERSE = [c.strip() for c in _env_str("COIN_UNIVERSE", "HYPE,BTC,ETH").split(",") if c.strip()]

MAX_COIN_ALLOCATION_PCT = _env_float("MAX_COIN_ALLOCATION_PCT", "0.40")
NUM_LEVELS = int(_env_float("NUM_LEVELS", "6"))
VOL_K = _env_float("VOL_K", "0.5")
MIN_STEP_PCT = _env_float("MIN_STEP_PCT", "0.003")
MAX_STEP_PCT = _env_float("MAX_STEP_PCT", "0.03")
STOP_BUFFER_PCT = _env_float("STOP_BUFFER_PCT", "0.15")
COOLDOWN_HOURS = _env_float("COOLDOWN_HOURS", "24")
MIN_ORDER_NOTIONAL = _env_float("MIN_ORDER_NOTIONAL", "12")
SYNC_INTERVAL_SECONDS = _env_float("SYNC_INTERVAL_SECONDS", "60")

# "max" = use each coin's exchange-defined max leverage (like hl-copytrader's
# ORDER_LEVERAGE=max): this only reduces margin RESERVED per order, it does not
# change order size/notional (sized independently from notional_per_level), so
# it does not increase position risk — see live.py's _ensure_leverage.
LEVERAGE = _env_str("LEVERAGE", "max").lower()

STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "cache" / "gridbot_state.json"
