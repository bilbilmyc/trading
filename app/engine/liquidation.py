"""Liquidation price calculator for perpetual contracts.

Inverse formulas for isolated margin:
  Long:  liq_price = entry * (1 - 1/leverage + MMR)
  Short: liq_price = entry * (1 + 1/leverage - MMR)

Where MMR (maintenance margin ratio) is typically 0.5% for BTC,
1% for alts. Simplified model — actual exchange formulas differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class LiquidationResult:
    entry_price: float
    leverage: float
    side: Side
    maintenance_margin_rate: float
    liquidation_price: float
    distance_pct: float            # |entry - liq| / entry
    margin_required: float


def liquidation_price(
    entry_price: float,
    leverage: float,
    side: Side,
    maintenance_margin_rate: float = 0.005,
) -> LiquidationResult:
    """Compute approximate liquidation price for isolated margin."""
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if leverage <= 1:
        raise ValueError("leverage must be > 1 for liquidation to be possible")
    if not 0 <= maintenance_margin_rate < 1:
        raise ValueError("maintenance_margin_rate must be in [0, 1)")

    if side == Side.LONG:
        liq = entry_price * (1 - 1 / leverage + maintenance_margin_rate)
    else:
        liq = entry_price * (1 + 1 / leverage - maintenance_margin_rate)

    distance = abs(entry_price - liq) / entry_price
    margin = entry_price / leverage

    return LiquidationResult(
        entry_price=entry_price,
        leverage=leverage,
        side=side,
        maintenance_margin_rate=maintenance_margin_rate,
        liquidation_price=round(liq, 4),
        distance_pct=round(distance, 4),
        margin_required=round(margin, 4),
    )


def liq_distance_pct(
    entry_price: float,
    mark_price: float,
    leverage: float,
    side: Side,
) -> float:
    """Percentage distance from current mark to liquidation price."""
    liq = liquidation_price(
        entry_price=entry_price,
        leverage=leverage,
        side=side,
    ).liquidation_price
    if liq <= 0:
        return 0.0
    if side == Side.LONG:
        return max(0.0, (mark_price - liq) / mark_price)
    return max(0.0, (liq - mark_price) / mark_price)


__all__ = ["Side", "LiquidationResult", "liquidation_price", "liq_distance_pct"]
