"""
Unified contract exchange interface.
"""

from abc import abstractmethod
from typing import Any, Dict, List, Optional

from app.exchanges.base import ExchangeBase
from app.models.contract import (
    ContractOrderIntent,
    ContractOrderRequest,
    CostEstimate,
    FeeRate,
    LiquidityType,
    MarginMode,
    PositionSide,
)
from app.models.market import ContractMarket


class ContractExchangeBase(ExchangeBase):
    """Base class for perpetual/futures exchange adapters."""

    @abstractmethod
    async def get_contract_markets(self, quote_asset: str = "USDT") -> List[ContractMarket]:
        """List tradable perpetual/futures contracts from public exchange metadata."""

        pass

    @abstractmethod
    async def get_fee_rate(self, symbol: str) -> FeeRate:
        """Get maker/taker fee rates for one contract symbol."""

        pass

    @abstractmethod
    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> Dict[str, Any]:
        """Set contract leverage before trading."""

        pass

    @abstractmethod
    async def place_contract_order(self, request: ContractOrderRequest) -> Dict[str, Any]:
        """Place a contract order using the unified contract request model."""

        pass

    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current positions for a symbol (or all symbols if None).

        Returns a list of raw position dicts that PositionSync can parse.
        Each dict should include keys: ``symbol``, ``quantity`` (signed: +long, -short),
        ``avg_price`` or ``entryPrice``, ``current_price`` or ``markPrice``.
        """

        pass

    async def estimate_order_cost(
        self,
        symbol: str,
        quantity: float,
        price: float,
        liquidity: LiquidityType = LiquidityType.MAKER,
    ) -> CostEstimate:
        """Estimate fee cost from notional and current account fee rates."""

        fee_rate = await self.get_fee_rate(symbol)
        notional = quantity * price
        rate = fee_rate.maker if liquidity == LiquidityType.MAKER else fee_rate.taker
        notes = [
            "This is a local fee estimate only.",
            "It excludes slippage, spread, funding rate, borrow costs, and liquidation risk.",
        ]
        return CostEstimate(
            exchange=self.name,
            symbol=symbol,
            notional=notional,
            liquidity=liquidity,
            fee_rate=rate,
            estimated_fee=notional * abs(rate),
            raw_fee=fee_rate,
            notes=notes,
        )

    def resolve_order_intent(self, intent: ContractOrderIntent) -> tuple[str, PositionSide, bool]:
        """Map a high-level intent into side, position side, and reduce-only."""

        mapping = {
            ContractOrderIntent.OPEN_LONG: ("buy", PositionSide.LONG, False),
            ContractOrderIntent.CLOSE_LONG: ("sell", PositionSide.LONG, True),
            ContractOrderIntent.OPEN_SHORT: ("sell", PositionSide.SHORT, False),
            ContractOrderIntent.CLOSE_SHORT: ("buy", PositionSide.SHORT, True),
        }
        return mapping[intent]
