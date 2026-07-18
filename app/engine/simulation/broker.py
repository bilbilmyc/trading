"""Deterministic bar-based broker used by the simulation engine."""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.simulation.events import (
    FillEvent,
    MarketEvent,
    OrderIntent,
    SimulationOrderStatus,
    SimulationSide,
)
from app.engine.simulation.models import ExecutionModelConfig


@dataclass(frozen=True)
class ExecutionResult:
    fill: FillEvent
    cash_delta: float
    position_delta: float


class DeterministicBarBroker:
    """Fill bar-scoped market intents with explicit friction.

    Any quantity left by the volume participation cap is reported on the
    fill and treated as cancelled rather than carried to the next bar.
    """

    def __init__(self, config: ExecutionModelConfig):
        self.config = config

    def execute(
        self,
        order: OrderIntent,
        market: MarketEvent,
        *,
        cash: float,
        position_quantity: float,
        raw_price: float | None = None,
        ignore_volume_limit: bool = False,
    ) -> ExecutionResult:
        price = self._execution_price(market.open if raw_price is None else raw_price, order.side)
        requested = self._requested_quantity(
            order,
            price=price,
            cash=cash,
            position_quantity=position_quantity,
        )
        filled = requested
        if not ignore_volume_limit:
            filled = min(filled, self._available_quantity(market, requested))

        if filled <= 1e-12:
            fill = FillEvent(
                order_id=order.order_id,
                index=market.index,
                time=market.time,
                side=order.side,
                requested_quantity=requested,
                filled_quantity=0.0,
                price=price,
                fee=0.0,
                remaining_quantity=requested,
                status=SimulationOrderStatus.REJECTED,
                reason=order.reason,
            )
            return ExecutionResult(fill=fill, cash_delta=0.0, position_delta=0.0)

        notional = filled * price
        fee = notional * self.config.fee_rate
        remaining = max(0.0, requested - filled)
        status = (
            SimulationOrderStatus.FILLED
            if remaining <= 1e-12
            else SimulationOrderStatus.PARTIALLY_FILLED
        )
        if order.side == SimulationSide.BUY:
            cash_delta = -(notional + fee)
            position_delta = filled
        else:
            cash_delta = notional - fee
            position_delta = -filled

        fill = FillEvent(
            order_id=order.order_id,
            index=market.index,
            time=market.time,
            side=order.side,
            requested_quantity=requested,
            filled_quantity=filled,
            price=price,
            fee=fee,
            remaining_quantity=remaining,
            status=status,
            reason=order.reason,
        )
        return ExecutionResult(fill=fill, cash_delta=cash_delta, position_delta=position_delta)

    def _execution_price(self, raw_price: float, side: SimulationSide) -> float:
        if side == SimulationSide.BUY:
            return raw_price * (1 + self.config.slippage_rate)
        return raw_price * (1 - self.config.slippage_rate)

    def _requested_quantity(
        self,
        order: OrderIntent,
        *,
        price: float,
        cash: float,
        position_quantity: float,
    ) -> float:
        if order.side == SimulationSide.SELL:
            requested = position_quantity if order.quantity is None else order.quantity
            return max(0.0, min(requested, position_quantity))
        if order.quantity is not None:
            affordable = cash / (price * (1 + self.config.fee_rate))
            return max(0.0, min(order.quantity, affordable))
        fraction = order.cash_fraction if order.cash_fraction is not None else 1.0
        allocation = cash * fraction
        return max(0.0, allocation / (price * (1 + self.config.fee_rate)))

    def _available_quantity(self, market: MarketEvent, requested: float) -> float:
        participation = self.config.max_volume_participation
        if participation is None:
            return requested
        if market.volume is None or market.volume <= 0:
            return 0.0
        return market.volume * participation


__all__ = ["DeterministicBarBroker", "ExecutionResult"]
