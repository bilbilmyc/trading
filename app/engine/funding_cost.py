"""Funding cost calculator for perpetual positions.

Perpetual contracts pay/receive funding every N hours (typically 8h).
This module computes the cost of holding a position over a period.

If rate > 0: longs pay shorts.
If rate < 0: shorts pay longs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class FundingCost:
    notional: float
    avg_rate: float             # per period
    periods: int                # # of funding events
    payment: float              # positive = paid, negative = received
    apr_equivalent: float       # annualized cost as fraction of notional


def funding_cost(
    notional: float,
    avg_rate_per_period: float,
    periods: int,
    side: Side,
    periods_per_year: int = 3 * 365,
) -> FundingCost:
    """Compute total funding payment for holding a position.

    notional: position size in quote currency (USDT).
    avg_rate_per_period: average funding rate per settlement (e.g. 0.0001 = 1bp).
    periods: number of funding events covered.
    side: long pays if rate > 0, short pays if rate < 0.
    periods_per_year: 3 per day for 8h settlements → 1095; default 3 * 365.
    """
    if notional < 0:
        raise ValueError("notional must be non-negative")
    if periods < 0:
        raise ValueError("periods must be non-negative")

    if side == Side.LONG:
        # Long pays when rate > 0.
        payment = notional * avg_rate_per_period * periods
    else:
        # Short pays when rate < 0.
        payment = -notional * avg_rate_per_period * periods

    apr = avg_rate_per_period * periods_per_year

    return FundingCost(
        notional=notional,
        avg_rate=avg_rate_per_period,
        periods=periods,
        payment=round(payment, 4),
        apr_equivalent=round(apr, 6),
    )


__all__ = ["Side", "FundingCost", "funding_cost"]
