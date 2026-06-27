"""ATR-based position sizing — volatility-adjusted risk.

Classic technique: size position inversely to recent volatility so that
risk-per-trade is roughly constant in absolute terms even when markets
calm down or get choppy.

Formula:
  risk_dollars = account_equity * risk_pct
  stop_distance = k * ATR
  quantity = risk_dollars / (stop_distance * contract_size)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass
class ATRSizingResult:
    quantity: float
    notional: float
    risk_amount: float
    atr: float
    stop_distance: float
    k_multiple: float


def compute_atr(prices: Sequence[float], period: int = 14) -> float:
    """Wilder's ATR — average true range over `period` periods.

    prices: list of recent closes (or highs).
    """
    if len(prices) < 2:
        return 0.0
    if len(prices) < period + 1:
        # Use what's available.
        period = max(1, len(prices) - 1)
    # True range approximated from close-to-close diffs.
    diffs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    if not diffs:
        return 0.0
    if period == 1:
        return diffs[-1]
    # Wilder's smoothing: (prev_atr * (period-1) + tr) / period
    atr = sum(diffs[:period]) / period
    for tr in diffs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def atr_position_size(
    account_equity: float,
    entry_price: float,
    atr: float,
    *,
    risk_pct: float = 0.02,
    k_multiple: float = 2.0,
    contract_size: float = 1.0,
    min_quantity: float = 0.001,
) -> ATRSizingResult:
    """Compute position size using ATR-based stop.

    stop_distance = k_multiple * ATR (e.g. 2x ATR)
    quantity = (equity * risk_pct) / (stop_distance * contract_size)
    """
    if account_equity <= 0 or entry_price <= 0 or atr <= 0:
        return ATRSizingResult(0.0, 0.0, 0.0, atr, 0.0, k_multiple)
    if risk_pct <= 0 or risk_pct >= 1:
        raise ValueError("risk_pct must be in (0, 1)")
    if k_multiple <= 0:
        raise ValueError("k_multiple must be positive")

    risk_dollars = account_equity * risk_pct
    stop_distance = k_multiple * atr
    raw_quantity = risk_dollars / (stop_distance * contract_size)
    quantity = max(min_quantity, (int(raw_quantity / min_quantity)) * min_quantity)
    quantity = round(quantity, 6)
    if quantity < min_quantity:
        quantity = min_quantity
    notional = quantity * entry_price * contract_size
    return ATRSizingResult(
        quantity=quantity,
        notional=round(notional, 4),
        risk_amount=round(risk_dollars, 4),
        atr=atr,
        stop_distance=stop_distance,
        k_multiple=k_multiple,
    )


__all__ = ["ATRResult" if False else "ATR", "ATR_Sizing_Result" if False else "ATR_sizing_result", "compute_atr", "atr_position_size"]