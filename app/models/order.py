"""
订单数据模型

使用 Pydantic v2 进行高效的数据验证和序列化。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """订单方向"""
    BUY = 'buy'
    SELL = 'sell'


class OrderType(str, Enum):
    """订单类型"""
    MARKET = 'market'
    LIMIT = 'limit'
    STOP_LIMIT = 'stop_limit'


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = 'pending'
    PARTIALLY_FILLED = 'partially_filled'
    FILLED = 'filled'
    CANCELLED = 'cancelled'
    REJECTED = 'rejected'
    EXPIRED = 'expired'


class Order(BaseModel):
    """订单数据模型
    
    Attributes:
        symbol: 交易对 (如 BTC-USDT)
        exchange: 交易所名称
        side: 买卖方向
        order_type: 订单类型
        quantity: 交易数量
        price: 委托价格 (限价单必需)
        stop_price: 止损触发价 (止损单用)
        order_id: 交易所订单 ID
        client_order_id: 客户端订单 ID
        status: 订单状态
        filled_quantity: 已成交数量
        avg_fill_price: 平均成交价
        created_at: 创建时间
        updated_at: 更新时间
    """

    symbol: str = Field(..., min_length=1, description="交易对")
    exchange: str = Field(..., min_length=1, description="交易所名称")
    side: OrderSide = Field(..., description="买卖方向")
    order_type: OrderType = Field(..., description="订单类型")
    quantity: float = Field(..., gt=0, description="交易数量")
    price: float | None = Field(None, gt=0, description="委托价格")
    stop_price: float | None = Field(None, gt=0, description="止损触发价")

    # 订单标识
    order_id: str | None = Field(None, description="交易所订单 ID")
    client_order_id: str | None = Field(None, description="客户端订单 ID")

    # 状态跟踪
    status: OrderStatus = Field(OrderStatus.PENDING, description="订单状态")
    filled_quantity: float = Field(0.0, ge=0, description="已成交数量")
    avg_fill_price: float | None = Field(None, ge=0, description="平均成交价")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    @property
    def remaining_quantity(self) -> float:
        """剩余未成交数量"""
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        """订单是否仍然活跃"""
        return self.status in [OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED]

    @property
    def is_filled(self) -> bool:
        """订单是否完全成交"""
        return self.status == OrderStatus.FILLED

    @property
    def fill_rate(self) -> float:
        """成交率"""
        if self.quantity == 0:
            return 0.0
        return self.filled_quantity / self.quantity

    def update_fill(self, filled_qty: float, fill_price: float):
        """更新成交信息"""
        self.filled_quantity += filled_qty
        self.updated_at = datetime.utcnow()

        # 更新平均成交价
        if self.avg_fill_price is None:
            self.avg_fill_price = fill_price
        else:
            total_value = (self.avg_fill_price * (self.filled_quantity - filled_qty)) + (fill_price * filled_qty)
            self.avg_fill_price = total_value / self.filled_quantity

        # 更新状态
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIALLY_FILLED

    def mark_cancelled(self):
        """标记为已取消"""
        self.status = OrderStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def mark_rejected(self):
        """标记为已拒绝"""
        self.status = OrderStatus.REJECTED
        self.updated_at = datetime.utcnow()
