"""Env-driven config for the live momentum engine — mirrors
hlvault.gridbot.config's pattern, with one deliberate difference: reads
.env.momentum via dotenv_values() into a private dict, NOT load_dotenv()'s
default of merging into the shared, process-wide os.environ.

Why: gridbot's config.py calls load_dotenv() for .env.gridbot. If both
config modules are ever imported into the same Python process — as they
already are today, in the shared test suite, since both .env.gridbot and
.env.momentum define several same-named keys (LEVERAGE, WALLET_ADDRESS,
WALLET_PRIVATE_KEY, NETWORK, MAX_DRAWDOWN_PCT, LIVE_TRADING) — whichever
module's config happens to load first "wins" for every shared key in BOTH
modules, because load_dotenv() writes into the one os.environ they both
read from. This was caught for real: .env.gridbot's LEVERAGE=max leaked
into momentum's LEVERAGE read and crashed float("max"). The same mechanism
could just as easily leak gridbot's WALLET_ADDRESS/WALLET_PRIVATE_KEY into
momentum — a much worse outcome. Reading this file's own isolated dict
(never touching os.environ, read or write) sidesteps this entirely without
any change to gridbot. In real production the two bots run as separate
systemd processes/env spaces so this specific collision never bites there,
but it's real and reproducible whenever they share one process, including
in this repo's own test suite.

No ALLOCATED_CAPITAL: this engine sizes off the wallet's actual live equity
each rebalance (the whole wallet is dedicated to this strategy), so capital
compounds instead of being pinned to a static pilot number."""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env.momentum"
_FILE_VALUES = dotenv_values(_ENV_PATH)  # isolated dict; never touches os.environ


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

COIN_UNIVERSE = [c.strip() for c in _env_str("COIN_UNIVERSE", "BTC,ETH,SOL,HYPE").split(",") if c.strip()]
MAX_COIN_ALLOCATION_PCT = _env_float("MAX_COIN_ALLOCATION_PCT", "0.40")
# Unlike gridbot's same-named LEVERAGE (margin-per-order only; sizing is
# independent of it), this is a DIRECT multiplier on notional exposure:
# risk.target_position_notional = clipped_signal * risk_budget * LEVERAGE,
# applied after MAX_COIN_ALLOCATION_PCT caps each coin's budget. Correlated
# coins (BTC/ETH/SOL/HYPE) can push aggregate gross exposure to roughly
# LEVERAGE x equity if signals align. It is NOT mechanically tied to
# MAX_DRAWDOWN_PCT: the drawdown breaker is polled every
# SYNC_INTERVAL_SECONDS, not a pre-trade hard cap, so a fast correlated move
# within one polling window can exceed the intended 20% budget first.
LEVERAGE = _env_float("LEVERAGE", "3")
ENTRY_THRESHOLD = _env_float("ENTRY_THRESHOLD", "0.5")
VOL_LOOKBACK_DAYS = int(_env_float("VOL_LOOKBACK_DAYS", "20"))
REBALANCE_INTERVAL_HOURS = _env_float("REBALANCE_INTERVAL_HOURS", "24")
SYNC_INTERVAL_SECONDS = _env_float("SYNC_INTERVAL_SECONDS", "300")
MIN_ORDER_NOTIONAL = _env_float("MIN_ORDER_NOTIONAL", "12")

TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID", "")

STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "cache" / "momentum_state.json"
