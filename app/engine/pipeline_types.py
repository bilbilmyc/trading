"""Value objects and Protocol types for LiveOrderPipeline.

These are the public surface of the pipeline's six ports. Keep this file
free of behaviour — only types live here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.strategies.base import Signal

# ── result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TradeReceipt:
    """Successful result of LiveOrderPipeline.execute."""

    order_id: str
    exchange: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None


@dataclass(frozen=True)
class TradeError:
    """Failed result of LiveOrderPipeline.execute.

    `stage` is the discriminator: which step vetoed or failed.
    """

    stage: str  # "guard" | "filter" | "risk" | "place"
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecision:
    """Result of RiskGate.check.

    `allowed` is the gate; when False, `reason` carries the violation.
    `stop_loss` / `take_profit` are advisory — pipeline may override with
    signal-level values when present.
    """

    allowed: bool
    reason: str
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True)
class TradeEvent:
    """An event the Observer records. `kind` is the discriminator."""

    kind: str  # "signal_filtered" | "signal_filter_error" | "gate_blocked" | "risk_rejected" | "order_placed" | "order_failed"
    payload: Mapping[str, Any] = field(default_factory=dict)


# ── ports ─────────────────────────────────────────────────────────────


class TradingGuard(Protocol):
    """Answers 'may we trade right now?' — kill switch + live-trading flag."""

    async def is_open(self) -> bool: ...


class RiskGate(Protocol):
    """Evaluates a Signal against position/value/drawdown/rate/daily-loss limits."""

    async def check(self, signal: Signal, price: float) -> RiskDecision: ...


class OrderTracker(Protocol):
    """Records a placed order locally for later reconciliation."""

    def track(self, order: Any) -> None: ...


class PositionRecorder(Protocol):
    """Updates local position state when an order is placed."""

    async def record(self, receipt: TradeReceipt) -> None: ...


class Observer(Protocol):
    """Emits TradeEvents to both human-facing alerts and persistent audit."""

    def record(self, event: TradeEvent) -> None: ...


class SignalFilter(Protocol):
    """Async veto on a Signal before placement."""

    async def check(self, signal: Signal, context: Mapping[str, Any]) -> bool: ...


# ── filter context ───────────────────────────────────────────────────


FilterContext = Mapping[str, Any]


__all__ = [
    "TradeReceipt",
    "TradeError",
    "RiskDecision",
    "TradeEvent",
    "TradingGuard",
    "RiskGate",
    "OrderTracker",
    "PositionRecorder",
    "Observer",
    "SignalFilter",
    "FilterContext",
]
