"""
核心数据模型模块

定义交易系统使用的统一数据模型，包括订单、持仓、余额等。
使用 Pydantic v2 进行数据验证和序列化优化。
"""

from app.models.balance import Balance
from app.models.contract import (
    ContractOrderIntent,
    ContractOrderRequest,
    CostEstimate,
    FeeRate,
    LiquidityType,
    MarginMode,
    MarketType,
    PositionSide,
)
from app.models.market import Candlestick, ContractMarket, Ticker, Trade
from app.models.order import Order, OrderSide, OrderStatus, OrderType
from app.models.position import Position

__all__ = [
    # Order
    'Order',
    'OrderSide',
    'OrderType',
    'OrderStatus',
    # Position
    'Position',
    # Balance
    'Balance',
    # Market
    'Ticker',
    'Candlestick',
    'Trade',
    'ContractMarket',
    # Contract
    'MarketType',
    'MarginMode',
    'PositionSide',
    'LiquidityType',
    'ContractOrderIntent',
    'FeeRate',
    'ContractOrderRequest',
    'CostEstimate',
]
