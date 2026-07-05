"""Shared strategy types. Strategies are pure: state in, target offers out."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class TargetOffer:
    rate: float         # daily decimal
    period: int         # days, 2..120
    amount: float       # USD
    tag: str = ""       # which rung produced it (journal/debug)


@dataclass(frozen=True)
class MarketState:
    frr: float                      # daily decimal
    last: float
    best_ask: Optional[float]       # lender side top of book
    best_bid: Optional[float]
    highs2: List[float] = field(default_factory=list)   # rolling window, hourly highs (2d market)
    highs30: List[float] = field(default_factory=list)  # rolling window, daily highs (30d market)


@dataclass(frozen=True)
class AccountState:
    available: float                # funding wallet available USD
    own_offers: list = field(default_factory=list)      # FundingOffer we placed
    foreign_offers: list = field(default_factory=list)  # NOT ours — never touch
    own_committed: float = 0.0      # engine capital out on loans (journal-attributed)
    wallet_total: float = 0.0
