"""ATR-based position sizing and volatility snapshots."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ATRSizingResult:
    quantity: float
    notional: float
    risk_amount: float
    atr: float
    stop_distance: float
    k_multiple: float


@dataclass(frozen=True)
class VolatilitySnapshot:
    """Validated ATR evidence used to tighten a pre-trade order-size cap."""

    symbol: str
    atr: float
    atr_pct: float
    candle_count: int

    def as_dict(self) -> dict[str, object]:
        """Return JSON-friendly evidence for risk status and audit views."""
        return {
            "symbol": self.symbol,
            "atr": self.atr,
            "atr_pct": self.atr_pct,
            "candle_count": self.candle_count,
        }


def compute_atr(prices: Sequence[float], period: int = 14) -> float:
    """Compute Wilder-style close-to-close ATR for a normalized price sequence."""
    if len(prices) < 2:
        return 0.0
    if len(prices) < period + 1:
        period = max(1, len(prices) - 1)
    diffs = [abs(prices[index] - prices[index - 1]) for index in range(1, len(prices))]
    if not diffs:
        return 0.0
    if period == 1:
        return diffs[-1]
    atr = sum(diffs[:period]) / period
    for true_range in diffs[period:]:
        atr = (atr * (period - 1) + true_range) / period
    return atr


def _timestamp_key(value: object) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)) and math.isfinite(value):
        parsed = float(value)
    else:
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return None
    if not math.isfinite(parsed):
        return None
    return parsed / 1000 if abs(parsed) >= 100_000_000_000 else parsed


def _normalized_candles(candles: Iterable[Mapping[str, Any]]) -> list[tuple[float, float, float]]:
    """Extract finite OHLC values and sort candles by their available open time."""
    parsed: list[tuple[float, float, float, float, int]] = []
    for index, candle in enumerate(candles):
        try:
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))
        except (TypeError, ValueError):
            continue
        if (
            not all(math.isfinite(value) and value > 0 for value in (high, low, close))
            or low > high
        ):
            continue
        timestamp = _timestamp_key(candle.get("open_time", candle.get("timestamp")))
        if timestamp is None:
            continue
        parsed.append((timestamp, high, low, close, index))
    parsed.sort(key=lambda item: (item[0], item[4]))
    return [(high, low, close) for _, high, low, close, _ in parsed]


def volatility_snapshot_from_candles(
    symbol: str, candles: Iterable[Mapping[str, Any]], *, atr_period: int
) -> VolatilitySnapshot | None:
    """Calculate a true-range ATR percentage from sufficiently complete candles."""
    if atr_period < 1:
        raise ValueError("atr_period must be positive")
    normalized = _normalized_candles(candles)
    if len(normalized) < atr_period + 1:
        return None
    true_ranges: list[float] = []
    previous_close = normalized[0][2]
    for high, low, close in normalized[1:]:
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    atr = sum(true_ranges[:atr_period]) / atr_period
    for true_range in true_ranges[atr_period:]:
        atr = (atr * (atr_period - 1) + true_range) / atr_period
    current_price = normalized[-1][2]
    if not math.isfinite(atr) or atr <= 0 or current_price <= 0:
        return None
    return VolatilitySnapshot(
        symbol=symbol.upper(),
        atr=atr,
        atr_pct=atr / current_price,
        candle_count=len(normalized),
    )


def volatility_adjusted_notional_cap(
    static_cap: float,
    atr_pct: float,
    *,
    target_atr_pct: float,
    min_multiplier: float,
) -> tuple[float, float]:
    """Return a cap that only tightens ``static_cap`` as volatility rises."""
    if not math.isfinite(min_multiplier) or not 0 <= min_multiplier <= 1:
        raise ValueError("min_multiplier must be in [0, 1]")
    if static_cap <= 0:
        return static_cap, 1.0
    if not all(math.isfinite(value) and value > 0 for value in (atr_pct, target_atr_pct)):
        return static_cap, 1.0
    multiplier = round(min(1.0, max(min_multiplier, target_atr_pct / atr_pct)), 10)
    return round(static_cap * multiplier, 10), multiplier


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
    """Compute position size using an ATR-multiple stop distance."""
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


__all__ = [
    "ATRSizingResult",
    "VolatilitySnapshot",
    "atr_position_size",
    "compute_atr",
    "volatility_adjusted_notional_cap",
    "volatility_snapshot_from_candles",
]
