"""Event types shared by deterministic backtests and paper/live adapters."""

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


class SimulationOrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    TAKE_PROFIT_MARKET = "take_profit_market"


class SimulationTimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class SimulationOrderStatus(str, Enum):
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class MarketEvent:
    index: int
    time: Any | None
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    market_regime: str = "normal"
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
        for name, value in (("bid", self.bid), ("ask", self.ask)):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError(f"market {name} must be finite and positive")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("market bid must not exceed ask")
        for name, value in (("bid_size", self.bid_size), ("ask_size", self.ask_size)):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"market {name} must be finite and non-negative")
        if self.market_regime not in {"normal", "volatile", "stressed"}:
            raise ValueError("market_regime must be normal, volatile, or stressed")


@dataclass(frozen=True)
class SignalEvent:
    index: int
    time: Any | None
    action: str
    reason: str = "signal"
    order_type: SimulationOrderType = SimulationOrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    post_only: bool = False
    time_in_force: SimulationTimeInForce = SimulationTimeInForce.IOC
    expires_index: int | None = None
    cancel_order_id: str | None = None
    event_type: SimulationEventType = field(default=SimulationEventType.SIGNAL, init=False)

    def __post_init__(self) -> None:
        if self.action not in {"enter", "exit", "cancel"}:
            raise ValueError("signal action must be enter, exit, or cancel")
        if self.action == "cancel" and not self.cancel_order_id:
            raise ValueError("cancel signals require cancel_order_id")
        if self.order_type == SimulationOrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if (
            self.order_type
            in {
                SimulationOrderType.STOP_MARKET,
                SimulationOrderType.TAKE_PROFIT_MARKET,
            }
            and self.stop_price is None
        ):
            raise ValueError("conditional orders require stop_price")
        for name, value in (("limit_price", self.limit_price), ("stop_price", self.stop_price)):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        if self.expires_index is not None and self.expires_index < self.index:
            raise ValueError("expires_index cannot be before the signal index")


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    created_index: int
    execute_index: int
    side: SimulationSide
    reason: str
    quantity: float | None = None
    cash_fraction: float | None = None
    order_type: SimulationOrderType = SimulationOrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    post_only: bool = False
    time_in_force: SimulationTimeInForce = SimulationTimeInForce.IOC
    expires_index: int | None = None
    event_type: SimulationEventType = field(default=SimulationEventType.ORDER, init=False)

    def __post_init__(self) -> None:
        if self.created_index < 0 or self.execute_index < self.created_index:
            raise ValueError("order indices are inconsistent")
        if self.quantity is not None and (not isfinite(self.quantity) or self.quantity <= 0):
            raise ValueError("order quantity must be finite and positive")
        if self.cash_fraction is not None and (
            not isfinite(self.cash_fraction) or not 0 < self.cash_fraction <= 1
        ):
            raise ValueError("cash_fraction must be between 0 (exclusive) and 1")
        if self.order_type == SimulationOrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if (
            self.order_type
            in {
                SimulationOrderType.STOP_MARKET,
                SimulationOrderType.TAKE_PROFIT_MARKET,
            }
            and self.stop_price is None
        ):
            raise ValueError("conditional orders require stop_price")
        for name, value in (("limit_price", self.limit_price), ("stop_price", self.stop_price)):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        if self.post_only and self.order_type != SimulationOrderType.LIMIT:
            raise ValueError("post_only is only supported for limit orders")
        if self.expires_index is not None and self.expires_index < self.execute_index:
            raise ValueError("expires_index cannot be before execute_index")


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
    order_type: SimulationOrderType = SimulationOrderType.MARKET
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
    "SimulationOrderType",
    "SimulationSide",
    "SimulationTimeInForce",
]
