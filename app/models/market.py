"""
市场数据模型

包括行情、K 线、成交记录等。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Ticker(BaseModel):
    """实时行情数据
    
    Attributes:
        symbol: 交易对
        exchange: 交易所名称
        last_price: 最新价
        bid_price: 买一价
        ask_price: 卖一价
        high_24h: 24 小时最高价
        low_24h: 24 小时最低价
        volume_24h: 24 小时成交量
        quote_volume_24h: 24 小时成交额
        price_change_24h: 24 小时涨跌额
        price_change_pct_24h: 24 小时涨跌幅
        timestamp: 数据时间戳
    """

    symbol: str = Field(..., min_length=1, description="交易对")
    exchange: str = Field(..., min_length=1, description="交易所名称")
    last_price: float = Field(0.0, ge=0, description="最新价")
    bid_price: float | None = Field(None, ge=0, description="买一价")
    ask_price: float | None = Field(None, ge=0, description="卖一价")
    high_24h: float | None = Field(None, ge=0, description="24 小时最高价")
    low_24h: float | None = Field(None, ge=0, description="24 小时最低价")
    volume_24h: float | None = Field(None, ge=0, description="24 小时成交量")
    quote_volume_24h: float | None = Field(None, ge=0, description="24 小时成交额")
    price_change_24h: float | None = Field(None, description="24 小时涨跌额")
    price_change_pct_24h: float | None = Field(None, description="24 小时涨跌幅")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="数据时间戳")

    @property
    def mid_price(self) -> float | None:
        """中间价 (买一和卖一的平均值)"""
        if self.bid_price is not None and self.ask_price is not None:
            return (self.bid_price + self.ask_price) / 2
        return self.last_price

    @property
    def spread(self) -> float | None:
        """买卖价差"""
        if self.bid_price is not None and self.ask_price is not None:
            return self.ask_price - self.bid_price
        return None


class Candlestick(BaseModel):
    """K 线数据
    
    Attributes:
        symbol: 交易对
        exchange: 交易所名称
        interval: K 线周期 (如 1m, 5m, 1h, 1d)
        open_time: 开盘时间
        open: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价
        volume: 成交量
        quote_volume: 成交额
        trade_count: 成交笔数
    """

    symbol: str = Field(..., min_length=1, description="交易对")
    exchange: str = Field(..., min_length=1, description="交易所名称")
    interval: str = Field(..., min_length=1, description="K 线周期")
    open_time: datetime = Field(..., description="开盘时间")
    open: float = Field(0.0, ge=0, description="开盘价")
    high: float = Field(0.0, ge=0, description="最高价")
    low: float = Field(0.0, ge=0, description="最低价")
    close: float = Field(0.0, ge=0, description="收盘价")
    volume: float = Field(0.0, ge=0, description="成交量")
    quote_volume: float = Field(0.0, ge=0, description="成交额")
    trade_count: int = Field(0, ge=0, description="成交笔数")

    @property
    def is_bullish(self) -> bool:
        """是否阳线"""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """是否阴线"""
        return self.close < self.open

    @property
    def body_size(self) -> float:
        """实体大小"""
        return abs(self.close - self.open)

    @property
    def upper_shadow(self) -> float:
        """上影线长度"""
        high = max(self.open, self.close)
        return self.high - high

    @property
    def lower_shadow(self) -> float:
        """下影线长度"""
        low = min(self.open, self.close)
        return low - self.low


class Trade(BaseModel):
    """成交记录
    
    Attributes:
        symbol: 交易对
        exchange: 交易所名称
        trade_id: 成交 ID
        price: 成交价
        quantity: 成交量
        side: 买卖方向 ('buy' 或 'sell')
        timestamp: 成交时间
    """

    symbol: str = Field(..., min_length=1, description="交易对")
    exchange: str = Field(..., min_length=1, description="交易所名称")
    trade_id: str = Field(..., min_length=1, description="成交 ID")
    price: float = Field(0.0, ge=0, description="成交价")
    quantity: float = Field(0.0, gt=0, description="成交量")
    side: str = Field(..., description="买卖方向")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="成交时间")

    @property
    def value(self) -> float:
        """成交金额"""
        return self.price * self.quantity


class ContractMarket(BaseModel):
    """交易所公开元数据接口返回的可交易合约。"""

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    base_asset: str = Field(..., min_length=1)
    quote_asset: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    contract_type: str = Field("perpetual")
    price_tick: float | None = Field(None, ge=0)
    quantity_step: float | None = Field(None, ge=0)
    min_quantity: float | None = Field(None, ge=0)
    raw: dict[str, Any] = Field(default_factory=dict)
