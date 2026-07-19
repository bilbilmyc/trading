"""PositionRecorder adapter — wraps PositionManager as the PositionRecorder port."""

from __future__ import annotations

from app.engine.pipeline_types import TradeReceipt
from app.engine.position_manager import PositionManager
from app.engine.post_trade_attribution import PostTradeRiskAttributor


class PositionRecorderAdapter:
    """Adapts PositionManager.update_position to the PositionRecorder port."""

    def __init__(
        self,
        position_manager: PositionManager,
        post_trade_attributor: PostTradeRiskAttributor | None = None,
    ) -> None:
        self._position_manager = position_manager
        self._post_trade_attributor = post_trade_attributor

    async def record(self, receipt: TradeReceipt) -> None:
        if self._post_trade_attributor is not None:
            attribution = await self._post_trade_attributor.record_receipt(receipt)
            if attribution is not None:
                return
        await self._position_manager.update_position(
            exchange=receipt.exchange,
            symbol=receipt.symbol,
            quantity=receipt.filled_quantity,
            price=receipt.avg_fill_price or receipt.price or 0.0,
            side=receipt.side,
        )


__all__ = ["PositionRecorderAdapter"]
