"""OrderTracker adapter — wraps OrderSync as the OrderTracker port."""

from __future__ import annotations

from app.engine.order_sync import OrderSync
from app.engine.pipeline_types import TradeReceipt


class OrderTrackerAdapter:
    """Adapts OrderSync to the OrderTracker port Protocol."""

    def __init__(self, order_sync: OrderSync) -> None:
        self._order_sync = order_sync

    def track(self, receipt: TradeReceipt) -> None:
        """Register the placed order locally for later reconciliation.

        The OrderTracker Protocol accepts any object — OrderSync just stores
        it. We adapt TradeReceipt into the existing Order model shape.
        """
        from app.models.order import Order, OrderSide, OrderType

        side = OrderSide.BUY if receipt.side.lower() == "buy" else OrderSide.SELL
        order_type = OrderType.MARKET if receipt.order_type == "market" else OrderType.LIMIT
        order = Order(
            symbol=receipt.symbol,
            exchange=receipt.exchange,
            side=side,
            order_type=order_type,
            quantity=receipt.quantity,
            price=receipt.price,
            order_id=receipt.order_id,
            filled_quantity=receipt.filled_quantity,
            avg_fill_price=receipt.avg_fill_price,
        )
        self._order_sync.track(order)


__all__ = ["OrderTrackerAdapter"]
