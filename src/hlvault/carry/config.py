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
