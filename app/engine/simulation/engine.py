"""Generic, deterministic event-driven simulation engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from app.engine.simulation.broker import DeterministicBarBroker, ExecutionResult
from app.engine.simulation.events import (
    EquityEvent,
    FillEvent,
    MarketEvent,
    OrderIntent,
    SignalEvent,
    SimulationEvent,
    SimulationOrderStatus,
    SimulationOrderType,
    SimulationSide,
    SimulationTimeInForce,
)
from app.engine.simulation.models import (
    SimulationConfig,
    SimulationPosition,
    SimulationResult,
    SimulationTrade,
)
from app.engine.trailing_stop import Side as TrailingSide
from app.engine.trailing_stop import TrailingStop


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    position_quantity: float
    entry_price: float
    equity: float


SignalModel = Callable[[Sequence[MarketEvent], int, AccountSnapshot], SignalEvent | None]


class EventDrivenSimulationEngine:
    """Run long-only signals through a deterministic exchange-style lifecycle.

    Signals are evaluated after a bar closes. Orders become eligible on the
    next bar plus ``additional_latency_bars``. GTC orders remain active across
    bars after a partial or non-marketable match; IOC/FOK retain their usual
    terminal semantics. The model is deterministic by design.
    """

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.broker = DeterministicBarBroker(config.execution)
        self._order_sequence = 0

    def run(self, markets: Sequence[MarketEvent], signal_model: SignalModel) -> SimulationResult:
        self._order_sequence = 0
        cash = self.config.initial_capital
        position = SimulationPosition()
        working_orders: list[OrderIntent] = []
        trailing_stop: TrailingStop | None = None
        equity_curve: list[float] = []
        trades: list[SimulationTrade] = []
        fills: list[FillEvent] = []
        events: list[SimulationEvent] = []

        for index, market in enumerate(markets):
            if market.index != index:
                raise ValueError("market indices must be contiguous and start at zero")
            events.append(market)

            cash, working_orders = self._process_working_orders(
                working_orders, market, cash, position, trades, fills, events
            )
            trailing_stop = self._sync_trailing_stop(trailing_stop, position)

            risk_order = self._risk_order(position, market, trailing_stop)
            if risk_order is not None:
                order, trigger_price = risk_order
                events.append(order)
                execution = self.broker.execute(
                    order,
                    market,
                    cash=cash,
                    position_quantity=position.quantity,
                    raw_price=trigger_price,
                )
                cash = self._record_execution(
                    execution, market, cash, position, trades, fills, events
                )
                trailing_stop = self._sync_trailing_stop(trailing_stop, position)

            equity = cash + position.quantity * market.close
            equity_curve.append(equity)
            events.append(
                EquityEvent(
                    index=index,
                    time=market.time,
                    cash=cash,
                    position_quantity=position.quantity,
                    mark_price=market.close,
                    equity=equity,
                )
            )
            if index == len(markets) - 1:
                continue

            signal = signal_model(
                markets,
                index,
                AccountSnapshot(
                    cash=cash,
                    position_quantity=position.quantity,
                    entry_price=position.entry_price,
                    equity=equity,
                ),
            )
            if signal is None:
                continue
            if signal.index != market.index:
                raise ValueError("signal index must match the market event being evaluated")
            events.append(signal)
            if signal.action == "cancel":
                working_orders = self._cancel_order(
                    working_orders, signal.cancel_order_id or "", market, fills, events
                )
                continue
            order = self._order_from_signal(signal, position)
            if order is not None:
                working_orders.append(order)
                events.append(order)

        if markets and position.is_open:
            market = markets[-1]
            order = self._new_order(
                created_index=market.index,
                execute_index=market.index,
                side=SimulationSide.SELL,
                reason="end_of_data",
                quantity=position.quantity,
            )
            events.append(order)
            execution = self.broker.execute(
                order,
                market,
                cash=cash,
                position_quantity=position.quantity,
                raw_price=market.close,
                ignore_volume_limit=True,
            )
            cash = self._record_execution(execution, market, cash, position, trades, fills, events)
            if equity_curve:
                equity_curve[-1] = cash

        return SimulationResult(
            initial_capital=self.config.initial_capital,
            final_equity=cash,
            equity_curve=equity_curve,
            trades=trades,
            fills=fills,
            events=events,
            max_drawdown=self._max_drawdown(equity_curve),
        )

    def _process_working_orders(
        self,
        working_orders: list[OrderIntent],
        market: MarketEvent,
        cash: float,
        position: SimulationPosition,
        trades: list[SimulationTrade],
        fills: list[FillEvent],
        events: list[SimulationEvent],
    ) -> tuple[float, list[OrderIntent]]:
        next_orders: list[OrderIntent] = []
        for order in working_orders:
            if order.execute_index > market.index:
                next_orders.append(order)
                continue
            if order.expires_index is not None and market.index > order.expires_index:
                self._record_terminal(
                    order, market, SimulationOrderStatus.EXPIRED, "expired", fills, events
                )
                continue
            execution = self.broker.execute(
                order, market, cash=cash, position_quantity=position.quantity
            )
            cash = self._record_execution(execution, market, cash, position, trades, fills, events)
            fill = execution.fill
            if fill.status == SimulationOrderStatus.PENDING:
                next_orders.append(order)
            elif fill.status == SimulationOrderStatus.PARTIALLY_FILLED:
                if order.time_in_force == SimulationTimeInForce.GTC:
                    next_orders.append(
                        replace(order, quantity=fill.remaining_quantity, cash_fraction=None)
                    )
                else:
                    self._record_terminal(
                        order,
                        market,
                        SimulationOrderStatus.CANCELLED,
                        "ioc_remainder_cancelled",
                        fills,
                        events,
                        remaining=fill.remaining_quantity,
                    )
        return cash, next_orders

    def _cancel_order(
        self,
        working_orders: list[OrderIntent],
        order_id: str,
        market: MarketEvent,
        fills: list[FillEvent],
        events: list[SimulationEvent],
    ) -> list[OrderIntent]:
        remaining: list[OrderIntent] = []
        for order in working_orders:
            if order.order_id == order_id:
                self._record_terminal(
                    order,
                    market,
                    SimulationOrderStatus.CANCELLED,
                    "cancelled_by_signal",
                    fills,
                    events,
                )
            else:
                remaining.append(order)
        return remaining

    def _order_from_signal(
        self, signal: SignalEvent, position: SimulationPosition
    ) -> OrderIntent | None:
        execute_index = signal.index + 1 + self.config.execution.additional_latency_bars
        if signal.action == "enter" and not position.is_open:
            return self._new_order(
                created_index=signal.index,
                execute_index=execute_index,
                side=SimulationSide.BUY,
                reason=signal.reason,
                cash_fraction=self.config.position_size_pct,
                order_type=signal.order_type,
                limit_price=signal.limit_price,
                stop_price=signal.stop_price,
                post_only=signal.post_only,
                time_in_force=signal.time_in_force,
                expires_index=signal.expires_index,
            )
        if signal.action == "exit" and position.is_open:
            return self._new_order(
                created_index=signal.index,
                execute_index=execute_index,
                side=SimulationSide.SELL,
                reason=signal.reason,
                quantity=position.quantity,
                order_type=signal.order_type,
                limit_price=signal.limit_price,
                stop_price=signal.stop_price,
                post_only=signal.post_only,
                time_in_force=signal.time_in_force,
                expires_index=signal.expires_index,
            )
        return None

    def _risk_order(
        self,
        position: SimulationPosition,
        market: MarketEvent,
        trailing_stop: TrailingStop | None,
    ) -> tuple[OrderIntent, float] | None:
        if not position.is_open:
            return None
        stop_pct = self.config.risk.stop_loss_pct
        take_pct = self.config.risk.take_profit_pct
        stop_price = position.entry_price * (1 - stop_pct) if stop_pct is not None else None
        take_price = position.entry_price * (1 + take_pct) if take_pct is not None else None
        if stop_price is not None and market.low <= stop_price:
            return self._protective_order(
                position, market, "stop_loss", min(market.open, stop_price)
            )
        if take_price is not None and market.high >= take_price:
            return self._protective_order(position, market, "take_profit", take_price)
        if trailing_stop is not None:
            trailing_stop.update(market.high)
            trailing_price = trailing_stop.current_stop
            if trailing_price is not None and market.low <= trailing_price:
                return self._protective_order(
                    position, market, "trailing_stop", min(market.open, trailing_price)
                )
        return None

    def _protective_order(
        self,
        position: SimulationPosition,
        market: MarketEvent,
        reason: str,
        trigger_price: float,
    ) -> tuple[OrderIntent, float]:
        return (
            self._new_order(
                created_index=market.index,
                execute_index=market.index,
                side=SimulationSide.SELL,
                reason=reason,
                quantity=position.quantity,
                order_type=SimulationOrderType.MARKET,
            ),
            trigger_price,
        )

    def _sync_trailing_stop(
        self,
        trailing_stop: TrailingStop | None,
        position: SimulationPosition,
    ) -> TrailingStop | None:
        if not position.is_open:
            return None
        if trailing_stop is not None:
            return trailing_stop
        stop_pct = self.config.risk.trailing_stop_pct
        if stop_pct is None:
            return None
        return TrailingStop(
            side=TrailingSide.LONG,
            entry_price=position.entry_price,
            ratchet_pct=stop_pct,
            activation_pct=self.config.risk.trailing_activation_pct,
        )

    def _new_order(
        self,
        *,
        created_index: int,
        execute_index: int,
        side: SimulationSide,
        reason: str,
        quantity: float | None = None,
        cash_fraction: float | None = None,
        order_type: SimulationOrderType = SimulationOrderType.MARKET,
        limit_price: float | None = None,
        stop_price: float | None = None,
        post_only: bool = False,
        time_in_force: SimulationTimeInForce = SimulationTimeInForce.IOC,
        expires_index: int | None = None,
    ) -> OrderIntent:
        self._order_sequence += 1
        return OrderIntent(
            order_id=f"sim-{self._order_sequence}",
            created_index=created_index,
            execute_index=execute_index,
            side=side,
            reason=reason,
            quantity=quantity,
            cash_fraction=cash_fraction,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            post_only=post_only,
            time_in_force=time_in_force,
            expires_index=expires_index,
        )

    @staticmethod
    def _record_execution(
        execution: ExecutionResult,
        market: MarketEvent,
        cash: float,
        position: SimulationPosition,
        trades: list[SimulationTrade],
        fills: list[FillEvent],
        events: list[SimulationEvent],
    ) -> float:
        cash += execution.cash_delta
        EventDrivenSimulationEngine._apply_fill(position, execution, market, trades)
        fills.append(execution.fill)
        events.append(execution.fill)
        return cash

    @staticmethod
    def _record_terminal(
        order: OrderIntent,
        market: MarketEvent,
        status: SimulationOrderStatus,
        reason: str,
        fills: list[FillEvent],
        events: list[SimulationEvent],
        remaining: float | None = None,
    ) -> None:
        quantity = (order.quantity or 0.0) if remaining is None else remaining
        fill = FillEvent(
            order_id=order.order_id,
            index=market.index,
            time=market.time,
            side=order.side,
            requested_quantity=quantity,
            filled_quantity=0.0,
            price=market.open,
            fee=0.0,
            remaining_quantity=quantity,
            status=status,
            reason=reason,
            order_type=order.order_type,
        )
        fills.append(fill)
        events.append(fill)

    @staticmethod
    def _max_drawdown(equity_curve: Sequence[float]) -> float:
        peak = 0.0
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
        return max_drawdown

    @staticmethod
    def _apply_fill(
        position: SimulationPosition,
        execution: ExecutionResult,
        market: MarketEvent,
        trades: list[SimulationTrade],
    ) -> None:
        fill = execution.fill
        if fill.filled_quantity <= 1e-12:
            return
        if fill.side == SimulationSide.BUY:
            if position.is_open:
                total_quantity = position.quantity + fill.filled_quantity
                position.entry_price = (
                    position.entry_price * position.quantity + fill.price * fill.filled_quantity
                ) / total_quantity
                position.quantity = total_quantity
                position.entry_quantity += fill.filled_quantity
                position.entry_fee += fill.fee
                return
            position.quantity = fill.filled_quantity
            position.entry_quantity = fill.filled_quantity
            position.entry_price = fill.price
            position.entry_index = market.index
            position.entry_time = market.time
            position.entry_fee = fill.fee
            position.exit_quantity = 0.0
            position.exit_notional = 0.0
            position.exit_fee = 0.0
            position.exit_reason = None
            return

        position.quantity = max(0.0, position.quantity - fill.filled_quantity)
        position.exit_quantity += fill.filled_quantity
        position.exit_notional += fill.filled_quantity * fill.price
        position.exit_fee += fill.fee
        if position.exit_reason is None:
            position.exit_reason = fill.reason
        elif position.exit_reason != fill.reason:
            position.exit_reason = "mixed"
        if position.is_open:
            return
        exit_price = position.exit_notional / position.exit_quantity
        gross_pnl = (exit_price - position.entry_price) * position.entry_quantity
        fees = position.entry_fee + position.exit_fee
        trades.append(
            SimulationTrade(
                entry_index=position.entry_index,
                exit_index=market.index,
                entry_time=position.entry_time,
                exit_time=market.time,
                quantity=position.entry_quantity,
                entry_price=position.entry_price,
                exit_price=exit_price,
                gross_pnl=gross_pnl,
                fees=fees,
                net_pnl=gross_pnl - fees,
                exit_reason=position.exit_reason or fill.reason,
            )
        )
        position.quantity = 0.0
        position.entry_quantity = 0.0
        position.entry_price = 0.0
        position.entry_index = -1
        position.entry_time = None
        position.entry_fee = 0.0
        position.exit_quantity = 0.0
        position.exit_notional = 0.0
        position.exit_fee = 0.0
        position.exit_reason = None


__all__ = ["AccountSnapshot", "EventDrivenSimulationEngine", "SignalModel"]
