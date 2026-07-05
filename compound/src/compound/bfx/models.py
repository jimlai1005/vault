"""Typed views over Bitfinex v2 keyless-array payloads.

v2 responses are JSON arrays without keys: field meaning is positional, and
some positions are permanent null placeholders. Fields are read by ABSOLUTE
index — never "skip the nulls". Index layouts follow
docs/bitfinex-api-reference.md (live-verified 2026-07-04); do not re-derive
them from memory.

Unit convention (architecture doc): every rate held here is the DAILY rate as
a decimal fraction, exactly as the API returns it. The single exception is
FundingStat.frr_365 — the funding-stats endpoint returns 1/365 of the daily
FRR (the documented odd one out); use FundingStat.frr_daily for the
normalized value.

Parsing is tolerant of null placeholders and short arrays (missing trailing
fields become None). A payload that is not an array at all raises — malformed
input must be loud, not silently wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DAYS_PER_YEAR = 365.0  # used only to undo the funding-stats 1/365 encoding


def require_funding_symbol(symbol):
    """Funding symbols are 'f' + currency ('fUSD'). Reject anything else
    loudly: a trading symbol ('tBTCUSD') is accepted by several endpoints but
    returns a different array layout, which would parse into garbage."""
    if not isinstance(symbol, str) or len(symbol) < 2 or not symbol.startswith("f"):
        raise ValueError("expected funding symbol like 'fUSD', got %r" % (symbol,))


def _require_array(model_name, arr):
    if not isinstance(arr, (list, tuple)):
        raise ValueError("%s.from_array expects an array, got %r" % (model_name, arr))


def _at(arr, idx):
    """Raw value at absolute index; None when the array is short or holds null."""
    if idx < len(arr):
        return arr[idx]
    return None


def _float_at(arr, idx):
    value = _at(arr, idx)
    if value is None:
        return None
    return float(value)


def _int_at(arr, idx):
    value = _at(arr, idx)
    if value is None:
        return None
    return int(value)


def _str_at(arr, idx):
    value = _at(arr, idx)
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class FundingTicker:
    """Funding ticker (API ref §3.1; 17 elements live, parse indices 0-15 only).

    All rates are daily decimals. ask is the lender side (where our offers sit);
    bid is borrower demand.
    """
    frr: Optional[float]
    bid: Optional[float]
    bid_period: Optional[int]
    bid_size: Optional[float]
    ask: Optional[float]
    ask_period: Optional[int]
    ask_size: Optional[float]
    daily_change: Optional[float]
    daily_change_relative: Optional[float]
    last: Optional[float]
    volume: Optional[float]
    high: Optional[float]
    low: Optional[float]
    frr_amount_available: Optional[float]

    @classmethod
    def from_array(cls, arr):
        _require_array("FundingTicker", arr)
        return cls(
            frr=_float_at(arr, 0),
            bid=_float_at(arr, 1),
            bid_period=_int_at(arr, 2),
            bid_size=_float_at(arr, 3),
            ask=_float_at(arr, 4),
            ask_period=_int_at(arr, 5),
            ask_size=_float_at(arr, 6),
            daily_change=_float_at(arr, 7),
            daily_change_relative=_float_at(arr, 8),
            last=_float_at(arr, 9),
            volume=_float_at(arr, 10),
            high=_float_at(arr, 11),
            low=_float_at(arr, 12),
            # 13, 14 are permanent null placeholders; 16 is undocumented — skip.
            frr_amount_available=_float_at(arr, 15),
        )


@dataclass(frozen=True)
class BookEntry:
    """Aggregated funding book row (API ref §3.2; precisions P0-P4 only).

    R0 raw rows have a different layout ([OFFER_ID, PERIOD, RATE, AMOUNT]) and
    are intentionally not modeled here.
    """
    rate: Optional[float]
    period: Optional[int]
    count: Optional[int]
    amount: Optional[float]

    @property
    def is_ask(self):
        """Funding book side convention (§3.2): AMOUNT > 0 = ask (funding
        offered by lenders — our side), AMOUNT < 0 = bid (borrower demand).
        This is inverted vs trading books. Raises TypeError on a null amount:
        a garbage row must be loud, not silently classified."""
        return self.amount > 0

    @classmethod
    def from_array(cls, arr):
        _require_array("BookEntry", arr)
        return cls(
            rate=_float_at(arr, 0),
            period=_int_at(arr, 1),
            count=_int_at(arr, 2),
            amount=_float_at(arr, 3),
        )


@dataclass(frozen=True)
class FundingOffer:
    """Active funding offer (API ref §4.5; also nested at index 4 of
    submit/cancel notifications)."""
    id: Optional[int]
    symbol: Optional[str]
    created_ms: Optional[int]
    updated_ms: Optional[int]
    amount: Optional[float]        # REMAINING amount (shrinks on partial fills)
    amount_orig: Optional[float]
    type: Optional[str]            # LIMIT | FRRDELTAFIX | FRRDELTAVAR
    flags: object                  # "future params object" — kept raw
    status: Optional[str]          # ACTIVE, PARTIALLY FILLED, EXECUTED, CANCELED
    rate: Optional[float]          # daily decimal
    period: Optional[int]          # days
    hidden: Optional[int]          # null/0 = visible, 1 = hidden
    renew: Optional[int]

    @classmethod
    def from_array(cls, arr):
        _require_array("FundingOffer", arr)
        return cls(
            id=_int_at(arr, 0),
            symbol=_str_at(arr, 1),
            created_ms=_int_at(arr, 2),
            updated_ms=_int_at(arr, 3),
            amount=_float_at(arr, 4),
            amount_orig=_float_at(arr, 5),
            type=_str_at(arr, 6),
            flags=_at(arr, 9),
            status=_str_at(arr, 10),
            rate=_float_at(arr, 14),
            period=_int_at(arr, 15),
            hidden=_int_at(arr, 17),
            renew=_int_at(arr, 19),
        )


@dataclass(frozen=True)
class FundingLoan:
    """Funding loan — filled lend NOT currently used in a position
    (API ref §4.6). Credits share the layout with one extra trailing field."""
    id: Optional[int]
    symbol: Optional[str]
    side: Optional[int]            # 1 lender, 0 both, -1 borrower
    created_ms: Optional[int]
    updated_ms: Optional[int]
    amount: Optional[float]
    flags: object                  # future params — kept raw
    status: Optional[str]
    rate_type: Optional[str]       # FIXED | VAR (FRR-pegged)
    rate: Optional[float]          # daily decimal
    period: Optional[int]          # days
    opened_ms: Optional[int]
    last_payout_ms: Optional[int]
    notify: Optional[int]
    hidden: Optional[int]
    renew: Optional[int]
    no_close: Optional[int]

    @classmethod
    def _kwargs_from_array(cls, arr):
        return dict(
            id=_int_at(arr, 0),
            symbol=_str_at(arr, 1),
            side=_int_at(arr, 2),
            created_ms=_int_at(arr, 3),
            updated_ms=_int_at(arr, 4),
            amount=_float_at(arr, 5),
            flags=_at(arr, 6),
            status=_str_at(arr, 7),
            rate_type=_str_at(arr, 8),
            rate=_float_at(arr, 11),
            period=_int_at(arr, 12),
            opened_ms=_int_at(arr, 13),
            last_payout_ms=_int_at(arr, 14),
            notify=_int_at(arr, 15),
            hidden=_int_at(arr, 16),
            renew=_int_at(arr, 18),
            no_close=_int_at(arr, 20),
        )

    @classmethod
    def from_array(cls, arr):
        _require_array("FundingLoan", arr)
        return cls(**cls._kwargs_from_array(arr))


@dataclass(frozen=True)
class FundingCredit(FundingLoan):
    """Funding credit — filled lend currently used in a position
    (API ref §4.6; loan layout + POSITION_PAIR at index 21)."""
    position_pair: Optional[str] = None

    @classmethod
    def from_array(cls, arr):
        _require_array("FundingCredit", arr)
        kwargs = cls._kwargs_from_array(arr)
        kwargs["position_pair"] = _str_at(arr, 21)
        return cls(**kwargs)


@dataclass(frozen=True)
class Wallet:
    """Wallet row (API ref §4.1). available_balance may be null until the
    server computes it (docs: use a calc request, or treat as unknown) — we
    keep it None; callers must not treat None as zero OR as balance."""
    wallet_type: Optional[str]     # exchange | margin | funding
    currency: Optional[str]        # bare currency, e.g. USD
    balance: Optional[float]
    unsettled_interest: Optional[float]
    available_balance: Optional[float]

    @classmethod
    def from_array(cls, arr):
        _require_array("Wallet", arr)
        return cls(
            wallet_type=_str_at(arr, 0),
            currency=_str_at(arr, 1),
            balance=_float_at(arr, 2),
            unsettled_interest=_float_at(arr, 3),
            available_balance=_float_at(arr, 4),
        )


@dataclass(frozen=True)
class Candle:
    """Funding candle (API ref §3.3). OHLC are daily rates."""
    mts: Optional[int]
    open: Optional[float]
    close: Optional[float]
    high: Optional[float]
    low: Optional[float]
    volume: Optional[float]

    @classmethod
    def from_array(cls, arr):
        _require_array("Candle", arr)
        return cls(
            mts=_int_at(arr, 0),
            open=_float_at(arr, 1),
            close=_float_at(arr, 2),
            high=_float_at(arr, 3),
            low=_float_at(arr, 4),
            volume=_float_at(arr, 5),
        )


@dataclass(frozen=True)
class FundingStat:
    """Funding stats row (API ref §3.5). UNIT TRAP: frr_365 is 1/365 of the
    daily FRR (documented quirk of this endpoint alone) — never feed it into
    an offer; use frr_daily."""
    mts: Optional[int]
    frr_365: Optional[float]
    avg_period: Optional[float]
    funding_amount: Optional[float]
    funding_amount_used: Optional[float]
    funding_below_threshold: Optional[float]

    @property
    def frr_daily(self):
        """Daily-rate FRR (decimal), normalized per the documented formula
        (rate x 365). This is decoding of this endpoint's odd unit, not a
        display conversion — daily<->APR conversions live in rates.py."""
        if self.frr_365 is None:
            return None
        return self.frr_365 * DAYS_PER_YEAR

    @property
    def utilization(self):
        """funding_amount_used / funding_amount — core demand signal."""
        if not self.funding_amount or self.funding_amount_used is None:
            return None
        return self.funding_amount_used / self.funding_amount

    @classmethod
    def from_array(cls, arr):
        _require_array("FundingStat", arr)
        return cls(
            mts=_int_at(arr, 0),
            frr_365=_float_at(arr, 3),
            avg_period=_float_at(arr, 4),
            funding_amount=_float_at(arr, 7),
            funding_amount_used=_float_at(arr, 8),
            funding_below_threshold=_float_at(arr, 11),
        )


@dataclass(frozen=True)
class FundingTrade:
    """Public funding trade (API ref §3.4)."""
    id: Optional[int]
    mts: Optional[int]
    amount: Optional[float]        # sign = taker direction
    rate: Optional[float]          # daily decimal
    period: Optional[int]          # days

    @classmethod
    def from_array(cls, arr):
        _require_array("FundingTrade", arr)
        return cls(
            id=_int_at(arr, 0),
            mts=_int_at(arr, 1),
            amount=_float_at(arr, 2),
            rate=_float_at(arr, 3),
            period=_int_at(arr, 4),
        )


@dataclass(frozen=True)
class LedgerEntry:
    """Ledger row (API ref §4.8). Category-28 entries are funding interest
    credits, already net of the exchange fee."""
    id: Optional[int]
    currency: Optional[str]
    wallet: Optional[str]
    mts: Optional[int]
    amount: Optional[float]
    balance: Optional[float]
    description: Optional[str]

    @classmethod
    def from_array(cls, arr):
        _require_array("LedgerEntry", arr)
        return cls(
            id=_int_at(arr, 0),
            currency=_str_at(arr, 1),
            wallet=_str_at(arr, 2),
            mts=_int_at(arr, 3),
            amount=_float_at(arr, 5),
            balance=_float_at(arr, 6),
            description=_str_at(arr, 8),
        )
