"""Rate conversions and fee netting. The ONLY place these formulas live.

Internal convention: all rates are DAILY rates as decimal fractions
(Bitfinex API native unit, e.g. 0.0003715 == 3.715 bps/day == 13.56% APR).
APR appears only at display/report edges.
"""

DAYS_PER_YEAR = 365


def daily_to_apr(daily):
    """Simple (non-compounding) annualized rate, the unit Bitfinex UI quotes."""
    return daily * DAYS_PER_YEAR


def apr_to_daily(apr):
    return apr / DAYS_PER_YEAR


def net_daily(gross_daily, fee):
    """Bitfinex takes `fee` (e.g. 0.15) of interest earned; returns lender's take."""
    if not 0.0 <= fee < 1.0:
        raise ValueError("fee out of range: %r" % fee)
    return gross_daily * (1.0 - fee)


def daily_to_apy(daily):
    """Compounded annual yield if interest is re-lent daily at the same rate."""
    return (1.0 + daily) ** DAYS_PER_YEAR - 1.0
