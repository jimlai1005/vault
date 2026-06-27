from __future__ import annotations

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
    min_alpha_tstat: float = 2.0
    cache_dir: str = "data/cache"
    derived_dir: str = "data/derived"
