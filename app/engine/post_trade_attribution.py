"""Confirmed-fill attribution for post-trade risk controls.

This module turns exchange-reported cumulative fills into one-time fill deltas,
updates the local position book, and feeds realized PnL back into RiskManager.
It deliberately never infers a fill from an accepted/submitted order alone.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.engine.pipeline_types import TradeReceipt
from app.engine.position_manager import PositionManager
from app.engine.risk_manager import RiskManager
from app.models.order import Order

if TYPE_CHECKING:
    from app.core.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class PostTradeAttribution:
    """One newly attributed confirmed-fill delta."""

    attribution_id: str
    exchange: str
    symbol: str
    side: str
    filled_quantity: float
    fill_price: float
    realized_pnl: float
    daily_pnl: float
    consecutive_losses: int
    drawdown: float

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "attribution_id": self.attribution_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "side": self.side,
            "filled_quantity": self.filled_quantity,
            "fill_price": self.fill_price,
            "realized_pnl": self.realized_pnl,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "drawdown": self.drawdown,
        }


class PostTradeRiskAttributor:
    """Apply confirmed fill deltas exactly once and update risk state.

    Exchanges generally report cumulative filled quantity and a cumulative
    average fill price.  The durable checkpoint stores both values so a later
    partial-fill update can be converted to the price and quantity of only its
    newly filled portion.
    """

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        store: SQLiteStore | None = None,
    ) -> None:
        self._position_manager = position_manager
        self._risk_manager = risk_manager
        self._store = store
        self._seen: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def record_order(self, order: Order) -> PostTradeAttribution | None:
        """Attribute the confirmed cumulative fill carried by an order sync."""

        attribution_id = order.client_order_id or order.order_id
        return await self.record_cumulative_fill(
            attribution_id=attribution_id,
            exchange=order.exchange,
            symbol=order.symbol,
            side=(order.side.value if hasattr(order.side, "value") else str(order.side)),
            cumulative_quantity=order.filled_quantity,
            cumulative_avg_price=order.avg_fill_price,
        )

    async def record_receipt(self, receipt: TradeReceipt) -> PostTradeAttribution | None:
        """Attribute a pipeline receipt when the venue supplied an order id."""

        if not receipt.order_id:
            return None
        return await self.record_cumulative_fill(
            attribution_id=f"{receipt.exchange}:{receipt.order_id}",
            exchange=receipt.exchange,
            symbol=receipt.symbol,
            side=receipt.side,
            cumulative_quantity=receipt.filled_quantity,
            cumulative_avg_price=receipt.avg_fill_price or receipt.price,
        )

    async def record_cumulative_fill(
        self,
        *,
        attribution_id: str | None,
        exchange: str,
        symbol: str,
        side: str,
        cumulative_quantity: float,
        cumulative_avg_price: float | None,
    ) -> PostTradeAttribution | None:
        """Apply only the unprocessed portion of a confirmed cumulative fill."""

        if not attribution_id or not self._valid_fill(cumulative_quantity, cumulative_avg_price):
            return None
        normalized_side = side.lower()
        if normalized_side not in {"buy", "sell"}:
            return None

        quantity = float(cumulative_quantity)
        average_price = float(cumulative_avg_price)
        async with self._lock:
            if self._store is not None:
                prior_quantity, prior_average = self._store.advance_post_trade_attribution(
                    attribution_id=attribution_id,
                    cumulative_quantity=quantity,
                    cumulative_avg_price=average_price,
                )
            else:
                prior_quantity, prior_average = self._seen.get(attribution_id, (0.0, 0.0))
                if quantity <= prior_quantity + 1e-12:
                    return None
                self._seen[attribution_id] = (quantity, average_price)

            delta_quantity = quantity - prior_quantity
            if delta_quantity <= 1e-12:
                return None
            delta_value = (quantity * average_price) - (prior_quantity * prior_average)
            fill_price = delta_value / delta_quantity
            if not math.isfinite(fill_price) or fill_price <= 0:
                return None

            realized_pnl = await self._position_manager.update_position(
                exchange=exchange,
                symbol=symbol,
                quantity=delta_quantity,
                price=fill_price,
                side=normalized_side,
            )
            await self._risk_manager.record_realized_pnl(realized_pnl)
            return PostTradeAttribution(
                attribution_id=attribution_id,
                exchange=exchange,
                symbol=symbol,
                side=normalized_side,
                filled_quantity=delta_quantity,
                fill_price=fill_price,
                realized_pnl=realized_pnl,
                daily_pnl=self._risk_manager.daily_pnl,
                consecutive_losses=self._risk_manager.consecutive_losses,
                drawdown=self._risk_manager.current_drawdown,
            )

    @staticmethod
    def _valid_fill(quantity: float, average_price: float | None) -> bool:
        try:
            return (
                average_price is not None
                and math.isfinite(float(quantity))
                and math.isfinite(float(average_price))
                and float(quantity) > 0
                and float(average_price) > 0
            )
        except (TypeError, ValueError):
            return False


__all__ = ["PostTradeAttribution", "PostTradeRiskAttributor"]
