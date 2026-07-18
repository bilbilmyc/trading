"""Event types shared by deterministic backtests and future paper/live adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any


class SimulationEventType(str, Enum):
    MARKET = "market"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    EQUITY = "equity"


class SimulationSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class SimulationOrderStatus(str, Enum):
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MarketEvent:
    index: int
    time: Any | None
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    event_type: SimulationEventType = field(default=SimulationEventType.MARKET, init=False)

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("market index must be non-negative")
        prices = (self.open, self.high, self.low, self.close)
        if any(not isfinite(value) or value <= 0 for value in prices):
            raise ValueError("market OHLC prices must be finite and positive")
        if self.low > self.high or not self.low <= self.open <= self.high:
            raise ValueError("market event has inconsistent OHLC prices")
        if not self.low <= self.close <= self.high:
            raise ValueError("market event has inconsistent OHLC prices")
        if self.volume is not None and (not isfinite(self.volume) or self.volume < 0):
            raise ValueError("market volume must be finite and non-negative")


@dataclass(frozen=True)
class SignalEvent:
    index: int
    time: Any | None
    action: str
    reason: str = "signal"
    event_type: SimulationEventType = field(default=SimulationEventType.SIGNAL, init=False)

    def __post_init__(self) -> None:
        if self.action not in {"enter", "exit"}:
            raise ValueError("signal action must be 'enter' or 'exit'")


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    created_index: int
    execute_index: int
    side: SimulationSide
    reason: str
    quantity: float | None = None
    cash_fraction: float | None = None
    event_type: SimulationEventType = field(default=SimulationEventType.ORDER, init=False)


@dataclass(frozen=True)
class FillEvent:
    order_id: str
    index: int
    time: Any | None
    side: SimulationSide
    requested_quantity: float
    filled_quantity: float
    price: float
    fee: float
    remaining_quantity: float
    status: SimulationOrderStatus
    reason: str
    event_type: SimulationEventType = field(default=SimulationEventType.FILL, init=False)


@dataclass(frozen=True)
class EquityEvent:
    index: int
    time: Any | None
    cash: float
    position_quantity: float
    mark_price: float
    equity: float
    event_type: SimulationEventType = field(default=SimulationEventType.EQUITY, init=False)


SimulationEvent = MarketEvent | SignalEvent | OrderIntent | FillEvent | EquityEvent


__all__ = [
    "EquityEvent",
    "FillEvent",
    "MarketEvent",
    "OrderIntent",
    "SignalEvent",
    "SimulationEvent",
    "SimulationEventType",
    "SimulationOrderStatus",
    "SimulationSide",
]
