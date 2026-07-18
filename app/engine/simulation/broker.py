"""Deterministic, bar-based matching and friction model."""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.simulation.events import (
    FillEvent,
    MarketEvent,
    OrderIntent,
    SimulationOrderStatus,
    SimulationOrderType,
    SimulationSide,
    SimulationTimeInForce,
)
from app.engine.simulation.models import ExecutionModelConfig


@dataclass(frozen=True)
class ExecutionResult:
    fill: FillEvent
    cash_delta: float
    position_delta: float


class DeterministicBarBroker:
    """Match orders against one deterministic OHLCV/L1 bar.

    Market data may include bid/ask and displayed sizes. Without it, the
    broker uses the bar open and the participation cap as a synthetic book.
    A passive limit order can also reserve a configured fraction of available
    depth for orders ahead of it, approximating price-time queue priority.
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
        matched_price = raw_price if raw_price is not None else self._matching_price(order, market)
        if matched_price is None:
            status = (
                SimulationOrderStatus.PENDING
                if order.time_in_force == SimulationTimeInForce.GTC
                else SimulationOrderStatus.REJECTED
            )
            reason = (
                "not_marketable"
                if status == SimulationOrderStatus.PENDING
                else "ioc_not_marketable"
            )
            return self._empty_result(order, market, status, reason)
        if order.post_only and self._is_marketable_post_only(order, market):
            return self._empty_result(
                order, market, SimulationOrderStatus.REJECTED, "post_only_would_take"
            )

        price = self._execution_price(matched_price, order, market)
        requested = self._requested_quantity(
            order,
            price=price,
            cash=cash,
            position_quantity=position_quantity,
        )
        if requested <= 1e-12:
            return self._empty_result(
                order, market, SimulationOrderStatus.REJECTED, "insufficient_balance"
            )

        filled = requested
        if not ignore_volume_limit:
            filled = min(filled, self._available_quantity(market, order, requested))
        if order.time_in_force == SimulationTimeInForce.FOK and filled + 1e-12 < requested:
            return self._empty_result(
                order, market, SimulationOrderStatus.REJECTED, "fok_unfilled", requested
            )
        if filled <= 1e-12:
            status = (
                SimulationOrderStatus.PENDING
                if order.time_in_force == SimulationTimeInForce.GTC
                else SimulationOrderStatus.REJECTED
            )
            return self._empty_result(order, market, status, "insufficient_liquidity", requested)

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
            order_type=order.order_type,
        )
        return ExecutionResult(fill=fill, cash_delta=cash_delta, position_delta=position_delta)

    def _empty_result(
        self,
        order: OrderIntent,
        market: MarketEvent,
        status: SimulationOrderStatus,
        reason: str,
        requested: float = 0.0,
    ) -> ExecutionResult:
        price = self._reference_price(order, market)
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
            status=status,
            reason=reason if reason else order.reason,
            order_type=order.order_type,
        )
        return ExecutionResult(fill=fill, cash_delta=0.0, position_delta=0.0)

    def _matching_price(self, order: OrderIntent, market: MarketEvent) -> float | None:
        quote = self._reference_price(order, market)
        if order.order_type == SimulationOrderType.MARKET:
            return quote
        if order.order_type == SimulationOrderType.LIMIT:
            assert order.limit_price is not None
            if order.side == SimulationSide.BUY and market.low <= order.limit_price:
                return min(quote, order.limit_price)
            if order.side == SimulationSide.SELL and market.high >= order.limit_price:
                return max(quote, order.limit_price)
            return None
        assert order.stop_price is not None
        if order.order_type == SimulationOrderType.STOP_MARKET:
            triggered = (
                market.high >= order.stop_price
                if order.side == SimulationSide.BUY
                else market.low <= order.stop_price
            )
        else:
            triggered = (
                market.low <= order.stop_price
                if order.side == SimulationSide.BUY
                else market.high >= order.stop_price
            )
        if not triggered:
            return None
        if order.side == SimulationSide.BUY:
            return max(quote, order.stop_price)
        return min(quote, order.stop_price)

    def _execution_price(
        self,
        raw_price: float,
        order: OrderIntent,
        market: MarketEvent,
    ) -> float:
        # A passive limit cannot receive an adverse price beyond its limit.
        if order.order_type == SimulationOrderType.LIMIT:
            return raw_price
        multiplier = 1.0
        if market.market_regime == "volatile":
            multiplier = self.config.volatile_slippage_multiplier
        elif market.market_regime == "stressed":
            multiplier = self.config.stressed_slippage_multiplier
        slippage = self.config.slippage_rate * multiplier
        if order.side == SimulationSide.BUY:
            return raw_price * (1 + slippage)
        return raw_price * (1 - slippage)

    @staticmethod
    def _reference_price(order: OrderIntent, market: MarketEvent) -> float:
        if order.side == SimulationSide.BUY:
            return market.ask if market.ask is not None else market.open
        return market.bid if market.bid is not None else market.open

    @staticmethod
    def _is_marketable_post_only(order: OrderIntent, market: MarketEvent) -> bool:
        assert order.limit_price is not None
        if order.side == SimulationSide.BUY:
            return order.limit_price >= (market.ask if market.ask is not None else market.open)
        return order.limit_price <= (market.bid if market.bid is not None else market.open)

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

    def _available_quantity(
        self,
        market: MarketEvent,
        order: OrderIntent,
        requested: float,
    ) -> float:
        depth = market.ask_size if order.side == SimulationSide.BUY else market.bid_size
        available = requested if depth is None else depth
        participation = self.config.max_volume_participation
        if participation is not None:
            volume_cap = 0.0 if market.volume is None else market.volume * participation
            available = min(available, volume_cap)
        if order.order_type == SimulationOrderType.LIMIT:
            available *= 1 - self.config.queue_position_fraction
        return max(0.0, available)


__all__ = ["DeterministicBarBroker", "ExecutionResult"]
