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
