"""LiveOrderPipeline — orchestrates one Signal end-to-end through six ports.

The interface is one method: `execute(signal) -> Result[TradeReceipt, TradeError]`.
All cross-cutting concerns (gating, filtering, risk, recording, observing) go
through injected ports; the only direct dependency is the exchange (for ticker
price fetch and order placement).

Ports:
    TradingGuard — kill switch / live-trading flag
    SignalFilter (sequence) — async veto chain
    RiskGate — position/value/drawdown/rate/daily-loss check
    OrderTracker — local order registry
    PositionRecorder — local position update
    Observer — alert + audit event emission

Returns:
    Ok(TradeReceipt) when the order was placed and recorded.
    Err(TradeError) at the first veto or unrecoverable failure.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.core.result import Err, Ok
from app.engine.pipeline_types import (
    FilterContext,
    Observer,
    OrderTracker,
    PositionRecorder,
    RiskGate,
    SignalFilter,
    TradeError,
    TradeEvent,
    TradeReceipt,
    TradingGuard,
)
from app.exchanges.base import ExchangeBase
from app.strategies.base import Signal


class LiveOrderPipeline:
    def __init__(
        self,
        exchange: ExchangeBase,
        trading_guard: TradingGuard,
        risk_gate: RiskGate,
        order_tracker: OrderTracker,
        position_recorder: PositionRecorder,
        observer: Observer,
        semaphore: asyncio.Semaphore,
        signal_filters: Sequence[SignalFilter] = (),
    ) -> None:
        self._exchange = exchange
        self._trading_guard = trading_guard
        self._risk_gate = risk_gate
        self._order_tracker = order_tracker
        self._position_recorder = position_recorder
        self._observer = observer
        self._semaphore = semaphore
        self._signal_filters: Sequence[SignalFilter] = tuple(signal_filters)

    async def execute(self, signal: Signal):
        # 1. Trading guard
        if not await self._trading_guard.is_open():
            self._observer.record(
                TradeEvent(
                    kind="gate_blocked",
                    payload={"symbol": signal.symbol, "action": signal.action.value},
                )
            )
            return Err(
                TradeError(stage="guard", reason="trading is disabled")
            )

        # 2. Signal filters (async veto chain)
        ctx: FilterContext = {"exchange": getattr(self._exchange, "name", "")}
        for f in self._signal_filters:
            try:
                if not await f.check(signal, ctx):
                    name = getattr(f, "__class__", type(f)).__name__
                    self._observer.record(
                        TradeEvent(
                            kind="signal_filtered",
                            payload={"filter": name, "symbol": signal.symbol},
                        )
                    )
                    return Err(
                        TradeError(stage="filter", reason=f"rejected by {name}")
                    )
            except Exception:
                # Filter exception = pass-through (per existing engine semantics).
                continue

        # 3. Concurrency control + price + risk + place
        async with self._semaphore:
            price = signal.price if (signal.price and signal.price > 0) else None
            if price is None:
                try:
                    ticker = await self._exchange.get_ticker(signal.symbol)
                    price = float(ticker.get("last_price", 0) or 0)
                except Exception as exc:
                    self._observer.record(
                        TradeEvent(
                            kind="order_failed",
                            payload={"stage": "price", "error": str(exc)},
                        )
                    )
                    return Err(
                        TradeError(stage="place", reason=f"price fetch failed: {exc}")
                    )

            decision = await self._risk_gate.check(signal, price)
            if not decision.allowed:
                self._observer.record(
                    TradeEvent(
                        kind="risk_rejected",
                        payload={"reason": decision.reason, "symbol": signal.symbol},
                    )
                )
                return Err(
                    TradeError(stage="risk", reason=decision.reason)
                )

            quantity = signal.quantity or 0.001
            sl = signal.stop_loss if signal.stop_loss is not None else decision.stop_loss
            tp = signal.take_profit if signal.take_profit is not None else decision.take_profit

            try:
                raw = await self._exchange.place_order(
                    symbol=signal.symbol,
                    side=signal.action.value,
                    order_type=signal.order_type,
                    quantity=quantity,
                    price=signal.price,
                    stop_loss=sl,
                    take_profit=tp,
                )
            except Exception as exc:
                self._observer.record(
                    TradeEvent(
                        kind="order_failed",
                        payload={"symbol": signal.symbol, "error": str(exc)},
                    )
                )
                return Err(
                    TradeError(stage="place", reason=str(exc))
                )

            receipt = TradeReceipt(
                order_id=str(raw.get("order_id") or raw.get("orderId") or ""),
                exchange=getattr(self._exchange, "name", ""),
                symbol=signal.symbol,
                side=signal.action.value,
                order_type=signal.order_type,
                quantity=quantity,
                price=signal.price,
                filled_quantity=float(raw.get("filled_quantity", raw.get("executedQty", quantity)) or quantity),
                avg_fill_price=raw.get("avg_fill_price") or raw.get("avgPrice") or price,
            )

            self._order_tracker.track(receipt)
            await self._position_recorder.record(receipt)

            self._observer.record(
                TradeEvent(
                    kind="order_placed",
                    payload={
                        "order_id": receipt.order_id,
                        "symbol": receipt.symbol,
                        "side": receipt.side,
                        "quantity": receipt.quantity,
                        "price": receipt.price,
                    },
                )
            )
            return Ok(receipt)


__all__ = ["LiveOrderPipeline"]
