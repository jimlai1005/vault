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
# A suffix-less path (e.g. CTA_ENV_FILE=".env", or any dot-less filename) must
# NOT silently fall back to "cta" -- that would make a misconfigured instance
# overwrite wallet A's cta_state.json. Fail loudly instead (principle #3/#5
# forcing function): the operator must name the file ".env.<instance>".
_instance_label = _ENV_PATH.suffix.lstrip(".")
if not _instance_label:
    raise RuntimeError(
        f"CTA_ENV_FILE={_ENV_NAME!r} (resolved: {_ENV_PATH}) has no suffix to derive "
        "an INSTANCE_LABEL from. Use a filename shaped like '.env.<instance>' "
        "(e.g. '.env.cta2'), not a suffix-less path -- an empty/defaulted label "
        "would collide with wallet A's cta_state.json.")
INSTANCE_LABEL = _instance_label


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

# ---- vol-target sizing (sub-project L B1; opt-in, default OFF) --------
# SIGMA_TARGET unset OR empty -> B1 completely disabled: every entry uses
# NOTIONAL_PER_TRADE unchanged (m == 1.0 always, no sigma is ever computed, no
# extra log fields, no new "m" key in the entries state record). Wallet A's
# .env.cta and instance cta2's .env.cta2 never set this key, so this is a
# guaranteed no-op for both existing live instances (bit-for-bit backward
# compatible) -- see hlvault.cta.live._process_coin and
# hlvault.cta.signals.sizing_multiplier for the consuming logic.
#
# Set e.g. "0.60" (60% annualized) to enable, on a NEW instance only: entry
# notional = NOTIONAL_PER_TRADE * m, where
#   m = clip(SIGMA_TARGET / sigma_i, SIGMA_CLIP_LO, SIGMA_CLIP_HI)
# and sigma_i is coin i's zero-mean EWMA volatility of 4h closed-bar log
# returns (span SIGMA_SPAN_BARS, annualized x sqrt(2190)).
#
# SIGMA_CLIP_HI is fixed at 1.0 and is deliberately NOT an env knob: cap-only
# sizing (spec §0 "槓桿只縮不加" -- docs/superpowers/specs/
# 2026-07-13-cta-staged-sizing-design.md) is a structural invariant of this
# feature, not an owner-tunable parameter.
_sigma_target_raw = _env_str("SIGMA_TARGET", "")
SIGMA_TARGET = float(_sigma_target_raw) if _sigma_target_raw else None
SIGMA_SPAN_BARS = _env_int("SIGMA_SPAN_BARS", "180")
SIGMA_CLIP_LO = _env_float("SIGMA_CLIP_LO", "0.25")
SIGMA_CLIP_HI = 1.0

# Import-time validity guard (engineering principle #3/#5 forcing function):
# a nonsensical B1 config must refuse to start, loudly, rather than be
# silently "repaired" downstream (clipping a bad value to a floor would hide
# the misconfiguration behind normal-looking orders). Deliberately gated on
# SIGMA_TARGET being SET: when B1 is off (wallet A / cta2 -- the key absent
# from their env files) this block is a no-op and the unset path stays
# bit-identical to pre-B1 behavior.
if SIGMA_TARGET is not None:
    if SIGMA_TARGET <= 0:
        raise RuntimeError(
            f"SIGMA_TARGET={SIGMA_TARGET} is invalid: must be > 0 (annualized "
            "vol target, e.g. 0.60). To DISABLE B1 vol-target sizing, leave "
            "SIGMA_TARGET unset or empty -- do not set it to 0.")
    if not (0 < SIGMA_CLIP_LO <= 1.0):
        raise RuntimeError(
            f"SIGMA_CLIP_LO={SIGMA_CLIP_LO} is invalid: must be in (0, 1] "
            "(lower bound of the cap-only multiplier m; SIGMA_CLIP_HI is "
            "fixed at 1.0). This guard fires only because SIGMA_TARGET is "
            f"set ({SIGMA_TARGET}).")

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
# Resolution order: the INSTANCE env file (.env.cta / .env.cta2) wins if it
# sets its OWN key; .env.research is the fallback. Two instances sharing one
# .env.research key would double the effective Coinalyze request rate against
# the shared 40 req/min free-tier budget (see COINALYZE_THROTTLE_SECONDS
# above and .env.cta2's template) -- giving instance B its own key here
# removes that shared budget entirely. Wallet A's .env.cta never sets this
# key, so it always falls through to .env.research exactly as before
# (backward compatible).
COINALYZE_API_KEY = _clean(
    _FILE_VALUES.get("COINALYZE_API_KEY") or _RESEARCH_VALUES.get("COINALYZE_API_KEY") or "")
COINALYZE_BASE_URL = "https://api.coinalyze.net/v1"
COINALYZE_THROTTLE_SECONDS = _env_float("COINALYZE_THROTTLE_SECONDS", "1.6")  # 40 req/min
BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
# coin -> Binance USDT-M symbol (klines) ; Coinalyze future-market symbol resolved at runtime
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
                   "HYPE": "HYPEUSDT", "DOGE": "DOGEUSDT", "XRP": "XRPUSDT",
                   "DOT": "DOTUSDT"}  # DOT: added 2026-07-14 for the B1 instance universe

# ---- notify / state ---------------------------------------------------
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID", "")
STATE_FILE = _ROOT / "data" / "cache" / f"{INSTANCE_LABEL}_state.json"
CACHE_DIR = _ROOT / "data" / "cache" / f"{INSTANCE_LABEL}_live"
