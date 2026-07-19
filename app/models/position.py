"""
持仓数据模型
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Position(BaseModel):
    """持仓数据模型

    Attributes:
        symbol: 交易对
        exchange: 交易所名称
        quantity: 持仓数量 (正数为多头，负数为空头)
        avg_entry_price: 平均入场价
        current_price: 当前价格
        unrealized_pnl: 未实现盈亏
        realized_pnl: 已实现盈亏
        created_at: 建仓时间
        updated_at: 更新时间
    """

    symbol: str = Field(..., min_length=1, description="交易对")
    exchange: str = Field(..., min_length=1, description="交易所名称")
    quantity: float = Field(0.0, description="持仓数量")
    avg_entry_price: float = Field(0.0, ge=0, description="平均入场价")
    current_price: float = Field(0.0, ge=0, description="当前价格")
    unrealized_pnl: float = Field(0.0, description="未实现盈亏")
    realized_pnl: float = Field(0.0, description="已实现盈亏")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="建仓时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")

    @property
    def market_value(self) -> float:
        """持仓市值"""
        return abs(self.quantity) * self.current_price

    @property
    def cost_basis(self) -> float:
        """持仓成本"""
        return abs(self.quantity) * self.avg_entry_price

    @property
    def side(self) -> str:
        """持仓方向"""
        if self.quantity > 0:
            return "long"
        elif self.quantity < 0:
            return "short"
        return "flat"

    @property
    def pnl_percentage(self) -> float:
        """盈亏百分比"""
        if self.cost_basis == 0:
            return 0.0
        return self.unrealized_pnl / self.cost_basis * 100

    def update_price(self, price: float):
        """更新当前价格并计算未实现盈亏"""
        self.current_price = price
        self.updated_at = datetime.utcnow()

        if self.quantity != 0:
            if self.quantity > 0:
                # 多头：(当前价 - 均价) * 数量
                self.unrealized_pnl = (price - self.avg_entry_price) * self.quantity
            else:
                # 空头：(均价 - 当前价) * |数量|
                self.unrealized_pnl = (self.avg_entry_price - price) * abs(self.quantity)
        else:
            self.unrealized_pnl = 0.0

    def update_position(self, quantity: float, price: float) -> float:
        """Apply one fill and return the newly realized PnL.

        Realized PnL is calculated from the actual fill price and the prior
        average entry price, not from a potentially stale mark-to-market value.
        """
        old_quantity = self.quantity
        new_quantity = old_quantity + quantity
        realized_pnl = 0.0

        if (
            old_quantity == 0
            or (old_quantity > 0 and quantity > 0)
            or (old_quantity < 0 and quantity < 0)
        ):
            old_cost = abs(old_quantity) * self.avg_entry_price
            new_cost = old_cost + abs(quantity) * price
            self.quantity = new_quantity
            self.avg_entry_price = new_cost / abs(new_quantity) if new_quantity else 0.0
        else:
            closed_quantity = min(abs(quantity), abs(old_quantity))
            if old_quantity > 0:
                realized_pnl = (price - self.avg_entry_price) * closed_quantity
            else:
                realized_pnl = (self.avg_entry_price - price) * closed_quantity
            self.realized_pnl += realized_pnl
            self.quantity = new_quantity
            if new_quantity == 0:
                self.avg_entry_price = 0.0
            elif (old_quantity > 0 > new_quantity) or (old_quantity < 0 < new_quantity):
                self.avg_entry_price = price

        self.current_price = price
        self.update_price(price)
        return realized_pnl

    def is_flat(self) -> bool:
        """是否空仓"""
        return self.quantity == 0

    def is_long(self) -> bool:
        """是否多头"""
        return self.quantity > 0

    def is_short(self) -> bool:
        """是否空头"""
        return self.quantity < 0
