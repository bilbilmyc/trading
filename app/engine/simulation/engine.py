"""Generic, deterministic event-driven simulation engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.engine.simulation.broker import DeterministicBarBroker, ExecutionResult
from app.engine.simulation.events import (
    EquityEvent,
    FillEvent,
    MarketEvent,
    OrderIntent,
    SignalEvent,
    SimulationEvent,
    SimulationSide,
)
from app.engine.simulation.models import (
    SimulationConfig,
    SimulationPosition,
    SimulationResult,
    SimulationTrade,
)


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    position_quantity: float
    entry_price: float
    equity: float


SignalModel = Callable[[Sequence[MarketEvent], int, AccountSnapshot], SignalEvent | None]


class EventDrivenSimulationEngine:
    """Run a long-only strategy through market, signal, order and fill events.

    Signals are evaluated after a bar closes. Market orders created from those
    signals execute on the following bar's open, preventing same-bar lookahead.
    """

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.broker = DeterministicBarBroker(config.execution)
        self._order_sequence = 0

    def run(self, markets: Sequence[MarketEvent], signal_model: SignalModel) -> SimulationResult:
        self._order_sequence = 0
        cash = self.config.initial_capital
        position = SimulationPosition()
        pending_order: OrderIntent | None = None
        equity_curve: list[float] = []
        trades: list[SimulationTrade] = []
        fills: list[FillEvent] = []
        events: list[SimulationEvent] = []

        for index, market in enumerate(markets):
            if market.index != index:
                raise ValueError("market indices must be contiguous and start at zero")
            events.append(market)

            if pending_order is not None and pending_order.execute_index == index:
                execution = self.broker.execute(
                    pending_order,
                    market,
                    cash=cash,
                    position_quantity=position.quantity,
                )
                cash += execution.cash_delta
                self._apply_fill(position, execution, market, trades)
                fills.append(execution.fill)
                events.append(execution.fill)
                pending_order = None

            risk_order = self._risk_order(position, market)
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
                cash += execution.cash_delta
                self._apply_fill(position, execution, market, trades)
                fills.append(execution.fill)
                events.append(execution.fill)

            equity = cash + position.quantity * market.close
            equity_curve.append(equity)
            equity_event = EquityEvent(
                index=index,
                time=market.time,
                cash=cash,
                position_quantity=position.quantity,
                mark_price=market.close,
                equity=equity,
            )
            events.append(equity_event)

            if index == len(markets) - 1:
                continue
            snapshot = AccountSnapshot(
                cash=cash,
                position_quantity=position.quantity,
                entry_price=position.entry_price,
                equity=equity,
            )
            signal = signal_model(markets, index, snapshot)
            if signal is None:
                continue
            if signal.index != market.index:
                raise ValueError("signal index must match the market event being evaluated")
            events.append(signal)
            pending_order = self._order_from_signal(signal, position, index + 1)
            if pending_order is not None:
                events.append(pending_order)

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
            cash += execution.cash_delta
            self._apply_fill(position, execution, market, trades)
            fills.append(execution.fill)
            events.append(execution.fill)
            if equity_curve:
                equity_curve[-1] = cash

        max_drawdown = self._max_drawdown(equity_curve)
        return SimulationResult(
            initial_capital=self.config.initial_capital,
            final_equity=cash,
            equity_curve=equity_curve,
            trades=trades,
            fills=fills,
            events=events,
            max_drawdown=max_drawdown,
        )

    def _order_from_signal(
        self,
        signal: SignalEvent,
        position: SimulationPosition,
        execute_index: int,
    ) -> OrderIntent | None:
        if signal.action == "enter" and not position.is_open:
            return self._new_order(
                created_index=signal.index,
                execute_index=execute_index,
                side=SimulationSide.BUY,
                reason=signal.reason,
                cash_fraction=self.config.position_size_pct,
            )
        if signal.action == "exit" and position.is_open:
            return self._new_order(
                created_index=signal.index,
                execute_index=execute_index,
                side=SimulationSide.SELL,
                reason=signal.reason,
                quantity=position.quantity,
            )
        return None

    def _risk_order(
        self,
        position: SimulationPosition,
        market: MarketEvent,
    ) -> tuple[OrderIntent, float] | None:
        if not position.is_open:
            return None
        stop_pct = self.config.risk.stop_loss_pct
        take_pct = self.config.risk.take_profit_pct
        stop_price = position.entry_price * (1 - stop_pct) if stop_pct is not None else None
        take_price = position.entry_price * (1 + take_pct) if take_pct is not None else None

        if stop_price is not None and market.low <= stop_price:
            trigger_price = min(market.open, stop_price)
            return (
                self._new_order(
                    created_index=market.index,
                    execute_index=market.index,
                    side=SimulationSide.SELL,
                    reason="stop_loss",
                    quantity=position.quantity,
                ),
                trigger_price,
            )
        if take_price is not None and market.high >= take_price:
            return (
                self._new_order(
                    created_index=market.index,
                    execute_index=market.index,
                    side=SimulationSide.SELL,
                    reason="take_profit",
                    quantity=position.quantity,
                ),
                take_price,
            )
        return None

    def _new_order(
        self,
        *,
        created_index: int,
        execute_index: int,
        side: SimulationSide,
        reason: str,
        quantity: float | None = None,
        cash_fraction: float | None = None,
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
        )

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
