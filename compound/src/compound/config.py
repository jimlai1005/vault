"""Runtime configuration: frozen dataclass loaded from .env (credentials) and
optional JSON overrides (strategy/engine params).

Credentials come ONLY from .env; strategy params ONLY from JSON/defaults, so a
leaked config file never contains secrets.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    # credentials (.env only)
    api_key: str = ""
    api_secret: str = ""
    # market facts
    symbol: str = "fUSD"
    fee: float = 0.15            # Bitfinex cut of interest earned
    min_offer: float = 150.0     # exchange minimum offer, USD
    max_period: int = 120        # user-authorized max lock (days)
    # engine
    tick_seconds: int = 300
    max_mutations_per_tick: int = 10
    journal_dir: str = "journal"
    # Max USD this engine may manage (own offers + own credits). Other capital in
    # the same wallet (legacy bot, manual loans) must never be touched.
    capital_budget: float = 328.0
    # live-test guardrails (enforced in code, not by operator discipline)
    live_test_mode: bool = True
    live_test_max_offer: float = 300.0
    live_test_max_period: int = 2
    live_test_max_concurrent: int = 2

    @property
    def journal_path(self):
        """journal_dir anchored to the repo root — a relative path resolved
        against CWD would give systemd/cron runs a fresh empty ownership
        registry, orphaning every live offer (review F3)."""
        from pathlib import Path

        p = Path(self.journal_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def require_credentials(self):
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "Missing BFX_API_KEY / BFX_API_SECRET (expected in %s/.env)"
                % PROJECT_ROOT
            )


def _parse_env_file(path):
    creds = {}
    if not path.exists():
        return creds
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        creds[key.strip()] = value.strip().strip('"').strip("'")
    return creds


def load(env_path=None, overrides_path=None):
    """Build Config from .env (credentials) + optional JSON overrides (params)."""
    env = _parse_env_file(Path(env_path) if env_path else PROJECT_ROOT / ".env")
    params = {}
    if overrides_path:
        params = json.loads(Path(overrides_path).read_text())
    field_names = {f.name for f in dataclasses.fields(Config)}
    unknown = set(params) - field_names
    if unknown:
        raise ValueError("Unknown config keys: %s" % sorted(unknown))
    params.pop("api_key", None)   # secrets never come from JSON
    params.pop("api_secret", None)
    return Config(
        api_key=env.get("BFX_API_KEY", ""),
        api_secret=env.get("BFX_API_SECRET", ""),
        **params
    )
