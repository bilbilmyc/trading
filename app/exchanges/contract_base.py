"""
统一合约交易所接口。

Binance USD-M、Bitget USDT Futures、OKX Swap 都继承这个抽象类。
API 层只依赖这里定义的方法，不直接关心每家交易所的 REST 参数差异。
"""

from abc import abstractmethod
from typing import Any

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
    """永续/期货交易所适配器基类。"""

    @abstractmethod
    async def get_contract_markets(self, quote_asset: str = "USDT") -> list[ContractMarket]:
        """从公开接口列出可交易合约。"""

        pass

    @abstractmethod
    async def get_fee_rate(self, symbol: str) -> FeeRate:
        """获取单个合约的 maker/taker 手续费率。"""

        pass

    @abstractmethod
    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> dict[str, Any]:
        """交易前设置合约杠杆。"""

        pass

    @abstractmethod
    async def place_contract_order(self, request: ContractOrderRequest) -> dict[str, Any]:
        """使用统一请求模型提交合约订单。"""

        pass

    @abstractmethod
    async def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """获取当前合约持仓。

        返回值保留交易所原始字段，但至少要让 PositionSync 能解析：
        ``symbol``、``quantity``、``avg_price``/``entryPrice``、
        ``current_price``/``markPrice``。
        """

        pass

    async def estimate_order_cost(
        self,
        symbol: str,
        quantity: float,
        price: float,
        liquidity: LiquidityType = LiquidityType.MAKER,
    ) -> CostEstimate:
        """根据名义价值和当前费率估算手续费。"""

        fee_rate = await self.get_fee_rate(symbol)
        notional = quantity * price
        rate = fee_rate.maker if liquidity == LiquidityType.MAKER else fee_rate.taker
        notes = [
            "这是本地手续费估算，不代表最终成交成本。",
            "估算未包含滑点、点差、资金费率、借贷成本和强平风险。",
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
        """把开多/平多/开空/平空翻译成 side、持仓方向和 reduce-only。"""

        mapping = {
            ContractOrderIntent.OPEN_LONG: ("buy", PositionSide.LONG, False),
            ContractOrderIntent.CLOSE_LONG: ("sell", PositionSide.LONG, True),
            ContractOrderIntent.OPEN_SHORT: ("sell", PositionSide.SHORT, False),
            ContractOrderIntent.CLOSE_SHORT: ("buy", PositionSide.SHORT, True),
        }
        return mapping[intent]
