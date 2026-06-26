"""PositionRecorder adapter — wraps PositionManager as the PositionRecorder port."""

from __future__ import annotations

from app.engine.pipeline_types import TradeReceipt
from app.engine.position_manager import PositionManager


class PositionRecorderAdapter:
    """Adapts PositionManager.update_position to the PositionRecorder port."""

    def __init__(self, position_manager: PositionManager) -> None:
        self._position_manager = position_manager

    async def record(self, receipt: TradeReceipt) -> None:
        await self._position_manager.update_position(
            exchange=receipt.exchange,
            symbol=receipt.symbol,
            quantity=receipt.quantity,
            price=receipt.price or 0.0,
            side=receipt.side,
        )


__all__ = ["PositionRecorderAdapter"]